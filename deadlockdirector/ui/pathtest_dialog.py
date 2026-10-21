"""Tools > Smooth path test: can exec-driven frames move the camera smoothly?"""
import os
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
                               QPushButton, QVBoxLayout)

from deadlockdirector import detect, keysender, pathtest
from deadlockdirector.ui.panels import button, label, spin

INTRO = ('This checks whether Deadlock can follow a smooth camera path. Each frame, the app writes the next camera '
         'position to <code>cfg/{cfg}.cfg</code> and taps a key you bind to <code>exec {cfg}</code>, so the game '
         'loads the frame itself. Keys are only sent while Deadlock is the active window.').format(cfg=pathtest.FRAME_CFG)

STEPS = ('<ol>'
         '<li>Launch Deadlock with <code>-condebug</code> and open a replay (pausing it makes the test easiest to judge).</li>'
         '<li>Press F7 and run the bind command below once.</li>'
         '<li>Release the camera into free-cam, aim at something, and run <code>spec_pos</code>. Close the console.</li>'
         '<li>Click <b>Read start position</b>, then <b>Start</b>, and click back into Deadlock within 3 seconds. '
         "Don't touch the mouse while it runs.</li>"
         '</ol>')


class _Signals(QObject):
    status = Signal(str)
    finished = Signal(str)


class PathTestDialog(QDialog):

    def __init__(self, settings, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle('Smooth path test')
        self.resize(620, 640)
        self.settings = settings
        self.start = None
        self.stopFlag = threading.Event()
        self.worker = None
        self.signals = _Signals(self)
        self.signals.status.connect(self._status)
        self.signals.finished.connect(self._finished)
        install = detect.find_install()
        layout = QVBoxLayout(self)
        layout.addWidget(label(INTRO, wrap=True))
        layout.addWidget(label(STEPS, wrap=True))

        box = QGroupBox('Setup')
        form = QFormLayout(box)
        self.cfgDir = QLineEdit(settings.value('pathtest/cfgdir') or pathtest.cfg_dir(install) or '')
        form.addRow('Deadlock cfg folder', self._browseRow(self.cfgDir, folder=True))
        self.logPath = QLineEdit(settings.value('pathtest/log') or pathtest.find_console_log(install) or '')
        form.addRow('console.log', self._browseRow(self.logPath, folder=False))
        self.key = QComboBox()
        for name, _, _ in pathtest.BIND_KEYS:
            self.key.addItem(name)
        self.key.currentIndexChanged.connect(self._refreshBind)
        self.bind = QLineEdit()
        self.bind.setReadOnly(True)
        copy = QPushButton('Copy')
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.bind.text()))
        row = QHBoxLayout()
        row.addWidget(self.key)
        row.addWidget(self.bind, 1)
        row.addWidget(copy)
        form.addRow('Key + bind command', row)
        layout.addWidget(box)

        box = QGroupBox('Test path: orbit around the point you are looking at')
        form = QFormLayout(box)
        self.startLabel = label('Not read yet', 'value')
        form.addRow(button('Read start position', self._readStart), self.startLabel)
        self.distance = spin(100, 5000, 600, decimals=0, step=50)
        form.addRow('Orbit radius (units)', self.distance)
        self.duration = spin(2, 60, 8, decimals=1, step=1, suffix=' s')
        form.addRow('Duration', self.duration)
        self.rate = QComboBox()
        for rate in (20, 30, 45, 60):
            self.rate.addItem('{} frames/s'.format(rate), rate)
        self.rate.setCurrentIndex(1)
        form.addRow('Update rate', self.rate)
        layout.addWidget(box)

        self.statusLabel = label('', 'heading', wrap=True)
        layout.addWidget(self.statusLabel)
        self.startButton = button('Start (3 s countdown)', self._toggle, accent=True)
        layout.addWidget(self.startButton)
        layout.addStretch(1)
        if not keysender.AVAILABLE:
            self.startButton.setEnabled(False)
            self.statusLabel.setText('This test only runs on Windows.')
        self._refreshBind()

    def _browseRow(self, edit, folder):
        browse = QPushButton('Browse…')

        def pick():
            if folder:
                path = QFileDialog.getExistingDirectory(self, 'Deadlock cfg folder', edit.text())
            else:
                path, _ = QFileDialog.getOpenFileName(self, 'console.log', edit.text(), 'Log (*.log);;All files (*)')
            if path:
                edit.setText(path)

        browse.clicked.connect(pick)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return row

    def _refreshBind(self, *args):
        self.bind.setText(pathtest.bind_command(self.key.currentText()))

    def _readStart(self):
        path = self.logPath.text().strip()
        if not os.path.isfile(path):
            self.startLabel.setText('console.log not found. Is Deadlock running with -condebug?')
            return
        self.settings.set_value('pathtest/log', path)
        state = pathtest.last_camera_in_log(path)
        if state is None:
            self.startLabel.setText('No spec_pos output in the log yet. Run spec_pos in the console.')
            return
        self.start = state
        self.startLabel.setText('{:.0f}, {:.0f}, {:.0f}  pitch {:.1f}  yaw {:.1f}'.format(
            state.x, state.y, state.z, state.pitch, state.yaw))

    def _status(self, text):
        self.statusLabel.setText(text)

    def _toggle(self):
        if self.worker and self.worker.is_alive():
            self.stopFlag.set()
            return
        folder = self.cfgDir.text().strip()
        if not os.path.isdir(folder):
            self.statusLabel.setText('Set the Deadlock cfg folder first (…/Deadlock/game/citadel/cfg).')
            return
        if self.start is None:
            self.statusLabel.setText('Read the start position first.')
            return
        self.settings.set_value('pathtest/cfgdir', folder)
        target = os.path.join(folder, pathtest.FRAME_CFG + '.cfg')
        path = pathtest.orbit_path(self.start, self.distance.value(), self.duration.value())
        template = self.settings.get('commands/camera')
        _, scancode, extended = pathtest.BIND_KEYS[self.key.currentIndex()]
        # Write the first frame now so the bind works even before the test runs.
        pathtest.write_frame(target, pathtest.frame_commands(template, *path(0.0)))
        self.stopFlag.clear()
        self.startButton.setText('Stop')
        args = (target, path, template, scancode, extended, self.duration.value(), self.rate.currentData())
        self.worker = threading.Thread(target=self._run, args=args, daemon=True)
        self.worker.start()

    def _run(self, target, path, template, scancode, extended, duration, rate):
        for remaining in (3, 2, 1):
            if self.stopFlag.is_set():
                self.signals.finished.emit('Stopped.')
                return
            self.signals.status.emit('Click into Deadlock… starting in {}'.format(remaining))
            time.sleep(1.0)
        frames = taps = skipped = unfocused = 0
        with keysender.precise_timer():
            pacer = pathtest.Pacer(rate)
            while not self.stopFlag.is_set():
                t = pacer.elapsed()
                if t > duration:
                    break
                frames += 1
                if not keysender.foreground_is_deadlock():
                    unfocused += 1
                    self.signals.status.emit('Paused: Deadlock is not the active window.')
                    pacer.wait()
                    continue
                if not pathtest.write_frame(target, pathtest.frame_commands(template, *path(t))):
                    skipped += 1
                elif keysender.tap(scancode, extended):
                    taps += 1
                if frames % rate == 0:
                    self.signals.status.emit('Running… {:.0f} / {:.0f} s'.format(t, duration))
                pacer.wait()
        elapsed = max(0.001, pacer.elapsed())
        report = ('Done. {} frames in {:.1f} s ({:.0f}/s): {} key taps sent, {} skipped because the game had the '
                  'file open, {} while Deadlock was not focused.\n\nDid the camera glide smoothly around the point, '
                  'jump between positions, or not move at all?').format(
            frames, elapsed, frames / elapsed, taps, skipped, unfocused)
        self.signals.finished.emit('Stopped early. ' + report if self.stopFlag.is_set() else report)

    def _finished(self, text):
        self.statusLabel.setText(text)
        self.startButton.setText('Start (3 s countdown)')

    def closeEvent(self, event):
        self.stopFlag.set()
        QDialog.closeEvent(self, event)
