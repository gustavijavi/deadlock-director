import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox, QSplitter, QWidget,
                               QSizePolicy)

from deadlockdirector import __version__
from deadlockdirector.game import STATUS_CONNECTED, DeadlockGame
from deadlockdirector.obs import ObsRecorder
from deadlockdirector.playback import PLAYING, PREROLL, SequencePlayer
from deadlockdirector.settings import Settings, sequences_dir
from deadlockdirector.ui import theme
from deadlockdirector.ui.document import Document
from deadlockdirector.ui.panels import (CameraPanel, ConnectionPanel, ConsolePanel, KeyframeInspector, ReplayPanel,
                                        SequencePanel, scrolling)
from deadlockdirector.ui.pathtest_dialog import PathTestDialog
from deadlockdirector.ui.pathview import PathView
from deadlockdirector.ui.settings_dialog import SettingsDialog
from deadlockdirector.ui.timeline import TimelineWidget, format_time

FILE_FILTER = 'Deadlock Director sequence (*.ddseq *.json)'

HELP = """<h3>Getting started</h3>
<ol>
<li>Click <b>Launch Deadlock with console port</b> (or add <code>-console -netconport 2121</code> to
Deadlock's Steam launch options). This opens Deadlock's own developer console on a local port.</li>
<li>Open a replay in Deadlock (Match history → Watch replay). Deadlock Director connects automatically.</li>
<li>Release the replay camera into free-cam (WASD), fly to a spot and press <b>K</b> / <b>Add Camera Keyframe</b>.
Move the playhead, fly somewhere else, add another keyframe.</li>
<li>Press <b>Space</b> to play the shot. Turn on <b>Start the replay at a fixed tick</b> in the Sequence panel
so every take starts at the same moment, and use <b>Record</b> with OBS to capture it.</li>
</ol>
<h3>Timeline</h3>
<p>Click to select, Shift/Ctrl-click to add to the selection, drag to move (Alt disables snapping), drag on empty space
to box-select, double-click a track to add a keyframe, right-click for blend modes. Ctrl+wheel zooms, wheel or
middle-drag pans.</p>
<h3>Fair play</h3>
<p>Deadlock Director never reads or writes game memory, injects code or simulates input. It only types the same console
commands you could type yourself into Deadlock's console, through a port the game opens when you ask it to.
Camera commands only have an effect when you are spectating or watching a replay.</p>
"""


class MainWindow(QMainWindow):

    def __init__(self):
        QMainWindow.__init__(self)
        self.settings = Settings()
        self.game = DeadlockGame(self.settings, self)
        self.document = Document(self)
        self.recorder = ObsRecorder(self.settings, self)
        self.player = SequencePlayer(self.game, self.settings, self.document.sequence, self.recorder, self)
        self.setDockNestingEnabled(True)
        self.resize(1400, 860)

        self.pathView = PathView(self.document)
        self.timeline = TimelineWidget(self.document)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.pathView)
        splitter.addWidget(self.timeline)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 190])
        self.setCentralWidget(splitter)

        self.cameraPanel = CameraPanel(self)
        self.inspector = KeyframeInspector(self)
        self.sequencePanel = SequencePanel(self)
        self.docks = {}
        self.addPanel('connection', 'Connection', ConnectionPanel(self.game, self.settings), Qt.LeftDockWidgetArea)
        self.addPanel('camera', 'Camera', self.cameraPanel, Qt.LeftDockWidgetArea)
        self.addPanel('replay', 'Replay', ReplayPanel(self.game), Qt.LeftDockWidgetArea)
        self.addPanel('keyframe', 'Keyframe', self.inspector, Qt.RightDockWidgetArea)
        self.addPanel('sequence', 'Sequence', self.sequencePanel, Qt.RightDockWidgetArea)
        self.addPanel('console', 'Console', ConsolePanel(self), Qt.RightDockWidgetArea)
        self.tabifyDockWidget(self.docks['camera'], self.docks['replay'])
        self.docks['camera'].raise_()
        self.tabifyDockWidget(self.docks['sequence'], self.docks['console'])
        self.docks['sequence'].raise_()

        self.createActions()
        self.statusLabel = QLabel()
        self.statusBar().addPermanentWidget(self.statusLabel)

        self.player.timeChanged.connect(self.onTime)
        self.player.stateChanged.connect(self.onPlayerState)
        self.player.message.connect(self.message)
        self.recorder.message.connect(self.message)
        self.timeline.timeScrubbed.connect(self.scrub)
        self.timeline.addKeyframeRequested.connect(self.addKeyframeAt)
        self.pathView.keyClicked.connect(lambda key: (self.document.select([('position', key)]), self.player.setTime(key.time)))
        self.game.cameraChanged.connect(self.pathView.setLiveCamera)
        self.game.captureFromGame.connect(self.onCaptureFromGame)
        self.game.statusChanged.connect(self.onStatus)
        self.document.fileChanged.connect(self.updateTitle)
        self.document.changed.connect(self.onDocumentChanged)

        self.restoreLayout()
        self.updateTitle()
        self.onStatus(self.game.status)
        self.onTime(0.0)
        self.game.poll()

    # -- construction ----------------------------------------------------
    def addPanel(self, name, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(scrolling(widget))
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, dock)
        self.docks[name] = dock
        return dock

    def action(self, text, slot, shortcut=None, tip=None, checkable=False):
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
        if tip:
            action.setToolTip('{} ({})'.format(tip, shortcut) if shortcut else tip)
        action.setCheckable(checkable)
        self.addAction(action)
        return action

    def createActions(self):
        self.actNew = self.action('New', self.newSequence, 'Ctrl+N')
        self.actOpen = self.action('Open…', self.openSequence, 'Ctrl+O')
        self.actSave = self.action('Save', self.saveSequence, 'Ctrl+S')
        self.actSaveAs = self.action('Save As…', lambda: self.saveSequence(True), 'Ctrl+Shift+S')
        self.actPlay = self.action('▶  Play', lambda: self.player.toggle(), 'Space', 'Play / stop the sequence')
        self.actFromStart = self.action('⏮  From start', self.playFromStart, 'Home', 'Play from the beginning')
        self.actRecord = self.action('●  Record', self.record, 'Ctrl+R', 'Play the sequence and record it with OBS')
        self.actKey = self.action('◆  Add Keyframe', self.captureKeyframe, 'K', 'Key the in-game camera at the playhead')
        self.actUndo = self.action('Undo', self.document.undo, 'Ctrl+Z')
        self.actRedo = self.action('Redo', self.document.redo, 'Ctrl+Shift+Z')
        self.action('Redo', self.document.redo, 'Ctrl+Y')
        self.actDelete = self.action('Delete keyframes', self.document.deleteSelected, 'Delete')
        self.actSelectAll = self.action('Select all keyframes', self.document.selectAll, 'Ctrl+A')
        self.actFit = self.action('Zoom timeline to fit', self.timeline.zoomToFit, 'F')
        self.actPrev = self.action('Step back', lambda: self.step(-1), 'Left')
        self.actNext = self.action('Step forward', lambda: self.step(1), 'Right')
        self.actHud = self.action('Hide in-game HUD', lambda v: self.game.setHudHidden(v), 'H', checkable=True)
        self.actSettings = self.action('Settings…', self.showSettings, 'Ctrl+,')

        menu = self.menuBar().addMenu('&File')
        for a in (self.actNew, self.actOpen, self.actSave, self.actSaveAs):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.action('Quit', self.close, 'Ctrl+Q'))
        menu = self.menuBar().addMenu('&Edit')
        for a in (self.actUndo, self.actRedo, None, self.actKey, self.actDelete, self.actSelectAll, None, self.actSettings):
            menu.addSeparator() if a is None else menu.addAction(a)
        menu = self.menuBar().addMenu('&Playback')
        for a in (self.actPlay, self.actFromStart, self.actRecord, None, self.actPrev, self.actNext, self.actFit, None, self.actHud):
            menu.addSeparator() if a is None else menu.addAction(a)
        menu = self.menuBar().addMenu('&View')
        for dock in self.docks.values():
            menu.addAction(dock.toggleViewAction())
        menu = self.menuBar().addMenu('&Tools')
        menu.addAction(self.action('Smooth path test…', self.showPathTest))
        menu = self.menuBar().addMenu('&Help')
        menu.addAction(self.action('How to use', self.showHelp, 'F1'))
        menu.addAction(self.action('About', self.showAbout))

        toolbar = self.addToolBar('Main')
        toolbar.setObjectName('toolbar')
        toolbar.setMovable(False)
        for a in (self.actFromStart, self.actPlay, self.actRecord, None, self.actKey, None, self.actUndo, self.actRedo):
            toolbar.addSeparator() if a is None else toolbar.addAction(a)
        toolbar.addSeparator()
        self.timeLabel = QLabel()
        self.timeLabel.setProperty('role', 'value')
        self.timeLabel.setStyleSheet('font-size: 15px; padding: 0 10px;')
        toolbar.addWidget(self.timeLabel)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        self.connectionLabel = QLabel()
        self.connectionLabel.setStyleSheet('padding: 0 10px;')
        toolbar.addWidget(self.connectionLabel)
        toolbar.addAction(self.actSettings)

    # -- state updates ---------------------------------------------------
    def message(self, text, timeout=6000):
        self.statusBar().showMessage(text, timeout)

    def updateTitle(self):
        self.setWindowTitle('{} — Deadlock Director'.format(self.document.title))

    def onTime(self, t):
        self.timeline.setTime(t)
        self.pathView.setTime(t)
        self.timeLabel.setText('{}  /  {}'.format(format_time(t), format_time(self.document.sequence.duration)))
        values = self.document.sequence.evaluate(t)
        self.cameraPanel.syncFromSequence(values)
        tick = self.document.sequence.tick_at(t)
        self.statusLabel.setText('replay tick {}'.format(tick) if tick is not None else '')

    def onDocumentChanged(self):
        self.onTime(self.player.time)

    def onPlayerState(self, state):
        playing = state in (PLAYING, PREROLL)
        self.actPlay.setText('■  Stop' if playing else '▶  Play')
        self.actRecord.setEnabled(not playing)
        if state == PREROLL:
            self.message('Seeking replay…' if self.player.synced else 'Starting…', 2000)

    def onStatus(self, status):
        connected = status == STATUS_CONNECTED
        color = theme.GOOD if connected else (theme.WARN if status == 'waiting' else theme.TEXT_DIM)
        text = {'connected': 'Connected', 'waiting': 'Waiting for console port', 'not_running': 'Deadlock not running'}.get(status, 'Disconnected')
        self.connectionLabel.setText('<span style="color:{}">●</span> {}'.format(color.name(), text))
        if connected:
            self.message('Connected to Deadlock')

    # -- editing ---------------------------------------------------------
    def scrub(self, t):
        if self.player.isActive():
            self.player.stop()
        self.player.setTime(t)

    def step(self, direction):
        if not self.player.isActive():
            self.player.setTime(max(0.0, self.player.time + direction / 30.0))

    def keyCamera(self, state, t=None):
        t = self.player.time if t is None else t
        self.document.begin()
        position = self.document.sequence.track('position').add(t, state.position)
        rotation = self.document.sequence.track('rotation').add(t, state.rotation)
        self.document.commit()
        self.document.select([('position', position), ('rotation', rotation)])
        self.message('Camera keyframe added at {}'.format(format_time(t)))

    def captureKeyframe(self):
        if self.player.isActive():
            return
        if not self.game.isConnected():
            self.message('Not connected to Deadlock — double-click a track to add a keyframe manually.')
            return
        t = self.player.time

        def done(state):
            if state is None:
                self.message('Could not read the camera. Is a replay open? Check the "Read camera" command in Settings.')
            else:
                self.keyCamera(state, t)

        self.game.queryCamera(done)

    def onCaptureFromGame(self, state):
        self.keyCamera(state)

    def addValueKey(self, track, value):
        self.document.addKeyframe(track, self.player.time, value)
        self.message('{} keyframe added at {}'.format(self.document.sequence.track(track).label, format_time(self.player.time)))

    def addKeyframeAt(self, track, t):
        sequence = self.document.sequence
        value = sequence.track(track).evaluate(t)
        if value is None:
            if track == 'position':
                value = self.game.camera.position if self.game.camera else [0.0, 0.0, 0.0]
            elif track == 'rotation':
                value = self.game.camera.rotation if self.game.camera else [0.0, 0.0, 0.0]
            elif track == 'fov':
                value = self.cameraPanel.fov.value()
            else:
                value = 1.0
        self.document.addKeyframe(track, t, value)
        self.player.setTime(t, apply=False)

    # -- playback --------------------------------------------------------
    def playFromStart(self):
        self.player.stop()
        self.player.setTime(0.0, apply=False)
        self.player.play(fromStart=True)

    def record(self):
        if not self.settings.get('obs/enabled'):
            QMessageBox.information(self, 'Recording', 'Recording uses OBS Studio. Enable it under Settings → OBS recording, '
                                                       'then add a Game Capture source for Deadlock in OBS.')
            return
        if self.document.sequence.is_empty():
            self.message('Add some keyframes first.')
            return
        self.player.stop()
        self.player.play(record=True, fromStart=True)

    # -- files -----------------------------------------------------------
    def confirmDiscard(self):
        if not self.document.dirty or self.document.sequence.is_empty():
            return True
        answer = QMessageBox.question(self, 'Unsaved changes', 'Save changes to {}?'.format(self.document.title.rstrip(' *')),
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.saveSequence()
        return answer == QMessageBox.Discard

    def newSequence(self):
        if self.confirmDiscard():
            self.player.stop()
            self.document.new()
            self.player.setTime(0.0, apply=False)

    def openSequence(self, path=None):
        if not self.confirmDiscard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Open sequence', self.lastDir(), FILE_FILTER)
        if path:
            try:
                self.player.stop()
                self.document.load(path)
                self.player.setTime(0.0, apply=False)
                self.timeline.zoomToFit()
                self.settings.set_value('ui/lastdir', os.path.dirname(path))
            except (OSError, ValueError, KeyError) as error:
                QMessageBox.warning(self, 'Open sequence', 'Could not open {}:\n{}'.format(path, error))

    def saveSequence(self, saveAs=False):
        path = self.document.path
        if saveAs or not path:
            suggested = os.path.join(self.lastDir(), (self.document.sequence.name or 'sequence') + '.ddseq')
            path, _ = QFileDialog.getSaveFileName(self, 'Save sequence', suggested, FILE_FILTER)
            if not path:
                return False
        try:
            self.document.save(path)
            self.settings.set_value('ui/lastdir', os.path.dirname(path))
            self.message('Saved ' + path)
            return True
        except OSError as error:
            QMessageBox.warning(self, 'Save sequence', 'Could not save:\n{}'.format(error))
            return False

    def lastDir(self):
        path = self.settings.value('ui/lastdir')
        return path if path and os.path.isdir(path) else sequences_dir()

    # -- dialogs ---------------------------------------------------------
    def showSettings(self):
        dialog = SettingsDialog(self.settings, self.recorder, self)
        if dialog.exec():
            self.game.lastSent.clear()
            self.cameraPanel.refreshFov()

    def showPathTest(self):
        PathTestDialog(self.settings, self).exec()

    def showHelp(self):
        QMessageBox.information(self, 'How to use Deadlock Director', HELP)

    def showAbout(self):
        QMessageBox.about(self, 'About Deadlock Director',
                          '<b>Deadlock Director {}</b><br>A cinematic camera sequencer for Deadlock replays, '
                          'inspired by Riot Games\' League Director.<br><br>Not affiliated with or endorsed by Valve.'.format(__version__))

    # -- window state ----------------------------------------------------
    def restoreLayout(self):
        geometry = self.settings.value('ui/geometry')
        state = self.settings.value('ui/state')
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def closeEvent(self, event):
        if not self.confirmDiscard():
            event.ignore()
            return
        self.player.stop()
        self.settings.set_value('ui/geometry', self.saveGeometry())
        self.settings.set_value('ui/state', self.saveState())
        self.game.disconnectFromGame()
        event.accept()
