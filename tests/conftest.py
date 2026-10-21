import os
import socket
import sys
import tempfile
import threading

# Keep tests away from the real user settings and make Qt run headless.
_tmp = tempfile.mkdtemp(prefix='ddir-tests-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp, 'data')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
from fake_deadlock import FakeGame, make_server  # noqa: E402


@pytest.fixture(scope='session')
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setOrganizationName('DeadlockDirectorTests')
    return instance


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def start_fake(protocol):
    """Run a fake Deadlock console; yields (server, port)."""
    port = free_port()
    server = make_server(port, FakeGame(), protocol=protocol)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def fake(app):
    yield from start_fake('netcon')


@pytest.fixture
def fake_vconsole(app):
    yield from start_fake('vconsole')
