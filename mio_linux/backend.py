"""Read-only Linux adapters. No shell execution, deletion, or privilege escalation."""

from __future__ import annotations

import os
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable


def human_size(value: int | float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(value) < 1024 or unit == "PiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    raise AssertionError("unreachable")


@dataclass
class Entry:
    path: Path
    size: int = 0
    files: int = 0
    old_size: int = 0
    is_dir: bool = False
    children: list[Entry] = field(default_factory=list)
    complete: bool = True


@dataclass
class Scan:
    root: Path
    entries: list[Entry] = field(default_factory=list)
    skipped: int = 0
    partial: bool = False
    visited: int = 0
    cancelled: bool = False

    @property
    def size(self) -> int:
        return sum(entry.size for entry in self.entries)


def scan_directory(
    root: Path,
    *,
    cancel: Event | None = None,
    max_nodes: int = 200_000,
    max_seconds: float = 20,
    now: float | None = None,
    retain_tree: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> Scan:
    """Logical file sizes grouped by immediate child; never follow symlinks.

    Directory descriptors prevent a renamed directory / swapped symlink from
    redirecting traversal. Skip other filesystems, special files, and unreadable
    entries. Budgets apply to the entire scan, including root enumeration.
    Hard links count per name; this is not an estimate of reclaimable space.
    """
    root = Path(os.path.abspath(root))
    result = Scan(root)
    cutoff = (time.time() if now is None else now) - 7 * 24 * 3600
    deadline = time.monotonic() + max_seconds
    last_report = time.monotonic()
    measured = 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    def exhausted() -> bool:
        if (cancel is not None and cancel.is_set()) or result.visited >= max_nodes or time.monotonic() >= deadline:
            result.partial = True
            result.cancelled = cancel is not None and cancel.is_set()
            return True
        return False

    def walk(fd: int, group: Entry | None, depth: int = 0) -> None:
        nonlocal last_report, measured
        if depth >= 128:
            result.partial = True
            result.skipped += 1
            if group is not None:
                group.complete = False
            return
        try:
            with os.scandir(fd) as children:
                for child in children:
                    if exhausted():
                        if group is not None:
                            group.complete = False
                        return
                    result.visited += 1
                    if progress is not None and time.monotonic() - last_report >= .15:
                        progress(result.visited, measured)
                        last_report = time.monotonic()
                    item = None
                    try:
                        info = child.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or info.st_dev != device:
                            result.skipped += 1
                            continue
                        is_dir = stat.S_ISDIR(info.st_mode)
                        if not is_dir and not stat.S_ISREG(info.st_mode):
                            result.skipped += 1
                            continue
                        item = Entry((group.path if group is not None else root) / child.name, is_dir=is_dir) if retain_tree or group is None else group
                        if group is None:
                            result.entries.append(item)
                        elif retain_tree:
                            group.children.append(item)
                        if is_dir:
                            nested = os.open(child.name, flags, dir_fd=fd)
                            try:
                                opened = os.fstat(nested)
                                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                                    result.skipped += 1
                                    result.partial = True
                                    item.complete = False
                                    if group is not None:
                                        group.complete = False
                                    continue
                                walk(nested, item, depth + 1)
                            finally:
                                os.close(nested)
                        else:
                            item.size += info.st_size
                            item.files += 1
                            measured += info.st_size
                            if info.st_mtime < cutoff:
                                item.old_size += info.st_size
                        if retain_tree and group is not None:
                            group.size += item.size
                            group.files += item.files
                            group.old_size += item.old_size
                            group.complete = group.complete and item.complete
                    except OSError:
                        result.skipped += 1
                        result.partial = True
                        if group is not None:
                            group.complete = False
                        if item is not None:
                            item.complete = False
        except OSError:
            result.skipped += 1
            result.partial = True
            if group is not None:
                group.complete = False

    # Open every root component without following links, including ancestors.
    fd = os.open(root.anchor, flags)
    try:
        for component in root.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        device = os.fstat(fd).st_dev
        walk(fd, None)
    finally:
        os.close(fd)
    result.entries.sort(key=lambda entry: (-entry.size, entry.path.name.casefold()))
    if progress is not None:
        progress(result.visited, measured)
    return result


def cache_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "")
    return Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".cache"


def memory_stats(proc: Path = Path("/proc")) -> tuple[int, int]:
    values = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.split()[0]) * 1024
    total = values["MemTotal"]
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return total - available, total


def cpu_ticks(proc: Path = Path("/proc")) -> tuple[int, int]:
    # guest and guest_nice are already included in user and nice.
    values = list(map(int, (proc / "stat").read_text().splitlines()[0].split()[1:9]))
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def cpu_percent(previous: tuple[int, int], current: tuple[int, int]) -> float:
    total, idle = current[0] - previous[0], current[1] - previous[1]
    return max(0.0, min(100.0, (total - idle) / total * 100)) if total > 0 else 0.0


def disk_stats(path: Path | None = None):
    return shutil.disk_usage(path or Path.home())
