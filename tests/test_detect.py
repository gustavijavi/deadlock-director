import os
import socket

import psutil

from deadlockdirector import detect

ME = (psutil.Process(os.getpid()).name().lower(),)


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_diagnose_ok(fake):
    _, port = fake
    verdict, details = detect.diagnose('127.0.0.1', port, names=ME)
    assert verdict == 'ok', details
    assert any(str(port) in line for line in details)


def test_diagnose_not_running():
    verdict, _ = detect.diagnose('127.0.0.1', free_port(), names=('surely-not-running.exe',))
    assert verdict == 'not_running'


def test_diagnose_other_port(fake):
    # The "game" (this process) listens on the fake console port, but the
    # app is configured for a different, closed port.
    _, port = fake
    verdict, details = detect.diagnose('127.0.0.1', free_port(), names=ME)
    assert verdict == 'other_port', details


def test_advice_formats():
    for text in detect.ADVICE.values():
        text.format(port=2121)
