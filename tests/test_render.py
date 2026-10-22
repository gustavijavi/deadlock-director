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


class LoggingGame(FakeGame):
    """Executes the exec'd cfg like Deadlock would and appends to console.log
    in its format (timestamp prefix, one decimal in spec_pos output)."""

    def __init__(self, cfg, logPath, **kwargs):
        FakeGame.__init__(self, cfg, **kwargs)
        self.logPath = logPath
        self.camera = [0.0] * 5
        open(logPath, 'w').write('10/22 09:00:00 Source2Init\n')

    def tap(self):
        FakeGame.tap(self)
        out = []
        for command in open(self.cfg).read().replace('\n', ';').split(';'):
            parts = command.split()
            if not parts:
                continue
            if parts[0] == 'spec_goto':
                self.camera = [float(v) for v in parts[1:6]]
            elif parts[0] == 'spec_pos':
                out.append('spec_goto {:.1f} {:.1f} {:.1f} {:.1f} {:.1f}'.format(*self.camera))
            elif parts[0] == 'echo':
                out.append(' '.join(parts[1:]))
        with open(self.logPath, 'a') as log:
            for line in out:
                log.write('10/22 09:00:01 ' + line + '\n')


def test_render_confirmed_by_console_log(tmp_path):
    cfg, logPath = str(tmp_path / 'ddir_frame.cfg'), str(tmp_path / 'console.log')
    game = LoggingGame(cfg, logPath)
    frames = render.plan_frames(orbit_path(CameraState(100, 200, 300, 15, 45)), 0.25, 64)

    class Sink(object):
        frames = 0

        def write(self, image):
            self.frames += 1

    log = render.LogWatcher(logPath)
    renderer = render.Renderer(cfg, TEMPLATE, game.tap, game.grab, Sink(), settle=0, sleep=lambda s: None, log=log)
    assert renderer.run(frames) == len(frames)
    assert all(r.confirmed for r in renderer.records)
    assert max(r.positionError() for r in renderer.records) < 0.1  # spec_pos prints one decimal
    summary = renderer.summary()
    assert '{0} of {0} frames confirmed'.format(len(frames)) in summary
    csv = str(tmp_path / 'frames.csv')
    renderer.write_diagnostics(csv)
    rows = open(csv).read().splitlines()
    assert len(rows) == len(frames) + 1 and rows[1].startswith('0,1,')


def test_render_reports_unconfirmed_frames(tmp_path):
    """If the game never runs the cfg (bind missing), frames are flagged."""
    cfg, logPath = str(tmp_path / 'ddir_frame.cfg'), str(tmp_path / 'console.log')
    open(logPath, 'w').write('')
    ticks = iter(range(10 ** 6))
    renderer = render.Renderer(cfg, TEMPLATE, lambda: None, lambda: b'x', type('S', (), {'frames': 0, 'write': lambda s, i: None})(),
                               settle=0, sleep=lambda s: None, log=render.LogWatcher(logPath),
                               confirmTimeout=0.5, clock=lambda: next(ticks) * 0.1)
    renderer.run(render.plan_frames(lambda t: (t, 0, 0, 0, 0), 0.05, 64))
    assert not any(r.confirmed for r in renderer.records)
    assert '0 of 4 frames confirmed' in renderer.summary()


def test_log_watcher_handles_partial_lines(tmp_path):
    path = str(tmp_path / 'console.log')
    open(path, 'w').write('old line\n')
    watcher = render.LogWatcher(path)
    with open(path, 'a') as f:
        f.write('10/22 09:00:01 DDIR_F1\n10/22 09:00:01 DDIR_')
    assert watcher.lines() == ['DDIR_F1']
    with open(path, 'a') as f:
        f.write('F2\n')
    assert watcher.lines() == ['DDIR_F2']
    watcher.close()


def test_motion_blur_blends_samples(tmp_path):
    if not render.ffmpeg_exe():
        pytest.skip('ffmpeg not available')
    out = str(tmp_path / 'blur.mp4')
    encoder = render.FfmpegEncoder(out, (16, 16), 64, blur=4)
    for i in range(32):  # 32 samples -> 8 output frames
        encoder.write(bytes([i * 8 % 256, 0, 0, 255]) * 256)
    assert encoder.close() == 0
    probe = subprocess.run([render.ffmpeg_exe(), '-i', out, '-f', 'null', '-'], capture_output=True, text=True)
    assert int(re.findall(r'frame=\s*(\d+)', probe.stderr)[-1]) == 8
    assert ' 64 fps' in probe.stderr


def test_check_log(tmp_path):
    cfg, logPath = str(tmp_path / 'ddir_frame.cfg'), str(tmp_path / 'console.log')
    game = LoggingGame(cfg, logPath)
    assert render.check_log(cfg, game.tap, render.LogWatcher(logPath), sleep=lambda s: None)
    ticks = iter(range(10 ** 6))
    assert not render.check_log(cfg, lambda: None, render.LogWatcher(logPath), timeout=1.0,
                                sleep=lambda s: None, clock=lambda: next(ticks) * 0.1)


def test_render_stops_after_repeated_misses(tmp_path):
    cfg, logPath = str(tmp_path / 'ddir_frame.cfg'), str(tmp_path / 'console.log')
    open(logPath, 'w').write('')
    ticks = iter(range(10 ** 6))
    renderer = render.Renderer(cfg, TEMPLATE, lambda: None, lambda: b'x', type('S', (), {'frames': 0, 'write': lambda s, i: None})(),
                               settle=0, sleep=lambda s: None, log=render.LogWatcher(logPath), maxMissed=3,
                               confirmTimeout=0.5, clock=lambda: next(ticks) * 0.1)
    with pytest.raises(render.RenderError):
        renderer.run(render.plan_frames(lambda t: (t, 0, 0, 0, 0), 1.0, 64))
    assert len(renderer.records) == 3
    assert open(cfg).read().startswith('citadel_hud_visible true')  # HUD restored on failure too
