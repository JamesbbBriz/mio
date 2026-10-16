"""Exercise real GTK widgets and asynchronous scan callbacks on fixture files.

Run from project root: python3 -m tests.smoke_gui
Requires a graphical session; writes only fixtures and project artifacts.
"""
import json
import os
from unittest.mock import patch
from mio_linux.recovery import Recovery
import tempfile
import time
from pathlib import Path

from mio_linux.app import Application
from gi.repository import GLib, Gtk


app = Application()
temp = tempfile.TemporaryDirectory()
root = Path(temp.name)
(root / "cache").mkdir()
(root / "cache" / "example.bin").write_bytes(b"x" * 4096)
disk_root = root / "演示磁盘"
for relative, mib in [("开发项目/frontend/node_modules", 400), ("图片/旅行/照片集", 250), ("视频/剪辑素材", 900), ("下载/安装包", 180), ("应用缓存/浏览器", 120), ("文档/工作资料", 60)]:
    path = disk_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        file.truncate(mib * 1024 * 1024)
deadline = time.monotonic() + 30
result = {"ok": False}
phase = 0
scan_generation = None
capture_after = 0
output = Path(__file__).resolve().parents[1] / "artifacts"
output.mkdir(exist_ok=True)


def fail(error):
    import traceback
    traceback.print_exc()
    result.update(ok=False, phase=phase, error=str(error))
    app.quit()
    return False


def screenshot(window, name):
    import gi
    gi.require_version("Graphene", "1.0")
    from gi.repository import Graphene
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    rect = Graphene.Rect()
    rect.init(0, 0, window.get_width(), window.get_height())
    texture = window.get_native().get_renderer().render_texture(node, rect)
    texture.save_to_png(str(output / name))


def tick():
    global phase, scan_generation, capture_after
    try:
        window = app.window
        if time.monotonic() > deadline:
            raise TimeoutError("GUI scan callbacks did not complete")
        if phase == 0:
            assert window.get_mapped()
            window.stack.set_transition_duration(0)
            window.start_cache(root / "cache")
            phase = 1
        elif phase == 1 and "cache" in window.completed:
            assert "4.0 KiB" in window.cache_summary.get_label()
            assert window.cache_results.get_first_child() is not None
            assert window.cache_button.get_sensitive()
            window.navigate("disk")
            window.start_disk(disk_root)
            phase = 2
        elif phase == 2 and "disk" in window.completed:
            assert window.disk_path == disk_root
            assert "1.9 GiB" in window.disk_summary.get_label()
            window.disk_note.set_label("演示数据 · 扫描完成 · 6 个目录 · 方块面积与逻辑体积成正比")
            capture_after = time.monotonic() + .6
            phase = 3
        elif phase == 3:
            if time.monotonic() < capture_after:
                return True
            assert len(window.treemap.tiles) == 6
            screenshot(window, "disk-treemap.png")
            scan_generation = window.disk_generation
            tile = next(tile for tile in window.treemap.tiles if tile.entry.path.name == "视频")
            # Drive the actual native map gesture handler, including hit testing.
            window.treemap.clicked(None, 1, tile.x + tile.width / 2, tile.y + tile.height / 2)
            assert window.disk_path == disk_root / "视频"
            assert "disk" not in window.jobs
            assert window.disk_generation == scan_generation
            # Breadcrumb callbacks go back through the in-memory scan tree.
            crumb = window.breadcrumbs.get_first_child()
            while crumb is not None:
                if isinstance(crumb, Gtk.Button) and crumb.get_label() == "演示磁盘":
                    crumb.emit("clicked")
                    break
                crumb = crumb.get_next_sibling()
            assert window.disk_path == disk_root
            assert window.disk_generation == scan_generation
            window.disk_search.set_text("图片")
            window.render_disk_list()
            assert window.disk_results.get_first_child().get_next_sibling() is None
            window.disk_results.get_first_child().emit("activate")
            assert window.disk_path == disk_root / "图片"
            phase = 4
        elif phase == 4:
            window.navigate("apps")
            assert "apps" in window.completed
            window.app_search.set_text("__mio_test_no_such_application__")
            window.filter_apps()
            assert "显示 0 /" in window.apps_note.get_label()
            window.app_search.set_text("")
            window.filter_apps()
            window.navigate("overview")
            phase = 5
        elif phase == 5:
            assert not window.errors, window.errors
            window.recovery = Recovery(root / 'mio-recovery')
            os.utime(root / 'cache/example.bin', (1, 1))
            window.cache_choices[0][0].set_active(True)
            window.review_cache()
            phase = 6
        elif phase == 6 and not window.operation_busy:
            assert window.last_review_dialog.get_heading() == '移入 Mio 回收站？'
            window.last_review_dialog.response('execute')
            phase = 7
        elif phase == 7 and not window.operation_busy:
            assert not (root / 'cache/example.bin').exists()
            records = window.recovery.records()
            assert len(records) == 1
            window.navigate('trash')
            window.review_recovery(records[0], False)
            window.last_review_dialog.response('execute')
            phase = 8
        elif phase == 8 and not window.operation_busy:
            assert (root / 'cache/example.bin').read_bytes() == b'x' * 4096
            assert window.recovery.records() == []
            from mio_linux.packages import Package
            window.package_items = [Package('apt', 'mio-fixture', '1')]
            window.render_packages()
            with patch('mio_linux.packages.review_uninstall', return_value='Remove mio-fixture only'):
                # Read-only plan is injected; the native dialog and launch wiring are real.
                window.confirm_operation('卸载 mio-fixture？', 'Remove mio-fixture only', lambda: window.start_transaction(['/usr/bin/true']))
            record = root / 'transaction.json'
            record.write_text(json.dumps({'state': 'finished', 'returncode': 0}))
            with patch('mio_linux.packages.launch', return_value=record) as launch:
                window.last_review_dialog.response('execute')
                assert launch.call_count == 1
            window.poll_transaction()
            assert '成功完成' in window.maintenance_note.get_label()
            window.review_maintenance('clean')
            window.last_review_dialog.response('cancel')
            assert window.transaction is None
            result.update(cleanup_confirm=True, recovery_restore=True, package_dispatch=True, maintenance_cancel=True)
            window.navigate('overview')
            phase = 9
        elif phase == 9:
            assert not window.errors, window.errors
            assert window.metrics["memory"][0].get_label() != "—"
            result.update(ok=True, views=list(window.nav), apps=len(window.app_items), cache=window.cache_summary.get_label(), treemap_click=True, cached_navigation=True, breadcrumbs=True, list_filter=True, errors=window.errors)
            # Snapshot our own app widget; no external desktop capture.
            try:
                screenshot(window, "overview.png")
                result["screenshot"] = str(output / "overview.png")
            except Exception as error:
                result["screenshot_error"] = str(error)
            app.quit()
            return False
    except Exception as error:
        return fail(error)
    return True


GLib.timeout_add(250, tick)
try:
    app.run(["mio-gui-test"])
finally:
    temp.cleanup()
    (output / "gui-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["ok"] else 1)
