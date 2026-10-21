import struct

import pytest

from deadlockdirector import vconsole


def prnt(text, version=0x00D40000):
    body = struct.pack('>i', 3) + b'\x00' * 24 + text.encode() + b'\x00'
    return vconsole.HEADER.pack(b'PRNT', version, 12 + len(body), 0) + body


def test_build_command_layout():
    packet = vconsole.build_command('spec_pos')
    assert packet[:4] == b'CMND'
    assert struct.unpack('>I', packet[4:8])[0] == 0x00D40000
    assert struct.unpack('>H', packet[8:10])[0] == len(packet) == 12 + len('spec_pos') + 1
    assert packet[12:] == b'spec_pos\x00'


def test_parse_chunks_handles_partial_and_multiple():
    data = prnt('hello') + prnt('world')
    chunks, rest = vconsole.parse_chunks(data[:-3])
    assert [vconsole.prnt_text(body) for _, _, body in chunks] == ['hello']
    assert rest == data[len(prnt('hello')):-3]
    chunks, rest = vconsole.parse_chunks(rest + data[-3:])
    assert [vconsole.prnt_text(body) for _, _, body in chunks] == ['world'] and rest == b''


def test_parse_chunks_rejects_garbage():
    with pytest.raises(ValueError):
        vconsole.parse_chunks(b'PRNT' + b'\x00\xd4\x00\x00' + b'\x00\x03' + b'\x00\x00')


def test_looks_like_vconsole():
    assert vconsole.looks_like_vconsole(prnt('x'))
    assert not vconsole.looks_like_vconsole(b'HTTP/1.1 501 Not Implemented\r\ncontent-type: text/plain\r\n')
    assert not vconsole.looks_like_vconsole(b'short')
