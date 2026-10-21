"""Drives the replay camera along a Sequence in real time."""
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

STOPPED = 'stopped'
PREROLL = 'preroll'
PLAYING = 'playing'


class SequencePlayer(QObject):
    timeChanged = Signal(float)
    stateChanged = Signal(str)
    message = Signal(str)

    def __init__(self, game, settings, sequence, recorder=None, parent=None):
        QObject.__init__(self, parent)
        self.game = game
        self.settings = settings
        self.sequence = sequence
        self.recorder = recorder
        self.time = 0.0
        self.state = STOPPED
        self.synced = False
        self.recording = False
        self.startTime = 0.0
        self.lastWall = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    # -- state -----------------------------------------------------------
    def isActive(self):
        return self.state != STOPPED

    def _setState(self, state):
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)

    def setTime(self, t, apply=True):
        self.time = max(0.0, float(t))
        self.timeChanged.emit(self.time)
        if apply and not self.isActive() and self.settings.get('playback/live_preview'):
            self.apply(self.time)

    def apply(self, t, timescale=False):
        """Push the sequence state at time t to the game."""
        values = self.sequence.evaluate(t)
        if 'position' in values or 'rotation' in values:
            self.game.setCamera(values.get('position'), values.get('rotation'))
        if 'fov' in values and self.game.hasFov():
            self.game.setFov(values['fov'])
        if timescale and 'speed' in values:
            self.game.setTimescale(self.sequence.speed_at(t))

    # -- transport -------------------------------------------------------
    def play(self, record=False, fromStart=False):
        if self.isActive():
            return
        if fromStart or self.time >= self.sequence.duration:
            self.time = 0.0
        self.startTime = self.time
        self.synced = bool(self.settings.get('playback/sync_replay')) and self.sequence.start_tick is not None
        self.recording = bool(record and self.recorder is not None)
        preroll = 0.0
        if self.synced:
            self.game.pause()
            self.game.seek(self.sequence.tick_at(self.time))
            preroll = self.settings.get('playback/preroll')
        self.apply(self.time, timescale=True)
        if self.recording:
            self.recorder.startRecording()
            preroll = max(preroll, 0.5)
        self._setState(PREROLL)
        self.timeChanged.emit(self.time)
        QTimer.singleShot(int(preroll * 1000), self, self._begin)

    def _begin(self):
        if self.state != PREROLL:
            return
        if self.synced:
            self.game.resume()
        self.lastWall = time.perf_counter()
        rate = max(10, min(240, self.settings.get('playback/rate')))
        self.timer.start(int(1000 / rate))
        self._setState(PLAYING)

    def _tick(self):
        now = time.perf_counter()
        dt = now - self.lastWall
        self.lastWall = now
        self.time += dt * self.sequence.speed_at(self.time)
        end = self.sequence.duration
        if self.time >= end:
            self.time = end
            self.apply(self.time, timescale=True)
            self.timeChanged.emit(self.time)
            self.stop(finished=True)
            return
        self.apply(self.time, timescale=True)
        self.timeChanged.emit(self.time)

    def stop(self, finished=False):
        if not self.isActive():
            return
        self.timer.stop()
        if self.recording:
            self.recorder.stopRecording()
            self.recording = False
        if self.synced and (not finished or self.settings.get('playback/pause_at_end')):
            self.game.pause()
        if self.sequence.track('speed').keyframes:
            self.game.setTimescale(1.0)
        self._setState(STOPPED)
        if finished:
            self.message.emit('Sequence finished')

    def toggle(self, record=False):
        if self.isActive():
            self.stop()
        else:
            self.play(record=record)
