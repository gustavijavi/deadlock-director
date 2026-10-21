"""Persistent application settings and the console command templates."""
import os

from PySide6.QtCore import QSettings, QStandardPaths

DEADLOCK_APP_ID = 1422450
DEADLOCK_PROCESS_NAMES = ('deadlock.exe', 'project8.exe', 'deadlock')

# Command templates. Placeholders use Python format syntax, e.g. {x:.2f}.
# These are the commands a user could type into Deadlock's console by hand.
# Deadlock is in active development, so every one of them is editable in the
# Settings dialog in case Valve renames something.
DEFAULTS = {
    'connection/host': '127.0.0.1',
    'connection/port': 2121,
    'connection/vconsole_port': 29000,
    'connection/protocol': 'auto',  # auto | netcon | vconsole
    'connection/launch_options': '-console -netconport 2121',
    'connection/autoconnect': True,

    # Deadlock's console: "spec_goto x y z <pitch yaw optional>" moves the
    # spectator camera, "spec_setang pitch yaw" points it. Neither is a cheat
    # command. Both are sent because spec_goto alone was reported to ignore angles.
    'commands/camera': 'spec_goto {x:.2f} {y:.2f} {z:.2f} {pitch:.2f} {yaw:.2f}; spec_setang {pitch:.2f} {yaw:.2f}',
    'commands/camera_query': 'spec_pos',
    'commands/fov': '',
    'commands/timescale': 'demo_timescale {value:.3f}',
    'commands/pause': 'demo_pause',
    'commands/resume': 'demo_resume',
    'commands/seek': 'demo_gototick {tick}',
    'commands/tick_query': 'demo_info',
    'commands/tick_regex': r'tick\D{0,3}(\d+)',
    'commands/hud_hide': 'citadel_hud_visible false; citadel_hide_replay_hud true',
    'commands/hud_show': 'citadel_hud_visible true; citadel_hide_replay_hud false',
    'commands/freecam_speed': 'citadel_observer_roaming_speed {value:.0f}',

    'playback/rate': 60,
    'playback/preroll': 1.5,
    'playback/live_preview': True,
    'playback/sync_replay': True,
    'playback/pause_at_end': True,
    'playback/capture_from_game': True,

    'obs/enabled': False,
    'obs/host': '127.0.0.1',
    'obs/port': 4455,
    'obs/password': '',
}

CAMERA_PRESETS = [
    ('spec_goto + spec_setang (default)', 'spec_goto {x:.2f} {y:.2f} {z:.2f} {pitch:.2f} {yaw:.2f}; spec_setang {pitch:.2f} {yaw:.2f}'),
    ('spec_setpos + spec_setang', 'spec_setpos {x:.2f} {y:.2f} {z:.2f}; spec_setang {pitch:.2f} {yaw:.2f}'),
    ('spec_goto only (position + angles)', 'spec_goto {x:.2f} {y:.2f} {z:.2f} {pitch:.2f} {yaw:.2f}'),
]


class Settings(object):

    def __init__(self, store=None):
        self.store = store or QSettings('DeadlockDirector', 'DeadlockDirector')

    def get(self, key):
        default = DEFAULTS[key]
        value = self.store.value(key, default)
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.lower() in ('1', 'true', 'yes')
            return bool(value)
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        if isinstance(default, float):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        return '' if value is None else str(value)

    def set(self, key, value):
        self.store.setValue(key, value)

    def reset(self, prefix=''):
        for key in DEFAULTS:
            if key.startswith(prefix):
                self.store.remove(key)

    def value(self, key, default=None):
        """Free-form values (window geometry, recent files...)."""
        return self.store.value(key, default)

    def set_value(self, key, value):
        self.store.setValue(key, value)


def user_dir():
    path = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not path:
        path = os.path.join(os.path.expanduser('~'), '.deadlockdirector')
    os.makedirs(path, exist_ok=True)
    return path


def sequences_dir():
    path = os.path.join(user_dir(), 'sequences')
    os.makedirs(path, exist_ok=True)
    return path
