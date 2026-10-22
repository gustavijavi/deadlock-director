"""Frame-by-frame rendering of a camera path from a paused Deadlock replay.

Live playback can't stay in step with the game's frame rate, so instead the
replay stays paused and every video frame is produced in lockstep:

    1. write the frame's camera position (and how many ticks to advance) to the
       exec'd cfg, 2. tap the bound key, 3. wait until the game has drawn it,
    4. capture the window and hand the pixels to ffmpeg.

Nothing races a clock, so the result is smooth however long each step takes.
The I/O pieces (tap, grab, encoder) are passed in so the loop can be tested.
"""
import math
import os
import subprocess
import sys
import time

from deadlockdirector import console, pathtest

PREAMBLE = 'demo_pause; citadel_hud_visible false; citadel_hide_replay_hud true'
POSTAMBLE = 'citadel_hud_visible true; citadel_hide_replay_hud false'


def plan_frames(path, duration, fps, ticks_per_frame=1.0):
    """[(camera tuple, ticks to advance before this frame)] for a path f(t).

    ticks_per_frame below 1 gives slow motion (the replay advances every few
    frames); 0 freezes the replay while the camera moves.
    """
    count = max(1, int(round(duration * fps)) + 1)
    frames = []
    owed = 0.0
    for i in range(count):
        steps = 0
        if i > 0:
            owed += ticks_per_frame
            steps = int(math.floor(owed + 1e-9))
            owed -= steps
        frames.append((tuple(path(i / fps)), steps))
    return frames


def frame_text(template, camera, steps):
    text = pathtest.frame_commands(template, *camera)
    if steps:
        text += '; demo_step_tick {}'.format(steps)
    return text


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class FfmpegEncoder(object):
    """Pipe raw BGRA frames into ffmpeg and get an H.264 MP4 out.

    With blur > 1 every `blur` consecutive input frames are averaged into one
    output frame (motion blur), so the input runs at fps * blur.
    """

    def __init__(self, path, size, fps, crf=14, exe=None, blur=1):
        exe = exe or ffmpeg_exe()
        if not exe:
            raise RuntimeError('ffmpeg is not available')
        width, height = size
        self.path = path
        self.logPath = path + '.ffmpeg.log'
        self.log = open(self.logPath, 'wb')
        flags = 0x08000000 if sys.platform == 'win32' else 0  # CREATE_NO_WINDOW
        blur = max(1, int(blur))
        filters = ['-vf', 'tmix=frames={0},framestep={0}'.format(blur)] if blur > 1 else []
        self.process = subprocess.Popen(
            [exe, '-y', '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', '{}x{}'.format(width, height),
             '-framerate', str(fps * blur), '-i', '-'] + filters +
            ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf),
             '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log, creationflags=flags)
        self.frames = 0

    def write(self, frame):
        self.process.stdin.write(frame)
        self.frames += 1

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        code = self.process.wait()
        self.log.close()
        if code == 0:
            os.remove(self.logPath)
        return code


class RenderError(Exception):
    pass


def check_log(cfgPath, tap, log, timeout=3.0, sleep=time.sleep, clock=time.perf_counter):
    """Prove the exec bind and console.log both work before a long render:
    run `echo DDIR_HELLO` through the bind and wait for it in the log."""
    token = 'DDIR_HELLO{}'.format(int(clock() * 1000) % 100000)
    while not pathtest.write_frame(cfgPath, 'echo ' + token):
        sleep(0.005)
    tap()
    start = clock()
    while clock() - start < timeout:
        if any(line.strip() == token for line in log.lines()):
            return True
        sleep(0.01)
    return False


class LogWatcher(object):
    """Follows Deadlock's -condebug console.log from its current end."""

    def __init__(self, path):
        self.file = open(path, 'rb')
        self.file.seek(0, os.SEEK_END)
        self.partial = b''

    def lines(self):
        data = self.file.read()
        if not data:
            return []
        data = self.partial + data
        complete, _, self.partial = data.rpartition(b'\n')
        if not complete and not _:
            self.partial = data
            return []
        return [console.clean_line(l.decode('utf-8', errors='replace')) for l in complete.split(b'\n')]

    def close(self):
        self.file.close()


def marker(index):
    return 'DDIR_F{}'.format(index)


class FrameRecord(object):
    __slots__ = ('index', 'intended', 'actual', 'confirmMs', 'confirmed')

    def __init__(self, index, intended):
        self.index = index
        self.intended = intended
        self.actual = None
        self.confirmMs = None
        self.confirmed = False

    def positionError(self):
        if self.actual is None:
            return None
        return math.dist(self.intended[:3], self.actual.position)


class Renderer(object):
    """Renders frames in lockstep with the game.

    With a LogWatcher, each frame's cfg ends in `spec_pos; echo DDIR_F<n>`:
    the marker appearing in console.log proves the camera commands ran, and
    the spec_pos line just before it records where the camera really was.
    Without one, it falls back to waiting until the captured image changes.
    """

    def __init__(self, cfgPath, template, tap, grab, encoder, settle=0.08, tickTime=1 / 64.0,
                 maxWait=0.75, isFocused=lambda: True, stopped=lambda: False, progress=lambda i, n: None,
                 sleep=time.sleep, log=None, confirmTimeout=2.0, clock=time.perf_counter, maxMissed=5):
        self.cfgPath = cfgPath
        self.template = template
        self.tap = tap
        self.grab = grab
        self.encoder = encoder
        self.settle = settle
        self.tickTime = tickTime
        self.maxWait = maxWait
        self.isFocused = isFocused
        self.stopped = stopped
        self.progress = progress
        self.sleep = sleep
        self.log = log
        self.confirmTimeout = confirmTimeout
        self.clock = clock
        self.maxMissed = maxMissed
        self.stale = 0  # frames that never changed on screen within maxWait
        self.records = []

    def _send(self, text):
        while not pathtest.write_frame(self.cfgPath, text):
            self.sleep(0.005)
        while not self.isFocused():
            if self.stopped():
                return False
            self.sleep(0.1)
        self.tap()
        return True

    def _confirm(self, record, sentAt):
        """Wait for this frame's marker in console.log."""
        token = marker(record.index)
        seen = []
        while self.clock() - sentAt < self.confirmTimeout:
            for line in self.log.lines():
                if token == line.strip():
                    record.confirmed = True
                    record.confirmMs = (self.clock() - sentAt) * 1000.0
                    for previous in reversed(seen):
                        state = console.parse_camera(previous)
                        if state is not None and 'spec_goto' in previous:
                            record.actual = state
                            break
                    return True
                seen.append(line)
            self.sleep(0.002)
        return False

    def run(self, frames):
        """Render every frame. Returns the number of frames written."""
        self._send(PREAMBLE)
        self.sleep(0.25)
        previousImage = previousCamera = None
        missed = 0
        try:
            for index, (camera, steps) in enumerate(frames):
                if self.stopped():
                    break
                record = FrameRecord(index, camera)
                self.records.append(record)
                text = frame_text(self.template, camera, steps)
                if self.log is not None:
                    text += '; spec_pos; echo {}'.format(marker(index))
                if not self._send(text):
                    break
                sentAt = self.clock()
                if self.log is not None:
                    if self._confirm(record, sentAt):
                        missed = 0
                    else:
                        missed += 1
                        if missed >= self.maxMissed:
                            raise RenderError('Deadlock stopped confirming frames in console.log ({} in a row). '
                                              'Was the console opened or the window switched?'.format(missed))
                    # Commands ran; give the game a few frames to draw and present.
                    self.sleep(self.settle + steps * self.tickTime)
                    image = self.grab()
                else:
                    self.sleep(self.settle + steps * self.tickTime)
                    image = self.grab()
                    # If the view should have changed but the screen hasn't caught
                    # up yet, keep waiting a little instead of writing a duplicate.
                    expectChange = camera != previousCamera or steps
                    waited = 0.0
                    while expectChange and previousImage is not None and image == previousImage and waited < self.maxWait:
                        self.sleep(0.02)
                        waited += 0.02
                        image = self.grab()
                    if expectChange and previousImage is not None and image == previousImage:
                        self.stale += 1
                self.encoder.write(image)
                previousImage, previousCamera = image, camera
                self.progress(index + 1, len(frames))
        finally:
            self._send(POSTAMBLE)
        return self.encoder.frames

    def summary(self):
        """Human-readable sync statistics for the report."""
        if self.log is None or not self.records:
            return ''
        confirmed = [r for r in self.records if r.confirmed]
        text = ' {} of {} frames confirmed by the game'.format(len(confirmed), len(self.records))
        if confirmed:
            times = sorted(r.confirmMs for r in confirmed)
            text += ' (typically {:.0f} ms, worst {:.0f} ms)'.format(times[len(times) // 2], times[-1])
        errors = [r.positionError() for r in confirmed if r.positionError() is not None]
        if errors:
            text += '; camera landed within {:.1f} units of the path'.format(max(errors))
        return text + '.'

    def write_diagnostics(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('frame,confirmed,confirm_ms,x,y,z,pitch,yaw,actual_x,actual_y,actual_z,actual_pitch,actual_yaw\n')
            for r in self.records:
                actual = (r.actual.position + r.actual.rotation[:2]) if r.actual else [''] * 5
                f.write(','.join(str(v) for v in [r.index, int(r.confirmed),
                                                   '' if r.confirmMs is None else round(r.confirmMs, 1)]
                                 + [round(v, 2) for v in r.intended] + list(actual)) + '\n')
