"""Run ONLY in an isolated HOME, data directory and private D-Bus session."""
from pathlib import Path
import os
import tempfile
import time
from gi.repository import Gio, GLib
from tests.trash_probe import TrashProbe
from mio_linux.recovery import Candidate, signature, identity, Recovery

root = Path(os.environ['MIO_TEST_ROOT'])
assert Path.home() == root / 'home'
assert os.environ['XDG_DATA_HOME'] == str(root / 'data')
trash = TrashProbe()
def records_for(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        found = [r for r in trash.records() if r['path'] == str(path)]
        if found:
            return found
        time.sleep(.05)
    raise AssertionError(f'System trash did not refresh: {path}; records={trash.records()}; disk={list((root / "data/Trash").rglob("*"))}')
assert trash.records() == []
source = root / '文件 % #.txt'
source.write_text('original')
candidate = Candidate(str(source), signature(source.stat()), identity(source.parent.stat()))
trash.move(candidate)
assert not source.exists()
records = records_for(source)
assert len(records) == 1 and records[0]['path'] == str(source)
# Metadata must be standard and visible to a second GIO consumer.
assert list((root / 'data/Trash/info').glob('*.trashinfo'))
info = Gio.File.new_for_uri('trash:///').enumerate_children('standard::name,trash::orig-path', 0, None).next_file(None)
assert info.get_attribute_byte_string('trash::orig-path') == str(source)
source.write_text('new')
try:
    trash.restore(records[0]['id'])
    raise AssertionError('overwrite was allowed')
except ValueError:
    pass
assert source.read_text() == 'new'
source.unlink()
trash.restore(records[0]['id'])
assert source.read_text() == 'original'
# A file manager's trash operation must appear in Mio, including nonempty folders.
folder = root / 'folder'
folder.mkdir()
(folder / 'child').write_text('child')
Gio.File.new_for_path(str(folder)).trash(None)
record = records_for(folder)[0]
assert record['is_dir']
trash.restore(record['id'])
assert (folder / 'child').read_text() == 'child'
Gio.File.new_for_path(str(folder)).trash(None)
trash.erase(records_for(folder)[0]['id'])
assert not folder.exists()
assert trash.records() == []
# Deleting a trashed symlink must leave its target untouched.
link = root / 'link'
link.symlink_to(source)
Gio.File.new_for_path(str(link)).trash(None)
trash.erase(records_for(link)[0]['id'])
assert source.read_text() == 'original'
# External restore invalidates an old selection.
Gio.File.new_for_path(str(source)).trash(None)
record = records_for(source)[0]
import json
uri = json.loads(record['id'])[0]
Gio.File.new_for_uri(uri).move(Gio.File.new_for_path(str(source)), 0, None, None, None)
try:
    trash.erase(record['id'])
    raise AssertionError('stale item was accepted')
except ValueError:
    pass
assert source.read_text() == 'original'
# Legacy migration preserves the original filename and recovery destination.
legacy = Recovery(Path.home() / '.local/share/mio/recovery')
legacy.move(Candidate(str(source), signature(source.stat()), identity(source.parent.stat())))
completed, errors = trash.migrate_legacy(legacy.records())
assert len(completed) == 1 and not errors, errors
assert not legacy.records()
record = records_for(source)[0]
assert record['path'] == str(source)
trash.restore(record['id'])
assert source.read_text() == 'original'
# A migration conflict must preserve both the live and legacy versions.
legacy.move(Candidate(str(source), signature(source.stat()), identity(source.parent.stat())))
source.write_text('occupied')
completed, errors = trash.migrate_legacy(legacy.records())
assert not completed and errors
assert source.read_text() == 'occupied' and len(legacy.records()) == 1
source.unlink()
# A failed second step must leave a restored original, not lose the file.
from unittest.mock import patch
with patch.object(trash, 'move', side_effect=ValueError('fixture trash failure')):
    completed, errors = trash.migrate_legacy(legacy.records())
assert not completed and errors
assert source.read_text() == 'original' and not legacy.records()
print('System trash interoperability: move, external visibility, conflict, directory restore/delete, symlink, external restore, legacy migration passed')
