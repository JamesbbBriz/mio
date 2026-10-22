import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from mio_linux.disk_operations import plan_disk, trash_disk


class DiskOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'folder'
        self.folder.mkdir()
        (self.folder / 'file').write_text('original')

    def test_changed_descendant_refuses_sink(self):
        plan = plan_disk(self.folder)
        (self.folder / 'file').write_text('changed')
        with patch('mio_linux.disk_operations.Gio.File.new_for_path') as sink:
            with self.assertRaisesRegex(ValueError, '变化'):
                trash_disk(plan)
            sink.assert_not_called()
        self.assertTrue(self.folder.exists())

    def test_replaced_parent_refuses_sink(self):
        plan = plan_disk(self.folder)
        self.folder.rename(self.root / 'old')
        self.folder.mkdir()
        (self.folder / 'file').write_text('original')
        with self.assertRaises(ValueError):
            trash_disk(plan)
        self.assertTrue((self.root / 'old/file').exists())

    def test_links_special_and_budgets_refuse(self):
        (self.folder / 'link').symlink_to(self.root)
        with self.assertRaises(ValueError):
            plan_disk(self.folder)
        (self.folder / 'link').unlink()
        with self.assertRaises(ValueError):
            plan_disk(self.folder, max_nodes=1)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ValueError):
            plan_disk(self.folder, cancel)
        os.mkfifo(self.folder / 'pipe')
        with self.assertRaises(ValueError):
            plan_disk(self.folder)

    def test_busy_and_protected_refuse(self):
        with patch('mio_linux.disk_operations.idle', return_value=False):
            with self.assertRaises(ValueError):
                plan_disk(self.folder)
        for path in [Path('/'), Path.home(), Path('/etc')]:
            with self.assertRaises(ValueError):
                plan_disk(path)

    def test_refusal_names_the_actual_link_or_special_file(self):
        cases = [('theme-link', '符号链接', lambda p: p.symlink_to(self.root)),
                 ('shared-file', '硬链接', lambda p: os.link(self.folder / 'file', p)),
                 ('named-pipe', '特殊文件', lambda p: os.mkfifo(p))]
        for name, kind, create in cases:
            with self.subTest(kind=kind):
                item = self.folder / name
                create(item)
                try:
                    with self.assertRaises(ValueError) as caught:
                        plan_disk(self.folder)
                    self.assertIn(kind, str(caught.exception))
                    self.assertIn(str(item if kind != '硬链接' else self.folder), str(caught.exception))
                finally:
                    item.unlink()

    def test_cancel_and_sink_failure_preserve_target(self):
        plan = plan_disk(self.folder)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ValueError):
            trash_disk(plan, cancel)
        with patch('mio_linux.disk_operations.Gio.File.new_for_path') as sink:
            sink.return_value.trash.return_value = False
            with self.assertRaises(ValueError):
                trash_disk(plan)
        self.assertTrue(self.folder.exists())
