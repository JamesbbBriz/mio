"""Install the current checkout's per-user desktop launcher and branded icon."""
from pathlib import Path
import os
import shutil
import subprocess

APP_ID = 'io.github.jamesbbbriz.Mio'


def install():
    root = Path(__file__).resolve().parents[1]
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    if not data.is_absolute():
        raise ValueError('XDG_DATA_HOME must be absolute')
    icons = data / 'icons/hicolor/256x256/apps'
    apps = data / 'applications'
    icons.mkdir(parents=True, exist_ok=True)
    apps.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'assets/mio-icon.png', icons / f'{APP_ID}.png')
    # Desktop Entry Exec quoting is not shell quoting. Escape field codes too.
    executable = str(root / 'run.sh').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    content = f'''[Desktop Entry]
Type=Application
Name=Mio · 澪
Comment=磁盘分析、缓存清理与系统维护
Exec="{executable}"
Icon={APP_ID}
Terminal=false
Categories=System;
StartupNotify=true
StartupWMClass={APP_ID}
'''
    launcher = apps / f'{APP_ID}.desktop'
    launcher.write_text(content)
    launcher.chmod(0o755)
    desktop = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if desktop and Path(desktop).is_dir() and Path(desktop) != Path.home():
        shortcut = Path(desktop) / launcher.name
        shutil.copyfile(launcher, shortcut)
        shortcut.chmod(0o755)
        subprocess.run(['gio', 'set', str(shortcut), 'metadata::trusted', 'true'], capture_output=True, timeout=5)
    for argv in (['update-desktop-database', str(apps)], ['gtk-update-icon-cache', '-f', '-t', str(data / 'icons/hicolor')]):
        if shutil.which(argv[0]):
            subprocess.run(argv, capture_output=True, timeout=10)
    return launcher


if __name__ == '__main__':
    print(install())
