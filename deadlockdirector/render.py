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

from deadlockdirector import pathtest

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
    """Pipe raw BGRA frames into ffmpeg and get an H.264 MP4 out."""

    def __init__(self, path, size, fps, crf=14, exe=None):
        exe = exe or ffmpeg_exe()
        if not exe:
            raise RuntimeError('ffmpeg is not available')
        width, height = size
        self.path = path
        self.logPath = path + '.ffmpeg.log'
        self.log = open(self.logPath, 'wb')
        flags = 0x08000000 if sys.platform == 'win32' else 0  # CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            [exe, '-y', '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', '{}x{}'.format(width, height),
             '-framerate', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf),
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


class Renderer(object):

    def __init__(self, cfgPath, template, tap, grab, encoder, settle=0.08, tickTime=1 / 64.0,
                 maxWait=0.75, isFocused=lambda: True, stopped=lambda: False, progress=lambda i, n: None,
                 sleep=time.sleep):
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
        self.stale = 0  # frames that never changed on screen within maxWait

    def _send(self, text):
        while not pathtest.write_frame(self.cfgPath, text):
            self.sleep(0.005)
        while not self.isFocused():
            if self.stopped():
                return False
            self.sleep(0.1)
        self.tap()
        return True

    def run(self, frames):
        """Render every frame. Returns the number of frames written."""
        self._send(PREAMBLE)
        self.sleep(0.25)
        previousImage = previousCamera = None
        try:
            for index, (camera, steps) in enumerate(frames):
                if self.stopped():
                    break
                if not self._send(frame_text(self.template, camera, steps)):
                    break
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
