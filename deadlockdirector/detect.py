"""Find out whether Deadlock is running / installed without touching the game.

Only the operating system's process list and Steam's own library files are
read. The game process itself is never opened, read or written.
"""
import os
import re
import socket
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


def find_processes(names=DEADLOCK_PROCESS_NAMES):
    """[(pid, name)] of running processes whose executable name matches."""
    if psutil is None:
        return None
    found = []
    try:
        for process in psutil.process_iter(['pid', 'name']):
            name = process.info.get('name') or ''
            if name.lower() in names:
                found.append((process.info['pid'], name))
    except Exception:
        return None
    return found


def listening_ports(pids=None):
    """{port: (pid, address)} for listening TCP sockets, from the operating
    system's connection table (the same list `netstat -ano` prints). This
    never opens or reads the processes themselves."""
    if psutil is None:
        return None
    try:
        connections = psutil.net_connections(kind='tcp')
    except Exception:
        return None
    result = {}
    for c in connections:
        if c.status == psutil.CONN_LISTEN and c.laddr and (pids is None or c.pid in pids):
            result[c.laddr.port] = (c.pid, c.laddr.ip)
    return result


def port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def diagnose(host, port, names=DEADLOCK_PROCESS_NAMES):
    """Work out why the console connection does or doesn't work.

    Returns (verdict, details) where verdict is one of 'ok', 'not_running',
    'not_listening', 'other_port', 'port_taken', 'unknown'.
    """
    port = int(port)
    details = []
    processes = find_processes(names)
    reachable = port_open(host, port)
    allPorts = listening_ports()
    if processes is None:
        details.append('Could not read the process list.')
    elif processes:
        details.append('Deadlock process: ' + ', '.join('{} (pid {})'.format(n, p) for p, n in processes))
    else:
        details.append('No process named {} is running.'.format(' / '.join(n for n in names if '.' in n)))
    gamePorts = {}
    if allPorts is None:
        details.append('Could not read the TCP connection table.')
    elif processes:
        pids = {p for p, _ in processes}
        gamePorts = {k: v for k, v in allPorts.items() if v[0] in pids}
        if gamePorts:
            details.append('Deadlock is listening on TCP port(s): ' + ', '.join(
                '{} ({})'.format(k, v[1]) for k, v in sorted(gamePorts.items())))
        else:
            details.append('Deadlock is not listening on any TCP port.')
    details.append('Port {} on {}: {}'.format(port, host, 'accepting connections' if reachable else 'closed'))

    if reachable:
        owner = allPorts.get(port) if allPorts else None
        if processes and owner and port not in gamePorts:
            ownerName = 'pid {}'.format(owner[0])
            try:
                ownerName = psutil.Process(owner[0]).name()
            except Exception:
                pass
            details.append('Port {} belongs to another program ({}).'.format(port, ownerName))
            return 'port_taken', details
        return 'ok', details
    if processes == []:
        return 'not_running', details
    if gamePorts:
        return 'other_port', details
    if processes:
        return 'not_listening', details
    return 'unknown', details


ADVICE = {
    'ok': 'The console port is open. Click Connect (or wait a moment for auto-connect).',
    'not_running': 'Start Deadlock first. If it IS running, open Task Manager > Details and tell us the name '
                   'of its .exe so it can be added to the detection list.',
    'not_listening': 'Deadlock is running but has not opened a console port, so the launch option did not reach it '
                     'or this Deadlock version ignores it.\n\n'
                     '1. Quit Deadlock completely (check the system tray / Task Manager).\n'
                     '2. Steam > Library > right-click Deadlock > Properties > General > Launch Options: '
                     '-console -netconport {port}\n'
                     '3. Start Deadlock from Steam, wait for the main menu and run Diagnose again.\n\n'
                     'If it still shows no port, this Deadlock build does not support -netconport.',
    'other_port': 'Deadlock is listening on a different port than {port}. Set "Console port" to the port listed '
                  'above (it is usually the -netconport value) and connect again.',
    'port_taken': 'Another program is already using port {port}. Pick a different number (e.g. 2122) in BOTH the '
                  'app and the launch options, then restart Deadlock.',
    'unknown': 'Could not determine the cause automatically.',
}


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
