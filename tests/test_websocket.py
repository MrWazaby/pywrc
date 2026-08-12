"""The WebSocket handshake and frames, as RFC 6455 describes them."""

from __future__ import annotations

import pytest
from conftest import FakeWriter, reading

from pywrc import websocket
from pywrc.websocket import BINARY, CLOSE, CONTINUATION, PING, PONG, TEXT, WebSocketError

KEY = "dGhlIHNhbXBsZSBub25jZQ=="
"""The "Sec-WebSocket-Key" of the example of RFC 6455, section 1.3."""

ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
"""The "Sec-WebSocket-Accept" the server answers to that key."""


def answer(accept: str = ACCEPT, status: str = "HTTP/1.1 101 Switching Protocols") -> bytes:
    """The answer of a server to a WebSocket handshake."""
    return (
        f"{status}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode()


def sent(opcode: int, payload: bytes = b"", final: bool = True) -> bytes:
    """A frame as the relay sends it: never masked, and possibly not the last one."""
    first = bytes([(websocket.FINAL if final else 0) | opcode])
    if len(payload) < 126:
        return first + bytes([len(payload)]) + payload
    if len(payload) < 1 << 16:
        return first + bytes([126]) + len(payload).to_bytes(2, "big") + payload
    return first + bytes([127]) + len(payload).to_bytes(8, "big") + payload


def received(data: bytes) -> tuple[int, bytes]:
    """Decode a frame written by the client, which must be masked."""
    assert data[1] & websocket.MASKED
    length = data[1] & ~websocket.MASKED
    start = 2
    if length == 126:
        length, start = int.from_bytes(data[2:4], "big"), 4
    elif length == 127:
        length, start = int.from_bytes(data[2:10], "big"), 10
    mask, payload = data[start : start + 4], data[start + 4 :]
    assert len(payload) == length
    return data[0] & 0x0F, websocket.unmask(payload, mask)


def test_the_accept_key_is_the_one_of_the_rfc():
    assert websocket.accept_key(KEY) == ACCEPT
    assert websocket.key() != websocket.key()


def test_the_request_is_an_http_get_asking_for_an_upgrade():
    request = websocket.request("my.server:9000", "weechat", KEY).decode()
    assert request.startswith("GET /weechat HTTP/1.1\r\n")
    assert request.endswith("\r\n\r\n")
    assert "Host: my.server:9000\r\n" in request
    assert "Upgrade: websocket\r\n" in request
    assert "Connection: Upgrade\r\n" in request
    assert f"Sec-WebSocket-Key: {KEY}\r\n" in request
    assert "Sec-WebSocket-Version: 13\r\n" in request
    assert "Origin:" not in request


def test_the_path_of_the_url_is_written_once():
    assert websocket.request("host", "/relay/weechat", KEY).startswith(b"GET /relay/weechat ")


def test_the_origin_is_sent_when_the_relay_asks_for_one():
    request = websocket.request("host", "weechat", KEY, origin="https://glowing-bear.org")
    assert b"Origin: https://glowing-bear.org\r\n" in request


def test_the_answer_of_the_server_is_checked():
    websocket.check_answer(answer(), KEY)  # no exception
    with pytest.raises(WebSocketError, match="404 Not Found"):
        websocket.check_answer(answer(status="HTTP/1.1 404 Not Found"), KEY)
    with pytest.raises(WebSocketError, match="wrong WebSocket key"):
        websocket.check_answer(answer(accept="wOuLdBeNiCe="), KEY)
    with pytest.raises(WebSocketError, match="did not upgrade"):
        websocket.check_answer(b"HTTP/1.1 101 Switching Protocols\r\n\r\n", KEY)


async def test_the_handshake_is_followed_by_the_frames(monkeypatch):
    monkeypatch.setattr(websocket, "key", lambda: KEY)
    writer = FakeWriter()
    reader = reading(answer() + sent(TEXT, b"hello"))
    stream = await websocket.connect(reader, writer, host="my.server:9000", path="weechat")
    assert writer.data == websocket.request("my.server:9000", "weechat", KEY)
    assert await stream.readexactly(5) == b"hello"


async def test_a_refused_handshake_is_reported(monkeypatch):
    monkeypatch.setattr(websocket, "key", lambda: KEY)
    reader = reading(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
    with pytest.raises(WebSocketError, match="403 Forbidden"):
        await websocket.connect(reader, FakeWriter(), host="host", path="weechat")


async def test_a_closed_connection_during_the_handshake_is_reported():
    with pytest.raises(WebSocketError, match="closed the connection"):
        await websocket.connect(reading(b"HTTP/1.1 101 "), FakeWriter(), host="h", path="weechat")


async def test_data_is_read_across_frames():
    frames = (sent(BINARY, b"one", final=False), sent(CONTINUATION, b"two"), sent(TEXT, b"three"))
    stream = websocket.WebSocketStream(reading(*frames), FakeWriter())
    assert await stream.readexactly(6) == b"onetwo"
    assert await stream.readexactly(5) == b"three"


async def test_long_payloads_are_read_and_written():
    for size in (125, 126, 1 << 16):
        payload = bytes(size)
        stream = websocket.WebSocketStream(reading(sent(BINARY, payload)), FakeWriter())
        assert await stream.readexactly(size) == payload
        assert received(websocket.frame(TEXT, payload)) == (TEXT, payload)


async def test_the_commands_are_sent_in_masked_text_frames():
    writer = FakeWriter()
    stream = websocket.WebSocketStream(reading(), writer)
    stream.write(b"input core.weechat /help\n")
    assert received(writer.data) == (TEXT, b"input core.weechat /help\n")
    assert websocket.frame(TEXT, b"x") != websocket.frame(TEXT, b"x")  # a new mask every time


async def test_a_ping_is_answered_with_a_pong():
    writer = FakeWriter()
    frames = (sent(PING, b"?"), sent(PONG), sent(TEXT, b"."))
    stream = websocket.WebSocketStream(reading(*frames), writer)
    assert await stream.readexactly(1) == b"."
    assert received(writer.data) == (PONG, b"?")


async def test_the_stream_ends_when_the_relay_closes_the_websocket():
    payload = (1000).to_bytes(2, "big") + b"bye"
    stream = websocket.WebSocketStream(reading(sent(CLOSE, payload)), FakeWriter())
    with pytest.raises(EOFError, match="1000 bye"):
        await stream.readexactly(1)


async def test_unexpected_frames_are_rejected():
    stream = websocket.WebSocketStream(reading(sent(0xB)), FakeWriter())
    with pytest.raises(WebSocketError, match="unknown WebSocket opcode 0xb"):
        await stream.readexactly(1)
    stream = websocket.WebSocketStream(reading(b"\x71\x00"), FakeWriter())
    with pytest.raises(WebSocketError, match="extension"):
        await stream.readexactly(1)


async def test_closing_says_goodbye():
    writer = FakeWriter()
    websocket.WebSocketStream(reading(), writer).close()
    assert received(writer.data) == (CLOSE, (1001).to_bytes(2, "big"))
    assert writer.closed
