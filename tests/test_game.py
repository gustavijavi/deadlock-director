"""End-to-end tests against the fake network console in tools/."""
import time

import pytest
from PySide6.QtCore import QCoreApplication, QSettings

from deadlockdirector.game import STATUS_CONNECTED, DeadlockGame
from deadlockdirector.playback import SequencePlayer
from deadlockdirector.sequence import Sequence
from deadlockdirector.settings import Settings

from conftest import free_port, start_fake


def wait_for(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture(params=['netcon', 'vconsole'])
def protocol(request):
    return request.param


@pytest.fixture
def fake(app, protocol):
    """Every test in this module runs against both console protocols."""
    yield from start_fake(protocol)


def make_settings(tmp_path, **values):
    settings = Settings(QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat))
    settings.set('connection/autoconnect', False)
    for key, value in values.items():
        settings.set('connection/' + key, value)
    return settings


@pytest.fixture
def game(fake, protocol, tmp_path):
    server, port = fake
    key = 'vconsole_port' if protocol == 'vconsole' else 'port'
    settings = make_settings(tmp_path, protocol=protocol, **{key: port})
    game = DeadlockGame(settings)
    game.detectTimer.stop()
    game.connectToGame()
    assert wait_for(lambda: game.status == STATUS_CONNECTED)
    yield game
    game.disconnectFromGame()


def test_query_camera(game, fake):
    server, _ = fake
    server.game.camera = [10.0, 20.0, 30.0, 5.0, 45.0]
    result = []
    game.queryCamera(result.append)
    assert wait_for(lambda: result)
    assert result[0].position == [10.0, 20.0, 30.0]
    assert result[0].rotation == [5.0, 45.0, 0.0]


def test_set_camera_and_dedupe(game, fake):
    server, _ = fake
    wait_for(lambda: False, 0.4)  # let the on-connect camera query finish
    game.setCamera([1, 2, 3], [4, 5, 0])
    assert wait_for(lambda: server.game.camera == [1.0, 2.0, 3.0, 4.0, 5.0])
    count = len(server.game.history)
    game.setCamera([1, 2, 3], [4, 5, 0])
    wait_for(lambda: False, 0.2)
    assert len(server.game.history) == count


def test_query_tick(game, fake):
    server, _ = fake
    server.game.paused = True
    server.game.tick = 4321
    result = []
    game.queryTick(result.append)
    assert wait_for(lambda: result)
    assert result[0] == 4321


def test_capture_from_in_game_bind(game, fake):
    server, _ = fake
    got = []
    game.queryCamera(got.append)
    assert wait_for(lambda: got)
    captured = []
    game.captureFromGame.connect(captured.append)
    # Simulate the user pressing a key bound to spec_pos: output arrives
    # without our markers around it.
    game.client.send('spec_pos')
    assert wait_for(lambda: captured)


def test_synced_playback(game, fake):
    server, _ = fake
    settings = game.settings
    settings.set('playback/preroll', 0.0)
    settings.set('playback/rate', 120)
    seq = Sequence()
    seq.start_tick = 2000
    seq.track('position').add(0, [0, 0, 100], 'linear')
    seq.track('position').add(0.5, [500, 0, 100], 'linear')
    seq.track('rotation').add(0, [10, 0, 0], 'linear')
    player = SequencePlayer(game, settings, seq)
    player.play()
    assert wait_for(lambda: player.state == 'stopped' and player.time >= 0.5, 3.0)
    wait_for(lambda: server.game.camera[0] == 500.0, 1.0)
    assert server.game.camera[:3] == [500.0, 0.0, 100.0]
    history = server.game.history
    assert 'demo_gototick 2000' in history
    assert 'demo_resume' in history
    assert history[-1] == 'demo_pause' or 'demo_pause' in history[-3:]
    moves = [h for h in history if h.startswith('spec_goto')]
    assert len(moves) > 10  # streamed, not just the two keyframes


@pytest.mark.parametrize('protocol', ['vconsole'])
def test_auto_mode_finds_vconsole(fake, protocol, tmp_path):
    """With the network console closed, automatic mode lands on VConsole."""
    server, port = fake
    settings = make_settings(tmp_path, protocol='auto', port=free_port(), vconsole_port=port)
    game = DeadlockGame(settings)
    game.detectTimer.stop()
    game.connectToGame()
    try:
        assert wait_for(lambda: game.status == STATUS_CONNECTED)
        assert game.protocol == 'vconsole' and game.port() == port
        server.game.camera = [7.0, 8.0, 9.0, 1.0, 2.0]
        result = []
        game.queryCamera(result.append)
        assert wait_for(lambda: result) and result[0].position == [7.0, 8.0, 9.0]
    finally:
        game.disconnectFromGame()


@pytest.mark.parametrize('protocol', ['netcon', 'vconsole'])
@pytest.mark.parametrize('greeting', [None, b'HTTP/1.1 501 Not Implemented\r\ncontent-type: text/plain\r\n\r\n'])
def test_non_console_port_is_not_reported_connected(protocol, greeting, tmp_path, monkeypatch, app):
    """A port that accepts connections but isn't a game console (a silent
    socket, or Deadlock's internal web server) must not show as connected."""
    import socket
    import threading
    from deadlockdirector import netcon
    monkeypatch.setattr(netcon, 'HANDSHAKE_TIMEOUT', 400)
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(4)
    port = server.getsockname()[1]
    held = []

    def run():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            held.append(conn)
            if greeting:
                conn.recv(1024)
                conn.sendall(greeting)

    threading.Thread(target=run, daemon=True).start()
    key = 'vconsole_port' if protocol == 'vconsole' else 'port'
    game = DeadlockGame(make_settings(tmp_path, protocol=protocol, **{key: port}))
    game.detectTimer.stop()
    game.connectToGame()
    try:
        assert wait_for(lambda: game.connectionErrors(), 3.0)
        assert game.status != STATUS_CONNECTED and not game.isConnected()
    finally:
        game.disconnectFromGame()
        server.close()
        for conn in held:
            conn.close()


@pytest.mark.parametrize('protocol', ['vconsole'])
def test_vconsole_reports_game_name(game):
    assert wait_for(lambda: game.gameName == 'citadel')
