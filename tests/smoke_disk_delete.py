"""Native disk review, failure, cancellation and success UI on temporary fixtures."""
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from gi.repository import GLib
from mio_linux.app import Application

app = Application()
temp = tempfile.TemporaryDirectory()
root = Path(temp.name)
source = root / 'scan'
source.mkdir()
folder = source / 'folder'
folder.mkdir()
(folder / 'file').write_bytes(b'x' * 1024)
phase = 0
ok = False
deadline = time.monotonic() + 35
mock = None
seen_phases = set()


def tick():
    global phase, ok, mock
    w = app.window
    try:
        assert time.monotonic() < deadline, 'disk deletion GUI timeout'
        if phase == 0:
            w.navigate('disk')
            assert w.disk_delete.get_label() == '删除所选…'
            assert w.disk_delete.get_sensitive()
            w.disk_delete.emit('clicked')
            assert '扫描此目录' in w.disk_action_note.get_label()
            assert not w.operation_busy
            w.start_disk(source)
            phase = 1
        elif phase == 1 and 'disk' in w.completed:
            w.disk_delete.emit('clicked')
            assert '请先单击' in w.disk_action_note.get_label()
            assert not w.operation_busy
            w.treemap.select(w.current_disk_scan.entries[0])
            w.current_disk_scan.partial = True
            w.disk_delete.emit('clicked')
            assert '部分扫描结果' in w.disk_action_note.get_label()
            assert not w.operation_busy
            w.current_disk_scan.partial = False
            w.disk_delete.emit('clicked')
            phase = 2
        elif phase == 2 and not w.operation_busy:
            w.last_review_dialog.response('cancel')
            assert folder.exists() and not w.disk_mutating
            assert w.celebration.play_count == 0
            mock = patch('mio_linux.disk_operations.trash_disk', side_effect=ValueError('fixture refusal'))
            mock.start()
            w.disk_delete.emit('clicked')
            phase = 3
        elif phase == 3 and not w.operation_busy:
            w.last_review_dialog.response('execute')
            phase = 4
        elif phase == 4 and not w.operation_busy:
            mock.stop()
            assert folder.exists() and w.celebration.play_count == 0
            assert 'fixture refusal' in w.disk_action_note.get_label(), w.disk_action_note.get_label()
            # Simulated sink uses only our fixture; real GIO tested separately in private HOME.
            mock = patch('mio_linux.disk_operations.trash_disk', side_effect=lambda plan, cancel: plan.path.rename(root / 'moved'))
            mock.start()
            w.disk_delete.emit('clicked')
            phase = 5
        elif phase == 5 and not w.operation_busy:
            w.last_review_dialog.response('execute')
            phase = 6
        elif phase == 6 and not w.operation_busy:
            mock.stop()
            assert not folder.exists()
            assert w.celebration.play_count == 1
            assert w.celebration.target is not None
            assert w.celebration.tile_effect is not None
            assert w.treemap.concealed_path == folder
            phase = 7
        elif phase == 7:
            effect = w.celebration.tile_effect
            if w.disk_mutating:
                assert effect is not None
                seen_phases.add(effect.phase(w.celebration.elapsed))
                assert w.current_disk_scan.entries, 'Map refreshed before fragments cleared'
                return True
            if 'disk' in w.jobs:
                return True
            assert not w.current_disk_scan.entries
            assert not w.disk_nodes.get(folder)
            assert w.disk_delete.get_sensitive()
            assert w.disk_selected is None
            assert w.treemap.concealed_path is None
            assert {'intact', 'split', 'shatter'} <= seen_phases, seen_phases
            ok = True
            app.quit()
            return False
    except Exception:
        import traceback
        traceback.print_exc()
        if mock:
            mock.stop()
        app.quit()
        return False
    return True

GLib.timeout_add(150, tick)
app.run(['mio-disk-delete-test'])
temp.cleanup()
assert ok
print('Disk GUI: selection, confirmation cancel, refusal, target slash and rescan passed')
