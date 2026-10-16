"""GNOME system trash via GIO/GVfs; no separate Mio trash namespace."""
from contextlib import contextmanager
from pathlib import Path
import os
import stat
import threading
import time

from gi.repository import Gio, GLib
from .recovery import directory, identity, signature, idle, Recovery

@contextmanager
def bounded(seconds=30):
    cancel = Gio.Cancellable()
    timer = threading.Timer(seconds, cancel.cancel)
    timer.daemon = True
    timer.start()
    try:
        yield cancel
    except GLib.Error as error:
        raise ValueError(f'系统回收站操作未完成：{error.message}') from error
    finally:
        timer.cancel()


class SystemTrash:
    def move(self, candidate):
        path = Path(candidate.path)
        with directory(path.parent) as parent, bounded() as cancel:
            if identity(os.fstat(parent)) != candidate.parent:
                raise ValueError('原目录已变化，请重新扫描')
            s = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if signature(s) != candidate.stamp or not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
                raise ValueError('文件已变化，请重新扫描')
            if not idle(path):
                raise ValueError('文件正在使用或无法确认空闲，请关闭相关应用')
            with directory(path.parent) as rebound:
                if identity(os.fstat(rebound)) != candidate.parent or signature(os.stat(path.name, dir_fd=rebound, follow_symlinks=False)) != candidate.stamp:
                    raise ValueError('文件在审阅后发生变化')
                # GLib owns volume selection, freedesktop metadata and the trash move.
                # No copy/delete or permanent-delete fallback is permitted.
                Gio.File.new_for_path(str(path)).trash(cancel)

    def batch(self, items, action, cancel=None):
        return Recovery.batch(self, items, action, cancel)

    def legacy_records(self):
        path = Path.home() / '.local/share/mio/recovery'
        if not path.exists():
            return []
        return Recovery(path).records()

    def migrate_legacy(self, items, cancel=None):
        """Restore legacy items, then use system trash so orig-path stays correct.

        An occupied/missing original parent refuses. If system trash fails after
        restoring, leave the original file intact and report its location.
        """
        legacy = Recovery(Path.home() / '.local/share/mio/recovery')
        completed, errors = [], []
        deadline = time.monotonic() + 60
        for item in items:
            if (cancel and cancel.is_set()) or time.monotonic() >= deadline:
                errors.append('迁移已停止，未处理项目仍保留在旧版回收站')
                break
            path = Path(item['path'])
            try:
                legacy.restore(item['id'])
                with directory(path.parent) as fd:
                    s = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
                    from .recovery import Candidate
                    candidate = Candidate(str(path), signature(s), identity(os.fstat(fd)))
                self.move(candidate)
                completed.append(item)
            except (OSError, ValueError) as error:
                errors.append(f'{path}: {error}；如果原文件已恢复，它会保留在原位置，不会删除')
        return completed, errors
