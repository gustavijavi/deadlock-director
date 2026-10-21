import math
import os

import pytest

from deadlockdirector import pathtest
from deadlockdirector.console import CameraState

SAMPLE_LOG = os.path.join(os.path.dirname(__file__), 'data', 'console_sample.log')


def look_at_error(frame, target):
    """Angle (degrees) between the camera's view direction and the target."""
    x, y, z, pitch, yaw = frame
    view = (math.cos(math.radians(yaw)) * math.cos(math.radians(pitch)),
            math.sin(math.radians(yaw)) * math.cos(math.radians(pitch)),
            -math.sin(math.radians(pitch)))
    to = (target[0] - x, target[1] - y, target[2] - z)
    length = math.sqrt(sum(c * c for c in to))
    dot = sum(a * b / length for a, b in zip(view, to))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


@pytest.mark.parametrize('pitch,yaw', [(0, 0), (20, 188.2), (-10, 31.5), (35, -90)])
def test_orbit_starts_at_camera_and_keeps_target_in_view(pitch, yaw):
    start = CameraState(1000, -500, 300, pitch, yaw)
    path = pathtest.orbit_path(start, distance=600, duration=8)
    x, y, z, p, w = path(0)
    assert (x, y, z) == pytest.approx((1000, -500, 300), abs=1e-6)
    assert p == pytest.approx(pitch, abs=1e-6)
    assert math.cos(math.radians(w - yaw)) == pytest.approx(1.0)
    target = (1000 + math.cos(math.radians(yaw)) * 600, -500 + math.sin(math.radians(yaw)) * 600,
              300 - math.tan(math.radians(pitch)) * 600)
    for i in range(41):
        frame = path(8 * i / 40)
        assert look_at_error(frame, target) < 0.01
        assert math.hypot(frame[0] - target[0], frame[1] - target[1]) == pytest.approx(600)
    # A full turn ends where it began.
    assert path(8)[:3] == pytest.approx(path(0)[:3], abs=1e-6)


def test_orbit_moves_smoothly():
    path = pathtest.orbit_path(CameraState(0, 0, 0, 10, 0), distance=600, duration=8)
    frames = [path(i / 30) for i in range(241)]
    steps = [math.dist(a[:3], b[:3]) for a, b in zip(frames, frames[1:])]
    # Never a jump bigger than a smooth orbit allows (circumference / frames * ease peak 1.5).
    assert max(steps) < 2 * math.pi * 600 / 240 * 1.6


def test_frame_file_roundtrip(tmp_path):
    target = str(tmp_path / 'ddir_frame.cfg')
    text = pathtest.frame_commands('spec_goto {x:.2f} {y:.2f} {z:.2f} {pitch:.2f} {yaw:.2f}; spec_setang {pitch:.2f} {yaw:.2f}',
                                   1, 2, 3, 4, 5)
    assert pathtest.write_frame(target, text)
    assert open(target).read() == 'spec_goto 1.00 2.00 3.00 4.00 5.00; spec_setang 4.00 5.00\n'
    assert not os.path.exists(target + '.tmp')


def test_last_camera_from_real_console_log():
    state = pathtest.last_camera_in_log(SAMPLE_LOG)
    assert state.position == pytest.approx([1089.6, 9974.8, 1386.3])
    assert state.rotation == pytest.approx([25.3, 31.5, 0.0])


def test_install_paths(tmp_path):
    log = tmp_path / 'game' / 'citadel' / 'console.log'
    log.parent.mkdir(parents=True)
    log.write_text('')
    assert pathtest.find_console_log(str(tmp_path)) == str(log)
    assert pathtest.cfg_dir(str(tmp_path)).endswith(os.path.join('game', 'citadel', 'cfg'))
    assert pathtest.bind_command('KP_MINUS') == 'bind KP_MINUS "exec ddir_frame"'
