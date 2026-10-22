"""Owned three-generation process tree; no host process is signalled."""
import ctypes
import os
import signal
import subprocess
import sys
from mio_linux.processes import MemorySnapshot, ProcessMonitor, read_process

# Isolate subreaper behavior in this helper, never in the app/test runner.
assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
parent_code = '''import subprocess,sys
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdout=subprocess.DEVNULL)
print(child.pid,flush=True)
sys.stdin.readline()
'''
parent = subprocess.Popen([sys.executable, '-c', parent_code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
child_pid = None
try:
    child_pid = int(parent.stdout.readline())
    monitor = ProcessMonitor()
    before = [read_process(os.getpid()), read_process(parent.pid), read_process(child_pid)]
    monitor.diagnose(MemorySnapshot(processes=before, enumerated={p.pid for p in before}))
    parent.stdin.write('exit\n');parent.stdin.flush()
    parent.wait(timeout=3)
    after = [read_process(os.getpid()), read_process(child_pid)]
    snapshot = monitor.diagnose(MemorySnapshot(processes=after, enumerated={p.pid for p in after}))
    orphan = next(p for p in snapshot.processes if p.pid == child_pid)
    # Some CI runners put every descendant in a service cgroup; diagnosis must
    # retain observed evidence even when a managed process remains read-only.
    assert orphan.identity in monitor.orphans
    assert str(parent.pid) in monitor.orphans[orphan.identity]
    assert orphan.ppid == os.getpid()
    assert orphan.category in ('observed', 'managed')
    print('Observed real parent exit and subreaper adoption')
finally:
    if parent.poll() is None:
        parent.terminate()
    parent.wait(timeout=3)
    if child_pid is not None:
        try:os.kill(child_pid, signal.SIGTERM)
        except ProcessLookupError:pass
        os.waitpid(child_pid, 0)
