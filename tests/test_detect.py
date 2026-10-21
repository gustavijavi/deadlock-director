import os
import socket
import struct
import threading

import psutil
import pytest

from deadlockdirector import detect

ME = (psutil.Process(os.getpid()).name().lower(),)


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def listener():
    """Start a one-shot TCP server whose behaviour on connect is `greeting`."""
    servers = []

    def start(greeting=None):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(4)
        servers.append(server)

        def run():
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return
                if greeting:
                    conn.sendall(greeting)
                threading.Timer(3.0, conn.close).start()

        threading.Thread(target=run, daemon=True).start()
        return server.getsockname()[1]

    yield start
    for server in servers:
        server.close()


def test_diagnose_ok(fake):
    _, port = fake
    verdict, details, found = detect.diagnose('127.0.0.1', port, names=ME)
    assert verdict == 'ok', details
    assert found == port


def test_diagnose_not_running():
    verdict, _, found = detect.diagnose('127.0.0.1', free_port(), names=('surely-not-running.exe',))
    assert verdict == 'not_running' and found is None


def test_diagnose_finds_console_on_other_port(fake):
    # The "game" (this process) runs a real console on the fake port, while
    # the app is configured for a different, closed port.
    _, port = fake
    verdict, details, found = detect.diagnose('127.0.0.1', free_port(), names=ME)
    assert verdict == 'other_port', details
    assert found == port


def test_probe_identifies_vconsole(listener):
    packet = b'AINF' + struct.pack('>IHH', 0x00D20000, 20, 0) + b'\x00' * 8
    assert detect.probe_port('127.0.0.1', listener(packet), listen=0.5)[0] == 'vconsole'


def test_probe_silent_port_is_not_a_console(listener):
    assert detect.probe_port('127.0.0.1', listener(), listen=0.3, timeout=0.3)[0] == 'silent'


def test_probe_closed_port():
    assert detect.probe_port('127.0.0.1', free_port())[0] == 'closed'


def test_advice_formats():
    for text in detect.ADVICE.values():
        text.format(port=2121, found=62090)
