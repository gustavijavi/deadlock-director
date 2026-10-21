"""High level controller for a running Deadlock replay.

Everything the app does to the game goes through `DeadlockGame`, which turns
intentions ("put the camera here", "pause the replay") into the console
commands configured in Settings and sends them over the network console.
"""
import re

from PySide6.QtCore import QObject, QTimer, Signal

from deadlockdirector import console, detect
from deadlockdirector.console import CameraState
from deadlockdirector.netcon import NetConClient

STATUS_NOT_RUNNING = 'not_running'
STATUS_WAITING = 'waiting'
STATUS_CONNECTED = 'connected'
STATUS_DISCONNECTED = 'disconnected'

_LEADING_TEXT = re.compile(r'^[^-+.\d]*')


class DeadlockGame(QObject):
    statusChanged = Signal(str)
    cameraChanged = Signal(object)        # CameraState
    captureFromGame = Signal(object)      # CameraState printed by an in-game bind
    consoleLine = Signal(str, bool)       # line, solicited
    commandSent = Signal(str)
    tickReceived = Signal(int)

    def __init__(self, settings, parent=None):
        QObject.__init__(self, parent)
        self.settings = settings
        self.client = NetConClient(self)
        self.client.connectedChanged.connect(self._onConnectedChanged)
        self.client.lineReceived.connect(self._onLine)
        self.client.commandSent.connect(self.commandSent)
        self.camera = None
        self.fov = None
        self.timescale = None
        self.running = None
        self.status = STATUS_DISCONNECTED
        self.cameraPrefix = None
        self.lastSent = {}
        self.manualDisconnect = False
        self.detectTimer = QTimer(self)
        self.detectTimer.timeout.connect(self.poll)
        self.detectTimer.start(2500)
        self.lastDetect = 0.0

    # -- connection ------------------------------------------------------
    def isConnected(self):
        return self.client.isConnected()

    def connectToGame(self):
        self.manualDisconnect = False
        self.client.connectTo(self.settings.get('connection/host'), self.settings.get('connection/port'))

    def disconnectFromGame(self):
        self.manualDisconnect = True
        self.client.close()
        self._setStatus(STATUS_DISCONNECTED)

    def poll(self):
        """Periodic process detection + automatic (re)connection."""
        self.running = detect.is_deadlock_running()
        if self.isConnected():
            self._setStatus(STATUS_CONNECTED)
            return
        if self.running is False:
            self._setStatus(STATUS_NOT_RUNNING)
        elif not self.manualDisconnect:
            self._setStatus(STATUS_WAITING)
        # Try even when no Deadlock process was spotted: the detection is
        # only a hint, and a failed localhost connect costs nothing.
        if not self.manualDisconnect and self.settings.get('connection/autoconnect'):
            self.client.connectTo(self.settings.get('connection/host'), self.settings.get('connection/port'))

    def _onConnectedChanged(self, connected):
        self.lastSent.clear()
        if connected:
            self._setStatus(STATUS_CONNECTED)
            QTimer.singleShot(200, self, self.queryCamera)
        else:
            self.poll()

    def _setStatus(self, status):
        if status != self.status:
            self.status = status
            self.statusChanged.emit(status)

    # -- raw console -----------------------------------------------------
    def run(self, text):
        """Send one or more raw console commands typed by the user."""
        query = self.settings.get('commands/camera_query').strip().lower()
        for command in console.split_commands(text):
            if query and command.lower() == query:
                # Route through the query path so the output updates the
                # camera readout instead of being captured as a keyframe.
                self.client.commandSent.emit(command)
                self.queryCamera()
            else:
                self.client.send(command)

    def execute(self, key, dedupe=None, **values):
        text = console.render(self.settings.get(key), **values)
        if not text:
            return False
        if dedupe is not None:
            if self.lastSent.get(dedupe) == text:
                return True
            self.lastSent[dedupe] = text
        sent = False
        for command in console.split_commands(text):
            sent = self.client.send(command) or sent
        return sent

    # -- camera ----------------------------------------------------------
    def setCamera(self, position=None, rotation=None):
        base = self.camera or CameraState()
        position = position if position is not None else base.position
        rotation = rotation if rotation is not None else base.rotation
        state = CameraState(*(list(position) + list(rotation)))
        values = dict(x=state.x, y=state.y, z=state.z, pitch=state.pitch, yaw=state.yaw, roll=state.roll)
        if self.execute('commands/camera', dedupe='camera', **values):
            self.camera = state
            self.cameraChanged.emit(state)

    def setFov(self, value):
        if self.execute('commands/fov', dedupe='fov', value=float(value)):
            self.fov = float(value)

    def setTimescale(self, value):
        # Quantize so a speed ramp doesn't resend the command every frame.
        value = round(float(value), 2)
        if self.execute('commands/timescale', dedupe='timescale', value=value):
            self.timescale = float(value)

    def pause(self):
        self.lastSent.pop('resume', None)
        self.execute('commands/pause')

    def resume(self):
        self.execute('commands/resume')

    def seek(self, tick):
        self.execute('commands/seek', tick=int(max(0, tick)))

    def setHudHidden(self, hidden):
        self.execute('commands/hud_hide' if hidden else 'commands/hud_show')

    def setFreecamSpeed(self, value):
        self.execute('commands/freecam_speed', value=float(value))

    def hasFov(self):
        return bool(self.settings.get('commands/fov').strip())

    # -- queries ---------------------------------------------------------
    def queryCamera(self, callback=None):
        command = self.settings.get('commands/camera_query')
        if not command or not self.isConnected():
            if callback:
                callback(None)
            return

        def done(lines):
            state = None
            for line in lines:
                state = console.parse_camera(line)
                if state is not None:
                    self.cameraPrefix = _LEADING_TEXT.match(line).group(0).strip().lower()
                    break
            if state is not None:
                self.camera = state
                self.lastSent.pop('camera', None)
                self.cameraChanged.emit(state)
            if callback:
                callback(state)

        self.client.query(command, done)

    def queryTick(self, callback=None):
        command = self.settings.get('commands/tick_query')
        if not command or not self.isConnected():
            if callback:
                callback(None)
            return

        def done(lines):
            tick = None
            try:
                tick = console.parse_tick(lines, self.settings.get('commands/tick_regex'))
            except re.error:
                pass
            if tick is not None:
                self.tickReceived.emit(tick)
            if callback:
                callback(tick)

        self.client.query(command, done)

    # -- incoming console output -----------------------------------------
    def _onLine(self, line, solicited):
        self.consoleLine.emit(line, solicited)
        if solicited or not self.settings.get('playback/capture_from_game'):
            return
        # A camera readout we didn't ask for means the user pressed an in-game
        # bind such as `bind KP_ENTER spec_pos`: turn it into a keyframe.
        if self.cameraPrefix is None:
            return
        if _LEADING_TEXT.match(line).group(0).strip().lower() != self.cameraPrefix:
            return
        state = console.parse_camera(line)
        if state is not None:
            self.camera = state
            self.lastSent.pop('camera', None)
            self.cameraChanged.emit(state)
            self.captureFromGame.emit(state)
