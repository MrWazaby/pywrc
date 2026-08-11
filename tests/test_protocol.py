"""Decoding of the objects described in the WeeChat Relay protocol documentation."""

from __future__ import annotations

import zlib

import pytest

from gwrc.protocol import Hdata, ProtocolError, decode_message, encode_command


def string(value: str) -> bytes:
    return len(value).to_bytes(4, "big") + value.encode()


def counted(value: str) -> bytes:
    return bytes([len(value)]) + value.encode()


def message(*body: bytes, compression: int = 0) -> bytes:
    """A message body: the compression flag, the identifier and the objects."""
    return bytes([compression]) + b"".join(body)


def test_decode_objects_of_the_test_command():
    """The objects returned by the "test" command, in the documented order."""
    body = message(
        string("test"),
        b"chr" + b"\x41",
        b"int" + b"\x00\x01\xe2\x40",
        b"int" + b"\xff\xfe\x1d\xc0",
        b"lon" + counted("1234567890"),
        b"lon" + counted("-1234567890"),
        b"str" + string("a string"),
        b"str" + string(""),
        b"str" + b"\xff\xff\xff\xff",
        b"buf" + string("buffer"),
        b"buf" + b"\xff\xff\xff\xff",
        b"ptr" + counted("1234abcd"),
        b"ptr" + counted("0"),
        b"tim" + counted("1321993456"),
        b"arr" + b"str" + b"\x00\x00\x00\x02" + string("abc") + string("de"),
        b"arr" + b"int" + b"\x00\x00\x00\x03" + b"\x00\x00\x00\x7b\x00\x00\x01\xc8\x00\x00\x03\x15",
    )
    decoded = decode_message(body)
    assert decoded.id == "test"
    assert decoded.objects == [
        65,
        123456,
        -123456,
        1234567890,
        -1234567890,
        "a string",
        "",
        None,
        b"buffer",
        None,
        "0x1234abcd",
        "0x0",
        1321993456,
        ["abc", "de"],
        [123, 456, 789],
    ]


def test_decode_hdata_with_two_buffers():
    body = message(
        string("hdata_buffers"),
        b"hda",
        string("buffer"),
        string("number:int,full_name:str"),
        b"\x00\x00\x00\x02",
        counted("12345") + b"\x00\x00\x00\x01" + string("core.weechat"),
        counted("6789a") + b"\x00\x00\x00\x02" + string("irc.server.libera"),
    )
    hdata = decode_message(body).hdata
    assert hdata == Hdata(
        path=["buffer"],
        keys={"number": "int", "full_name": "str"},
        items=[
            {"__path": ["0x12345"], "number": 1, "full_name": "core.weechat"},
            {"__path": ["0x6789a"], "number": 2, "full_name": "irc.server.libera"},
        ],
    )


def test_decode_empty_hdata():
    body = message(string("hotlist"), b"hda", b"\xff\xff\xff\xff", b"\xff\xff\xff\xff", bytes(4))
    assert decode_message(body).hdata == Hdata(path=[], keys={}, items=[])


def test_decode_hashtable_of_the_handshake():
    body = message(
        string("handshake"),
        b"htb" + b"str" + b"str" + b"\x00\x00\x00\x02",
        string("password_hash_algo") + string("pbkdf2+sha256"),
        string("nonce") + string("85B1EE00"),
    )
    assert decode_message(body).objects == [
        {"password_hash_algo": "pbkdf2+sha256", "nonce": "85B1EE00"}
    ]


def test_decode_infolist():
    body = message(
        string("infolist"),
        b"inl" + string("buffer") + b"\x00\x00\x00\x01",
        b"\x00\x00\x00\x02" + string("pointer") + b"ptr" + counted("12345"),
        string("number") + b"int" + b"\x00\x00\x00\x01",
    )
    assert decode_message(body).objects == [("buffer", [{"pointer": "0x12345", "number": 1}])]


def test_decode_compressed_message():
    body = message(string("test"), b"int" + b"\x00\x00\x00\x2a")
    compressed = bytes([1]) + zlib.compress(body[1:])
    assert decode_message(compressed) == decode_message(body)


def test_decode_rejects_unknown_type_and_truncated_data():
    with pytest.raises(ProtocolError, match="unknown object type"):
        decode_message(message(string("x"), b"zzz"))
    with pytest.raises(ProtocolError, match="truncated"):
        decode_message(message(string("x"), b"int" + b"\x00\x00"))
    with pytest.raises(ProtocolError, match="zstd"):
        decode_message(message(string("x"), compression=2))


def test_encode_command():
    assert encode_command("sync") == b"sync\n"
    assert encode_command("test", "id") == b"(id) test\n"
