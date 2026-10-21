"""Helpers for talking to the Deadlock developer console (pure, Qt free).

Deadlock Director only ever communicates with the game through its own
developer console, using the same commands a player could type by hand.
"""
import re

_NUMBER = re.compile(r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?')
_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
# -condebug console.log lines start with "MM/DD HH:MM:SS ".
_LOG_TIMESTAMP = re.compile(r'^\d{1,2}/\d{1,2} \d{1,2}:\d{2}:\d{2}\s+')

MARKER_PREFIX = 'DDIR'


class CameraState(object):
    __slots__ = ('x', 'y', 'z', 'pitch', 'yaw', 'roll')

    def __init__(self, x=0.0, y=0.0, z=0.0, pitch=0.0, yaw=0.0, roll=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)

    @property
    def position(self):
        return [self.x, self.y, self.z]

    @property
    def rotation(self):
        return [self.pitch, self.yaw, self.roll]

    def __eq__(self, other):
        return isinstance(other, CameraState) and self.position == other.position and self.rotation == other.rotation

    def __repr__(self):
        return 'CameraState({:.2f}, {:.2f}, {:.2f} | {:.2f}, {:.2f}, {:.2f})'.format(
            self.x, self.y, self.z, self.pitch, self.yaw, self.roll)


def clean_line(line):
    """Strip ANSI colour codes, log timestamps, carriage returns and NULs."""
    line = _ANSI.sub('', line).replace('\r', '').replace('\x00', '').strip()
    return _LOG_TIMESTAMP.sub('', line)


def parse_camera(text):
    """Parse the output of a camera position query.

    Accepts the common Source engine formats, e.g.
        spec_goto 123.0 -456.5 200.0 12.5 90.0
        setpos 123.0 -456.5 200.0;setang 12.5 90.0 0.0
        123.0 -456.5 200.0 12.5 90.0
    i.e. any line that carries five (x y z pitch yaw) or six (… roll) numbers.
    """
    for line in text.splitlines() if isinstance(text, str) else text:
        line = clean_line(line)
        if not line or MARKER_PREFIX in line:
            continue
        numbers = [float(n) for n in _NUMBER.findall(line)]
        if len(numbers) in (5, 6):
            return CameraState(*numbers)
    return None


def parse_tick(text, pattern=r'tick\D{0,3}(\d+)'):
    """Pull a replay tick number out of console output."""
    regex = re.compile(pattern, re.IGNORECASE)
    for line in text.splitlines() if isinstance(text, str) else text:
        match = regex.search(clean_line(line))
        if match:
            return int(match.group(1))
    return None


class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def render(template, **values):
    """Fill a command template. Unknown placeholders are left untouched so a
    typo in a user template doesn't throw."""
    if not template:
        return ''
    try:
        return template.format_map(SafeDict(values))
    except (ValueError, IndexError, TypeError):
        return ''


def split_commands(text):
    """Split a template that may contain several commands (';' or newlines)."""
    commands = []
    for line in text.replace('\r', '').split('\n'):
        for part in line.split(';'):
            part = part.strip()
            if part:
                commands.append(part)
    return commands


def sanitize(command):
    """Never let a single command smuggle a line break into the console."""
    return command.replace('\r', ' ').replace('\n', ' ').strip()
