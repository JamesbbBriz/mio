"""GTK 4 / libadwaita desktop frontend."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Gdk, Pango

from .backend import cache_root, cpu_percent, cpu_ticks, disk_stats, human_size, memory_stats, scan_directory
from .backend import Entry, Scan
from .disk_view import Treemap
from .operations_ui import OperationsUI
from .celebration import SlashCelebration
from .character_nav import CharacterNav
from .memory_ui import MemoryUI


CSS = """
window { background: #f7f7fb; color: #303448; }
.sidebar { background: #f0edf8; border-right: 1px solid #e1ddec; padding: 20px 14px; }
.brand { font-size: 23px; font-weight: 800; }
.tag { color: #77748c; font-size: 11px; letter-spacing: 1px; }
.nav { background: transparent; box-shadow: none; border: none; padding: 15px 14px; border-radius: 12px; }
.nav.active { background: #e3dcf3; color: #5c4782; }
.nav:hover { background: #e8e1f3; }
.page { padding: 24px 30px 32px; }
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #7a7592; }
.page-title { font-size: 29px; font-weight: 800; }
.muted { color: #777b8e; }
.card { background: #ffffff; border: 1px solid #e4e9e5; border-radius: 18px; padding: 22px; }
.hero { background: linear-gradient(110deg, #f6e3ef, #e3edfc); border: 1px solid #e4dced; border-radius: 22px; padding: 28px; }
.hero-title { font-size: 30px; font-weight: 800; }
.metric { font-size: 29px; font-weight: 700; }
.small { font-size: 12px; }
.section-title { font-size: 17px; font-weight: 700; }
.pill { background: #edf4ef; color: #42654c; border-radius: 20px; padding: 6px 12px; font-size: 11px; }
.suggested-action { background: #7565a3; color: white; border-radius: 10px; padding: 10px 20px; }
.results { background: white; border-radius: 14px; border: 1px solid #e4e9e5; }
.result-row { padding: 8px 10px; }
.disk-page { padding: 16px 24px; }
.disk-map { background: #e8e7f0; padding: 6px; border-radius: 14px; }
.path-bar { background: #ffffff; border: 1px solid #e1ddec; border-radius: 12px; padding: 6px 10px; }
.breadcrumbs button { background: transparent; box-shadow: none; border: none; padding: 6px 8px; font-size: 13px; }
.breadcrumbs button:hover { background: #eeebf6; }
.breadcrumbs .current-path { background: #eeebf6; color: #5c4782; font-weight: 700; }
.disk-detail { background: #eeebf6; padding: 12px 16px; border-radius: 12px; }
progressbar trough { background: #ebe8f3; min-height: 6px; border-radius: 6px; }
progressbar progress { background: #a295c5; min-height: 6px; border-radius: 6px; }
"""

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def label(text: str, css: str = "", *, wrap: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0, wrap=wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for name in css.split():
        widget.add_css_class(name)
    return widget


def box(vertical: bool = True, spacing: int = 12, css: str = "") -> Gtk.Box:
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for name in css.split():
        widget.add_css_class(name)
    return widget


def flow():
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                       row_spacing=6, column_spacing=6, min_children_per_line=1,
                       max_children_per_line=12, valign=Gtk.Align.START)


def button(text: str, callback, css: str = "") -> Gtk.Button:
    widget = Gtk.Button(label=text)
    widget.connect("clicked", callback)
    for name in css.split():
        widget.add_css_class(name)
    return widget


def clear(widget: Gtk.Box | Gtk.ListBox) -> None:
    while child := widget.get_first_child():
        widget.remove(child)


class Window(MemoryUI, OperationsUI, Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Mio · 澪", default_width=1120, default_height=860)
        self.set_size_request(420, 420)
        self.set_icon_name("io.github.jamesbbbriz.Mio")
        self.cancel = threading.Event()
        self.jobs = set()
        self.completed = set()
        self.errors = []
        self.page_decorations = []
        self.pages = []
        self.disk_path = Path.home()
        self.disk_scan = None
        self.disk_nodes = {}
        self.disk_cancel = threading.Event()
        self.disk_generation = 0
        self.disk_visible_limit = 100
        self.previous_cpu = cpu_ticks()
        self.connect("close-request", self.on_close)
        outer = Gtk.Overlay()
        split = Adw.OverlaySplitView(min_sidebar_width=254, max_sidebar_width=254,
                                     sidebar_width_unit=Adw.LengthUnit.PX)
        self.split_view = split
        sidebar = box(spacing=8, css="sidebar")
        sidebar.set_size_request(254, -1)
        brand = box(False, 10)
        mascot = Gtk.Image.new_from_file(str(ASSETS / "mio-icon.png"))
        mascot.set_pixel_size(44)
        brand.append(mascot)
        brand.append(label("mio / 澪", "brand"))
        brand_handle = Gtk.WindowHandle(child=brand)
        sidebar.append(brand_handle)
        sidebar.append(label("本机空间 · 清晰掌握", "tag"))
        spacer = box()
        spacer.set_size_request(-1, 4)
        sidebar.append(spacer)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True, vexpand=True)
        self.nav = {}
        for key, title, icon in [
            ("overview", "系统概览", "view-grid-symbolic"),
            ("cache", "缓存清理", "edit-clear-all-symbolic"),
            ("disk", "磁盘分析", "drive-harddisk-symbolic"),
            ("apps", "应用管理", "application-x-executable-symbolic"),
            ("maintenance", "系统维护", "preferences-system-symbolic"),
            ("memory", "内存诊断", "system-run-symbolic"),
        ]:
            nav = CharacterNav(key, title)
            nav.connect("clicked", lambda _, name=key: self.navigate(name))
            sidebar.append(nav)
            self.nav[key] = nav
        footer = box(css="small")
        footer.set_valign(Gtk.Align.END)
        footer.set_vexpand(True)
        motion = Gtk.CheckButton(label="角色动作", active=True)
        motion.connect("toggled", lambda widget: setattr(self.celebration, "enabled", widget.get_active()))
        footer.append(motion)
        footer.append(label("●  本地运行 · 可恢复清理", "muted"))
        footer.append(label("独立 Linux 开源工具\nv0.4.0 · 免费", "muted small"))
        sidebar.append(footer)
        sidebar_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_child(sidebar)
        split.set_sidebar(sidebar_scroll)
        split.set_content(self.stack)
        outer.set_child(split)
        self.celebration = SlashCelebration()
        outer.add_overlay(self.celebration)
        # Frameless appearance: only the controls are overlaid. The window's
        # capture controller delegates top-background drags to the compositor,
        # without putting an invisible input-blocking widget over the page.
        self.menu_toggle = Gtk.Button(icon_name="sidebar-show-symbolic", tooltip_text="显示／收起功能导航",
                                      halign=Gtk.Align.START, valign=Gtk.Align.START,
                                      margin_start=8, margin_top=6, visible=False)
        self.menu_toggle.connect("clicked", lambda _: split.set_show_sidebar(not split.get_show_sidebar()))
        outer.add_overlay(self.menu_toggle)
        outer.add_overlay(Gtk.WindowControls(side=Gtk.PackType.END, halign=Gtk.Align.END,
                                             valign=Gtk.Align.START, margin_top=6, margin_end=8))
        self.set_content(outer)
        self.drag_gesture = Gtk.GestureClick(button=1)
        self.drag_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.drag_gesture.connect("pressed", self.drag_top_background)
        self.add_controller(self.drag_gesture)
        self.build_overview()
        self.build_cache()
        self.build_disk()
        self.build_apps()
        self.setup_operations()
        self.build_memory()
        self.setup_responsive()
        self.navigate("overview")
        self.refresh_status()
        self.timer = GLib.timeout_add_seconds(2, self.refresh_status)

    def is_top_drag_point(self, x, y):
        if not (0 <= y < 44 and 0 <= x < self.get_width()):
            return False
        picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if picked is None:
            return False
        # Never steal clicks from controls, including controls scrolled into
        # the top strip, the navigation drawer, or a map selection.
        while picked is not None and picked is not self:
            if isinstance(picked, (Gtk.Button, Gtk.MenuButton, Gtk.Editable, Gtk.TextView, Gtk.Switch, Gtk.DropDown,
                                   Gtk.ListBoxRow, Gtk.DrawingArea, Gtk.Range, Gtk.CheckButton)):
                return False
            picked = picked.get_parent()
        return True

    def drag_top_background(self, gesture, presses, x, y):
        if not self.is_top_drag_point(x, y):
            return
        device = gesture.get_current_event_device()
        if device is None:
            return
        if presses == 2:
            self.unmaximize() if self.is_maximized() else self.maximize()
        else:
            self.get_surface().begin_move(device, 1, x, y, gesture.get_current_event_time())
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def setup_responsive(self):
        # Libadwaita applies the last matching breakpoint. Register specific
        # width/height combinations last so both dimensions adapt together.
        for max_width in (None, 1000, 740):
            for short in (False, True):
                if max_width is None and not short:
                    continue
                conditions = ([f"max-width: {max_width}px"] if max_width else [])
                if short:
                    conditions.append("max-height: 680px")
                bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(" and ".join(conditions)))
                compact, narrow = max_width is not None, max_width == 740
                bp.add_setter(self.split_view, "collapsed", compact)
                bp.add_setter(self.split_view, "show-sidebar", not compact)
                bp.add_setter(self.menu_toggle, "visible", compact)
                for widget in (self.chart_row, self.overview_hero, self.overview_cards, self.disk_actions):
                    bp.add_setter(widget, "orientation", Gtk.Orientation.VERTICAL if narrow else Gtk.Orientation.HORIZONTAL)
                for decoration in self.page_decorations:
                    bp.add_setter(decoration, "visible", not short)
                for page in self.pages:
                    bp.add_setter(page, "spacing", 10 if short else (12 if page.has_css_class("disk-page") else 18))
                bp.add_setter(self.treemap, "content-height", 250 if short else 360)
                bp.add_setter(self.disk_list_scroll, "min-content-height", 180 if short else 285)
                bp.connect("apply", lambda _, c=compact, n=narrow, s=short: self.apply_layout_classes(c, n, s))
                bp.connect("unapply", lambda _: self.apply_layout_classes(False, False, False))
                self.add_breakpoint(bp)

    def apply_layout_classes(self, compact, narrow, short):
        for name, active in (("compact-sidebar", compact), ("narrow-layout", narrow), ("short-layout", short)):
            (self.add_css_class if active else self.remove_css_class)(name)
        self.narrow_layout = narrow
        self.update_breadcrumbs()

    def on_close(self, *_):
        self.dismiss_context_menu()
        self.celebration.stop()
        self.cancel.set()
        self.operation_cancel.set()
        self.disk_cancel.set()
        GLib.source_remove(self.timer)
        GLib.source_remove(self.memory_timer)
        return False

    def page(self, key, number, title, subtitle):
        content = box(spacing=18, css="page")
        drag_handle = Gtk.WindowHandle(child=label(number, "eyebrow"))
        content.append(drag_handle)
        content.append(label(title, "page-title", wrap=True))
        subtitle_label = label(subtitle, "muted", wrap=True)
        content.append(subtitle_label)
        self.page_decorations.append(subtitle_label)
        self.pages.append(content)
        companion = box(False, 8)
        avatar = Gtk.Image.new_from_file(str(ASSETS / "mio-icon.png"))
        avatar.set_pixel_size(27)
        companion.append(avatar)
        lines = {"overview": "澪 · 今天也一起照顾电脑吧。", "cache": "澪 · 确认清单后，我来帮你收纳。", "disk": "澪 · 方块越大，藏着的文件越多。", "apps": "澪 · 先确认软件来源，再决定去留。", "maintenance": "澪 · 系统操作的每一步，都交给你确认。"}
        companion.append(label(lines.get(key, "澪 · 我在这里。"), "character-note", wrap=True))
        if key == "memory":
            companion.get_last_child().set_label("琥珀 · 先找到失联的父进程，再决定要不要告别。")
        content.append(companion)
        self.page_decorations.append(companion)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(content)
        self.stack.add_named(scroller, key)
        return content

    def navigate(self, key):
        if getattr(self, "disk_mutating", False):
            return
        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)
        self.stack.set_visible_child_name(key)
        for name, nav in self.nav.items():
            (nav.add_css_class if name == key else nav.remove_css_class)("active")
        if key == "memory" and self.memory_snapshot is None:
            self.start_memory()
        if key == "apps" and key not in self.completed:
            self.load_apps()

    def build_overview(self):
        page = self.page("overview", "01 / OVERVIEW", "给电脑，留一点呼吸空间。", "从真实数据开始，了解你的 Linux 桌面。")
        hero = box(False, 20, "hero")
        self.overview_hero = hero
        copy = box(spacing=14)
        copy.set_hexpand(True)
        copy.append(label("让空间，回到你手里。", "hero-title", wrap=True))
        copy.append(label("看看缓存占了多少空间，\n找到最大的文件夹，掌握系统状态。", "muted", wrap=True))
        action = button("开始扫描缓存  →", lambda _: self.start_cache(), "suggested-action")
        action.set_halign(Gtk.Align.START)
        copy.append(action)
        preview = button("✦ 看澪的斩击动作", lambda _: self.celebration.play(preview=True))
        preview.set_halign(Gtk.Align.START)
        copy.append(preview)
        copy.append(label("扫描只读取文件，不会删除或修改内容。", "small muted", wrap=True))
        hero.append(copy)
        art = Gtk.Picture.new_for_filename(str(ASSETS / "mio-mascot.png"))
        art.set_content_fit(Gtk.ContentFit.CONTAIN)
        art.set_size_request(190, 220)
        art.set_can_shrink(True)
        hero.append(art)
        page.append(hero)
        cards = box(False, 14)
        self.overview_cards = cards
        self.metrics = {}
        for key, name in [("cpu", "CPU 使用率"), ("memory", "内存使用率"), ("disk", "主目录所在磁盘")]:
            card = box(spacing=10, css="card")
            card.set_hexpand(True)
            card.append(label(name, "muted small"))
            value = label("—", "metric")
            detail = label("读取中", "muted small", wrap=True)
            progress = Gtk.ProgressBar()
            card.append(value)
            card.append(progress)
            card.append(detail)
            cards.append(card)
            self.metrics[key] = (value, detail, progress)
        page.append(cards)
        page.append(label("从这里开始", "section-title"))
        for title, detail, key in [
            ("缓存预览", "按目录查看缓存体积与超过 7 天未修改的文件。", "cache"),
            ("磁盘分析", "按体积排序，逐层找到占空间的目录。", "disk"),
            ("应用列表", "查看当前桌面环境可见的应用，快速搜索。", "apps"),
        ]:
            item = Adw.ActionRow(title=title, subtitle=detail, activatable=True)
            item.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            item.connect("activated", lambda _, name=key: self.navigate(name))
            group = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
            group.append(item)
            page.append(group)
        self.status_note = label("每 2 秒更新 · 数据来自 /proc 与本机文件系统", "small muted", wrap=True)
        page.append(self.status_note)

    def refresh_status(self):
        try:
            current = cpu_ticks()
            cpu = cpu_percent(self.previous_cpu, current)
            self.previous_cpu = current
            used, total = memory_stats()
            disk = disk_stats()
            for key, value, detail, fraction in [
                ("cpu", f"{cpu:.0f}%", "所有逻辑核心 · 实时采样", cpu / 100),
                ("memory", f"{used / total:.0%}", f"{human_size(used)} / {human_size(total)}", used / total),
                ("disk", human_size(disk.free), f"可用 / 共 {human_size(disk.total)}", disk.used / disk.total),
            ]:
                number, text, bar = self.metrics[key]
                number.set_label(value)
                text.set_label(detail)
                bar.set_fraction(fraction)
        except (OSError, ValueError, KeyError, ZeroDivisionError) as error:
            self.status_note.set_label(f"部分系统数据读取失败：{error}")
        return not self.cancel.is_set()

    def results_list(self):
        return Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["results"])

    def build_cache(self):
        page = self.page("cache", "02 / CACHE", "先看清楚，再决定。", "查看缓存占用，审阅后移入系统回收站。文件较旧并不代表可以安全删除。")
        controls = flow()
        self.cache_button = button("扫描缓存", lambda _: self.start_cache(), "suggested-action")
        self.cache_spinner = Gtk.Spinner()
        self.cache_controls = controls
        controls.append(self.cache_button)
        controls.append(self.cache_spinner)
        page.append(controls)
        self.cache_action_note = label("澪 · 清理成功后会播放斩击动作，文件仍可从系统回收站恢复。", "character-note", wrap=True)
        page.append(self.cache_action_note)
        self.cache_summary = label("尚未扫描", "metric")
        self.cache_note = label(str(cache_root()), "small muted", wrap=True)
        page.append(self.cache_summary)
        page.append(self.cache_note)
        page.append(label("目录 · 总体积 / 超过 7 天未修改", "section-title"))
        self.cache_results = self.results_list()
        self.bind_context_menu(self.cache_results, self.cache_context_menu)
        page.append(self.cache_results)
        page.append(label("勾选目录后审阅超过 7 天的普通文件；请先关闭相关应用。移入系统回收站后可恢复，永久删除才释放空间。", "small muted", wrap=True))

    def run_job(self, key, work, done, control, spinner):
        if key in self.jobs:
            return
        self.jobs.add(key)
        control.set_sensitive(False)
        spinner.start()

        def finish(value, error):
            self.jobs.discard(key)
            if self.cancel.is_set():
                return False
            control.set_sensitive(True)
            spinner.stop()
            if error:
                self.errors.append(str(error))
                target = self.cache_note if key == "cache" else self.disk_note
                target.set_label(f"读取失败：{error}")
            else:
                done(value)
                self.completed.add(key)
            return False

        def worker():
            try:
                value = work()
            except Exception as error:
                GLib.idle_add(finish, None, error)
            else:
                GLib.idle_add(finish, value, None)

        threading.Thread(target=worker, daemon=True, name=f"mole-{key}").start()

    @staticmethod
    def scan_note(scan):
        state = "已停止 · 部分结果" if scan.cancelled else ("部分结果：达到时间、深度或条目上限" if scan.partial else "扫描完成")
        return f"{state} · 检查 {scan.visited:,} 项 · 跳过 {scan.skipped:,} 项（链接、跨磁盘或不可读等）"

    def start_cache(self, root=None):
        self.dismiss_context_menu()
        self.navigate("cache")
        self.cache_note.set_label("正在扫描…")
        self.run_job("cache", lambda: scan_directory(root or cache_root(), cancel=self.cancel), self.show_cache, self.cache_button, self.cache_spinner)

    def show_cache(self, scan):
        clear(self.cache_results)
        self.cache_scan = scan
        self.cache_choices = []
        self.cache_summary.set_label(f"{human_size(scan.size)}  缓存体积")
        self.cache_note.set_label(f"{scan.root}\n{self.scan_note(scan)}\n按文件名累加逻辑体积；硬链接可能重复计算，不代表可回收空间。")
        for entry in scan.entries[:200]:
            row = Adw.ActionRow(title=GLib.markup_escape_text(entry.path.name), subtitle=f"{entry.files:,} 个文件 · 较旧 {human_size(entry.old_size)}")
            row.add_prefix(Gtk.Image(icon_name="folder-symbolic" if entry.is_dir else "text-x-generic-symbolic"))
            row.add_suffix(label(human_size(entry.size)))
            row.set_tooltip_text(str(entry.path))
            row.mio_entry = entry
            check = Gtk.CheckButton()
            row.add_prefix(check)
            self.cache_choices.append((check, entry.path))
            self.cache_results.append(row)
        if not scan.entries:
            self.cache_results.append(Adw.ActionRow(title="未发现可显示的缓存文件"))
        elif len(scan.entries) > 200:
            self.cache_results.append(Adw.ActionRow(title=f"仅显示最大的 200 项，共 {len(scan.entries):,} 项"))

    def build_disk(self):
        page = self.page("disk", "03 / ANALYZE", "大文件夹，一眼就看见。", "方块越大，占用越多。单击选中，双击文件夹进入；面包屑随时返回。")
        page.add_css_class("disk-page")
        page.set_spacing(12)
        controls = flow()
        self.parent_button = button("↑ 上一级", lambda _: self.open_disk_path(self.disk_path.parent))
        self.choose_button = button("选择文件夹", self.choose_folder)
        self.home_button = button("主目录", lambda _: self.open_disk_path(Path.home()))
        self.disk_button = button("扫描此目录", lambda _: self.start_disk(self.disk_path), "suggested-action")
        self.stop_button = button("停止", lambda _: self.disk_cancel.set())
        self.stop_button.set_sensitive(False)
        self.disk_spinner = Gtk.Spinner()
        for child in (self.home_button, self.parent_button, self.choose_button, self.disk_button, self.stop_button, self.disk_spinner):
            controls.append(child)
        page.append(controls)
        path_bar = box(False, 6, "path-bar")
        path_bar.append(Gtk.Image(icon_name="folder-open-symbolic"))
        self.path_stack = Gtk.Stack(hexpand=True)
        self.breadcrumbs = box(False, 2, "breadcrumbs")
        self.path_stack.add_named(self.breadcrumbs, "crumbs")
        self.path_entry = Gtk.Entry(placeholder_text="输入完整路径，支持 ~/", hexpand=True)
        self.path_entry.connect("activate", self.submit_disk_path)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.path_key_pressed)
        self.path_entry.add_controller(keys)
        self.path_stack.add_named(self.path_entry, "edit")
        path_bar.append(self.path_stack)
        edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="输入路径")
        edit.connect("clicked", lambda _: self.edit_disk_path())
        path_bar.append(edit)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="复制完整路径")
        copy.connect("clicked", lambda _: self.get_display().get_clipboard().set(str(self.disk_path)))
        path_bar.append(copy)
        page.append(path_bar)
        self.disk_summary = label("选择文件夹，开始发现空间。", "section-title")
        self.disk_note = label("点击扫描，或在路径栏输入文件夹位置。", "small muted", wrap=True)
        page.append(self.disk_summary)
        page.append(self.disk_note)
        actions = box(False, 10)
        self.disk_actions = actions
        self.disk_delete = button("删除所选…", lambda _: self.review_disk_delete(), "suggested-action")
        self.disk_delete.set_tooltip_text("删除所选文件或文件夹：确认后移入系统回收站，可恢复")
        actions.append(self.disk_delete)
        self.disk_action_note = label("选中文件或文件夹，再确认移入系统回收站。", "small muted", wrap=True)
        self.disk_action_note.set_hexpand(True)
        actions.append(self.disk_action_note)
        self.disk_mutating = False
        self.disk_selected = None
        page.append(actions)
        chart_row = box(False, 12)
        self.chart_row = chart_row
        chart_frame = box(css="disk-map")
        chart_frame.set_hexpand(True)
        self.treemap = Treemap(self.select_disk_entry, self.open_disk_path)
        self.bind_context_menu(self.treemap, self.disk_map_context_menu)
        chart_frame.append(self.treemap)
        chart_row.append(chart_frame)
        list_column = box(spacing=8)
        list_column.set_size_request(245, -1)
        list_column.append(label("按体积排序", "section-title"))
        self.disk_search = Gtk.SearchEntry(placeholder_text="筛选当前目录")
        self.disk_search.connect("search-changed", lambda _: self.render_disk_list())
        list_column.append(self.disk_search)
        self.disk_results = self.results_list()
        self.disk_results.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.disk_results.set_activate_on_single_click(False)
        self.disk_results.connect("row-selected", self.select_disk_row)
        self.disk_results.connect("row-activated", self.activate_disk_row)
        self.bind_context_menu(self.disk_results, self.disk_list_context_menu)
        list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=285)
        self.disk_list_scroll = list_scroll
        list_scroll.set_vexpand(True)
        list_scroll.set_child(self.disk_results)
        list_column.append(list_scroll)
        chart_row.append(list_column)
        page.append(chart_row)
        detail = box(spacing=3, css="disk-detail")
        self.disk_selection = label("悬停方块或选中列表项，查看体积与占比", "section-title", wrap=True)
        self.disk_selection_path = label("扫描结果只保留在本次会话中。", "small muted", wrap=True)
        detail.append(self.disk_selection)
        detail.append(self.disk_selection_path)
        page.append(detail)
        page.append(label("扫描只读，删除需单独确认 · 逻辑体积按文件名计数，硬链接可能重复计算 · 不跟随链接、不跨文件系统\n扫描上限 60 秒 / 500,000 项；未扫描完会明确标注，图中占比仅针对已扫描内容。", "small muted", wrap=True))
        self.update_breadcrumbs()

    def choose_folder(self, *_):
        dialog = Gtk.FileDialog(title="选择要分析的文件夹")

        def selected(source, result):
            try:
                folder = source.select_folder_finish(result)
                path = folder.get_path()
                if path:
                    self.start_disk(Path(path))
            except GLib.Error:
                pass

        dialog.select_folder(self, None, selected)

    def start_disk(self, root):
        if "disk" in self.jobs or self.disk_mutating:
            return
        self.dismiss_context_menu()
        self.disk_selected = None
        self.disk_delete.set_sensitive(False)
        target = Path(root)
        self.disk_cancel = threading.Event()
        self.disk_generation += 1
        generation = self.disk_generation
        self.disk_note.set_label(f"{target}\n正在扫描…")
        self.stop_button.set_sensitive(True)
        self.parent_button.set_sensitive(False)
        self.choose_button.set_sensitive(False)
        self.home_button.set_sensitive(False)
        self.jobs.add("disk")
        self.disk_button.set_sensitive(False)
        self.disk_spinner.start()

        def progress(visited, size):
            def show():
                if generation == self.disk_generation and "disk" in self.jobs and not self.cancel.is_set():
                    self.disk_note.set_label(f"{target}\n正在扫描 {visited:,} 项 · 已统计 {human_size(size)} · 可以停止")
                return False
            GLib.idle_add(show)

        def finish(scan, error):
            self.jobs.discard("disk")
            if self.cancel.is_set():
                return False
            for control in (self.disk_button, self.parent_button, self.choose_button, self.home_button, self.disk_delete):
                control.set_sensitive(True)
            self.stop_button.set_sensitive(False)
            self.disk_spinner.stop()
            if error:
                self.errors.append(str(error))
                self.disk_note.set_label(f"读取失败：{error}。保留上次结果。")
            else:
                self.disk_scan = scan
                self.disk_nodes = {scan.root: Entry(scan.root, size=scan.size, files=sum(e.files for e in scan.entries), is_dir=True, children=scan.entries, complete=not scan.partial)}
                pending = list(scan.entries)
                while pending:
                    entry = pending.pop()
                    if entry.is_dir:
                        self.disk_nodes[entry.path] = entry
                        pending.extend(entry.children)
                self.show_disk(scan)
                self.completed.add("disk")
            return False

        def worker():
            try:
                scan = scan_directory(target, cancel=self.disk_cancel, max_seconds=60, max_nodes=500_000, retain_tree=True, progress=progress)
            except Exception as error:
                GLib.idle_add(finish, None, error)
            else:
                GLib.idle_add(finish, scan, None)

        threading.Thread(target=worker, daemon=True, name="disk-scan").start()

    def open_disk_path(self, path):
        if "disk" in self.jobs or self.disk_mutating:
            return
        path = Path(path)
        if path in self.disk_nodes:
            entry = self.disk_nodes[path]
            self.show_disk(Scan(path, entries=entry.children, partial=(self.disk_scan.partial or not entry.complete), skipped=self.disk_scan.skipped, visited=self.disk_scan.visited, cancelled=self.disk_scan.cancelled))
        else:
            self.start_disk(path)

    def edit_disk_path(self):
        self.path_entry.set_text(str(self.disk_path))
        self.path_entry.remove_css_class("error")
        self.path_stack.set_visible_child_name("edit")
        self.path_entry.grab_focus()
        self.path_entry.select_region(0, -1)

    def path_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.path_stack.set_visible_child_name("crumbs")
            return True
        return False

    def submit_disk_path(self, entry):
        text = entry.get_text().strip()
        try:
            expanded = Path(text).expanduser()
        except (RuntimeError, ValueError):
            expanded = Path()
        if not text or not expanded.is_absolute():
            entry.add_css_class("error")
            entry.set_tooltip_text("请输入绝对路径，例如 /media，或使用 ~/ 开头")
            return
        if "disk" in self.jobs or self.disk_mutating:
            return
        import os
        target = Path(os.path.abspath(expanded))
        entry.remove_css_class("error")
        entry.set_tooltip_text(None)
        self.path_stack.set_visible_child_name("crumbs")
        self.open_disk_path(target)

    def update_breadcrumbs(self):
        clear(self.breadcrumbs)
        self.path_stack.set_visible_child_name("crumbs")
        home = Path.home()
        within_home = self.disk_path == home or home in self.disk_path.parents
        anchor = home if within_home else Path(self.disk_path.anchor)
        segments = [("主目录" if within_home else "计算机", anchor)]
        current = anchor
        for part in self.disk_path.relative_to(anchor).parts:
            current = current / part
            segments.append((part, current))
        limit = 3 if getattr(self, "narrow_layout", False) else 4
        visible = segments if len(segments) <= limit else [segments[0], None, *segments[-(limit - 2):]]
        for index, segment in enumerate(visible):
            if index:
                self.breadcrumbs.append(label("›", "muted"))
            if segment is None:
                menu = Gtk.MenuButton(label="…", tooltip_text="展开中间目录")
                popover = Gtk.Popover()
                choices = box(spacing=2)
                for name, path in segments[1:-(limit - 2)]:
                    item = button(name, lambda _, target=path: (popover.popdown(), self.open_disk_path(target)))
                    item.set_tooltip_text(str(path))
                    choices.append(item)
                scroll = Gtk.ScrolledWindow(max_content_height=300, propagate_natural_height=True)
                scroll.set_child(choices)
                popover.set_child(scroll)
                menu.set_popover(popover)
                self.breadcrumbs.append(menu)
                continue
            name, path = segment
            crumb = button(name, lambda _, target=path: self.open_disk_path(target))
            crumb.set_tooltip_text(str(path))
            text = crumb.get_child()
            text.set_ellipsize(3)
            text.set_max_width_chars(14)
            if path == self.disk_path:
                crumb.add_css_class("current-path")
            self.breadcrumbs.append(crumb)

    def select_disk_entry(self, entry):
        if self.disk_mutating or "disk" in self.jobs:
            return
        self.disk_selected = entry if any(entry is e for e in self.current_disk_scan.entries) else None
        self.disk_delete.set_sensitive(True)
        row = self.disk_results.get_first_child()
        while row is not None:
            if getattr(row, "mio_entry", None) is self.disk_selected and self.disk_results.get_selected_row() is not row:
                self.disk_results.select_row(row)
                break
            row = row.get_next_sibling()
        total = self.current_disk_scan.size
        percent = f"{entry.size / total:.1%}" if total else "0%"
        incomplete = " · 未完整扫描" if not entry.complete else ""
        self.disk_selection.set_label(f"{entry.path.name} · {human_size(entry.size)} · {percent}{incomplete}")
        self.disk_selection_path.set_label(str(entry.path))

    def show_disk(self, scan):
        self.dismiss_context_menu()
        self.disk_selected = None
        self.disk_delete.set_sensitive(True)
        self.disk_path = scan.root
        self.current_disk_scan = scan
        self.disk_visible_limit = 100
        self.disk_search.set_text("")
        self.update_breadcrumbs()
        self.disk_summary.set_label(f"{human_size(scan.size)}  已扫描文件体积")
        self.disk_note.set_label(f"{self.scan_note(scan)} · {len(scan.entries):,} 个直接子项")
        self.treemap.set_entries(scan.entries)
        self.disk_selection.set_label("单击方块选中 · 双击文件夹进入")
        self.disk_selection_path.set_label(str(scan.root))
        self.render_disk_list()

    def render_disk_list(self):
        if not hasattr(self, "current_disk_scan"):
            return
        self.dismiss_context_menu()
        clear(self.disk_results)
        scan = self.current_disk_scan
        query = self.disk_search.get_text().casefold()
        entries = sorted((e for e in scan.entries if query in e.path.name.casefold()), key=lambda e: (-e.size, e.path.name.casefold()))
        for entry in entries[:self.disk_visible_limit]:
            row = Gtk.ListBoxRow(activatable=True)
            content = box(False, 8, "result-row")
            content.append(Gtk.Image(icon_name="folder-symbolic" if entry.is_dir else "text-x-generic-symbolic"))
            name = label(entry.path.name)
            name.set_ellipsize(3)
            name.set_hexpand(True)
            name.set_width_chars(8)
            content.append(name)
            content.append(label(human_size(entry.size), "small muted"))
            row.set_child(content)
            row.set_tooltip_text(f"{entry.path}\n{'目录' if entry.is_dir else '文件'} · {entry.files:,} 个文件{' · 未完整扫描' if not entry.complete else ''}")
            row.mio_entry = entry
            # Native row activation provides the keyboard alternative to the map.
            self.disk_results.append(row)
        if not entries:
            self.disk_results.append(label("没有匹配的项目", "muted"))
        elif len(entries) > self.disk_visible_limit:
            more = button(f"再显示 100 项（共 {len(entries):,}）", self.more_disk_entries)
            self.disk_results.append(more)

    def select_disk_row(self, listbox, row):
        entry = getattr(row, "mio_entry", None)
        if entry is not None:
            self.treemap.select(entry)

    def activate_disk_entry(self, entry):
        if self.disk_mutating or "disk" in self.jobs:
            return
        self.treemap.select(entry)
        if entry.is_dir:
            self.open_disk_path(entry.path)

    def activate_disk_row(self, listbox, row):
        entry = getattr(row, "mio_entry", None)
        if entry is not None:
            self.activate_disk_entry(entry)

    def more_disk_entries(self, *_):
        self.disk_visible_limit += 100
        self.render_disk_list()

    def build_apps(self):
        page = self.page("apps", "04 / APPLICATIONS", "桌面应用，一目了然。", "读取桌面环境中的应用入口，包括系统安装和用户安装的可见应用。")
        self.app_search = Gtk.SearchEntry(placeholder_text="搜索应用名称或入口 ID")
        self.app_search.connect("search-changed", lambda _: self.filter_apps())
        page.append(self.app_search)
        self.apps_note = label("读取中…", "small muted")
        page.append(self.apps_note)
        self.app_results = self.results_list()
        page.append(self.app_results)
        page.append(label("下方按软件包来源卸载，保留用户配置。桌面入口与软件包名称可能不同。", "small muted", wrap=True))
        self.package_section = box()
        page.append(self.package_section)
        self.app_items = []

    def load_apps(self):
        self.app_items = sorted([info for info in Gio.AppInfo.get_all() if info.should_show()], key=lambda info: info.get_display_name().casefold())
        self.completed.add("apps")
        self.filter_apps()

    def filter_apps(self):
        clear(self.app_results)
        query = self.app_search.get_text().casefold()
        matches = [info for info in self.app_items if query in f"{info.get_display_name()} {info.get_id()}".casefold()]
        self.apps_note.set_label(f"显示 {len(matches)} / {len(self.app_items)} 个桌面应用")
        for info in matches:
            row = Adw.ActionRow(title=GLib.markup_escape_text(info.get_display_name()), subtitle=GLib.markup_escape_text(info.get_id() or "桌面应用"))
            icon = info.get_icon()
            row.add_prefix(Gtk.Image.new_from_gicon(icon) if icon else Gtk.Image(icon_name="application-x-executable-symbolic"))
            row.set_tooltip_text(info.get_description() or info.get_display_name())
            self.app_results.append(row)
        if not matches:
            self.app_results.append(Adw.ActionRow(title="没有匹配的桌面应用"))


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.jamesbbbriz.Mio", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        Gtk.IconTheme.get_for_display(self.get_display()).add_search_path(str(Path.home() / ".local/share/icons"))
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS + (Path(__file__).with_name("anime.css")).read_text())
        Gtk.StyleContext.add_provider_for_display(self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        self.window = Window(self)
        self.window.present()

    def get_display(self):
        from gi.repository import Gdk
        return Gdk.Display.get_default()


def main():
    return Application().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
