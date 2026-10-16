"""Reviewed file moves into a private recovery store; no recursive deletion."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
import ctypes
import errno
import fcntl
import json
import os
import stat
import subprocess
import time
import uuid

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('需要绝对路径，且不能包含 ..')
    fd = os.open('/', FLAGS)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def identity(s):
    return (s.st_dev, s.st_ino)


def signature(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_nlink, s.st_uid)


def idle(path):
    """fuser reports 1 for no matches; diagnostic output means unknown."""
    try:
        result = subprocess.run(['/usr/bin/fuser', str(path)], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=3, env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip()


@dataclass(frozen=True)
class Candidate:
    path: str
    stamp: tuple
    parent: tuple


def plan_cache(root, selected, cancel=None):
    from .backend import scan_directory
    root = Path(root)
    selected = set(map(str, selected))
    entries = []
    visited = 0
    scan_deadline = time.monotonic() + 20
    from .backend import Entry
    with directory(root) as root_fd:
        for name in sorted(selected):
            path = Path(name)
            if path.parent != root:
                raise ValueError('只能清理本次缓存根目录的子项')
            st = os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
            if st.st_dev != os.fstat(root_fd).st_dev:
                raise ValueError('不跨文件系统清理')
            if stat.S_ISDIR(st.st_mode):
                scan = scan_directory(path, retain_tree=True, max_nodes=20000 - visited, max_seconds=max(0, scan_deadline - time.monotonic()), cancel=cancel)
                if scan.partial or scan.cancelled:
                    raise ValueError('所选目录未完整扫描，请缩小范围')
                visited += scan.visited
                entries.extend(scan.entries)
            elif stat.S_ISREG(st.st_mode):
                entries.append(Entry(path))
            else:
                raise ValueError('不处理链接或特殊文件')
    result = []
    cutoff = time.time() - 7 * 86400
    deadline = time.monotonic() + 30
    def visit(entry):
        if (cancel and cancel.is_set()) or time.monotonic() > deadline:
            raise ValueError('审阅计划已取消或超时；未移动文件')
        if entry.is_dir:
            for child in entry.children:
                visit(child)
        else:
            with directory(entry.path.parent) as fd:
                s = os.stat(entry.path.name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == os.getuid() and s.st_mtime < cutoff and s.st_dev == os.fstat(fd).st_dev:
                    if idle(entry.path):
                        result.append(Candidate(str(entry.path), signature(s), identity(os.fstat(fd))))
    for entry in entries:
        visit(entry)
    return result


def rename_new(source_fd, source, dest_fd, dest):
    libc = ctypes.CDLL(None, use_errno=True)
    func = libc.renameat2
    func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    func.restype = ctypes.c_int
    if func(source_fd, os.fsencode(source), dest_fd, os.fsencode(dest), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


class Recovery:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path.home() / '.local/share/mio/recovery'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with directory(self.root) as fd:
            s = os.fstat(fd)
            if s.st_uid != os.getuid() or s.st_mode & 0o077:
                raise ValueError('Mio 回收站必须属于当前用户，且权限为 0700')

    @contextmanager
    def locked(self):
        with directory(self.root) as fd:
            lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield fd
            finally:
                os.close(lock)

    def records(self):
        result = []
        with self.locked() as fd:
            for name in os.listdir(fd):
                if name.endswith('.json'):
                    try:
                        item = self.read(fd, name[:-5])
                        s = os.stat(item['id'] + '.file', dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISREG(s.st_mode) and identity(s) == tuple(item['stamp'][:2]):
                            result.append(item)
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
        return sorted(result, key=lambda r: r['time'], reverse=True)

    def read(self, fd, key):
        if len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('无效回收记录')
        f = os.open(key + '.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(f) as stream:
            item = json.loads(stream.read(65536))
        if item['id'] != key:
            raise ValueError('回收记录不匹配')
        return item

    def move(self, candidate):
        path = Path(candidate.path)
        with self.locked() as dest, directory(path.parent) as src:
            if identity(os.fstat(src)) != candidate.parent:
                raise ValueError('父目录发生变化，请重新扫描')
            s = os.stat(path.name, dir_fd=src, follow_symlinks=False)
            if signature(s) != candidate.stamp or not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
                raise ValueError('文件已变化，请重新扫描')
            if s.st_dev != os.fstat(dest).st_dev:
                raise ValueError('回收站与文件不在同一文件系统，已保留原文件')
            if not idle(path):
                raise ValueError('文件正在使用或无法确认空闲，请关闭相关应用')
            if signature(os.stat(path.name, dir_fd=src, follow_symlinks=False)) != candidate.stamp:
                raise ValueError('文件在审阅后发生变化')
            key = uuid.uuid4().hex
            item = {**asdict(candidate), 'id': key, 'time': time.time()}
            meta = os.open(key + '.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dest)
            with os.fdopen(meta, 'w') as stream:
                json.dump(item, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(dest)
            with directory(path.parent) as rebound:
                if identity(os.fstat(rebound)) != candidate.parent:
                    raise ValueError('原目录发生变化，请重新扫描')
            rename_new(src, path.name, dest, key + '.file')
            os.fsync(src)
            os.fsync(dest)
            return key

    def restore(self, key):
        with self.locked() as src:
            item = self.read(src, key)
            path = Path(item['path'])
            s = os.stat(key + '.file', dir_fd=src, follow_symlinks=False)
            if not stat.S_ISREG(s.st_mode) or identity(s) != tuple(item['stamp'][:2]):
                raise ValueError('回收文件发生变化')
            with directory(path.parent) as dest:
                if identity(os.fstat(dest)) != tuple(item['parent']):
                    raise ValueError('原父目录已变化，无法自动恢复')
                rename_new(src, key + '.file', dest, path.name)
                os.fsync(dest)
                os.fsync(src)
            os.unlink(key + '.json', dir_fd=src)
            os.fsync(src)

    def erase(self, key):
        with self.locked() as fd:
            item = self.read(fd, key)
            s = os.stat(key + '.file', dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(s.st_mode) or identity(s) != tuple(item['stamp'][:2]) or s.st_nlink != 1:
                raise ValueError('回收文件发生变化，拒绝永久删除')
            os.unlink(key + '.file', dir_fd=fd)
            os.fsync(fd)
            os.unlink(key + '.json', dir_fd=fd)
            os.fsync(fd)

    def batch(self, items, action, cancel=None):
        completed, failures = [], []
        deadline = time.monotonic() + 60
        for item in items:
            if (cancel and cancel.is_set()) or time.monotonic() > deadline:
                failures.append('已停止；未处理的项目保持原样，可以重新审阅')
                break
            try:
                getattr(self, action)(item)
                completed.append(item)
            except (OSError, ValueError) as error:
                failures.append(f'{getattr(item, "path", item)}: {error}')
        return completed, failures
