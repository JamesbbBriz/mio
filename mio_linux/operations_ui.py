"""Native review surfaces for recovery and system transactions."""
from pathlib import Path
import json
import shlex
import threading
from gi.repository import Adw, GLib, Gtk
from . import packages
from .backend import human_size
from .recovery import plan_cache
from .system_trash import SystemTrash


class OperationsUI:
    def setup_operations(self):
        from .app import label, button
        self.operation_busy = False
        self.operation_cancel = threading.Event()
        self.cache_choices = []
        self.package_items = []
        self.transaction = None
        self.recovery = SystemTrash()
        self.cache_review = button('审阅所选缓存文件', lambda _: self.review_cache())
        self.cache_controls.append(self.cache_review)
        self.cache_controls.append(button('停止操作', lambda _: self.operation_cancel.set()))
        self.cache_controls.append(button('打开系统回收站 ↗', lambda _: self.open_system_trash()))
        legacy = Path.home() / '.local/share/mio/recovery'
        if legacy.is_dir() and any(legacy.glob('*.file')):
            self.cache_controls.append(button('迁移旧版回收文件', lambda _: self.review_legacy_migration()))
        page = self.page('maintenance', '05 / MAINTENANCE', '系统维护，交给系统。', '操作将在桌面终端中运行。你可以查看完整输出、输入管理员密码并确认实际变更。')
        self.maintenance_note = label('尚未运行操作', 'small muted', wrap=True)
        page.append(self.maintenance_note)
        for key, (title, detail, argv) in packages.MAINTENANCE.items():
            row = Adw.ActionRow(title=title, subtitle=detail)
            row.add_suffix(button('审阅', lambda _, k=key: self.review_maintenance(k)))
            group = self.results_list()
            group.append(row)
            page.append(group)
        self.package_section.append(button('刷新软件包清单', lambda _: self.load_packages()))
        self.package_search = Gtk.SearchEntry(placeholder_text='搜索已安装软件包（APT / Snap / Flatpak）')
        self.package_search.connect('search-changed', lambda _: self.render_packages())
        self.package_section.append(self.package_search)
        self.package_note = label('点击刷新获取真实软件包清单', 'small muted', wrap=True)
        self.package_section.append(self.package_note)
        self.package_rows = self.results_list()
        self.package_section.append(self.package_rows)
        self.operation_dialogs = []
        self.transaction_timer = GLib.timeout_add_seconds(2, self.poll_transaction)

    def operation(self, work, done, note):
        if self.operation_busy:
            note.set_label('另一项操作正在运行，请等待完成')
            return
        self.operation_busy = True
        self.operation_cancel = threading.Event()
        note.set_label('处理中…')
        def finish(value, error):
            self.operation_busy = False
            if self.cancel.is_set():
                return False
            if error:
                note.set_label(f'未完成：{error}')
            else:
                done(value)
            return False
        def worker():
            try:
                result = work()
            except Exception as error:
                GLib.idle_add(finish, None, error)
            else:
                GLib.idle_add(finish, result, None)
        threading.Thread(target=worker, daemon=True).start()

    def confirm_operation(self, title, text, callback, destructive=False):
        dialog = Adw.MessageDialog(transient_for=self, heading=title, body='请核对以下具体目标和影响。')
        view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(text)
        scroll = Gtk.ScrolledWindow(min_content_height=220, min_content_width=520, max_content_height=400)
        scroll.set_child(view)
        dialog.set_extra_child(scroll)
        dialog.add_response('cancel', '取消')
        dialog.add_response('execute', '确认永久删除' if destructive else '确认继续')
        dialog.set_response_appearance('execute', Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', lambda _, response: callback() if response == 'execute' else None)
        self.last_review_dialog = dialog
        dialog.present()

    def review_cache(self):
        if not hasattr(self, 'cache_scan'):
            self.cache_note.set_label('请先扫描缓存并勾选目录')
            return
        selected = [path for check, path in self.cache_choices if check.get_active()]
        if not selected:
            self.cache_note.set_label('请先勾选要清理的缓存目录')
            return
        def ready(plan):
            self.cache_note.set_label(f'可审阅 {len(plan)} 个超过 7 天、未检测到占用的普通文件')
            if not plan:
                return
            listing = '\n'.join(f'{human_size(item.stamp[2])}  {item.path}' for item in plan)
            self.confirm_operation('移入系统回收站？',
                '请先关闭相关应用。只移动以下文件，不移除目录。\n同盘移动不会释放空间；可在回收站恢复或永久删除。\n\n' + listing,
                lambda: self.execute_cache(plan))
        self.operation(lambda: plan_cache(self.cache_scan.root, selected, self.operation_cancel), ready, self.cache_note)

    def execute_cache(self, plan):
        def done(result):
            completed, errors = result
            self.cache_note.set_label(f'已移入回收站 {len(completed)} / {len(plan)} 项；尚未释放磁盘空间。' + ('\n' + '\n'.join(errors[:10]) if errors else ''))
            self.disk_nodes.clear()
            for check, _ in self.cache_choices:
                check.set_active(False)

        self.operation(lambda: self.recovery.batch(plan, 'move', self.operation_cancel), done, self.cache_note)

    def open_system_trash(self):
        from gi.repository import Gio
        try:
            Gio.AppInfo.launch_default_for_uri('trash:///', None)
        except GLib.Error as error:
            self.navigate('cache')
            self.cache_note.set_label(f'无法打开文件管理器：{error.message}')

    def review_legacy_migration(self):
        def ready(items):
            if not items:
                self.cache_note.set_label('没有旧版 Mio 回收文件需要迁移')
                return
            def execute():
                def done(result):
                    completed, errors = result
                    self.cache_note.set_label(f'已迁移 {len(completed)} / {len(items)} 项。' + '\n'.join(errors))
                self.operation(lambda: self.recovery.migrate_legacy(items, self.operation_cancel), done, self.cache_note)
            self.confirm_operation('迁移到系统回收站？',
                '以下文件将先恢复到原位置，再进入系统回收站。同名冲突时保留旧副本；如果第二步失败，文件保留在原位置。\n\n' + '\n'.join(item['path'] for item in items), execute)
        self.operation(self.recovery.legacy_records, ready, self.cache_note)

    def load_packages(self):
        def done(result):
            self.package_items, errors = result
            self.package_errors = errors
            self.render_packages()
        self.operation(packages.inventory, done, self.package_note)

    def render_packages(self):
        from .app import clear, button
        clear(self.package_rows)
        query = self.package_search.get_text().casefold()
        matches = [p for p in self.package_items if query in f'{p.provider} {p.name} {p.scope}'.casefold()]
        self.package_note.set_label(f'{len(matches)} 个匹配软件包，显示前 100 项；可搜索缩小范围。\n' + '\n'.join(getattr(self, 'package_errors', [])))
        for package in matches[:100]:
            row = Adw.ActionRow(title=GLib.markup_escape_text(package.name), subtitle=GLib.markup_escape_text(f'{package.provider.upper()} · {package.scope} · {package.version}'))
            row.add_suffix(button('卸载…', lambda _, p=package: self.review_package(p)))
            self.package_rows.append(row)

    def review_package(self, package):
        def ready(text):
            self.package_note.set_label('审阅已生成；实际依赖变更以包管理器最终确认内容为准')
            argv = packages.uninstall_command(package)
            self.confirm_operation('卸载 ' + package.name + '？', text + '\n\n' + shlex.join(argv), lambda: self.start_transaction(argv))
        self.operation(lambda: packages.review_uninstall(package), ready, self.package_note)

    def review_maintenance(self, key):
        title, detail, argv = packages.MAINTENANCE[key]
        self.confirm_operation(title, detail + '\n\n' + shlex.join(argv), lambda: self.start_transaction(argv))

    def start_transaction(self, argv):
        if self.transaction:
            self.maintenance_note.set_label('已有终端事务等待完成，请先完成或关闭该事务')
            self.navigate('maintenance')
            return
        try:
            self.transaction = packages.launch(argv)
            self.maintenance_note.set_label('已请求打开终端；等待终端确认与操作结果。未收到结果前不表示成功。')
        except (OSError, ValueError) as error:
            self.maintenance_note.set_label(str(error))
        self.navigate('maintenance')

    def poll_transaction(self):
        if self.cancel.is_set():
            return False
        if self.transaction and self.transaction.exists():
            try:
                result = json.loads(self.transaction.read_text())
                state = result['state']
                if state == 'running':
                    self.maintenance_note.set_label('终端事务进行中或等待确认，请查看终端窗口')
                else:
                    status = result.get('returncode')
                    self.maintenance_note.set_label('操作成功完成（退出状态 0）' if state == 'finished' and status == 0 else f'操作未成功完成：{state} / {status} {result.get("error", "")}')
                    self.transaction = None
                    self.package_items = []
                    self.package_note.set_label('系统状态已变化，请刷新软件包清单')
            except (OSError, ValueError, KeyError):
                pass
        return True
