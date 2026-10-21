"""High level controller for a running Deadlock replay.

Everything the app does to the game goes through `DeadlockGame`, which turns
intentions ("put the camera here", "pause the replay") into the console
commands configured in Settings and sends them over the network console.
"""
import functools
import re

from PySide6.QtCore import QObject, QTimer, Signal

from deadlockdirector import console, detect
from deadlockdirector.console import CameraState
from deadlockdirector.netcon import NetConClient
from deadlockdirector.vconsole import VConsoleClient

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
    connectionProblem = Signal(str)

    def __init__(self, settings, parent=None):
        QObject.__init__(self, parent)
        self.settings = settings
        # Two ways into the same console: the plain-text network console
        # (-netconport) and Source 2's VConsole protocol. Whichever connects
        # first becomes the active client.
        self.clients = {'netcon': NetConClient(self), 'vconsole': VConsoleClient(self)}
        for protocol, client in self.clients.items():
            client.connectedChanged.connect(functools.partial(self._onClientConnected, protocol))
            client.lineReceived.connect(self._onLine)
            client.commandSent.connect(self.commandSent)
            client.errorOccurred.connect(self.connectionProblem)
        self.client = self.clients['netcon']
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

    @property
    def protocol(self):
        return self.client.protocol

    @property
    def gameName(self):
        """Name the game reported over VConsole ('citadel' is Deadlock)."""
        return getattr(self.client, 'gameName', '')

    def connectionErrors(self):
        """Ports that answered but failed the console handshake."""
        return [c.lastError for c in self.clients.values() if c.lastError]

    def port(self, protocol=None):
        protocol = protocol or self.client.protocol
        return self.settings.get('connection/vconsole_port' if protocol == 'vconsole' else 'connection/port')

    def _protocols(self):
        mode = self.settings.get('connection/protocol')
        return [mode] if mode in self.clients else ['netcon', 'vconsole']

    def connectToGame(self):
        self.manualDisconnect = False
        self._attempt()

    def _attempt(self):
        if self.isConnected():
            return
        host = self.settings.get('connection/host')
        for protocol in self._protocols():
            self.clients[protocol].connectTo(host, self.port(protocol))

    def disconnectFromGame(self):
        self.manualDisconnect = True
        for client in self.clients.values():
            client.close()
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
            self._attempt()

    def _onClientConnected(self, protocol, connected):
        client = self.clients[protocol]
        if connected:
            if self.client is not client and self.client.isConnected():
                client.close()  # already talking to the game the other way
                return
            self.client = client
            for other in self.clients.values():
                if other is not client:
                    other.close()
            self.lastSent.clear()
            self._setStatus(STATUS_CONNECTED)
            QTimer.singleShot(200, self, self.queryCamera)
        elif client is self.client:
            self.lastSent.clear()
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
