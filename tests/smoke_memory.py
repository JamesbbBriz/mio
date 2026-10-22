"""Native diagnosis and confirmation UI, with synthetic process identities."""
import os
import time
from pathlib import Path
from unittest.mock import patch
from mio_linux.app import Application
from gi.repository import GLib, Gtk
from mio_linux.processes import Process, MemorySnapshot
from mio_linux.process_actions import ExitResult

uid = os.getuid()
def p(pid, category='normal', protected=''):
    return Process(pid=pid,ppid=1,start=pid*10,name=f'演示进程-{pid}',state='Z' if category=='zombie' else 'S',
                   uid=uid,uids=(uid,)*4,rss=128*1024**2,swap=0,session=1,exe=f'/演示应用/app-{pid}',
                   exe_id=(1,pid),cgroup='0::/app-fixture.scope',category=category,
                   evidence='父进程 700 已退出；现在由 PID 1 接管。' if category=='observed' else '首次采样，不能确认原父进程是否退出。',
                   protected=protected,orphan_observed=(category=='observed'))
entries = [p(800,'observed'),p(801,'suspected'),p(802,'zombie','僵尸已退出'),p(803,'managed','托管服务')]
snapshot = MemorySnapshot(processes=entries,total=16*1024**3,available=6*1024**3,swap_total=4*1024**3,
                          swap_used=512*1024**2,pressure=.35,elapsed=.02)
app=Application(); phase=0; ok=False; deadline=time.monotonic()+20; sink=None


def capture(w):
    import gi
    gi.require_version('Graphene','1.0')
    from gi.repository import Graphene
    s=Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(w).snapshot(s,w.get_width(),w.get_height())
    rect=Graphene.Rect();rect.init(0,0,w.get_width(),w.get_height())
    texture=w.get_native().get_renderer().render_texture(s.to_node(),rect)
    Path('artifacts').mkdir(exist_ok=True)
    texture.save_to_png('artifacts/mio-memory.png')


def tick():
    global phase,ok,sink
    w=app.window
    try:
        assert time.monotonic()<deadline
        if phase==0:
            w.stack.set_transition_duration(0)
            w.memory_watch.set_active(False)
            w.show_memory(snapshot)
            w.navigate('memory')
            assert '已观察到孤儿 1' in w.memory_summary.get_label()
            w.memory_filter.set_selected(1)
            w.render_memory()
            phase=1
        elif phase==1:
            capture(w)
            groups=[];child=w.memory_rows.get_first_child()
            while child:
                if isinstance(child,Gtk.Expander):groups.append(child)
                child=child.get_next_sibling()
            assert len(groups)==2
            # Click the real group selection button, then the actual review button.
            groups[0].get_child().get_first_child().emit('clicked')
            assert list(w.memory_selected)==[entries[0].identity]
            w.memory_close.emit('clicked')
            assert w.memory_reviewing
            assert '请求所选进程退出' in w.last_review_dialog.get_heading()
            phase=2
        elif phase==2:
            w.last_review_dialog.response('cancel')
            assert not w.memory_reviewing and not w.operation_busy
            sink=patch('mio_linux.memory_ui.request_exit',side_effect=ValueError('fixture identity changed'))
            sink.start()
            w.memory_close.emit('clicked')
            w.last_review_dialog.response('execute')
            phase=3
        elif phase==3 and not w.operation_busy:
            sink.stop()
            assert 'fixture identity changed' in w.memory_action_note.get_label()
            assert not w.memory_reviewing
            # Follow-up refresh uses synthetic data too (patched below).
            if w.memory_scanning:return True
            w.select_memory_group([entries[0],entries[1]])
            sink=patch('mio_linux.memory_ui.request_exit',return_value=[
                ExitResult(800,entries[0].name,'exited','已确认退出'),
                ExitResult(801,entries[1].name,'requested','未确认退出')])
            sink.start()
            w.memory_close.emit('clicked')
            w.last_review_dialog.response('execute')
            phase=4
        elif phase==4 and not w.operation_busy:
            sink.stop()
            assert '已确认退出 1' in w.memory_action_note.get_label()
            assert '尚未确认 1' in w.memory_action_note.get_label()
            assert not w.memory_selected and not w.memory_reviewing
            assert w.celebration.play_count==0, 'Memory exit must not claim trash recovery'
            ok=True;app.quit();return False
    except Exception:
        import traceback;traceback.print_exc()
        if sink:sink.stop()
        app.quit();return False
    return True

with patch('mio_linux.processes.ProcessMonitor.scan',return_value=snapshot):
    GLib.timeout_add(150,tick)
    app.run(['mio-memory-test'])
assert ok
print('Memory GUI: orphan filter, protected rows, exact selection, cancel, stale identity, exit/pending receipts passed')
