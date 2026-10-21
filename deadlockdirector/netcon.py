"""Client for the Source 2 engine's built-in network console.

Deadlock (like other Source 2 games) can open its developer console on a
local TCP port when launched with ``-netconport <port>``. The protocol is
plain text: each line we send is executed as a console command, and console
output is streamed back line by line. No memory access, injection or input
simulation is involved.
"""
import itertools
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from deadlockdirector.console import MARKER_PREFIX, clean_line, sanitize


class _Query(object):
    __slots__ = ('ident', 'callback', 'lines', 'window', 'started', 'deadline')

    def __init__(self, ident, callback, deadline):
        self.ident = ident
        self.callback = callback
        self.lines = []
        self.window = []
        self.started = False
        self.deadline = deadline


class NetConClient(QObject):
    """Plain-text console (-netconport): one command per line each way."""
    protocol = 'netcon'
    connectedChanged = Signal(bool)
    lineReceived = Signal(str, bool)  # line, solicited (part of one of our queries)
    errorOccurred = Signal(str)
    commandSent = Signal(str)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self.socket = QTcpSocket(self)
        self.socket.connected.connect(self._onConnected)
        self.socket.disconnected.connect(self._onDisconnected)
        self.socket.readyRead.connect(self._onReadyRead)
        self.socket.errorOccurred.connect(self._onError)
        self.buffer = b''
        self.queries = {}
        self.counter = itertools.count(1)
        self.echoCommands = True
        self.expiryTimer = QTimer(self)
        self.expiryTimer.setInterval(50)
        self.expiryTimer.timeout.connect(self._expireQueries)

    # -- connection ------------------------------------------------------
    def isConnected(self):
        return self.socket.state() == QAbstractSocket.ConnectedState

    def isBusy(self):
        return self.socket.state() in (QAbstractSocket.HostLookupState, QAbstractSocket.ConnectingState)

    def connectTo(self, host, port):
        if self.isConnected() or self.isBusy():
            return
        self.socket.connectToHost(host, int(port))

    def close(self):
        self.socket.abort()
        self._failQueries()
        self.buffer = b''

    def _onConnected(self):
        self.connectedChanged.emit(True)

    def _onDisconnected(self):
        self._failQueries()
        self.connectedChanged.emit(False)

    def _onError(self, error):
        # Connection refused is the normal "game not running yet" case.
        if error != QAbstractSocket.RemoteHostClosedError:
            self.errorOccurred.emit(self.socket.errorString())

    # -- sending ---------------------------------------------------------
    def send(self, command):
        command = sanitize(command)
        if not command or not self.isConnected():
            return False
        self.socket.write(self.encode(command))
        if self.echoCommands:
            self.commandSent.emit(command)
        return True

    def query(self, command, callback, timeout=1500):
        """Run a command and hand every output line it produced to callback.

        The command is bracketed by two `echo` markers so its output can be
        told apart from whatever else the console is printing. If the markers
        never show up, the callback still receives every line seen during the
        timeout window.
        """
        if not self.isConnected():
            callback([])
            return
        query = _Query(next(self.counter), callback, time.monotonic() + timeout / 1000.0)
        self.queries[query.ident] = query
        echo, self.echoCommands = self.echoCommands, False
        self.send('echo {}_B{}'.format(MARKER_PREFIX, query.ident))
        self.send(command)
        self.send('echo {}_E{}'.format(MARKER_PREFIX, query.ident))
        self.echoCommands = echo
        if not self.expiryTimer.isActive():
            self.expiryTimer.start()

    def _expireQueries(self):
        now = time.monotonic()
        for ident, query in list(self.queries.items()):
            if now >= query.deadline:
                self._finish(ident)
        if not self.queries:
            self.expiryTimer.stop()

    def _finish(self, ident):
        query = self.queries.pop(ident, None)
        if query is None:
            return
        lines = query.lines if query.started else query.window
        query.callback(list(lines))

    def _failQueries(self):
        for ident in list(self.queries):
            self._finish(ident)

    # -- wire format (overridden by VConsoleClient) -----------------------
    def encode(self, command):
        return (command + '\n').encode('utf-8')

    def decode(self):
        """Consume complete messages from self.buffer, yielding text lines."""
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            yield raw.decode('utf-8', errors='replace')

    # -- receiving -------------------------------------------------------
    def _onReadyRead(self):
        self.buffer += bytes(self.socket.readAll().data())
        for raw in self.decode():
            line = clean_line(raw)
            if line:
                self._handleLine(line)

    def _handleLine(self, line):
        solicited = False
        for ident, query in list(self.queries.items()):
            begin = '{}_B{}'.format(MARKER_PREFIX, ident)
            end = '{}_E{}'.format(MARKER_PREFIX, ident)
            if begin in line:
                query.started = True
                solicited = True
            elif end in line:
                solicited = True
                if query.started:
                    self._finish(ident)
            elif query.started:
                query.lines.append(line)
                solicited = True
            else:
                query.window.append(line)
        if MARKER_PREFIX in line:
            solicited = True
        self.lineReceived.emit(line, solicited)
