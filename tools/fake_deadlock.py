"""A tiny stand-in for Deadlock's console, for developing and testing
Deadlock Director without the game running.

    python tools/fake_deadlock.py --port 2121                      # network console
    python tools/fake_deadlock.py --port 29000 --protocol vconsole # VConsole

It understands the handful of commands the app uses (spec_pos, spec_goto,
demo_* ...) and keeps a simulated camera and replay clock.
"""
import argparse
import socketserver
import struct
import threading
import time

VCON_HEADER = struct.Struct('>4sIHH')
VCON_VERSION = 0x00D40000


def vconsole_chunk(kind, body):
    return VCON_HEADER.pack(kind, VCON_VERSION, VCON_HEADER.size + len(body), 0) + body


def vconsole_print(text, channel=7):
    return vconsole_chunk(b'PRNT', struct.pack('>i', channel) + b'\x00' * 24 + text.encode('utf-8') + b'\x00')


class FakeGame(object):

    def __init__(self, tickrate=64.0):
        self.lock = threading.Lock()
        self.camera = [0.0, 0.0, 512.0, 15.0, 90.0]
        self.tickrate = tickrate
        self.tick = 1000.0
        self.timescale = 1.0
        self.paused = False
        self.last = time.monotonic()
        self.convars = {}
        self.history = []

    def advance(self):
        now = time.monotonic()
        if not self.paused:
            self.tick += (now - self.last) * self.tickrate * self.timescale
        self.last = now

    def execute(self, line):
        with self.lock:
            self.advance()
            self.history.append(line)
            parts = line.split()
            if not parts:
                return []
            name, args = parts[0].lower(), parts[1:]
            if name == 'echo':
                return [' '.join(args)]
            if name == 'spec_pos':
                return ['spec_goto {:.2f} {:.2f} {:.2f} {:.2f} {:.2f}'.format(*self.camera)]
            if name in ('spec_goto', 'spec_setpos'):
                values = [float(a) for a in args[:5 if name == 'spec_goto' else 3]]
                self.camera[:len(values)] = values
                return []
            if name == 'spec_setang':
                self.camera[3:3 + len(args[:2])] = [float(a) for a in args[:2]]
                return []
            if name == 'demo_pause':
                self.paused = True
                return []
            if name == 'demo_resume':
                self.paused = False
                return []
            if name == 'demo_timescale' and args:
                self.timescale = float(args[0])
                return []
            if name == 'demo_gototick' and args:
                self.tick = float(args[0])
                return []
            if name == 'demo_info':
                return ['Demo: replay.dem', 'Current tick: {}'.format(int(self.tick))]
            if args:
                self.convars[name] = ' '.join(args)
                return []
            if name in self.convars:
                return ['{} = {}'.format(name, self.convars[name])]
            return ["Unknown command '{}'".format(name)]


def make_server(port, game=None, host='127.0.0.1', verbose=False, protocol='netcon'):
    game = game or FakeGame()

    class VConsoleHandler(socketserver.StreamRequestHandler):
        def handle(self):
            # Like the real thing: announce ourselves before the client speaks.
            self.wfile.write(vconsole_chunk(b'AINF', b'\x00' * 77))
            self.wfile.write(vconsole_chunk(b'ADON', struct.pack('>HH', 0, 8) + b'citadel\x00'))
            self.wfile.flush()
            while True:
                header = self.rfile.read(VCON_HEADER.size)
                if len(header) < VCON_HEADER.size:
                    return
                kind, _, length, _ = VCON_HEADER.unpack(header)
                body = self.rfile.read(length - VCON_HEADER.size)
                if kind != b'CMND':
                    continue
                line = body.split(b'\x00', 1)[0].decode('utf-8', errors='replace').strip()
                if verbose:
                    print('>', line, flush=True)
                for output in game.execute(line):
                    self.wfile.write(vconsole_print(output))
                self.wfile.flush()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for raw in self.rfile:
                line = raw.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                if verbose:
                    print('>', line, flush=True)
                for output in game.execute(line):
                    self.wfile.write((output + '\n').encode('utf-8'))
                self.wfile.flush()

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server((host, port), VConsoleHandler if protocol == 'vconsole' else Handler)
    server.game = game
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=2121)
    parser.add_argument('--protocol', choices=('netcon', 'vconsole'), default='netcon')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    server = make_server(args.port, verbose=not args.quiet, protocol=args.protocol)
    print('Fake Deadlock {} listening on 127.0.0.1:{}'.format(args.protocol, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
