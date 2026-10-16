import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from mio_linux.backend import cache_root, cpu_percent, cpu_ticks, human_size, memory_stats, scan_directory


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_groups_sorting_and_age_are_from_real_files(self):
        folder = self.root / "app-cache"
        folder.mkdir()
        old = folder / "old"
        old.write_bytes(b"a" * 50)
        os.utime(old, (0, 0))
        (folder / "new").write_bytes(b"b" * 20)
        (self.root / "single").write_bytes(b"c" * 10)
        result = scan_directory(self.root)
        self.assertEqual(result.size, 80)
        self.assertEqual(result.entries[0].path, folder)
        self.assertEqual(result.entries[0].files, 2)
        self.assertEqual(result.entries[0].old_size, 50)
        self.assertFalse(result.partial)

    def test_never_follows_symlinks_or_special_files(self):
        (self.root / "real").write_bytes(b"a" * 10)
        (self.root / "link-file").symlink_to(self.root / "real")
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        os.mkfifo(self.root / "pipe")
        result = scan_directory(self.root)
        self.assertEqual(result.size, 10)
        self.assertEqual(result.skipped, 3)

    def test_root_and_ancestor_symlinks_are_rejected(self):
        folder = self.root / "real"
        folder.mkdir()
        nested = folder / "nested"
        nested.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(folder, target_is_directory=True)
        for path in (alias, alias / "nested"):
            with self.subTest(path=path), self.assertRaises(OSError):
                scan_directory(path)

    def test_scan_does_not_modify_files(self):
        data = self.root / "precious"
        data.write_bytes(b"do not change")
        before = data.stat()
        scan_directory(self.root)
        self.assertEqual(data.read_bytes(), b"do not change")
        after = data.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ino), (after.st_size, after.st_mtime_ns, after.st_ino))

    def test_retained_tree_has_correct_totals_and_can_drill_down(self):
        nested = self.root / "one" / "two"
        nested.mkdir(parents=True)
        (nested / "old").write_bytes(b"a" * 11)
        os.utime(nested / "old", (0, 0))
        (self.root / "one" / "new").write_bytes(b"b" * 7)
        reports = []
        result = scan_directory(self.root, retain_tree=True, progress=lambda count, size: reports.append((count, size)))
        self.assertEqual(result.size, 18)
        top = result.entries[0]
        child = next(item for item in top.children if item.is_dir)
        self.assertEqual((top.size, top.files, top.old_size), (18, 2, 11))
        self.assertEqual((child.path, child.size, child.files), (nested, 11, 1))
        self.assertEqual(child.children[0].path, nested / "old")
        self.assertEqual(reports[-1], (4, 18))
        self.assertTrue(top.complete)

    def test_retained_tree_marks_ancestors_incomplete_on_budget(self):
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        for index in range(3):
            (nested / str(index)).write_bytes(b"a")
        result = scan_directory(self.root, retain_tree=True, max_nodes=3)
        self.assertTrue(result.partial)
        self.assertFalse(result.entries[0].complete)
        self.assertEqual(result.size, 1)

    def test_cancelled_scan_is_distinguished_from_budget(self):
        (self.root / "test").touch()
        cancel = threading.Event()
        cancel.set()
        result = scan_directory(self.root, cancel=cancel, retain_tree=True)
        self.assertTrue(result.cancelled)
        self.assertTrue(result.partial)

    def test_cancellation_and_budgets_are_reported(self):
        for index in range(5):
            (self.root / str(index)).write_bytes(b"a")
        event = threading.Event()
        event.set()
        for options in ({"cancel": event}, {"max_nodes": 2}, {"max_seconds": 0}):
            with self.subTest(options=options):
                result = scan_directory(self.root, **options)
                self.assertTrue(result.partial)
                self.assertLessEqual(result.visited, 2)

    def test_unreadable_subdirectory_is_reported(self):
        folder = self.root / "blocked"
        folder.mkdir(mode=0)
        self.addCleanup(lambda: folder.chmod(0o700))
        if os.getuid() == 0:
            self.skipTest("root can read mode 000")
        result = scan_directory(self.root)
        self.assertEqual(result.skipped, 1)

    def test_missing_root_raises(self):
        with self.assertRaises(FileNotFoundError):
            scan_directory(self.root / "missing")

    def test_proc_parsing_avoids_double_counting_guest_time(self):
        (self.root / "stat").write_text("cpu  100 10 30 400 20 5 5 0 50 5\n")
        (self.root / "meminfo").write_text("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 600 kB\n")
        self.assertEqual(cpu_ticks(self.root), (570, 420))
        self.assertEqual(memory_stats(self.root), (400 * 1024, 1000 * 1024))
        self.assertEqual(cpu_percent((100, 20), (200, 70)), 50)
        self.assertEqual(cpu_percent((100, 20), (100, 20)), 0)

    def test_cache_xdg_rules_and_sizes(self):
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root)}):
            self.assertEqual(cache_root(), self.root)
        with patch.dict(os.environ, {"XDG_CACHE_HOME": "relative"}):
            self.assertEqual(cache_root(), Path.home() / ".cache")
        self.assertEqual(human_size(1024), "1.0 KiB")


if __name__ == "__main__":
    unittest.main()
