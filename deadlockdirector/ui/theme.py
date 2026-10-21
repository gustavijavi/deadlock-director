from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QStyleFactory

BACKGROUND = QColor('#15171b')
SURFACE = QColor('#1d2026')
SURFACE_ALT = QColor('#23272e')
BORDER = QColor('#30353d')
TEXT = QColor('#d9d6cf')
TEXT_DIM = QColor('#8a8f98')
ACCENT = QColor('#d4a85a')       # brass
ACCENT_DIM = QColor('#8c6d36')
PLAYHEAD = QColor('#e0533d')
LIVE = QColor('#4fb3a9')         # in-game camera
GOOD = QColor('#6cc070')
WARN = QColor('#e0a03d')
BAD = QColor('#d65a4a')

TRACK_COLORS = {
    'position': QColor('#d4a85a'),
    'rotation': QColor('#7aa7d9'),
    'fov': QColor('#b48ad6'),
    'speed': QColor('#6cc070'),
}

STYLESHEET = """
QMainWindow, QDialog { background: #15171b; }
QDockWidget { color: #d9d6cf; font-weight: 600; }
QDockWidget::title { background: #1d2026; padding: 6px 8px; border-bottom: 1px solid #30353d; }
QToolBar { background: #1d2026; border: none; border-bottom: 1px solid #30353d; spacing: 4px; padding: 4px; }
QToolButton { color: #d9d6cf; padding: 5px 9px; border-radius: 4px; }
QToolButton:hover { background: #2b3038; }
QToolButton:checked { background: #3a2f1c; color: #f0cf8f; }
QPushButton { background: #2a2e36; color: #d9d6cf; border: 1px solid #353b44; border-radius: 4px; padding: 5px 10px; }
QPushButton:hover { background: #333842; }
QPushButton:pressed { background: #23272e; }
QPushButton:disabled { color: #5d626a; }
QPushButton[accent="true"] { background: #6b5225; border-color: #8c6d36; color: #fbe7c0; }
QPushButton[accent="true"]:hover { background: #7d5f2b; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {
    background: #121418; color: #d9d6cf; border: 1px solid #30353d; border-radius: 3px; padding: 3px 5px;
    selection-background-color: #8c6d36;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border-color: #8c6d36; }
QGroupBox { border: 1px solid #30353d; border-radius: 5px; margin-top: 14px; padding-top: 6px; color: #8a8f98; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLabel[role="value"] { font-family: Consolas, "DejaVu Sans Mono", monospace; color: #f0e6d2; }
QLabel[role="hint"] { color: #8a8f98; }
QLabel[role="heading"] { color: #d4a85a; font-weight: 600; }
QStatusBar { background: #1d2026; color: #8a8f98; border-top: 1px solid #30353d; }
QTabWidget::pane { border: 1px solid #30353d; }
QTabBar::tab { background: #1d2026; color: #8a8f98; padding: 6px 12px; border: 1px solid #30353d; border-bottom: none; }
QTabBar::tab:selected { background: #23272e; color: #d9d6cf; }
QScrollBar:horizontal, QScrollBar:vertical { background: #15171b; border: none; height: 10px; width: 10px; }
QScrollBar::handle { background: #353b44; border-radius: 4px; min-width: 20px; min-height: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QSplitter::handle { background: #30353d; }
QMenu { background: #1d2026; color: #d9d6cf; border: 1px solid #30353d; }
QMenu::item:selected { background: #3a2f1c; }
QToolTip { background: #23272e; color: #d9d6cf; border: 1px solid #30353d; }
"""


def apply(app):
    app.setStyle(QStyleFactory.create('Fusion'))
    palette = QPalette()
    palette.setColor(QPalette.Window, BACKGROUND)
    palette.setColor(QPalette.WindowText, TEXT)
    palette.setColor(QPalette.Base, QColor('#121418'))
    palette.setColor(QPalette.AlternateBase, SURFACE)
    palette.setColor(QPalette.ToolTipBase, SURFACE_ALT)
    palette.setColor(QPalette.ToolTipText, TEXT)
    palette.setColor(QPalette.Text, TEXT)
    palette.setColor(QPalette.Button, SURFACE_ALT)
    palette.setColor(QPalette.ButtonText, TEXT)
    palette.setColor(QPalette.Highlight, ACCENT_DIM)
    palette.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    palette.setColor(QPalette.Disabled, QPalette.Text, TEXT_DIM)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, TEXT_DIM)
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
