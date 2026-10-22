"""Bounded Linux process/memory snapshots and evidence-based orphan diagnosis.

Read-only: process control lives in process_actions.py. Parent PID alone never
proves a process is unwanted. Identities include kernel start ticks, not names.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import time

PROC = Path('/proc')
CRITICAL = {'systemd', 'init', 'dbus-daemon', 'dbus-broker', 'dbus-broker-launch',
            'gnome-shell', 'gnome-session-binary', 'gnome-session', 'plasmashell',
            'kwin_wayland', 'kwin_x11', 'Xorg', 'Xwayland', 'gdm', 'gdm3', 'sddm',
            'sshd', 'pipewire', 'pipewire-pulse', 'wireplumber', 'pulseaudio',
            'cinnamon', 'xfce4-session', 'xfwm4', 'sway', 'weston', 'login', 'systemd-logind'}
LABELS = {'observed': '已观察到孤儿', 'suspected': '疑似孤儿', 'zombie': '僵尸进程',
          'managed': '托管服务', 'normal': '普通进程', 'unknown': '信息不完整'}


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    start: int
    name: str
    state: str
    uid: int
    uids: tuple
    rss: int
    swap: int
    session: int
    exe: str
    exe_id: tuple
    cgroup: str
    pss: int | None = None
    category: str = 'normal'
    evidence: str = ''
    protected: str = ''
    complete: bool = True
    orphan_observed: bool = False

    @property
    def identity(self):
        return self.pid, self.start

    @property
    def app(self):
        return Path(self.exe.removesuffix(' (deleted)')).name if self.exe else self.name

    @property
    def fingerprint(self):
        return self.identity, self.uids, self.exe, self.exe_id, self.cgroup


@dataclass
class MemorySnapshot:
    processes: list = field(default_factory=list)
    total: int = 0
    available: int = 0
    swap_total: int = 0
    swap_used: int = 0
    pressure: float | None = None
    partial: bool = False
    skipped: int = 0
    captured_at: float = field(default_factory=time.time)
    elapsed: float = 0
    enumerated: set = field(default_factory=set)
    enumeration_complete: bool = True


def read_text(path, limit=65536):
    with path.open('r', errors='replace') as stream:
        text = stream.read(limit + 1)
    if len(text) > limit:
        raise ValueError('进程信息超出读取上限')
    return text


def parse_stat(text):
    end = text.rfind(')')
    start = text.find('(')
    fields = text[end + 2:].split()
    if start < 0 or end < start or len(fields) < 22:
        raise ValueError('进程状态不完整')
    return (int(text[:start]), text[start + 1:end], fields[0], int(fields[1]),
            int(fields[3]), int(fields[19]), max(0, int(fields[21])) * os.sysconf('SC_PAGE_SIZE'))


def service_unit(cgroup):
    # user@UID.service is an ancestor of normal desktop app scopes, not their
    # owner unit. Inspect the nearest unit (including .scope), never a substring.
    for line in cgroup.splitlines():
        path = line.split(':', 2)[-1]
        for part in reversed(path.split('/')):
            if part.endswith('.service'):
                return part
            if part.endswith('.scope'):
                break
    return ''


def read_process(pid, proc=PROC, detailed=False):
    directory = proc / str(pid)
    stat = parse_stat(read_text(directory / 'stat', 8192))
    if stat[0] != pid:
        raise ValueError('进程编号变化')
    status = {}
    for line in read_text(directory / 'status').splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            status[key] = value.strip()
    uids = tuple(map(int, status['Uid'].split()))
    if len(uids) != 4:
        raise ValueError('无法确认进程所有者')
    rss = int(status.get('VmRSS', str(stat[6] // 1024)).split()[0]) * 1024
    swap = int(status.get('VmSwap', '0').split()[0]) * 1024
    complete = True
    try:
        cgroup = read_text(directory / 'cgroup')
    except (OSError, ValueError):
        cgroup, complete = '', False
    try:
        exe = os.readlink(directory / 'exe')
        info = (directory / 'exe').stat()
        exe_id = (info.st_dev, info.st_ino)
    except OSError:
        exe, exe_id, complete = '', (), False
    pss = None
    if detailed and stat[2] != 'Z':
        try:
            for line in read_text(directory / 'smaps_rollup').splitlines():
                if line.startswith('Pss:'):
                    pss = int(line.split()[1]) * 1024
                    break
        except (OSError, ValueError):
            pass  # RSS remains available; never label it PSS.
    final = parse_stat(read_text(directory / 'stat', 8192))
    if (stat[0], stat[3], stat[5]) != (final[0], final[3], final[5]):
        raise ValueError('采样期间进程身份或父进程变化')
    return Process(pid, stat[3], stat[5], stat[1], final[2], uids[0], uids,
                   max(0, rss), max(0, swap), stat[4], exe, exe_id, cgroup,
                   pss=pss, complete=complete)


def protected_reason(process, current_uid=None):
    uid = os.getuid() if current_uid is None else current_uid
    if process.pid <= 1:
        return '系统基础进程'
    if process.state == 'Z':
        return '僵尸已退出，需由父进程回收，不能再次结束来释放内存'
    if process.state in ('X', 'x'):
        return '进程已退出'
    if process.uids != (uid,) * 4 or uid == 0:
        return '仅允许操作当前普通用户自己的进程'
    if not process.complete or not process.exe_id:
        return '身份或托管信息不完整，无法安全操作'
    if process.name in CRITICAL or process.app in CRITICAL:
        return '桌面会话或基础服务'
    if service_unit(process.cgroup):
        return '由服务管理器托管，请在对应服务中管理'
    return ''


def relatives(processes, own_pid):
    """Protect Mio, its ancestors and its descendants, with cycle bounds."""
    by_pid = {p.pid: p for p in processes}
    protected, pid = {own_pid}, own_pid
    for _ in range(128):
        p = by_pid.get(pid)
        if p is None or p.ppid in protected or p.ppid <= 0:
            break
        pid = p.ppid
        protected.add(pid)
    for p in processes:
        seen, pid = set(), p.pid
        for _ in range(128):
            if pid == own_pid:
                protected.add(p.pid)
                break
            if pid in seen or pid not in by_pid:
                break
            seen.add(pid)
            pid = by_pid[pid].ppid
    return protected


class ProcessMonitor:
    def __init__(self, proc=PROC):
        self.proc = Path(proc)
        self.previous = {}
        self.orphans = {}

    def diagnose(self, snapshot, own_pid=None, uid=None):
        current = {p.pid: p for p in snapshot.processes}
        related = relatives(snapshot.processes, os.getpid() if own_pid is None else own_pid)
        observations = {}
        for p in snapshot.processes:
            previous = self.previous.get(p.pid)
            evidence = self.orphans.get(p.identity, '')
            if previous and previous.identity == p.identity and previous.ppid != p.ppid:
                old_parent = self.previous.get(previous.ppid)
                new_old_parent = current.get(previous.ppid)
                old_gone = ((new_old_parent is not None and old_parent is not None and
                             (new_old_parent.identity != old_parent.identity or new_old_parent.state in ('Z', 'X', 'x'))) or
                            (snapshot.enumeration_complete and previous.ppid not in snapshot.enumerated))
                if old_parent is not None and old_gone:
                    evidence = f'连续采样观察到父进程 {previous.ppid}（{old_parent.name}）退出；现由 PID {p.ppid} 接管。父进程退出不代表此进程无用。'
            if evidence:
                observations[p.identity] = evidence
            parent = current.get(p.ppid)
            adopted = p.ppid == 1 or (parent is not None and parent.app in {'systemd', 'init'})
            reason = protected_reason(p, uid)
            if p.pid in related:
                reason = 'Mio 本身、启动链或工作进程'
            if p.state == 'Z':
                category, detail = 'zombie', f'已结束，等待父进程 PID {p.ppid} 回收；不能通过再次关闭来释放内存。'
            elif service_unit(p.cgroup) or p.app in CRITICAL or p.name in CRITICAL:
                category, detail = 'managed', '服务或会话组件；后台运行属于正常生命周期。'
                if evidence:
                    detail += ' ' + evidence
            elif evidence:
                category, detail = 'observed', evidence
            elif not p.complete:
                category, detail = 'unknown', '读取权限或进程变化导致信息不完整，无法判断是否孤儿。'
            elif adopted:
                category, detail = 'suspected', f'当前父进程为 PID {p.ppid}，未观察到原父进程退出；也可能是主动后台运行或正常启动的应用。'
            else:
                category, detail = 'normal', f'父进程 PID {p.ppid}；本次未发现孤儿证据。'
            current[p.pid] = replace(p, category=category, evidence=detail, protected=reason, orphan_observed=bool(evidence))
        self.orphans = observations
        self.previous = current
        snapshot.processes = sorted(current.values(), key=lambda p: (-p.rss, p.pid))
        return snapshot

    def scan(self, cancel=None, max_processes=4096, max_seconds=4):
        start = time.monotonic()
        result = MemorySnapshot()
        values = {}
        for line in read_text(self.proc / 'meminfo').splitlines():
            key, value = line.split(':', 1)
            values[key] = int(value.split()[0]) * 1024
        result.total = values['MemTotal']
        result.available = values.get('MemAvailable', values.get('MemFree', 0))
        result.swap_total = values.get('SwapTotal', 0)
        result.swap_used = max(0, result.swap_total - values.get('SwapFree', 0))
        try:
            for line in read_text(self.proc / 'pressure/memory').splitlines():
                if line.startswith('some '):
                    result.pressure = float(dict(item.split('=') for item in line.split()[1:])['avg10'])
        except (OSError, ValueError, KeyError):
            pass
        with os.scandir(self.proc) as directories:
            for entry in directories:
                if entry.name.isdecimal():
                    if len(result.enumerated) >= max_processes or time.monotonic() - start >= max_seconds or (cancel and cancel.is_set()):
                        result.partial, result.enumeration_complete = True, False
                        break
                    result.enumerated.add(int(entry.name))
        for pid in sorted(result.enumerated):
            if time.monotonic() - start >= max_seconds or (cancel and cancel.is_set()):
                result.partial = True
                break
            try:
                result.processes.append(read_process(pid, self.proc))
            except (OSError, ValueError, KeyError):
                result.skipped += 1
        # Detailed proportional memory is optional and budgeted. Never add RSS
        # across apps and call that reclaimable memory; shared pages repeat.
        for p in sorted(result.processes, key=lambda p: -p.rss)[:32]:
            if time.monotonic() - start >= max_seconds or (cancel and cancel.is_set()):
                break
            if p.uid == os.getuid() and p.rss:
                try:
                    detailed = read_process(p.pid, self.proc, detailed=True)
                    if detailed.identity == p.identity:
                        result.processes[result.processes.index(p)] = detailed
                except (OSError, ValueError, KeyError):
                    pass
        result.elapsed = time.monotonic() - start
        return self.diagnose(result)
