"""Check actual GTK allocations at desktop and compact window sizes."""
import time
import sys
import gi
gi.require_version("Graphene", "1.0")
from pathlib import Path
import tempfile
from mio_linux.app import Application
from gi.repository import GLib, Gtk, Graphene

app = Application()
temp = tempfile.TemporaryDirectory()
root = Path(temp.name)
for name in ['a', 'a-very-long-folder-name-without-spaces-' * 4]:
    (root / name).mkdir()
    (root / name / 'file').write_bytes(b'x' * 2048)
sizes = [(1120, 860), (850, 600), (600, 700), (420, 600), (1600, 1000), (420, 420)]
pages = ['overview', 'cache', 'disk', 'apps', 'maintenance', 'memory']
cases = [(size, page) for size in sizes for page in pages]
phase = 0
index = 0
ready_at = 0
ok = False
callback_errors = []
original_hook = sys.excepthook
def report_callback_error(kind, error, traceback):
    callback_errors.append(str(error))
    original_hook(kind, error, traceback)
sys.excepthook = report_callback_error
output = Path('artifacts'); output.mkdir(exist_ok=True)


def capture(w, name):
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(w).snapshot(snapshot, w.get_width(), w.get_height())
    rect = Graphene.Rect(); rect.init(0, 0, w.get_width(), w.get_height())
    texture = w.get_native().get_renderer().render_texture(snapshot.to_node(), rect)
    texture.save_to_png(str(output / name))


def hit(widget, window):
    valid, bounds = widget.compute_bounds(window)
    assert valid
    picked = window.pick(bounds.get_x() + bounds.get_width() / 2,
                         bounds.get_y() + bounds.get_height() / 2, Gtk.PickFlags.DEFAULT)
    assert picked is not None
    assert picked is widget or picked.is_ancestor(widget), ('blocked hit target', type(widget).__name__, type(picked).__name__)


def advance(w):
    global index, phase, ready_at
    index += 1
    if index == len(cases):
        w.confirm_operation('移入系统回收站？', str(root / ('long-name-' * 20)) + '\n确认后可恢复。', lambda: None)
        ready_at = time.monotonic() + .5
        phase = 3
    else:
        phase = 1


def tick():
    global phase, index, ready_at, ok
    w = app.window
    try:
        if phase == 0:
            w.stack.set_transition_duration(0)
            w.start_disk(root)
            phase = 1
        elif phase == 1 and 'disk' not in w.jobs:
            (width, height), page = cases[index]
            w.set_default_size(width, height)
            w.navigate(page)
            if width <= 600 and page == 'disk':
                w.disk_path = root / ('long-folder-name-' * 5) / 'nested' / ('深层目录' * 12)
                w.update_breadcrumbs()
            ready_at = time.monotonic() + .4
            phase = 2
        elif phase == 2 and time.monotonic() >= ready_at:
            (width, height), page = cases[index]
            assert w.get_width() <= width + 2, (page, width, w.get_width())
            assert w.get_height() <= height + 2, (page, height, w.get_height())
            assert all(d.get_visible() == (height > 680) for d in w.page_decorations)
            assert w.split_view.get_collapsed() == (width <= 1000)
            assert (w.chart_row.get_orientation() == Gtk.Orientation.VERTICAL) == (width <= 740)
            assert not hasattr(w, 'window_handle'), 'visible titlebar returned'
            assert w.is_top_drag_point(width / 2, 12)
            assert not w.is_top_drag_point(width / 2, 70)
            from unittest.mock import Mock, patch
            gesture, surface = Mock(), Mock()
            gesture.get_current_event_device.return_value = object()
            gesture.get_current_event_time.return_value = 1234
            with patch.object(w, 'get_surface', return_value=surface):
                w.drag_top_background(gesture, 1, width / 2, 12)
            surface.begin_move.assert_called_once_with(gesture.get_current_event_device.return_value, 1, width / 2, 12, 1234)
            if w.menu_toggle.get_visible():
                valid, bounds = w.menu_toggle.compute_bounds(w)
                assert not w.is_top_drag_point(bounds.get_x() + bounds.get_width() / 2, bounds.get_y() + bounds.get_height() / 2)
            scroller = w.stack.get_visible_child()
            adj = scroller.get_hadjustment()
            assert adj.get_upper() <= adj.get_page_size() + 2, (page, width, 'horizontal overflow')
            # Native page contents must fit; allow vertical scrolling on short screens.
            def inspect(widget):
                if widget.get_mapped():
                    valid, bounds = widget.compute_bounds(w)
                    if valid:
                        assert bounds.get_x() >= -2 and bounds.get_x() + bounds.get_width() <= w.get_width() + 2, (page, width, type(widget).__name__, bounds.get_x(), bounds.get_width())
                    child = widget.get_first_child()
                    while child:
                        inspect(child)
                        child = child.get_next_sibling()
            inspect(scroller.get_child())
            if page == 'disk':
                capture(w, f'responsive-{width}x{height}.png')
                if width <= 1000:
                    hit(w.menu_toggle, w)
                    w.menu_toggle.emit('clicked')
                    assert w.split_view.get_show_sidebar()
                    ready_at = time.monotonic() + .4
                    phase = 4
                    return True
            advance(w)
        elif phase == 4 and time.monotonic() >= ready_at:
            hit(w.nav['cache'], w)
            w.nav['cache'].emit('clicked')
            assert w.stack.get_visible_child_name() == 'cache'
            assert not w.split_view.get_show_sidebar()
            advance(w)
        elif phase == 3 and time.monotonic() >= ready_at:
            dialog = w.last_review_dialog
            assert 0 < dialog.get_width() <= w.get_width(), ('dialog width', dialog.get_width())
            assert 0 < dialog.get_height() <= w.get_height(), ('dialog height', dialog.get_height())
            dialog.response('cancel')
            ok = True
            app.quit()
            return False
    except Exception:
        import traceback
        traceback.print_exc()
        capture(w, 'responsive-failure.png')
        app.quit()
        return False
    return True

GLib.timeout_add(120, tick)
GLib.timeout_add_seconds(60, lambda: (app.quit(), False)[1])
app.run(['mio-responsive-test'])
temp.cleanup()
assert ok
assert not callback_errors, callback_errors
print(f'Responsive GUI passed: {len(cases)} page/size combinations')
