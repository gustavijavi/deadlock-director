"""A tiny stand-in for Deadlock's network console, for developing and testing
Deadlock Director without the game running.

    python tools/fake_deadlock.py --port 2121

It understands the handful of commands the app uses (spec_pos, spec_goto,
demo_* ...) and keeps a simulated camera and replay clock.
"""
import argparse
import socketserver
import threading
import time


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
            if name == 'spec_goto':
                values = [float(a) for a in args[:5]]
                self.camera[:len(values)] = values
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


def make_server(port, game=None, host='127.0.0.1', verbose=False):
    game = game or FakeGame()

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

    server = Server((host, port), Handler)
    server.game = game
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=2121)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    server = make_server(args.port, verbose=not args.quiet)
    print('Fake Deadlock console listening on 127.0.0.1:{}'.format(args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
