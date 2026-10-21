"""Smoke test: build the main window and run a capture / undo / save cycle."""
from test_game import wait_for

from deadlockdirector.game import STATUS_CONNECTED
from deadlockdirector.sequence import Sequence
from deadlockdirector.ui.mainwindow import MainWindow


def test_main_window_capture_cycle(app, fake, tmp_path):
    server, port = fake
    window = MainWindow()
    window.settings.set('connection/port', port)
    window.show()
    window.game.connectToGame()
    assert wait_for(lambda: window.game.status == STATUS_CONNECTED)

    server.game.camera = [100.0, 200.0, 300.0, 10.0, 45.0]
    window.player.setTime(2.0, apply=False)
    window.captureKeyframe()
    seq = window.document.sequence
    assert wait_for(lambda: len(seq.track('position').keyframes) == 1)
    assert seq.track('position').keyframes[0].time == 2.0
    assert seq.track('rotation').keyframes[0].value == [10.0, 45.0, 0.0]

    window.addKeyframeAt('fov', 1.0)
    assert len(seq.track('fov').keyframes) == 1
    window.document.undo()
    assert not seq.track('fov').keyframes

    window.document.selectAll()
    assert len(window.document.selection) == 2
    window.timeline.repaint()
    window.pathView.repaint()

    path = str(tmp_path / 'shot.ddseq')
    window.document.save(path)
    assert Sequence.load(path).to_dict() == seq.to_dict()
    window.document.dirty = False
    window.close()
