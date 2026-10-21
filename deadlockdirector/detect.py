"""Find out whether Deadlock is running / installed without touching the game.

Only the operating system's process list and Steam's own library files are
read. The game process itself is never opened, read or written.
"""
import os
import re
import socket
import sys
import time

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


PROBE_MARKER = b'DDIR_PROBE'


def _printable(data, limit=48):
    text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:limit])
    return text + ('…' if len(data) > limit else '')


def _classify(data):
    from deadlockdirector.vconsole import looks_like_vconsole
    if data.startswith(b'HTTP/'):
        return 'http'
    if looks_like_vconsole(data):
        return 'vconsole'
    printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return 'text' if printable >= len(data) * 0.9 else 'binary'


def probe_port(host, port, listen=1.5, timeout=1.0):
    """Identify what kind of service a local port is.

    Connects and first only listens: a Source 2 VConsole server announces
    itself straight away with binary chunks (AINF, ADON, CHAN…). If the port
    stays silent, one harmless `echo` line is sent to see whether it is a
    plain-text network console (-netconport).

    Returns (kind, sample): kind is 'netcon', 'vconsole', 'http', 'text',
    'binary', 'silent' or 'closed'.
    """
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError:
        return 'closed', ''

    def read(seconds):
        data = b''
        end = time.monotonic() + seconds
        sock.settimeout(0.1)
        while time.monotonic() < end and len(data) < 4096:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            data += chunk
        return data

    try:
        data = read(listen)
        if data:
            return _classify(data), _printable(data)
        try:
            sock.sendall(b'echo ' + PROBE_MARKER + b'\n')
        except OSError:
            return 'silent', ''
        data = read(timeout)
        if PROBE_MARKER in data:
            return 'netcon', _printable(data)
        return (_classify(data), _printable(data)) if data else ('silent', '')
    finally:
        sock.close()


PORT_KINDS = {
    'netcon': 'network console (usable)',
    'vconsole': 'Source 2 VConsole (usable)',
    'http': 'web server (not a console)',
    'text': 'unknown text service',
    'binary': 'unknown binary service',
    'silent': 'no response (probably internal to the game)',
    'closed': 'refused the connection',
    'busy': 'in use by Deadlock Director right now',
}


def diagnose(host, port, vport=29000, names=DEADLOCK_PROCESS_NAMES, skip=(), probe=True):
    """Work out why the console connection does or doesn't work.

    port / vport are the configured network-console and VConsole ports; ports
    in `skip` are already connected and are not probed again.

    Returns (verdict, details, found): verdict is one of 'ok', 'other_port',
    'vconsole', 'port_taken', 'not_running', 'not_listening', 'unknown';
    found is the port it refers to (or None).
    """
    port, vport = int(port), int(vport)
    details = []
    processes = find_processes(names)
    allPorts = listening_ports()
    pids = {p for p, _ in processes or []}
    if processes is None:
        details.append('Could not read the process list.')
    elif processes:
        details.append('Deadlock process: ' + ', '.join('{} (pid {})'.format(n, p) for p, n in processes))
    else:
        details.append('No process named {} is running.'.format(' / '.join(n for n in names if '.' in n)))

    candidates = {}
    if allPorts is None:
        details.append('Could not read the TCP connection table.')
    else:
        candidates = {k: v[1] for k, v in allPorts.items() if v[0] in pids}
    for configured in (port, vport):
        if configured not in candidates and port_open(host, configured):
            candidates[configured] = host
    if processes and allPorts is not None and not candidates:
        details.append('Deadlock has no TCP ports open (console port {} and VConsole port {} are closed).'.format(port, vport))

    kinds = {}
    for number, address in sorted(candidates.items())[:8]:
        if number in skip:
            kind, sample = 'busy', ''
        elif probe:
            target = '127.0.0.1' if address in ('0.0.0.0', '::', '') else address
            kind, sample = probe_port(target, number)
        else:
            kind, sample = 'silent', ''
        kinds[number] = kind
        owner = allPorts.get(number) if allPorts else None
        foreign = owner is not None and pids and owner[0] not in pids
        line = 'Port {}{}: {}'.format(number, ' (another program)' if foreign else '', PORT_KINDS.get(kind, kind))
        if sample:
            line += '\n    first bytes: ' + sample
        details.append(line)
        if foreign and number in (port, vport):
            kinds[number] = 'foreign'

    for number in (port, vport):
        if kinds.get(number) in ('netcon', 'vconsole', 'busy'):
            return 'ok', details, number
    for kind, verdict in (('netcon', 'other_port'), ('vconsole', 'vconsole')):
        for number, found in sorted(kinds.items()):
            if found == kind:
                return verdict, details, number
    if 'foreign' in kinds.values():
        return 'port_taken', details, next(n for n, k in kinds.items() if k == 'foreign')
    if processes == []:
        return 'not_running', details, None
    if processes:
        return 'not_listening', details, None
    return 'unknown', details, None


ADVICE = {
    'ok': 'A console port is open. Deadlock Director will connect (or is already connected).',
    'not_running': 'Start Deadlock first. If it IS running, open Task Manager > Details and tell us the name '
                   'of its .exe so it can be added to the detection list.',
    'not_listening': 'Deadlock is running but has not opened a console port, so it ignored the launch options. '
                     '(Any other ports listed are not a console.)\n\n'
                     'Try other launch options in the Connection panel, e.g. "-console -vconsole" (asks the '
                     'engine for a VConsole port), quit Deadlock completely, start it again and run Diagnose '
                     'again. Avoid -tools: Deadlock fails to start with it.',
    'other_port': 'Found a working network console on port {found}. Deadlock Director switched to it.',
    'vconsole': 'Found a working VConsole on port {found}. Deadlock Director switched to it.',
    'port_taken': 'Another program is already using port {found}. Pick a different port number in the app and '
                  'in the launch options, then restart Deadlock.',
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


def launch_deadlock(args):
    """Ask Steam to start Deadlock with these launch options for this launch
    only. Steam shows its own confirmation dialog for launch arguments."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    url = QUrl('steam://run/{}//{}/'.format(DEADLOCK_APP_ID, args))
    return QDesktopServices.openUrl(url)
