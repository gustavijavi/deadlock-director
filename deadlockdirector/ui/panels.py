"""Dockable side panels."""
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCharFormat, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from deadlockdirector import detect, game as gamemod, interpolation
from deadlockdirector.console import split_commands
from deadlockdirector.ui import theme
from deadlockdirector.ui.timeline import format_time


def label(text, role=None, wrap=False):
    widget = QLabel(text)
    if role:
        widget.setProperty('role', role)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def button(text, slot=None, accent=False, tip=None):
    widget = QPushButton(text)
    if accent:
        widget.setProperty('accent', True)
    if slot:
        widget.clicked.connect(slot)
    if tip:
        widget.setToolTip(tip)
    return widget


def spin(minimum, maximum, value, decimals=2, step=1.0, suffix=''):
    if decimals == 0:
        widget = QSpinBox()
        widget.setRange(int(minimum), int(maximum))
        widget.setValue(int(value))
        widget.setSingleStep(int(step))
    else:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setSingleStep(step)
        widget.setValue(value)
    widget.setKeyboardTracking(False)
    if suffix:
        widget.setSuffix(suffix)
    return widget


def row(*widgets, stretch=False):
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        if isinstance(w, int):
            layout.addSpacing(w)
        else:
            layout.addWidget(w)
    if stretch:
        layout.addStretch(1)
    return layout


def scrolling(widget):
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    return area


class _DiagnoseResult(QObject):
    ready = Signal(str, list, object)


PROTOCOLS = [('auto', 'Automatic (try both)'), ('netcon', 'Network console (-netconport)'),
             ('vconsole', 'VConsole (-vconsole)')]
PROTOCOL_NAMES = {'netcon': 'network console', 'vconsole': 'VConsole'}


class ConnectionPanel(QWidget):

    def __init__(self, game, settings, parent=None):
        QWidget.__init__(self, parent)
        self.game = game
        self.settings = settings
        self.diagnoseResult = _DiagnoseResult(self)
        self.diagnoseResult.ready.connect(self._showDiagnosis)
        layout = QVBoxLayout(self)

        self.dot = QLabel('●')
        self.dot.setAlignment(Qt.AlignTop)
        self.status = label('', wrap=True)
        statusRow = row(self.dot, self.status)
        statusRow.setStretch(1, 1)
        layout.addLayout(statusRow)

        form = QFormLayout()
        self.protocol = QComboBox()
        for name, text in PROTOCOLS:
            self.protocol.addItem(text, name)
        names = [name for name, _ in PROTOCOLS]
        mode = settings.get('connection/protocol')
        self.protocol.setCurrentIndex(names.index(mode) if mode in names else 0)
        self.protocol.currentIndexChanged.connect(self._protocolChanged)
        form.addRow('Connect via', self.protocol)
        self.host = QLineEdit(settings.get('connection/host'))
        self.host.editingFinished.connect(lambda: settings.set('connection/host', self.host.text().strip() or '127.0.0.1'))
        form.addRow('Host', self.host)
        self.port = spin(1, 65535, settings.get('connection/port'), decimals=0)
        self.port.valueChanged.connect(lambda v: self._setting('connection/port', v))
        form.addRow('Console port', self.port)
        self.vport = spin(1, 65535, settings.get('connection/vconsole_port'), decimals=0)
        self.vport.valueChanged.connect(lambda v: self._setting('connection/vconsole_port', v))
        form.addRow('VConsole port', self.vport)
        layout.addLayout(form)

        self.auto = QCheckBox('Connect automatically')
        self.auto.setChecked(settings.get('connection/autoconnect'))
        self.auto.toggled.connect(lambda v: settings.set('connection/autoconnect', v))
        layout.addWidget(self.auto)

        self.connectButton = button('Connect', self.game.connectToGame)
        self.disconnectButton = button('Disconnect', self.game.disconnectFromGame)
        layout.addLayout(row(self.connectButton, self.disconnectButton))

        box = QGroupBox('Deadlock launch options')
        boxLayout = QVBoxLayout(box)
        self.launchOptions = QLineEdit(settings.get('connection/launch_options'))
        self.launchOptions.setToolTip('Used by the buttons below. Try "-console -vconsole" if the network console '
                                      'port never opens. (Avoid -tools: Deadlock does not ship the files it needs.)')
        self.launchOptions.editingFinished.connect(
            lambda: settings.set('connection/launch_options', self.launchOptions.text().strip()))
        boxLayout.addWidget(self.launchOptions)
        boxLayout.addWidget(button('Launch Deadlock with these options', self._launch, accent=True,
                                   tip='Asks Steam to start Deadlock with these options for this launch only.'))
        boxLayout.addWidget(button('Copy launch options', self._copy,
                                   tip='To set them permanently: Steam > Deadlock > Properties > Launch Options'))
        layout.addWidget(box)

        self.diagnoseButton = button('Diagnose connection', self._diagnose,
                                     tip='Checks whether Deadlock is running and what each of its open ports is')
        layout.addWidget(self.diagnoseButton)
        self.options = label('', 'hint', wrap=True)
        layout.addWidget(self.options)
        install = detect.find_install()
        if install:
            layout.addWidget(label('Install: ' + install, 'hint', wrap=True))
        layout.addStretch(1)

        game.statusChanged.connect(self.refresh)
        game.connectionProblem.connect(self.refresh)
        self.refresh()

    def _setting(self, key, value):
        self.settings.set(key, value)
        self.refresh()

    def _protocolChanged(self, index):
        self.settings.set('connection/protocol', self.protocol.itemData(index))
        self.refresh()

    def _launchArgs(self):
        args = self.launchOptions.text().strip()
        self.settings.set('connection/launch_options', args)
        return args

    def _launch(self):
        if not detect.launch_deadlock(self._launchArgs()):
            self.options.setText('Could not open Steam. Add the launch options manually.')

    def _copy(self):
        QGuiApplication.clipboard().setText(self._launchArgs())
        self.options.setText('Copied! Paste into Steam > Deadlock > Properties > Launch Options.')

    def _diagnose(self):
        self.diagnoseButton.setEnabled(False)
        self.diagnoseButton.setText('Diagnosing…')
        host = self.settings.get('connection/host')
        port, vport = self.settings.get('connection/port'), self.settings.get('connection/vconsole_port')
        skip = {self.game.port()} if self.game.isConnected() else set()

        def work():
            try:
                verdict, details, found = detect.diagnose(host, port, vport, skip=skip)
            except Exception as error:
                verdict, details, found = 'unknown', ['Diagnosis failed: {}'.format(error)], None
            self.diagnoseResult.ready.emit(verdict, details, found)

        threading.Thread(target=work, daemon=True).start()

    def _showDiagnosis(self, verdict, details, found):
        self.diagnoseButton.setEnabled(True)
        self.diagnoseButton.setText('Diagnose connection')
        # Point the app at a console the diagnosis discovered elsewhere.
        if verdict == 'other_port':
            self.port.setValue(found)
        elif verdict == 'vconsole':
            self.vport.setValue(found)
        if verdict in ('other_port', 'vconsole') and self.settings.get('connection/protocol') != 'auto':
            self.protocol.setCurrentIndex(0)
        if verdict in ('ok', 'other_port', 'vconsole') and not self.game.isConnected():
            self.game.connectToGame()
        advice = detect.ADVICE.get(verdict, '').format(port=self.settings.get('connection/port'), found=found)
        box = QMessageBox(QMessageBox.Information if verdict in ('ok', 'other_port', 'vconsole') else QMessageBox.Warning,
                          'Connection diagnosis', advice, QMessageBox.Ok, self)
        box.setInformativeText('\n'.join(details))
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.exec()

    def refresh(self, *args):
        status = self.game.status
        mode = self.settings.get('connection/protocol')
        port, vport = self.settings.get('connection/port'), self.settings.get('connection/vconsole_port')
        waitingFor = {'netcon': 'console port {}'.format(port), 'vconsole': 'VConsole port {}'.format(vport)}.get(
            mode, 'console port {} / VConsole port {}'.format(port, vport))
        via = '{} (port {})'.format(PROTOCOL_NAMES.get(self.game.protocol, self.game.protocol), self.game.port())
        if self.game.gameName:
            via += ', game "{}"'.format(self.game.gameName)
        text, color = {
            gamemod.STATUS_CONNECTED: ('Connected to the game console via {}. Open a replay to start directing.'.format(via),
                                       theme.GOOD),
            gamemod.STATUS_WAITING: ('Waiting for Deadlock\'s {}. Stuck here? Click "Diagnose connection".'.format(
                waitingFor), theme.WARN),
            gamemod.STATUS_NOT_RUNNING: ('Deadlock is not running.', theme.TEXT_DIM),
            gamemod.STATUS_DISCONNECTED: ('Disconnected.', theme.TEXT_DIM),
        }.get(status, ('', theme.TEXT_DIM))
        if status != gamemod.STATUS_CONNECTED and self.game.connectionErrors():
            text += '\n\n⚠ ' + ' '.join(self.game.connectionErrors())
        self.status.setText(text)
        self.dot.setStyleSheet('color: {}; font-size: 16px;'.format(color.name()))
        connected = status == gamemod.STATUS_CONNECTED
        self.connectButton.setEnabled(not connected)
        self.disconnectButton.setEnabled(connected)
        self.port.setEnabled(mode != 'vconsole')
        self.vport.setEnabled(mode != 'netcon')


class CameraPanel(QWidget):

    def __init__(self, director, parent=None):
        QWidget.__init__(self, parent)
        self.director = director
        self.game = director.game
        layout = QVBoxLayout(self)

        box = QGroupBox('In-game camera')
        grid = QGridLayout(box)
        self.values = {}
        for i, name in enumerate(('X', 'Y', 'Z', 'Pitch', 'Yaw', 'Roll')):
            value = label('—', 'value')
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.values[name] = value
            grid.addWidget(label(name, 'hint'), i % 3, (i // 3) * 2)
            grid.addWidget(value, i % 3, (i // 3) * 2 + 1)
        layout.addWidget(box)

        self.auto = QCheckBox('Follow in-game camera')
        self.auto.setToolTip('Poll the camera position twice a second while not playing a sequence')
        self.auto.setChecked(True)
        layout.addLayout(row(button('Refresh', lambda: self.game.queryCamera()), self.auto, stretch=True))
        layout.addWidget(button('Add Camera Keyframe  (K)', director.captureKeyframe, accent=True,
                                tip='Reads the replay camera and keys position + rotation at the playhead'))

        box = QGroupBox('Other tracks at playhead')
        form = QFormLayout(box)
        self.fov = spin(10, 170, 90, decimals=1, step=1)
        self.fov.valueChanged.connect(self._previewFov)
        self.fovKey = button('Key', lambda: director.addValueKey('fov', self.fov.value()))
        form.addRow('FOV', row(self.fov, self.fovKey))
        self.speed = spin(0.05, 8, 1.0, decimals=2, step=0.05, suffix='×')
        form.addRow('Replay speed', row(self.speed, button('Key', lambda: director.addValueKey('speed', self.speed.value()))))
        self.fovHint = label('', 'hint', wrap=True)
        form.addRow(self.fovHint)
        layout.addWidget(box)
        layout.addStretch(1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(500)
        self.game.cameraChanged.connect(self.setCamera)
        self.refreshFov()

    def refreshFov(self):
        has = self.game.hasFov()
        self.fovHint.setText('' if has else 'FOV keys are saved but not sent: set the FOV command in Settings once you '
                                            'know the Deadlock console variable (try "find fov" in the console tab).')
        self.fovHint.setVisible(not has)

    def _previewFov(self, value):
        if not self.director.player.isActive():
            self.game.setFov(value)

    def _poll(self):
        if self.auto.isChecked() and self.game.isConnected() and not self.director.player.isActive():
            self.game.queryCamera()

    def setCamera(self, state):
        for name, value in zip(('X', 'Y', 'Z', 'Pitch', 'Yaw', 'Roll'), state.position + state.rotation):
            self.values[name].setText('{:.2f}'.format(value))

    def syncFromSequence(self, values):
        for name, widget in (('fov', self.fov), ('speed', self.speed)):
            if name in values and not widget.hasFocus():
                widget.blockSignals(True)
                widget.setValue(values[name])
                widget.blockSignals(False)


class ReplayPanel(QWidget):

    def __init__(self, game, parent=None):
        QWidget.__init__(self, parent)
        self.game = game
        layout = QVBoxLayout(self)
        layout.addLayout(row(button('Pause', game.pause), button('Resume', game.resume)))

        form = QFormLayout()
        self.timescale = spin(0.05, 8, 1.0, decimals=2, step=0.05, suffix='×')
        form.addRow('Speed', row(self.timescale, button('Apply', lambda: game.setTimescale(self.timescale.value()))))
        self.tick = spin(0, 10_000_000, 0, decimals=0, step=64)
        form.addRow('Tick', row(self.tick, button('Seek', lambda: game.seek(self.tick.value()))))
        self.tickLabel = label('—', 'value')
        form.addRow('Current', row(self.tickLabel, button('Read', lambda: game.queryTick()), stretch=True))
        self.freecam = spin(50, 5000, 600, decimals=0, step=50)
        form.addRow('Free-cam speed', row(self.freecam, button('Apply', lambda: game.setFreecamSpeed(self.freecam.value()))))
        layout.addLayout(form)

        self.hud = QCheckBox('Hide HUD + replay controls (clean feed)')
        self.hud.toggled.connect(game.setHudHidden)
        layout.addWidget(self.hud)
        layout.addWidget(label(
            'Tip: bind a key in Deadlock\'s console, e.g.  bind KP_ENTER spec_pos  — every press drops a camera '
            'keyframe at the playhead while you fly the free-cam.', 'hint', wrap=True))
        layout.addStretch(1)
        game.tickReceived.connect(self._tick)

    def _tick(self, tick):
        self.tickLabel.setText(str(tick))
        self.tick.setValue(tick)


class SequencePanel(QWidget):

    def __init__(self, director, parent=None):
        QWidget.__init__(self, parent)
        self.director = director
        self.document = director.document
        self.settings = director.settings
        self.updating = False
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._nameChanged)
        form.addRow('Name', self.name)
        layout.addLayout(form)

        box = QGroupBox('Replay sync')
        boxLayout = QFormLayout(box)
        self.sync = QCheckBox('Start the replay at a fixed tick')
        self.sync.setToolTip('When set, playing the sequence seeks the replay to this tick first so every take is identical.')
        self.sync.toggled.connect(self._changed)
        boxLayout.addRow(self.sync)
        self.startTick = spin(0, 10_000_000, 0, decimals=0, step=64)
        self.startTick.valueChanged.connect(self._changed)
        boxLayout.addRow('Start tick', row(self.startTick, button('Use current', self._useCurrentTick)))
        self.tickrate = spin(1, 512, 64, decimals=1, step=1)
        self.tickrate.setToolTip('Replay ticks per second. Check it against the replay if seeks land in the wrong spot.')
        self.tickrate.valueChanged.connect(self._changed)
        boxLayout.addRow('Tick rate', self.tickrate)
        self.preroll = spin(0, 10, self.settings.get('playback/preroll'), decimals=1, step=0.5, suffix=' s')
        self.preroll.valueChanged.connect(lambda v: self.settings.set('playback/preroll', v))
        boxLayout.addRow('Pre-roll', self.preroll)
        layout.addWidget(box)

        box = QGroupBox('Playback')
        boxLayout = QVBoxLayout(box)
        for key, text, tip in (
                ('playback/live_preview', 'Live preview while scrubbing', 'Move the in-game camera as you scrub the timeline'),
                ('playback/sync_replay', 'Seek + resume replay on play', 'Uses the start tick above'),
                ('playback/pause_at_end', 'Pause replay when sequence ends', None),
                ('playback/capture_from_game', 'Keyframe on in-game spec_pos bind', 'Unrequested camera readouts become keyframes')):
            check = QCheckBox(text)
            check.setChecked(self.settings.get(key))
            check.toggled.connect(lambda v, k=key: self.settings.set(k, v))
            if tip:
                check.setToolTip(tip)
            boxLayout.addWidget(check)
        layout.addWidget(box)

        self.info = label('', 'hint', wrap=True)
        layout.addWidget(self.info)
        layout.addStretch(1)
        self.document.changed.connect(self.refresh)
        self.director.game.tickReceived.connect(self._tickReceived)
        self.wantTick = False
        self.refresh()

    def refresh(self):
        self.updating = True
        seq = self.document.sequence
        if not self.name.hasFocus():
            self.name.setText(seq.name)
        self.sync.setChecked(seq.start_tick is not None)
        self.startTick.setEnabled(seq.start_tick is not None)
        if seq.start_tick is not None:
            self.startTick.setValue(seq.start_tick)
        self.tickrate.setValue(seq.tickrate)
        count = sum(1 for _ in seq.keyframes())
        self.info.setText('{} keyframes · length {}'.format(count, format_time(seq.duration)))
        self.updating = False

    def _nameChanged(self):
        if self.name.text() != self.document.sequence.name:
            self.document.sequence.name = self.name.text()
            self.document.touchSettings()

    def _changed(self, *args):
        if self.updating:
            return
        seq = self.document.sequence
        seq.start_tick = self.startTick.value() if self.sync.isChecked() else None
        seq.tickrate = self.tickrate.value()
        self.startTick.setEnabled(self.sync.isChecked())
        self.document.touchSettings()

    def _useCurrentTick(self):
        self.wantTick = True
        self.director.game.queryTick(lambda tick: tick is None and self.director.message(
            'Could not read the replay tick. Check the tick query command in Settings.'))

    def _tickReceived(self, tick):
        if self.wantTick:
            self.wantTick = False
            self.sync.setChecked(True)
            self.startTick.setValue(tick)


class KeyframeInspector(QWidget):

    def __init__(self, director, parent=None):
        QWidget.__init__(self, parent)
        self.director = director
        self.document = director.document
        self.updating = False
        layout = QVBoxLayout(self)
        self.title = label('No keyframe selected', 'heading', wrap=True)
        layout.addWidget(self.title)

        self.form = QWidget()
        form = QFormLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        self.time = spin(0, 100000, 0, decimals=3, step=0.1, suffix=' s')
        self.time.valueChanged.connect(self._edit)
        form.addRow('Time', self.time)
        self.components = []
        self.componentLabels = []
        for i in range(3):
            widget = spin(-1e6, 1e6, 0, decimals=2, step=1)
            widget.valueChanged.connect(self._edit)
            text = QLabel('')
            form.addRow(text, widget)
            self.components.append(widget)
            self.componentLabels.append(text)
        self.blend = QComboBox()
        for name, text in interpolation.BLEND_MODES:
            self.blend.addItem(text, name)
        self.blend.currentIndexChanged.connect(self._blend)
        form.addRow('Blend to next', self.blend)
        layout.addWidget(self.form)

        self.setFromGame = button('Set from in-game camera', self._setFromGame)
        layout.addWidget(self.setFromGame)
        layout.addLayout(row(button('Jump to', self._jump), button('Delete', self.document.deleteSelected)))
        layout.addStretch(1)
        self.document.selectionChanged.connect(self.refresh)
        self.document.changed.connect(self.refresh)
        self.refresh()

    def _single(self):
        return self.document.selection[0] if len(self.document.selection) == 1 else None

    def refresh(self):
        self.updating = True
        selection = self.document.selection
        single = self._single()
        self.form.setVisible(bool(selection))
        self.setFromGame.setVisible(single is not None and single[0] in ('position', 'rotation'))
        if not selection:
            self.title.setText('No keyframe selected.\nClick a diamond on the timeline, or double-click a track to add one.')
        elif single is None:
            self.title.setText('{} keyframes selected'.format(len(selection)))
            self.time.setEnabled(False)
            for widget, text in zip(self.components, self.componentLabels):
                widget.setVisible(False)
                text.setVisible(False)
        else:
            track, key = single
            info = self.document.sequence.track(track)
            self.title.setText(info.label)
            self.time.setEnabled(True)
            self.time.setValue(key.time)
            values = key.value if isinstance(key.value, list) else [key.value]
            for i, (widget, text) in enumerate(zip(self.components, self.componentLabels)):
                visible = i < len(values)
                widget.setVisible(visible)
                text.setVisible(visible)
                if visible:
                    text.setText(info.components[i])
                    widget.setDecimals(3 if track in ('speed',) else 2)
                    widget.setValue(values[i])
        blends = {k.blend for _, k in selection}
        if len(blends) == 1:
            self.blend.setCurrentIndex(interpolation.BLEND_NAMES.index(blends.pop()))
        self.updating = False

    def _edit(self, *args):
        single = self._single()
        if self.updating or single is None:
            return
        track, key = single
        self.document.begin()
        key.time = round(self.time.value(), 4)
        if isinstance(key.value, list):
            key.value = [w.value() for w in self.components[:len(key.value)]]
        else:
            key.value = self.components[0].value()
        self.document.sequence.track(track).sort()
        self.document.commit()
        self.director.player.setTime(self.director.player.time)

    def _blend(self, index):
        if not self.updating:
            self.document.setBlend(self.blend.itemData(index))

    def _jump(self):
        if self.document.selection:
            self.director.player.setTime(self.document.selection[0][1].time)

    def _setFromGame(self):
        single = self._single()
        if single is None:
            return
        track, key = single

        def done(state):
            if state is None:
                self.director.message('Could not read the in-game camera.')
                return
            self.document.begin()
            key.value = state.position if track == 'position' else state.rotation
            self.document.commit()

        self.director.game.queryCamera(done)


class ConsolePanel(QWidget):

    def __init__(self, director, parent=None):
        QWidget.__init__(self, parent)
        self.director = director
        self.game = director.game
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(3000)
        self.output.setStyleSheet('font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 11px;')
        layout.addWidget(self.output)
        self.input = QLineEdit()
        self.input.setPlaceholderText('Type a Deadlock console command, e.g. "find spec_" or "find fov", and press Enter')
        self.input.returnPressed.connect(self._submit)
        self.input.installEventFilter(self)
        self.traffic = QCheckBox('Show Director traffic')
        layout.addLayout(row(self.input, self.traffic))
        self.history = []
        self.historyIndex = 0
        self.typed = []
        self.game.consoleLine.connect(self._line)
        self.game.commandSent.connect(self._sent)

    def _append(self, text, color):
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if not self.output.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(text, fmt)
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def _line(self, line, solicited):
        if solicited and not self.traffic.isChecked():
            return
        self._append(line, theme.TEXT_DIM if solicited else theme.TEXT)

    def _sent(self, command):
        if command in self.typed:
            self.typed.remove(command)
            self._append('] ' + command, theme.ACCENT)
        elif self.traffic.isChecked() and not self.director.player.isActive():
            self._append('] ' + command, QColor('#6b6f76'))

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.history.append(text)
        self.historyIndex = len(self.history)
        self.input.clear()
        if not self.game.isConnected():
            self._append('Not connected to Deadlock.', theme.BAD)
            return
        self.typed = split_commands(text)
        self.game.run(text)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress and self.history:
            if event.key() == Qt.Key_Up:
                self.historyIndex = max(0, self.historyIndex - 1)
                self.input.setText(self.history[self.historyIndex])
                return True
            if event.key() == Qt.Key_Down:
                self.historyIndex = min(len(self.history), self.historyIndex + 1)
                self.input.setText(self.history[self.historyIndex] if self.historyIndex < len(self.history) else '')
                return True
        return QWidget.eventFilter(self, obj, event)
