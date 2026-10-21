"""Optional OBS Studio integration (obs-websocket v5) for recording shots.

Deadlock has no built-in video capture like League's replay API, so the
recording side is handed to OBS, which captures the game window the same way
it does for any stream.
"""
import base64
import hashlib
import json
import threading
import uuid

from PySide6.QtCore import QObject, Signal

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover
    websocket = None


def auth_response(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsError(Exception):
    pass


def obs_request(host, port, password, request_type, data=None, timeout=3.0):
    """Open a connection, identify, run one request and return its data."""
    if websocket is None:
        raise ObsError('The websocket-client package is not installed')
    ws = websocket.create_connection('ws://{}:{}'.format(host, int(port)), timeout=timeout)
    try:
        hello = json.loads(ws.recv())
        if hello.get('op') != 0:
            raise ObsError('Unexpected OBS handshake')
        identify = {'rpcVersion': 1}
        auth = hello['d'].get('authentication')
        if auth:
            if not password:
                raise ObsError('OBS requires a password (Settings > OBS)')
            identify['authentication'] = auth_response(password, auth['salt'], auth['challenge'])
        ws.send(json.dumps({'op': 1, 'd': identify}))
        identified = json.loads(ws.recv())
        if identified.get('op') != 2:
            raise ObsError('OBS rejected the connection (wrong password?)')
        request_id = str(uuid.uuid4())
        payload = {'requestType': request_type, 'requestId': request_id}
        if data:
            payload['requestData'] = data
        ws.send(json.dumps({'op': 6, 'd': payload}))
        while True:
            message = json.loads(ws.recv())
            if message.get('op') == 7 and message['d'].get('requestId') == request_id:
                status = message['d'].get('requestStatus', {})
                if not status.get('result'):
                    raise ObsError(status.get('comment') or 'OBS request {} failed'.format(request_type))
                return message['d'].get('responseData') or {}
    except (OSError, ValueError, KeyError) as error:
        raise ObsError(str(error))
    finally:
        ws.close()


class ObsRecorder(QObject):
    """Starts/stops OBS recording on a worker thread so the UI never blocks."""
    message = Signal(str)

    def __init__(self, settings, parent=None):
        QObject.__init__(self, parent)
        self.settings = settings

    def enabled(self):
        return self.settings.get('obs/enabled')

    def _run(self, request_type, success):
        host = self.settings.get('obs/host')
        port = self.settings.get('obs/port')
        password = self.settings.get('obs/password')

        def work():
            try:
                result = obs_request(host, port, password, request_type)
                self.message.emit(success(result) if callable(success) else success)
            except Exception as error:
                self.message.emit('OBS: {}'.format(error))

        threading.Thread(target=work, daemon=True).start()

    def startRecording(self):
        self._run('StartRecord', 'OBS: recording started')

    def stopRecording(self):
        self._run('StopRecord', lambda r: 'OBS: recording saved to {}'.format(r.get('outputPath', '?')))

    def test(self):
        self._run('GetVersion', lambda r: 'OBS: connected to OBS {} (websocket {})'.format(
            r.get('obsVersion', '?'), r.get('obsWebSocketVersion', '?')))
