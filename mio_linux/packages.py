"""Exact package inventory and manager-owned interactive transactions."""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import uuid


@dataclass(frozen=True)
class Package:
    provider: str
    name: str
    version: str
    scope: str = ''


def probe(argv, timeout=30):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or f'退出状态 {result.returncode}')
    return result.stdout


def inventory():
    packages, errors = [], []
    if shutil.which('dpkg-query'):
        try:
            text = probe(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'])
            for line in text.splitlines():
                name, version, status = line.split('\t')
                if status == 'installed':
                    packages.append(Package('apt', name, version))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            errors.append(f'APT: {error}')
    if shutil.which('snap'):
        try:
            for line in probe(['/usr/bin/snap', 'list']).splitlines()[1:]:
                fields = line.split()
                if len(fields) < 6:
                    raise ValueError('无法解析 Snap 清单')
                packages.append(Package('snap', fields[0], fields[1]))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            errors.append(f'Snap: {error}')
    if shutil.which('flatpak'):
        for scope in ('user', 'system'):
            try:
                for line in probe(['/usr/bin/flatpak', 'list', '--app', '--' + scope, '--columns=ref,version']).splitlines():
                    fields = line.split('\t')
                    packages.append(Package('flatpak', fields[0], fields[1] if len(fields) > 1 else '', scope))
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                errors.append(f'Flatpak {scope}: {error}')
    return sorted(packages, key=lambda p: (p.provider, p.name, p.scope)), errors


def uninstall_command(package):
    if package.provider == 'apt' and re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?', package.name):
        return ['/usr/bin/sudo', '/usr/bin/apt-get', 'remove', '--', package.name]
    if package.provider == 'snap' and re.fullmatch(r'[a-z0-9][a-z0-9_-]*', package.name):
        return ['/usr/bin/sudo', '/usr/bin/snap', 'remove', package.name]
    if package.provider == 'flatpak' and package.scope in ('user', 'system') and re.fullmatch(r'(?:app/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', package.name):
        return ['/usr/bin/flatpak', 'uninstall', '--' + package.scope, package.name]
    raise ValueError('软件包标识或来源无效')


def review_uninstall(package):
    argv = uninstall_command(package)
    current, errors = inventory()
    if package not in current:
        raise ValueError('软件包清单已变化或无法确认安装状态，请刷新')
    if package.provider == 'apt':
        return probe(['/usr/bin/apt-get', '--simulate', 'remove', '--', package.name], timeout=60)
    return ('移除精确的软件包：' + package.name + '\n安装范围：' + (package.scope or '系统') +
            '\n保留用户数据。Snap 使用其默认自动快照；Flatpak 由包管理器再次确认。')


MAINTENANCE = {
    'update': ('刷新软件源', '下载 APT 软件索引，需要网络；不会安装更新。', ['/usr/bin/sudo', '/usr/bin/apt-get', 'update']),
    'upgrade': ('安装系统更新', 'APT 在终端显示实际更新计划并再次确认；可能需要重启。', ['/usr/bin/sudo', '/usr/bin/apt-get', 'upgrade']),
    'check': ('检查软件包依赖', '检查 APT 依赖一致性。', ['/usr/bin/sudo', '/usr/bin/apt-get', 'check']),
    'clean': ('清理 APT 下载缓存', '永久删除已下载的安装包缓存，不能从 Mio 恢复；以后可重新下载。', ['/usr/bin/sudo', '/usr/bin/apt-get', 'clean']),
    'journal': ('保留最近 14 天系统日志', '永久清理超过 14 天的归档日志，不可恢复；活动日志不受影响。', ['/usr/bin/sudo', '/usr/bin/journalctl', '--vacuum-time=14d']),
}


def terminal_command(command):
    if shutil.which('xdg-terminal-exec'):
        return [shutil.which('xdg-terminal-exec'), '--', *command]
    if shutil.which('gnome-terminal'):
        return [shutil.which('gnome-terminal'), '--', *command]
    if shutil.which('ptyxis'):
        return [shutil.which('ptyxis'), '--new-window', '--', *command]
    raise ValueError('未找到桌面终端，请安装 xdg-terminal-exec、Ptyxis 或 GNOME Terminal')


def launch(argv):
    """Run as current user; sudo/manager owns authentication and final consent."""
    if not Path(argv[0]).is_file() or (argv[0].endswith('/sudo') and not Path(argv[1]).is_file()):
        raise ValueError('本机未安装此操作需要的工具')
    root = Path.home() / '.local/state/mio/operations'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = uuid.uuid4().hex
    request = root / (key + '.request.json')
    result = root / (key + '.result.json')
    request.write_text(json.dumps({'argv': argv, 'result': str(result)}))
    request.chmod(0o600)
    runner = Path(__file__).with_name('transaction_runner.py')
    subprocess.Popen(terminal_command(['/usr/bin/python3', str(runner), str(request)]), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return result
