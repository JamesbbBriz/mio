"""Explicitly reviewed disk targets; bounded snapshots and system-trash-only sink."""
from dataclasses import dataclass
from pathlib import Path
import os
import stat
import time
from gi.repository import Gio
from .recovery import directory, identity, signature, idle
from .system_trash import bounded


@dataclass(frozen=True)
class DiskPlan:
    path: Path
    parent: tuple
    entries: tuple
    size: int


def plan_disk(path, cancel=None, max_nodes=20000, max_seconds=30):
    path = Path(path)
    home = Path.home()
    trash = Path(os.environ.get('XDG_DATA_HOME', str(home / '.local/share'))) / 'Trash'
    if (not path.is_absolute() or '..' in path.parts or path == home or path in home.parents
            or path == trash or trash in path.parents or path in trash.parents
            or len(path.parts) <= 2):
        raise ValueError('此系统目录、主目录或回收站不可在这里删除，请选择具体子项')
    deadline = time.monotonic() + max_seconds
    stamps, size = [], 0

    def check():
        if (cancel and cancel.is_set()) or time.monotonic() >= deadline:
            raise ValueError('检查已取消或超时，未移动文件；请缩小范围')

    def visit(parent, name, relative, device, depth=0):
        nonlocal size
        check()
        if len(stamps) >= max_nodes or depth >= 128:
            raise ValueError('目标过大，无法完整检查；请选择较小的子目录')
        s = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if s.st_dev != device or s.st_uid != os.getuid():
            raise ValueError('目标包含其他文件系统或其他用户的文件，未移动')
        is_dir = stat.S_ISDIR(s.st_mode)
        if not is_dir and (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1):
            refused = path if relative == '.' else path / relative
            if stat.S_ISLNK(s.st_mode):
                kind = '符号链接（指向其他位置的链接文件）'
            elif stat.S_ISREG(s.st_mode):
                kind = '硬链接（与其他文件名共享数据）'
            else:
                kind = '特殊文件（如管道或套接字）'
            raise ValueError(f'包含{kind}：{refused}。当前不支持整项移动；可进入目录另选普通文件。')
        if not idle(path if relative == '.' else path / relative):
            raise ValueError('目标正在使用或无法确认空闲；请关闭相关应用')
        check()
        stamps.append((relative, signature(s)))
        if is_dir:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(name, flags, dir_fd=parent)
            try:
                if signature(os.fstat(fd)) != signature(s):
                    raise ValueError('目录在检查时变化，请重试')
                with os.scandir(fd) as children:
                    for child in children:
                        visit(fd, child.name, child.name if relative == '.' else relative + '/' + child.name, device, depth + 1)
                if signature(os.fstat(fd)) != signature(s):
                    raise ValueError('目录在检查时变化，请重试')
            finally:
                os.close(fd)
        else:
            size += s.st_size
        if signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != signature(s):
            raise ValueError('目标在检查时变化，请重新审阅')

    with directory(path.parent) as fd:
        parent_id = identity(os.fstat(fd))
        visit(fd, path.name, '.', parent_id[0])
    return DiskPlan(path, parent_id, tuple(sorted(stamps)), size)


def trash_disk(plan, cancel=None):
    fresh = plan_disk(plan.path, cancel)
    if fresh != plan:
        raise ValueError('目标或内容在确认后发生变化，请重新扫描并审阅')
    with directory(plan.path.parent) as fd, bounded() as gio_cancel:
        if (identity(os.fstat(fd)) != plan.parent
                or signature(os.stat(plan.path.name, dir_fd=fd, follow_symlinks=False)) != dict(plan.entries)['.']):
            raise ValueError('目标已变化，未移动')
        if cancel and cancel.is_set():
            raise ValueError('操作已取消，未移动')
        # No permanent-delete or copy/remove fallback. GIO owns volume routing.
        if not Gio.File.new_for_path(str(plan.path)).trash(gio_cancel):
            raise ValueError('系统回收站未确认成功，请重新扫描核对')
