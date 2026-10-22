import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from mio_linux.processes import Process, ProcessMonitor, MemorySnapshot, parse_stat, protected_reason, service_unit, read_process
from mio_linux.process_actions import request_exit, validate_process, check_relationship

UID = os.getuid()


def process(pid, ppid=50, **kwargs):
    fields = dict(pid=pid, ppid=ppid, start=pid * 10, name='fixture', state='S', uid=UID,
                  uids=(UID,) * 4, rss=1024, swap=0, session=50, exe='/usr/bin/fixture',
                  exe_id=(8, 12), cgroup='0::/user.slice/user@1000.service/app.slice/app-fixture.scope')
    fields.update(kwargs)
    return Process(**fields)


def snapshot(*entries, enumerated=None, enumeration_complete=True):
    return MemorySnapshot(processes=list(entries), enumerated={p.pid for p in entries} if enumerated is None else enumerated,
                          enumeration_complete=enumeration_complete)


class ProcessDiagnosisTests(unittest.TestCase):
    def test_stat_handles_spaces_and_parentheses(self):
        fields = ['S','1','12','13'] + ['0'] * 15 + ['999','10000','7']
        parsed = parse_stat('42 (odd ) app (name)) ' + ' '.join(fields))
        self.assertEqual(parsed[:6], (42, 'odd ) app (name)', 'S', 1, 13, 999))
        self.assertEqual(parsed[6], 7 * os.sysconf('SC_PAGE_SIZE'))

    def test_initial_adoption_is_only_suspected(self):
        m = ProcessMonitor()
        s = m.diagnose(snapshot(process(100, 1)), own_pid=999, uid=UID)
        self.assertEqual(s.processes[0].category, 'suspected')
        self.assertIn('主动后台', s.processes[0].evidence)

    def test_observed_parent_exit_including_subreaper_and_persistent_evidence(self):
        for adopted in (1, 75):
            m = ProcessMonitor()
            m.diagnose(snapshot(process(50), process(100, 50), process(75)), own_pid=999)
            s = m.diagnose(snapshot(process(100, adopted), process(75)), own_pid=999)
            orphan = next(p for p in s.processes if p.pid == 100)
            self.assertEqual(orphan.category, 'observed')
            self.assertIn('父进程 50', orphan.evidence)
            s = m.diagnose(snapshot(process(100, adopted), process(75)), own_pid=999)
            self.assertEqual(next(p for p in s.processes if p.pid == 100).category, 'observed')

    def test_exited_parent_waiting_to_be_reaped_is_evidence(self):
        m = ProcessMonitor()
        m.diagnose(snapshot(process(50), process(100, 50)), own_pid=999)
        s = m.diagnose(snapshot(process(50, state='Z'), process(100, 1)), own_pid=999)
        self.assertEqual(next(p for p in s.processes if p.pid == 100).category, 'observed')

    def test_pid_reuse_and_partial_enumeration_do_not_invent_orphans(self):
        m = ProcessMonitor()
        m.diagnose(snapshot(process(50), process(100, 50)), own_pid=999)
        s = m.diagnose(snapshot(process(100, 1, start=9999)), own_pid=999)
        self.assertEqual(s.processes[0].category, 'suspected')
        m = ProcessMonitor()
        m.diagnose(snapshot(process(50), process(100, 50)), own_pid=999)
        s = m.diagnose(snapshot(process(100, 1), enumeration_complete=False), own_pid=999)
        self.assertEqual(s.processes[0].category, 'suspected')
        # A permission-denied parent remains in the enumeration: missing details
        # are not evidence that the parent exited.
        m = ProcessMonitor()
        m.diagnose(snapshot(process(50), process(100, 50)), own_pid=999)
        s = m.diagnose(snapshot(process(100, 1), enumerated={50,100}), own_pid=999)
        self.assertEqual(s.processes[0].category, 'suspected')

    def test_services_zombies_and_critical_session_are_not_orphan_targets(self):
        m = ProcessMonitor()
        entries = [process(100, 1, cgroup='0::/user.slice/user@1000.service/app.slice/pipewire.service'),
                   process(101, 1, state='Z'), process(102, 1, exe='/usr/bin/gnome-shell')]
        s = m.diagnose(snapshot(*entries), own_pid=999)
        self.assertEqual([p.category for p in s.processes], ['managed', 'zombie', 'managed'])
        self.assertTrue(all(p.protected for p in s.processes))
        self.assertEqual(service_unit(process(100).cgroup), '')

    def test_self_ancestors_and_workers_are_protected(self):
        m = ProcessMonitor()
        s = m.diagnose(snapshot(process(50, 1), process(100, 50), process(101, 100)), own_pid=100)
        self.assertTrue(all('Mio' in p.protected for p in s.processes))

    def test_other_users_and_unknown_information_are_read_only(self):
        self.assertTrue(protected_reason(process(100, uids=(UID+1,)*4)))
        self.assertTrue(protected_reason(process(100, complete=False)))

    def test_real_parent_exit_and_subreaper_adoption(self):
        result = subprocess.run([sys.executable, '-m', 'tests.process_orphan_fixture'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Observed real parent exit', result.stdout)

    def test_real_proc_read_is_bounded_and_self_identity_matches(self):
        own = read_process(os.getpid())
        self.assertEqual(own.pid, os.getpid())
        self.assertEqual(own.uid, UID)
        m = ProcessMonitor()
        s = m.scan(max_processes=1)
        self.assertTrue(s.partial)
        cancel = threading.Event(); cancel.set()
        self.assertTrue(m.scan(cancel).partial)


class ProcessActionTests(unittest.TestCase):
    def test_identity_change_refuses_before_any_signal(self):
        p = process(100)
        with patch('mio_linux.process_actions.read_process', return_value=replace(p, start=p.start+1)), \
             patch('mio_linux.process_actions.signal.pidfd_send_signal') as send:
            with self.assertRaisesRegex(ValueError, '身份'):
                validate_process(p)
            send.assert_not_called()

    def test_whole_set_is_validated_before_signal_and_descriptors_close(self):
        with patch('mio_linux.process_actions.os.pidfd_open', side_effect=[71,72]), \
             patch('mio_linux.process_actions.os.close') as close, \
             patch('mio_linux.process_actions.validate_process', side_effect=[process(100), ValueError('changed')]), \
             patch('mio_linux.process_actions.signal.pidfd_send_signal') as send:
            with self.assertRaisesRegex(ValueError, 'changed'):
                request_exit([process(100),process(101)])
            send.assert_not_called()
            self.assertEqual([c.args[0] for c in close.call_args_list], [71,72])

    def test_cancel_after_validation_stops_all_signals(self):
        cancel = threading.Event()
        count = 0
        def validate(p):
            nonlocal count
            count += 1
            if count == 3:  # Both initially eligible; cancel during final check.
                cancel.set()
            return p
        with patch('mio_linux.process_actions.os.pidfd_open', side_effect=[71,72]), \
             patch('mio_linux.process_actions.os.close'), \
             patch('mio_linux.process_actions.validate_process', side_effect=validate), \
             patch('mio_linux.process_actions.signal.pidfd_send_signal') as send:
            results = request_exit([process(100),process(101)], cancel)
            send.assert_not_called()
            self.assertEqual([r.state for r in results], ['refused','refused'])

    def test_request_does_not_claim_exit_when_process_ignores_term(self):
        with patch('mio_linux.process_actions.os.pidfd_open', return_value=71), \
             patch('mio_linux.process_actions.os.close'), \
             patch('mio_linux.process_actions.validate_process', side_effect=lambda p:p), \
             patch('mio_linux.process_actions.signal.pidfd_send_signal') as send, \
             patch('mio_linux.process_actions.select.poll') as poll:
            poll.return_value.poll.return_value = []
            result = request_exit([process(100)], wait_seconds=0)
            send.assert_called_once_with(71, signal.SIGTERM, None, 0)
            self.assertEqual(result[0].state, 'requested')

    def test_real_self_and_parent_are_protected(self):
        for pid in (os.getpid(), os.getppid()):
            with self.assertRaises(ValueError):
                check_relationship(pid)

    def test_real_pidfd_only_terminates_owned_fixture(self):
        # Use a sibling control helper: the app deliberately protects its own
        # descendants. The helper validates the real fixture through /proc.
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'ready'
            target = subprocess.Popen([sys.executable, '-c',
                'import time,sys;from pathlib import Path;Path(sys.argv[1]).write_text("ready");time.sleep(30)', str(marker)])
            try:
                import time
                end = time.monotonic()+5
                while not marker.exists() and time.monotonic()<end:
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                helper = '''import sys
from dataclasses import replace
from unittest.mock import patch
from mio_linux.processes import read_process
from mio_linux.process_actions import request_exit
pid=int(sys.argv[1])
def fixture_read(target, proc=None):
    p=read_process(target)
    # CI runs under a service cgroup; only this owned fixture is represented
    # as an app scope. PID/start/UID/executable checks remain real.
    return replace(p,cgroup='0::/fixture/app-fixture.scope') if target == pid else p
p=fixture_read(pid)
with patch('mio_linux.process_actions.read_process', side_effect=fixture_read):
    result=request_exit([p])
assert result[0].state == 'exited', result
print('fixture exited')
'''
                result = subprocess.run([sys.executable,'-c',helper,str(target.pid)], capture_output=True,text=True,timeout=8)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('fixture exited',result.stdout)
                self.assertEqual(target.wait(timeout=2),-signal.SIGTERM)
            finally:
                if target.poll() is None:
                    target.terminate()
                target.wait(timeout=3)


if __name__ == '__main__':
    unittest.main()
