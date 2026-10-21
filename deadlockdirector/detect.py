"""Find out whether Deadlock is running / installed without touching the game.

Only the operating system's process list and Steam's own library files are
read. The game process itself is never opened, read or written.
"""
import os
import re
import sys

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is optional
    psutil = None

from deadlockdirector.settings import DEADLOCK_APP_ID, DEADLOCK_PROCESS_NAMES


def is_deadlock_running():
    """Return True / False, or None when the process list isn't available."""
    if psutil is None:
        return None
    try:
        for process in psutil.process_iter(['name']):
            name = (process.info.get('name') or '').lower()
            if name in DEADLOCK_PROCESS_NAMES:
                return True
    except Exception:
        return None
    return False


def _steam_roots():
    roots = []
    if sys.platform == 'win32':
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                              (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        for value in ('SteamPath', 'InstallPath'):
                            try:
                                roots.append(winreg.QueryValueEx(handle, value)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots.append(r'C:\Program Files (x86)\Steam')
    else:
        home = os.path.expanduser('~')
        roots += [os.path.join(home, '.steam', 'steam'), os.path.join(home, '.local', 'share', 'Steam')]
    seen, result = set(), []
    for root in roots:
        root = os.path.normpath(root)
        if root.lower() not in seen and os.path.isdir(root):
            seen.add(root.lower())
            result.append(root)
    return result


def find_install():
    """Locate the Deadlock install folder through Steam's libraryfolders.vdf."""
    for root in _steam_roots():
        libraries = [root]
        vdf = os.path.join(root, 'steamapps', 'libraryfolders.vdf')
        try:
            with open(vdf, 'r', encoding='utf-8', errors='replace') as f:
                libraries += [p.replace('\\\\', '\\') for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError:
            pass
        for library in libraries:
            manifest = os.path.join(library, 'steamapps', 'appmanifest_{}.acf'.format(DEADLOCK_APP_ID))
            if os.path.isfile(manifest):
                folder = 'Deadlock'
                try:
                    with open(manifest, 'r', encoding='utf-8', errors='replace') as f:
                        match = re.search(r'"installdir"\s+"([^"]+)"', f.read())
                        if match:
                            folder = match.group(1)
                except OSError:
                    pass
                path = os.path.join(library, 'steamapps', 'common', folder)
                if os.path.isdir(path):
                    return path
    return None


def launch_options(port):
    return '-console -netconport {}'.format(int(port))


def launch_deadlock(port):
    """Ask Steam to start Deadlock with the console port open for this launch
    only. Steam shows its own confirmation dialog for launch arguments."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    args = launch_options(port)
    url = QUrl('steam://run/{}//{}/'.format(DEADLOCK_APP_ID, args))
    return QDesktopServices.openUrl(url)
