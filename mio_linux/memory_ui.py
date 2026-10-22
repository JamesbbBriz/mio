"""Native memory diagnosis, orphan evidence and exact-process confirmation."""
from collections import defaultdict
import os
import threading
import time
from gi.repository import GLib, Gtk
from .backend import human_size
from .processes import ProcessMonitor, LABELS
from .process_actions import request_exit


class MemoryUI:
    def build_memory(self):
        from .app import box, button, flow, label
        self.memory_monitor = ProcessMonitor()
        self.memory_snapshot = None
        self.memory_selected = {}
        self.memory_scanning = False
        self.memory_reviewing = False
        self.memory_limit = 100
        page = self.page('memory', '06 / MEMORY', '谁占着内存，一眼看清。',
                         '琥珀持续观察父进程变化，帮你找出孤儿线索。先看证据，再决定是否关闭。')
        controls = flow()
        self.memory_refresh = button('刷新诊断', lambda _: self.start_memory(manual=True), 'suggested-action')
        controls.append(self.memory_refresh)
        self.memory_spinner = Gtk.Spinner()
        controls.append(self.memory_spinner)
        self.memory_watch = Gtk.CheckButton(label='持续观察（每 5 秒）', active=True)
        controls.append(self.memory_watch)
        self.memory_mine = Gtk.CheckButton(label='仅我的进程', active=True)
        self.memory_mine.connect('toggled', lambda _: self.render_memory())
        controls.append(self.memory_mine)
        page.append(controls)
        self.memory_summary = label('打开页面开始诊断', 'section-title', wrap=True)
        self.memory_health = label('内存、Swap 与等待压力', 'small muted', wrap=True)
        page.append(self.memory_summary)
        page.append(self.memory_health)
        self.memory_evidence = label('“已观察到孤儿”需要看到父进程退出和接管变化；首次发现已被接管的进程只能算疑似。正常后台应用也可能这样运行。采样无法保证发现所有孤儿。', 'character-note', wrap=True)
        page.append(self.memory_evidence)
        filters = flow()
        self.memory_filter = Gtk.DropDown.new_from_strings(['全部进程 · 按占用排序', '孤儿线索优先', '僵尸进程', '托管服务'])
        self.memory_filter.connect('notify::selected', lambda *_: self.render_memory())
        filters.append(self.memory_filter)
        self.memory_search = Gtk.SearchEntry(placeholder_text='搜索应用、进程名或 PID')
        self.memory_search.connect('search-changed', lambda _: self.render_memory())
        filters.append(self.memory_search)
        page.append(filters)
        actions = flow()
        self.memory_close = button('请求退出所选…', lambda _: self.review_memory_exit())
        self.memory_close.set_sensitive(False)
        actions.append(self.memory_close)
        actions.append(button('清空选择', lambda _: self.clear_memory_selection()))
        self.memory_selection_note = label('未选择进程', 'small muted', wrap=True)
        page.append(actions)
        page.append(self.memory_selection_note)
        self.memory_action_note = label('先保存工作再确认关闭。仅请求所选进程退出，不会强制结束；不会自动处理孤儿。', 'small muted', wrap=True)
        page.append(self.memory_action_note)
        self.memory_note = label('诊断尚未开始', 'small muted', wrap=True)
        page.append(self.memory_note)
        self.memory_rows = box(spacing=8)
        page.append(label('按可执行程序分组 · 点击展开查看 PID 与证据', 'small muted', wrap=True))
        page.append(self.memory_rows)
        page.append(label('RSS 含共享内存，多个进程相加可能重复；PSS 按共享比例分摊，权限允许时显示。显示占用不等于可释放量。僵尸已经退出，应由父进程回收。', 'small muted', wrap=True))
        self.memory_timer = GLib.timeout_add_seconds(5, self.memory_tick)

    def memory_tick(self):
        if self.cancel.is_set():
            return False
        if self.memory_snapshot is not None and self.memory_watch.get_active():
            self.start_memory()
        return True

    def start_memory(self, manual=False):
        if self.memory_scanning or self.memory_reviewing or self.operation_busy:
            return
        if self.memory_selected and not manual:
            return
        if manual:
            self.memory_selected.clear()
        self.memory_scanning = True
        self.memory_refresh.set_sensitive(False)
        self.memory_close.set_sensitive(False)
        self.memory_spinner.start()
        self.memory_note.set_label('正在读取本机进程，界面仍可操作…')
        def finish(snapshot, error):
            self.memory_scanning = False
            if self.cancel.is_set():
                return False
            self.memory_refresh.set_sensitive(True)
            self.memory_spinner.stop()
            if error:
                self.memory_note.set_label(f'诊断未完成：{error}；保留上次结果')
            else:
                self.show_memory(snapshot)
            return False
        def worker():
            try:
                snapshot = self.memory_monitor.scan(self.cancel)
            except Exception as error:
                GLib.idle_add(finish, None, error)
            else:
                GLib.idle_add(finish, snapshot, None)
        threading.Thread(target=worker, daemon=True, name='mio-memory-scan').start()

    def show_memory(self, snapshot):
        self.memory_snapshot = snapshot
        self.memory_selected.clear()
        observed = sum(p.orphan_observed for p in snapshot.processes)
        suspected = sum(p.category == 'suspected' for p in snapshot.processes)
        zombies = sum(p.category == 'zombie' for p in snapshot.processes)
        self.memory_summary.set_label(f'可用 {human_size(snapshot.available)} / {human_size(snapshot.total)} · 已观察到孤儿 {observed} · 疑似 {suspected} · 僵尸 {zombies}')
        pressure = f'{snapshot.pressure:.2f}%' if snapshot.pressure is not None else '不可用'
        self.memory_health.set_label(f'Swap {human_size(snapshot.swap_used)} / {human_size(snapshot.swap_total)} · 内存等待占比（近 10 秒）{pressure}')
        state = '部分结果（达到上限或已取消）' if snapshot.partial else '本轮采样完成'
        self.memory_note.set_label(f'{time.strftime("%H:%M:%S", time.localtime(snapshot.captured_at))} · {state} · {len(snapshot.processes)} 个进程 · {snapshot.skipped} 项退出或无法读取 · {snapshot.elapsed:.2f} 秒')
        self.render_memory()

    def clear_memory_selection(self):
        if self.memory_reviewing:
            return
        self.memory_selected.clear()
        self.render_memory()

    def update_memory_selection(self, check, process):
        if check.get_active():
            self.memory_selected[process.identity] = process
        else:
            self.memory_selected.pop(process.identity, None)
        self.update_memory_actions()

    def update_memory_actions(self):
        count = len(self.memory_selected)
        self.memory_close.set_sensitive(0 < count <= 64 and not self.memory_scanning and not self.memory_reviewing and not self.operation_busy)
        self.memory_selection_note.set_label(f'已选 {count} 个进程 · 选择期间暂停自动更新 · 每次最多 64 个' if count else '未选择进程')

    def render_memory(self):
        from .app import box, button, clear, label
        if self.memory_snapshot is None:
            return
        clear(self.memory_rows)
        query = self.memory_search.get_text().casefold().strip()
        mode = self.memory_filter.get_selected()
        groups = defaultdict(list)
        for process in self.memory_snapshot.processes:
            if self.memory_mine.get_active() and process.uid != os.getuid():
                continue
            if query and query not in f'{process.app} {process.name} {process.pid} {process.exe}'.casefold():
                continue
            if mode == 1 and not process.orphan_observed and process.category != 'suspected':
                continue
            if mode == 2 and process.category != 'zombie':
                continue
            if mode == 3 and process.category != 'managed':
                continue
            groups[(process.exe or process.name, process.uid)].append(process)
        priority = {'observed': 0, 'suspected': 1}
        items = sorted(groups.values(), key=lambda group: (min(0 if p.orphan_observed else priority.get(p.category, 2) for p in group) if mode == 1 else 0, -sum(p.rss for p in group)))
        shown = 0
        for group in items:
            if shown >= self.memory_limit:
                break
            group = sorted(group, key=lambda p: (-p.rss, p.pid))
            total = sum(p.rss for p in group)
            heading = label(f'{group[0].app} · RSS {human_size(total)} · {len(group)} 个进程', 'section-title', wrap=True)
            expander = Gtk.Expander(expanded=(mode != 0 or bool(query) or len(items) <= 3))
            expander.set_label_widget(heading)
            expander.add_css_class('memory-group')
            children = box(spacing=8)
            choose = button('选择此组可关闭进程', lambda _, entries=tuple(group): self.select_memory_group(entries))
            choose.set_sensitive(any(not p.protected for p in group) and not self.memory_reviewing and not self.memory_scanning)
            children.append(choose)
            visible_group = group[:max(0, self.memory_limit - shown)]
            for p in visible_group:
                content = box(spacing=4, css='memory-process')
                check = Gtk.CheckButton()
                check.set_child(label(f'{p.name} · PID {p.pid}', wrap=True))
                check.set_active(p.identity in self.memory_selected)
                check.set_sensitive(not p.protected and not self.memory_scanning and not self.memory_reviewing)
                check.connect('toggled', self.update_memory_selection, p)
                content.append(check)
                pss = human_size(p.pss) if p.pss is not None else '不可用'
                content.append(label(f'RSS {human_size(p.rss)} · PSS {pss} · Swap {human_size(p.swap)} · 父 PID {p.ppid}', 'small muted', wrap=True))
                content.append(label(LABELS[p.category] + ' · ' + p.evidence, 'small', wrap=True))
                if p.protected:
                    content.append(label('只读：' + p.protected, 'small muted', wrap=True))
                path = label(p.exe or '程序路径不可读', 'small muted', wrap=True)
                content.append(path)
                children.append(content)
                shown += 1
            if len(visible_group) < len(group):
                children.append(label('此组还有未显示的进程；展开更多后可逐项检查。', 'small muted', wrap=True))
            expander.set_child(children)
            self.memory_rows.append(expander)
        if not items:
            self.memory_rows.append(label('本轮没有匹配的进程。未观察到孤儿，不代表后台进程都已被排除。', 'muted', wrap=True))
        total_count = sum(len(group) for group in items)
        if shown < total_count:
            self.memory_rows.append(button(f'再显示 100 个（当前 {shown} / {total_count}）', self.more_memory))
        self.update_memory_actions()

    def more_memory(self, *_):
        self.memory_limit += 100
        self.render_memory()

    def select_memory_group(self, entries):
        if self.memory_scanning or self.memory_reviewing:
            return
        allowed = [p for p in entries if not p.protected]
        combined = dict(self.memory_selected)
        combined.update((p.identity, p) for p in allowed)
        if len(combined) > 64:
            self.memory_action_note.set_label('这组超过单次 64 个进程上限，请逐项选择。')
            return
        self.memory_selected = combined
        self.render_memory()

    def review_memory_exit(self):
        if self.memory_scanning or self.memory_reviewing or self.operation_busy:
            return
        plan = tuple(self.memory_selected.values())
        if not plan or len(plan) > 64:
            self.memory_action_note.set_label('请选择 1–64 个可关闭的进程')
            return
        self.memory_reviewing = True
        self.render_memory()
        listing = '\n\n'.join(f'{p.app} / {p.name} · PID {p.pid} · RSS {human_size(p.rss)}\n{p.exe}\n{LABELS[p.category]}：{p.evidence}' for p in plan)
        self.confirm_operation('请求所选进程退出？',
            '请先保存工作，退出可能丢失未保存的内容。\n只向下列进程发送 SIGTERM，不强制结束，也不会自动扩大到其他进程。\n孤儿标签不代表可以放心关闭；占用量不等于释放量。\n\n' + listing,
            lambda: self.execute_memory_exit(plan))
        def response(_, response_id):
            if response_id != 'execute':
                self.memory_reviewing = False
                self.render_memory()
        self.last_review_dialog.connect('response', response)

    def execute_memory_exit(self, plan):
        # Always release the review lock, including validation failures.
        def work():
            try:
                return request_exit(plan, self.operation_cancel), None
            except Exception as error:
                return [], str(error)
        def done(result):
            results, error = result
            self.memory_reviewing = False
            self.memory_selected.clear()
            if error:
                self.memory_action_note.set_label('未发送退出请求：' + error)
            else:
                exited = sum(item.state == 'exited' for item in results)
                pending = sum(item.state == 'requested' for item in results)
                refused = sum(item.state == 'refused' for item in results)
                details = '\n'.join(f'{item.name}（PID {item.pid}）：{item.detail}' for item in results if item.state != 'exited')
                self.memory_action_note.set_label(f'已确认退出 {exited} · 尚未确认 {pending} · 未发送 {refused}\n{details}\n内存用量将重新采样，不按原占用量宣称已释放。')
            self.render_memory()
            self.start_memory()
        self.operation(work, done, self.memory_action_note)
