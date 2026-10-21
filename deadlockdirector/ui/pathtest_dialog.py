"""Tools > Smooth path test: can exec-driven frames move the camera smoothly?"""
import os
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
                               QPushButton, QVBoxLayout)

from deadlockdirector import capture, detect, keysender, pathtest, render
from deadlockdirector.ui.panels import button, label, spin

INTRO = ('This checks whether Deadlock can follow a smooth camera path. Each frame, the app writes the next camera '
         'position to <code>cfg/{cfg}.cfg</code> and taps a key you bind to <code>exec {cfg}</code>, so the game '
         'loads the frame itself. Keys are only sent while Deadlock is the active window.').format(cfg=pathtest.FRAME_CFG)

STEPS = ('<ol>'
         '<li>Launch Deadlock with <code>-condebug</code> in <b>borderless or windowed</b> mode and open a replay.</li>'
         '<li>Press F7 and run the bind command below once.</li>'
         '<li>Release the camera into free-cam, aim at something, and run <code>spec_pos</code>. Close the console.</li>'
         '<li>Click <b>Read start position</b>, then <b>Render to video</b> (or the live test), and click back into '
         "Deadlock within 3 seconds. Don't touch the mouse or keyboard while it runs.</li>"
         '</ol>')


class _Signals(QObject):
    status = Signal(str)
    finished = Signal(str)


class PathTestDialog(QDialog):

    def __init__(self, settings, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle('Smooth path test')
        self.resize(660, 900)
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
        for rate in (30, 60, 90, 120, 144):
            self.rate.addItem('{} frames/s'.format(rate), rate)
        self.rate.setCurrentIndex(1)
        self.rate.setToolTip('Matching your monitor / fps_max reduces stutter, but live playback cannot sync to '
                             'the game\'s frames exactly.')
        form.addRow('Update rate', self.rate)
        self.command = QComboBox()
        self.command.addItem('spec_goto + spec_setang', None)
        self.command.addItem('spec_setpos + spec_setang', 'spec_setpos {x:.2f} {y:.2f} {z:.2f}; spec_setang {pitch:.2f} {yaw:.2f}')
        form.addRow('Camera command', self.command)
        layout.addWidget(box)

        self.startButton = button('Live test (3 s countdown)', self._toggle)
        layout.addWidget(self.startButton)

        box = QGroupBox('Render to video (frame by frame, smooth)')
        form = QFormLayout(box)
        form.addRow(label('The replay stays paused. For each frame the app moves the camera, steps the replay one '
                          'tick, waits for Deadlock to draw it and captures the window. Run Deadlock in '
                          '<b>borderless or windowed</b> mode, keep it in front, and leave the mouse alone.',
                          'hint', wrap=True))
        videos = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation) or os.path.expanduser('~')
        self.output = QLineEdit(self.settings.value('pathtest/output') or os.path.join(videos, 'deadlock_orbit.mp4'))
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._pickOutput)
        row = QHBoxLayout()
        row.addWidget(self.output, 1)
        row.addWidget(browse)
        form.addRow('Save video to', row)
        self.fps = spin(10, 240, 64, decimals=0, step=1, suffix=' fps')
        self.fps.setToolTip('One replay tick per frame. At 64 fps that is real-time speed if Deadlock runs at 64 ticks/s.')
        form.addRow('Video frame rate', self.fps)
        self.advance = QCheckBox('Replay plays during the shot (unticked = frozen moment)')
        self.advance.setChecked(True)
        form.addRow(self.advance)
        self.settle = spin(20, 1000, 80, decimals=0, step=10, suffix=' ms')
        self.settle.setToolTip('How long to give Deadlock to draw each frame before capturing. Raise it if the '
                               'video shows repeated or half-updated frames.')
        form.addRow('Wait per frame', self.settle)
        layout.addWidget(box)
        self.renderButton = button('Render to video (3 s countdown)', self._toggleRender, accent=True)
        layout.addWidget(self.renderButton)

        self.statusLabel = label('', 'heading', wrap=True)
        layout.addWidget(self.statusLabel)
        layout.addStretch(1)
        if not keysender.AVAILABLE:
            self.startButton.setEnabled(False)
            self.renderButton.setEnabled(False)
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

    def _pickOutput(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save video', self.output.text(), 'MP4 video (*.mp4)')
        if path:
            self.output.setText(path)

    def _prepare(self):
        """Validate the setup. Returns (cfg path, camera path, template, key) or None."""
        folder = self.cfgDir.text().strip()
        if not os.path.isdir(folder):
            self.statusLabel.setText('Set the Deadlock cfg folder first (…/Deadlock/game/citadel/cfg).')
            return None
        if self.start is None:
            self.statusLabel.setText('Read the start position first.')
            return None
        self.settings.set_value('pathtest/cfgdir', folder)
        target = os.path.join(folder, pathtest.FRAME_CFG + '.cfg')
        path = pathtest.orbit_path(self.start, self.distance.value(), self.duration.value())
        template = self.command.currentData() or self.settings.get('commands/camera')
        _, scancode, extended = pathtest.BIND_KEYS[self.key.currentIndex()]
        # Write the first frame now so the bind works even before the test runs.
        pathtest.write_frame(target, pathtest.frame_commands(template, *path(0.0)))
        return target, path, template, (scancode, extended)

    def _busy(self):
        if self.worker and self.worker.is_alive():
            self.stopFlag.set()
            return True
        return False

    def _toggle(self):
        if self._busy():
            return
        prepared = self._prepare()
        if prepared is None:
            return
        target, path, template, (scancode, extended) = prepared
        self.stopFlag.clear()
        self.startButton.setText('Stop')
        self.renderButton.setEnabled(False)
        args = (target, path, template, scancode, extended, self.duration.value(), self.rate.currentData())
        self.worker = threading.Thread(target=self._run, args=args, daemon=True)
        self.worker.start()

    def _toggleRender(self):
        if self._busy():
            return
        prepared = self._prepare()
        if prepared is None:
            return
        if not render.ffmpeg_exe():
            self.statusLabel.setText('The bundled ffmpeg is missing, so video can not be encoded.')
            return
        output = self.output.text().strip()
        if not output.lower().endswith('.mp4'):
            output += '.mp4'
        self.settings.set_value('pathtest/output', output)
        target, path, template, key = prepared
        fps = int(self.fps.value())
        frames = render.plan_frames(path, self.duration.value(), fps, 1.0 if self.advance.isChecked() else 0.0)
        self.stopFlag.clear()
        self.renderButton.setText('Stop rendering')
        self.startButton.setEnabled(False)
        args = (target, template, key, frames, fps, output, self.settle.value() / 1000.0)
        self.worker = threading.Thread(target=self._runRender, args=args, daemon=True)
        self.worker.start()

    def _runRender(self, target, template, key, frames, fps, output, settle):
        for remaining in (3, 2, 1):
            if self.stopFlag.is_set():
                self.signals.finished.emit('Stopped.')
                return
            self.signals.status.emit('Click into Deadlock… rendering starts in {}'.format(remaining))
            time.sleep(1.0)
        rect = capture.deadlock_rect()
        if rect is None:
            self.signals.finished.emit('Deadlock was not the active window, so there was nothing to capture.')
            return
        started = time.perf_counter()
        grabber = encoder = None
        try:
            grabber = capture.Grabber(rect)
            encoder = render.FfmpegEncoder(output, grabber.size, fps)
            renderer = render.Renderer(
                target, template, lambda: keysender.tap(*key), grabber.grab, encoder, settle=settle,
                isFocused=keysender.foreground_is_deadlock, stopped=self.stopFlag.is_set,
                progress=lambda i, n: self.signals.status.emit('Rendering frame {} / {}'.format(i, n)))
            with keysender.precise_timer():
                written = renderer.run(frames)
        except Exception as error:
            self.signals.finished.emit('Render failed: {}'.format(error))
            return
        finally:
            if grabber:
                grabber.close()
            code = encoder.close() if encoder else None
        took = time.perf_counter() - started
        if code:
            self.signals.finished.emit('ffmpeg failed (code {}). Details: {}'.format(code, encoder.logPath))
            return
        stale = ' {} frames never changed on screen in time; raise "Wait per frame" if you see stutter.'.format(
            renderer.stale) if renderer.stale else ''
        self.signals.finished.emit('{}Rendered {} frames ({}x{}, {:.1f} s of video) in {:.0f} s.{}\n\nSaved to {}'.format(
            'Stopped early. ' if self.stopFlag.is_set() else '', written, grabber.size[0], grabber.size[1],
            written / float(fps), took, stale, output))

    def _run(self, target, path, template, scancode, extended, duration, rate):
        for remaining in (3, 2, 1):
            if self.stopFlag.is_set():
                self.signals.finished.emit('Stopped.')
                return
            self.signals.status.emit('Click into Deadlock… starting in {}'.format(remaining))
            time.sleep(1.0)
        frames = taps = skipped = unfocused = 0
        tapTimes = []
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
                    tapTimes.append(time.perf_counter())
                if frames % rate == 0:
                    self.signals.status.emit('Running… {:.0f} / {:.0f} s'.format(t, duration))
                pacer.wait()
        elapsed = max(0.001, pacer.elapsed())
        gaps = [(b - a) * 1000.0 for a, b in zip(tapTimes, tapTimes[1:])]
        timing = ''
        if gaps:
            timing = ' Gap between taps: target {:.1f} ms, actual {:.1f}–{:.1f} ms.'.format(
                1000.0 / rate, min(gaps), max(gaps))
        report = ('Done. {} frames in {:.1f} s ({:.0f}/s): {} key taps sent, {} skipped because the game had the '
                  'file open, {} while Deadlock was not focused.{}\n\nDid the camera glide smoothly around the point, '
                  'jump between positions, or not move at all?').format(
            frames, elapsed, frames / elapsed, taps, skipped, unfocused, timing)
        self.signals.finished.emit('Stopped early. ' + report if self.stopFlag.is_set() else report)

    def _finished(self, text):
        self.statusLabel.setText(text)
        self.startButton.setText('Live test (3 s countdown)')
        self.renderButton.setText('Render to video (3 s countdown)')
        self.startButton.setEnabled(keysender.AVAILABLE)
        self.renderButton.setEnabled(keysender.AVAILABLE)

    def closeEvent(self, event):
        self.stopFlag.set()
        QDialog.closeEvent(self, event)
