import sys

from PySide6.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Deadlock Director')
    app.setOrganizationName('DeadlockDirector')
    from deadlockdirector.ui import theme
    from deadlockdirector.ui.mainwindow import MainWindow
    theme.apply(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.openSequence(sys.argv[1])
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
