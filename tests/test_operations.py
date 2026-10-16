import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from mio_linux.recovery import Recovery, Candidate, signature, identity, plan_cache
from mio_linux.packages import Package, uninstall_command, MAINTENANCE


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.store = Recovery(self.root / 'recovery')
        self.file = self.cache / 'old.bin'
        self.file.write_bytes(b'recover me')
        os.utime(self.file, (time.time() - 864000, time.time() - 864000))
        self.probe = patch('mio_linux.recovery.idle', return_value=True)
        self.probe.start()

    def tearDown(self):
        self.probe.stop()
        self.temp.cleanup()

    def plan(self):
        return plan_cache(self.cache, [self.file])

    def test_round_trip_and_persistent_record(self):
        plan = self.plan()
        self.assertEqual(len(plan), 1)
        key = self.store.move(plan[0])
        self.assertFalse(self.file.exists())
        reopened = Recovery(self.store.root)
        self.assertEqual(reopened.records()[0]['id'], key)
        reopened.restore(key)
        self.assertEqual(self.file.read_bytes(), b'recover me')
        self.assertEqual(reopened.records(), [])

    def test_restore_never_overwrites(self):
        key = self.store.move(self.plan()[0])
        self.file.write_bytes(b'new data')
        with self.assertRaises(FileExistsError):
            self.store.restore(key)
        self.assertEqual(self.file.read_bytes(), b'new data')
        self.assertEqual(len(self.store.records()), 1)

    def test_stale_file_refused(self):
        plan = self.plan()
        self.file.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.store.move(plan[0])
        self.assertEqual(self.store.records(), [])
        self.assertEqual(self.file.read_bytes(), b'changed')

    def test_symlink_and_hardlink_refused(self):
        other = self.cache / 'link'
        other.symlink_to(self.file)
        with self.assertRaises(ValueError):
            plan_cache(self.cache, [other])
        other.unlink()
        os.link(self.file, other)
        self.assertEqual(self.plan(), [])

    def test_busy_final_probe_refused(self):
        plan = self.plan()
        with patch('mio_linux.recovery.idle', return_value=False):
            with self.assertRaises(ValueError):
                self.store.move(plan[0])
        self.assertTrue(self.file.exists())

    def test_parent_symlink_refused(self):
        plan = self.plan()
        moved = self.root / 'moved'
        self.cache.rename(moved)
        self.cache.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.move(plan[0])
        self.assertTrue((moved / self.file.name).exists())

    def test_cancel_stops_next_eligible_candidate(self):
        other = self.cache / 'other'
        other.write_bytes(b'next')
        os.utime(other, (1, 1))
        plan = plan_cache(self.cache, [self.file, other])
        self.assertEqual(len(plan), 2)
        cancel = threading.Event()
        original = self.store.move
        def move(candidate):
            result = original(candidate)
            cancel.set()
            return result
        with patch.object(self.store, 'move', side_effect=move) as sink:
            completed, failures = self.store.batch(plan, 'move', cancel)
        self.assertEqual(sink.call_count, 1)
        self.assertEqual(len(completed), 1)
        self.assertTrue(Path(plan[1].path).exists())
        self.assertIn('已停止', failures[0])

    def test_permanent_delete_only_stored_file(self):
        key = self.store.move(self.plan()[0])
        self.file.write_text('new cache')
        self.store.erase(key)
        self.assertEqual(self.file.read_text(), 'new cache')
        self.assertEqual(self.store.records(), [])

    def test_restore_parent_replaced(self):
        key = self.store.move(self.plan()[0])
        self.cache.rename(self.root / 'old-parent')
        self.cache.mkdir()
        with self.assertRaises(ValueError):
            self.store.restore(key)
        self.assertEqual(len(self.store.records()), 1)

    def test_incomplete_scan_refused(self):
        from mio_linux.backend import Scan
        folder = self.cache / 'folder'
        folder.mkdir()
        with patch('mio_linux.backend.scan_directory', return_value=Scan(folder, partial=True)):
            with self.assertRaises(ValueError):
                plan_cache(self.cache, [folder])

    def test_real_probe_and_move_fixture(self):
        self.probe.stop()
        try:
            plan = self.plan()
            self.assertEqual(len(plan), 1)
            key = self.store.move(plan[0])
            self.store.restore(key)
            self.assertEqual(self.file.read_bytes(), b'recover me')
        finally:
            self.probe.start()


class PackageTests(unittest.TestCase):
    def test_precise_commands_preserve_data(self):
        self.assertEqual(uninstall_command(Package('apt', 'example:amd64', '1'))[-2:], ['--', 'example:amd64'])
        self.assertNotIn('--purge', uninstall_command(Package('snap', 'example', '1')))
        command = uninstall_command(Package('flatpak', 'org.example.App/x86_64/stable', '1', 'user'))
        self.assertIn('--user', command)
        self.assertNotIn('--delete-data', command)
        self.assertNotIn('-y', command)

    def test_option_or_shell_injection_refused(self):
        for provider in ('apt', 'snap', 'flatpak'):
            for name in ('--all', 'foo;rm -rf /', '../foo', 'foo\nbar'):
                with self.assertRaises(ValueError):
                    uninstall_command(Package(provider, name, '1', 'user'))

    def test_no_forced_maintenance(self):
        for _, _, argv in MAINTENANCE.values():
            self.assertNotIn('-y', argv)
            self.assertNotIn('autoremove', argv)
            self.assertNotIn('sh', argv)


class RunnerTests(unittest.TestCase):
    def test_runner_records_actual_exit_and_cancellation(self):
        import json
        import subprocess
        import sys
        from mio_linux import transaction_runner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, result = root / 'request.json', root / 'result.json'
            for command, answer, state, code in [('/usr/bin/true', 'YES\n\n', 'finished', 0), ('/usr/bin/false', 'YES\n\n', 'finished', 1), ('/usr/bin/false', 'NO\n', 'cancelled', None)]:
                request.write_text(json.dumps({'argv': [command], 'result': str(result)}))
                subprocess.run([sys.executable, transaction_runner.__file__, str(request)], input=answer, text=True, capture_output=True, timeout=5, check=True)
                actual = json.loads(result.read_text())
                self.assertEqual(actual['state'], state)
                self.assertEqual(actual.get('returncode'), code)


if __name__ == '__main__':
    unittest.main()
