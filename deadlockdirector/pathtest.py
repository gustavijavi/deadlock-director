"""Feasibility test for exec-driven camera paths.

Deadlock exposes no console port, but it does run `exec <file>` from a key
bind. The test writes the next camera position into a cfg file and taps the
bound key many times a second, so the game itself loads each frame of a path.
This module holds the pure parts: the test path, cfg writing and reading the
camera back from Deadlock's -condebug console.log.
"""
import math
import os
import time

from deadlockdirector import console

FRAME_CFG = 'ddir_frame'
BIND_KEYS = [
    # (Source 2 key name, Windows scan code, extended key?)
    ('KP_MINUS', 0x4A, False),
    ('KP_PLUS', 0x4E, False),
    ('KP_MULTIPLY', 0x37, False),
]


def bind_command(key):
    return 'bind {} "exec {}"'.format(key, FRAME_CFG)


def orbit_path(start, distance=600.0, duration=8.0, turns=1.0):
    """A camera orbit that starts at `start` (CameraState) and circles the
    point it is looking at, `distance` units ahead, keeping it in frame.

    Returns f(t) -> (x, y, z, pitch, yaw) for 0 <= t <= duration.
    """
    yaw0 = math.radians(start.yaw)
    pitch0 = math.radians(start.pitch)
    # Look-at point: along the view direction, `distance` away horizontally.
    tx = start.x + math.cos(yaw0) * distance
    ty = start.y + math.sin(yaw0) * distance
    tz = start.z - math.tan(pitch0) * distance  # positive pitch looks down
    a0 = math.atan2(start.y - ty, start.x - tx)

    def at(t):
        u = min(1.0, max(0.0, t / duration))
        # Ease in and out so the orbit starts and stops gently.
        u = u * u * (3.0 - 2.0 * u)
        a = a0 + u * turns * 2.0 * math.pi
        x = tx + math.cos(a) * distance
        y = ty + math.sin(a) * distance
        z = start.z
        yaw = math.degrees(math.atan2(ty - y, tx - x))
        pitch = math.degrees(math.atan2(z - tz, distance))
        return x, y, z, pitch, yaw

    return at


def frame_commands(template, x, y, z, pitch, yaw):
    return console.render(template, x=x, y=y, z=z, pitch=pitch, yaw=yaw, roll=0.0)


def write_frame(path, text):
    """Write a cfg so that Deadlock never reads a half-written file.

    Returns False if the game had the file open and the frame was skipped.
    """
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text + '\n')
    try:
        os.replace(temp, path)
        return True
    except PermissionError:
        return False


def cfg_dir(install):
    return os.path.join(install, 'game', 'citadel', 'cfg') if install else None


def find_console_log(install):
    if not install:
        return None
    for candidate in (os.path.join(install, 'game', 'citadel', 'console.log'),
                      os.path.join(install, 'game', 'console.log'),
                      os.path.join(install, 'console.log')):
        if os.path.isfile(candidate):
            return candidate
    return None


def last_camera_in_log(path, max_bytes=512 * 1024):
    """The most recent camera readout (`spec_pos` output) in console.log."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            lines = f.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if 'spec_goto' in line or 'setpos' in line:
            state = console.parse_camera(line)
            if state is not None:
                return state
    return None


class Pacer(object):
    """Fixed-rate loop timing that doesn't drift."""

    def __init__(self, rate):
        self.interval = 1.0 / rate
        self.start = time.perf_counter()
        self.frame = 0

    def elapsed(self):
        return time.perf_counter() - self.start

    def wait(self):
        self.frame += 1
        target = self.start + self.frame * self.interval
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
