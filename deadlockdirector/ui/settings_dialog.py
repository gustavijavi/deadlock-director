from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QPushButton, QSpinBox, QDoubleSpinBox, QTabWidget, QVBoxLayout, QWidget)

from deadlockdirector.settings import CAMERA_PRESETS, DEFAULTS
from deadlockdirector.ui.panels import label

COMMANDS = [
    ('commands/camera', 'Move camera', 'Placeholders: {x} {y} {z} {pitch} {yaw} {roll}'),
    ('commands/camera_query', 'Read camera', 'Must print x y z pitch yaw [roll] on one line'),
    ('commands/fov', 'Set FOV', 'Placeholder: {value}. Leave empty to disable'),
    ('commands/timescale', 'Replay speed', 'Placeholder: {value}'),
    ('commands/pause', 'Pause replay', ''),
    ('commands/resume', 'Resume replay', ''),
    ('commands/seek', 'Seek replay', 'Placeholder: {tick}'),
    ('commands/tick_query', 'Read tick', 'Output is searched with the regex below'),
    ('commands/tick_regex', 'Tick regex', 'First capture group = tick number'),
    ('commands/hud_hide', 'Hide HUD', 'Several commands can be separated with ;'),
    ('commands/hud_show', 'Show HUD', ''),
    ('commands/freecam_speed', 'Free-cam speed', 'Placeholder: {value}'),
]


class SettingsDialog(QDialog):

    def __init__(self, settings, recorder, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle('Settings')
        self.resize(640, 520)
        self.settings = settings
        self.recorder = recorder
        self.fields = {}
        tabs = QTabWidget()

        # commands
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(label('These are ordinary Deadlock console commands. Deadlock is still in development, so if Valve '
                          'renames something you can fix it here without updating the app.', 'hint', wrap=True))
        self.preset = QComboBox()
        self.preset.addItem('Presets…')
        for name, template in CAMERA_PRESETS:
            self.preset.addItem(name, template)
        self.preset.activated.connect(self._preset)
        form.addRow('Camera preset', self.preset)
        for key, text, hint in COMMANDS:
            edit = QLineEdit(settings.get(key))
            edit.setPlaceholderText(DEFAULTS[key] or '(disabled)')
            if hint:
                edit.setToolTip(hint)
            self.fields[key] = edit
            form.addRow(text, edit)
        reset = QPushButton('Restore default commands')
        reset.clicked.connect(self._resetCommands)
        form.addRow(reset)
        tabs.addTab(page, 'Console commands')

        # playback
        page = QWidget()
        form = QFormLayout(page)
        rate = QSpinBox()
        rate.setRange(10, 240)
        rate.setValue(settings.get('playback/rate'))
        rate.setSuffix(' updates/s')
        rate.setToolTip('How often camera commands are sent while a sequence plays')
        self.fields['playback/rate'] = rate
        form.addRow('Camera update rate', rate)
        preroll = QDoubleSpinBox()
        preroll.setRange(0, 10)
        preroll.setSingleStep(0.5)
        preroll.setSuffix(' s')
        preroll.setValue(settings.get('playback/preroll'))
        self.fields['playback/preroll'] = preroll
        form.addRow('Pre-roll after seeking', preroll)
        tabs.addTab(page, 'Playback')

        # obs
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(label('Deadlock has no built-in video export, so "Record" drives OBS Studio over its WebSocket '
                          'server (OBS > Tools > WebSocket Server Settings). Capture the Deadlock window in OBS as usual.',
                          'hint', wrap=True))
        enabled = QCheckBox('Enable OBS recording')
        enabled.setChecked(settings.get('obs/enabled'))
        self.fields['obs/enabled'] = enabled
        form.addRow(enabled)
        host = QLineEdit(settings.get('obs/host'))
        self.fields['obs/host'] = host
        form.addRow('Host', host)
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(settings.get('obs/port'))
        self.fields['obs/port'] = port
        form.addRow('Port', port)
        password = QLineEdit(settings.get('obs/password'))
        password.setEchoMode(QLineEdit.Password)
        self.fields['obs/password'] = password
        form.addRow('Password', password)
        test = QPushButton('Test connection')
        test.clicked.connect(self._testObs)
        form.addRow(test)
        tabs.addTab(page, 'OBS recording')

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _preset(self, index):
        template = self.preset.itemData(index)
        if template:
            self.fields['commands/camera'].setText(template)

    def _resetCommands(self):
        for key, _, _ in COMMANDS:
            self.fields[key].setText(DEFAULTS[key])

    def save(self):
        for key, widget in self.fields.items():
            if isinstance(widget, QLineEdit):
                self.settings.set(key, widget.text().strip())
            elif isinstance(widget, QCheckBox):
                self.settings.set(key, widget.isChecked())
            else:
                self.settings.set(key, widget.value())

    def _testObs(self):
        self.save()
        self.recorder.test()

    def accept(self):
        self.save()
        QDialog.accept(self)
