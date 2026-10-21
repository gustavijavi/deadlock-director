"""Sequence data model: tracks of keyframes that drive the replay camera."""
import copy
import json

from deadlockdirector import interpolation

FILE_VERSION = 1

# name -> (label, kind, default blend, component labels)
TRACKS = {
    'position': ('Camera Position', 'vector', 'spline', ('X', 'Y', 'Z')),
    'rotation': ('Camera Rotation', 'vector', 'spline', ('Pitch', 'Yaw', 'Roll')),
    'fov': ('Field of View', 'float', 'smooth', ('FOV',)),
    'speed': ('Replay Speed', 'float', 'smooth', ('Speed',)),
}
TRACK_ORDER = ['position', 'rotation', 'fov', 'speed']


class Keyframe(object):
    __slots__ = ('time', 'value', 'blend')

    def __init__(self, time, value, blend='spline'):
        self.time = float(time)
        self.value = list(value) if isinstance(value, (list, tuple)) else float(value)
        self.blend = blend if blend in interpolation.BLEND_NAMES else 'linear'

    def to_dict(self):
        return {'time': self.time, 'value': copy.copy(self.value), 'blend': self.blend}

    @classmethod
    def from_dict(cls, data):
        return cls(data['time'], data['value'], data.get('blend', 'linear'))

    def __repr__(self):
        return 'Keyframe({!r}, {!r}, {!r})'.format(self.time, self.value, self.blend)


class Track(object):

    def __init__(self, name):
        self.name = name
        self.label, self.kind, self.default_blend, self.components = TRACKS[name]
        self.keyframes = []

    def sort(self):
        self.keyframes.sort(key=lambda k: k.time)

    def add(self, time, value, blend=None):
        """Add a keyframe, replacing any existing keyframe at the same time."""
        time = round(float(time), 4)
        for key in self.keyframes:
            if abs(key.time - time) < 1e-4:
                key.value = list(value) if isinstance(value, (list, tuple)) else float(value)
                if blend:
                    key.blend = blend
                return key
        key = Keyframe(time, value, blend or self.default_blend)
        self.keyframes.append(key)
        self.sort()
        return key

    def remove(self, key):
        if key in self.keyframes:
            self.keyframes.remove(key)

    def evaluate(self, t):
        if not self.keyframes:
            return None
        times = [k.time for k in self.keyframes]
        values = [k.value for k in self.keyframes]
        blends = [k.blend for k in self.keyframes]
        if self.name == 'rotation':
            values = interpolation.unwrap_angles(values)
        return interpolation.evaluate(times, values, blends, t)


class Sequence(object):
    """A named set of tracks plus how the timeline maps onto the replay.

    Sequence time 0 corresponds to replay tick `start_tick` (when set). The
    replay advances `tickrate` ticks per second of sequence time.
    """

    def __init__(self):
        self.name = 'Untitled'
        self.start_tick = None
        self.tickrate = 64.0
        self.tracks = {name: Track(name) for name in TRACK_ORDER}

    # -- queries ---------------------------------------------------------
    def track(self, name):
        return self.tracks[name]

    def keyframes(self):
        for name in TRACK_ORDER:
            for key in self.tracks[name].keyframes:
                yield name, key

    def is_empty(self):
        return not any(self.tracks[name].keyframes for name in TRACK_ORDER)

    @property
    def duration(self):
        end = 0.0
        for _, key in self.keyframes():
            end = max(end, key.time)
        return end

    def evaluate(self, t):
        """Return {track name: value} for every track with keyframes."""
        result = {}
        for name in TRACK_ORDER:
            value = self.tracks[name].evaluate(t)
            if value is not None:
                result[name] = value
        return result

    def speed_at(self, t):
        value = self.tracks['speed'].evaluate(t)
        return 1.0 if value is None else max(0.01, float(value))

    def tick_at(self, t):
        if self.start_tick is None:
            return None
        return int(round(self.start_tick + t * self.tickrate))

    # -- serialization ---------------------------------------------------
    def to_dict(self):
        return {
            'version': FILE_VERSION,
            'app': 'deadlock-director',
            'name': self.name,
            'start_tick': self.start_tick,
            'tickrate': self.tickrate,
            'tracks': {name: [k.to_dict() for k in self.tracks[name].keyframes] for name in TRACK_ORDER},
        }

    @classmethod
    def from_dict(cls, data):
        seq = cls()
        seq.load_dict(data)
        return seq

    def load_dict(self, data):
        self.name = data.get('name', 'Untitled')
        start = data.get('start_tick')
        self.start_tick = None if start is None else int(start)
        self.tickrate = float(data.get('tickrate', 64.0))
        for name in TRACK_ORDER:
            track = self.tracks[name]
            track.keyframes = [Keyframe.from_dict(k) for k in data.get('tracks', {}).get(name, [])]
            track.sort()

    def save(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_dict(json.load(f))


class History(object):
    """Snapshot based undo / redo for a Sequence."""

    def __init__(self, sequence, limit=200):
        self.sequence = sequence
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []

    def push(self):
        """Call *before* mutating the sequence."""
        self.undo_stack.append(self.sequence.to_dict())
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.sequence.to_dict())
        self.sequence.load_dict(self.undo_stack.pop())
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.sequence.to_dict())
        self.sequence.load_dict(self.redo_stack.pop())
        return True

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
