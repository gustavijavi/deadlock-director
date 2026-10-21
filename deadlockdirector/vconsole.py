"""Client for Source 2's VConsole protocol (the one Valve's VConsole2 tool uses).

Some Source 2 games only expose their console this way, typically when started
in `-tools` mode, on TCP port 29000. The stream is a series of chunks:

    char[4] type     e.g. AINF, ADON, CHAN, CVAR, CFGV, PRNT (from the game), CMND (to it)
    uint32  version  big-endian protocol version, e.g. 0x00D40000
    uint16  length   big-endian, whole chunk including this 12-byte header
    uint16  handle

A CMND body is the command text plus a NUL. A PRNT body is a channel id, 24
bytes of metadata, then the NUL-terminated message text. The layout follows
the open-source implementations Penguinwizzard/VConsoleLib,
uilton-oliveira/VConsoleLib.python and theokyr/CS2RemoteConsole.
"""
import struct

from deadlockdirector.netcon import NetConClient

HEADER = struct.Struct('>4sIHH')
DEFAULT_VERSION = 0x00D40000
PRNT_TEXT_OFFSET = 28


def build_command(command, version=DEFAULT_VERSION):
    body = command.encode('utf-8') + b'\x00'
    return HEADER.pack(b'CMND', version, HEADER.size + len(body), 0) + body


def parse_chunks(buffer):
    """Split a byte buffer into complete chunks.

    Returns (chunks, rest) where chunks is [(type, version, body)] and rest is
    the unconsumed tail. Raises ValueError on a corrupt stream.
    """
    chunks = []
    while len(buffer) >= HEADER.size:
        kind, version, length, _ = HEADER.unpack_from(buffer)
        if length < HEADER.size:
            raise ValueError('corrupt VConsole chunk length {}'.format(length))
        if len(buffer) < length:
            break
        chunks.append((kind.decode('ascii', errors='replace'), version, buffer[HEADER.size:length]))
        buffer = buffer[length:]
    return chunks, buffer


def prnt_text(body):
    text = body[PRNT_TEXT_OFFSET:].split(b'\x00', 1)[0]
    return text.decode('utf-8', errors='replace')


def looks_like_vconsole(data):
    """True if raw bytes start with a plausible VConsole chunk header."""
    if len(data) < HEADER.size:
        return False
    kind, version, length, _ = HEADER.unpack_from(data)
    return kind.isalpha() and kind.isupper() and data[4] == 0 and length >= HEADER.size


class VConsoleClient(NetConClient):
    protocol = 'vconsole'

    def __init__(self, parent=None):
        NetConClient.__init__(self, parent)
        self.version = DEFAULT_VERSION
        self.chunkTypes = set()

    def encode(self, command):
        return build_command(command, self.version)

    def decode(self):
        try:
            chunks, self.buffer = parse_chunks(self.buffer)
        except ValueError as error:
            self.buffer = b''
            self.errorOccurred.emit(str(error))
            return
        for kind, version, body in chunks:
            # Answer in whatever protocol version the game speaks.
            self.version = version
            self.chunkTypes.add(kind)
            if kind == 'PRNT':
                for line in prnt_text(body).splitlines():
                    yield line
