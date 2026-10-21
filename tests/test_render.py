import os
import re
import subprocess

import pytest

from deadlockdirector import render
from deadlockdirector.console import CameraState
from deadlockdirector.pathtest import orbit_path

TEMPLATE = 'spec_goto {x:.2f} {y:.2f} {z:.2f} {pitch:.2f} {yaw:.2f}; spec_setang {pitch:.2f} {yaw:.2f}'


def test_plan_frames_ticks():
    path = lambda t: (t, 0, 0, 0, 0)
    assert [s for _, s in render.plan_frames(path, 0.1, 50, 1.0)] == [0, 1, 1, 1, 1, 1]
    assert [s for _, s in render.plan_frames(path, 0.1, 50, 0.5)] == [0, 0, 1, 0, 1, 0]
    assert [s for _, s in render.plan_frames(path, 0.1, 50, 2.0)] == [0, 2, 2, 2, 2, 2]
    assert [s for _, s in render.plan_frames(path, 0.1, 50, 0.0)] == [0] * 6
    assert render.plan_frames(path, 1.0, 64)[-1][0][0] == pytest.approx(1.0)


def test_frame_text():
    assert render.frame_text('spec_goto {x:.0f} {y:.0f} {z:.0f}', (1, 2, 3, 0, 0), 0) == 'spec_goto 1 2 3'
    assert render.frame_text('spec_goto {x:.0f} {y:.0f} {z:.0f}', (1, 2, 3, 0, 0), 2).endswith('; demo_step_tick 2')


class FakeGame(object):
    """The 'screen' shows whatever camera frame was last exec'd, but only
    `lag` grabs after the key tap, like a real game catching up."""

    def __init__(self, cfg, size=(64, 36), lag=0):
        self.cfg, self.size, self.lag = cfg, size, lag
        self.shown = b''
        self.pending = None
        self.countdown = 0
        self.taps = 0

    def tap(self):
        self.taps += 1
        self.pending = open(self.cfg, 'rb').read()
        self.countdown = self.lag

    def grab(self):
        if self.pending is not None:
            if self.countdown == 0:
                self.shown, self.pending = self.pending, None
            else:
                self.countdown -= 1
        width, height = self.size
        seed = sum(self.shown) % 251
        return bytes([seed, (seed * 7) % 256, (seed * 13) % 256, 255]) * (width * height)


@pytest.mark.parametrize('lag', [0, 3])
def test_render_orbit_to_mp4(tmp_path, lag):
    if not render.ffmpeg_exe():
        pytest.skip('ffmpeg not available')
    cfg = str(tmp_path / 'ddir_frame.cfg')
    game = FakeGame(cfg, lag=lag)
    frames = render.plan_frames(orbit_path(CameraState(0, 0, 100, 10, 0)), 0.5, 64)
    out = str(tmp_path / 'orbit.mp4')
    encoder = render.FfmpegEncoder(out, game.size, 64)
    progress = []
    renderer = render.Renderer(cfg, TEMPLATE, game.tap, game.grab, encoder, settle=0, sleep=lambda s: None,
                               progress=lambda i, n: progress.append(i))
    written = renderer.run(frames)
    assert encoder.close() == 0
    assert written == len(frames) == 33
    assert renderer.stale == 0           # waited for every frame to show up
    assert game.taps == len(frames) + 2  # preamble + frames + postamble
    assert progress[-1] == len(frames)
    assert open(cfg).read().startswith('citadel_hud_visible true')
    probe = subprocess.run([render.ffmpeg_exe(), '-i', out, '-f', 'null', '-'], capture_output=True, text=True)
    counted = int(re.findall(r'frame=\s*(\d+)', probe.stderr)[-1])
    assert counted == len(frames)
    assert os.path.getsize(out) > 0 and not os.path.exists(out + '.ffmpeg.log')


def test_render_stops_when_asked(tmp_path):
    cfg = str(tmp_path / 'ddir_frame.cfg')
    game = FakeGame(cfg)

    class Sink(object):
        frames = 0

        def write(self, image):
            self.frames += 1

    calls = []
    renderer = render.Renderer(cfg, TEMPLATE, game.tap, game.grab, Sink(), settle=0, sleep=lambda s: None,
                               stopped=lambda: len(calls) >= 5, progress=lambda i, n: calls.append(i))
    assert renderer.run(render.plan_frames(lambda t: (t, 0, 0, 0, 0), 1.0, 64)) == 5
    assert open(cfg).read().startswith('citadel_hud_visible true')  # HUD restored even when stopped
