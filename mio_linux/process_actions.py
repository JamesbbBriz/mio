"""Explicit, reviewed SIGTERM requests bound to Linux pidfds. No force kill."""
from dataclasses import dataclass
import os
import select
import signal
import time
from .processes import PROC, read_process, protected_reason


@dataclass(frozen=True)
class ExitResult:
    pid: int
    name: str
    state: str
    detail: str


def check_relationship(pid, proc=PROC):
    own = os.getpid()
    def chain(start):
        seen = set()
        for _ in range(128):
            if start <= 0:
                return seen
            if start in seen:
                raise ValueError('父进程链异常，未发送退出请求')
            seen.add(start)
            if start == 1:
                return seen
            start = read_process(start, proc).ppid
        raise ValueError('父进程链过深，未发送退出请求')
    if pid in chain(own) or own in chain(pid):
        raise ValueError('不能关闭 Mio 本身、启动链或工作进程')


def validate_process(reviewed, proc=PROC):
    current = read_process(reviewed.pid, proc)
    if current.fingerprint != reviewed.fingerprint:
        raise ValueError('进程身份、程序或托管关系已变化，请重新扫描并确认')
    reason = protected_reason(current)
    if reason:
        raise ValueError(reason)
    check_relationship(current.pid, proc)
    return current


def request_exit(processes, cancel=None, wait_seconds=3):
    """Validate the whole reviewed set, then signal only pinned process handles.

    Opening pidfds before re-reading /proc prevents a reused PID from becoming
    the recipient. A process can exec after final validation; the handle still
    refers to the same process, never another PID generation.
    """
    plan = tuple(processes)
    if not plan or len(plan) > 64 or len({p.pid for p in plan}) != len(plan):
        raise ValueError('每次请选择 1–64 个不同进程')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise ValueError('当前内核或 Python 不支持安全进程句柄，未发送请求')
    handles = []
    deadline = time.monotonic() + 8
    def check():
        if cancel and cancel.is_set():
            raise ValueError('操作已取消，未继续发送退出请求')
        if time.monotonic() > deadline:
            raise ValueError('检查超时，未继续发送退出请求')
    try:
        # Nothing is signalled if any member fails initial validation.
        for process in plan:
            check()
            fd = os.pidfd_open(process.pid, 0)
            handles.append((process, fd))
            validate_process(process)
        results, pending = [], {}
        for process, fd in handles:
            try:
                check()
                validate_process(process)
                check()
                signal.pidfd_send_signal(fd, signal.SIGTERM, None, 0)
                pending[fd] = process
            except (OSError, ValueError) as error:
                results.append(ExitResult(process.pid, process.name, 'refused', str(error)))
        # Observe actual exit. A successful send is not an exit, and RSS is not
        # a claim about reclaimed RAM. The wait is bounded for the entire batch.
        poller = select.poll()
        for fd in pending:
            poller.register(fd, select.POLLIN)
        end = time.monotonic() + min(5, max(0, wait_seconds))
        while pending:
            timeout = max(0, min(100, int((end - time.monotonic()) * 1000)))
            for fd, events in poller.poll(timeout):
                if events & select.POLLIN:
                    process = pending.pop(fd)
                    poller.unregister(fd)
                    results.append(ExitResult(process.pid, process.name, 'exited', '已确认退出'))
            if time.monotonic() >= end or (cancel and cancel.is_set()):
                break
        results.extend(ExitResult(p.pid, p.name, 'requested', '已发送退出请求，尚未确认退出；未强制结束') for p in pending.values())
        return results
    finally:
        for _, fd in handles:
            os.close(fd)
