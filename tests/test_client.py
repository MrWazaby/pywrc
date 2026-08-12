"""What the client makes of what it reads, when it is not the WeeChat protocol."""

from __future__ import annotations

import pytest
from conftest import FakeWriter, reading

from pywrc.client import HttpAnswer, RelayClient, RelayError, Socket
from pywrc.config import Config

NGINX = (
    b"HTTP/1.1 400 Bad Request\r\n"
    b"Server: nginx/1.24.0\r\n"
    b"Date: Sun, 12 Jul 2026 09:41:12 GMT\r\n"
    b"Content-Type: text/html\r\n"
    b"Content-Length: 157\r\n"
    b"Connection: close\r\n"
    b"\r\n"
    b"<html>\r\n<head><title>400 Bad Request</title></head>\r\n"
    b"<body>\r\n<center><h1>400 Bad Request</h1></center>\r\n"
    b"<hr><center>nginx/1.24.0</center>\r\n</body>\r\n</html>\r\n"
)
"""What a web server in front of the relay answers to a relay command."""


def client(**settings: object) -> RelayClient:
    """A client for a relay on "my.server:9000"."""
    return RelayClient(Config(hostname="my.server", port=9000, **settings))  # type: ignore[arg-type]


def answering(data: bytes, **settings: object) -> RelayClient:
    """A client reading those bytes, without any connection behind them."""
    relay = client(**settings)
    relay.transport = Socket(reading(data), FakeWriter())  # type: ignore[arg-type]
    return relay


async def test_an_http_answer_is_reported_instead_of_a_huge_message():
    """The first four bytes of "HTTP/1.1 ..." read as a length of 1213486160 bytes."""
    with pytest.raises(HttpAnswer) as error:
        await answering(NGINX).read_message()
    assert 'my.server:9000 answered "HTTP/1.1 400 Bad Request"' in str(error.value)
    assert "websocket = true" in str(error.value)


async def test_an_http_answer_cut_short_is_reported_too():
    with pytest.raises(HttpAnswer, match=r"HTTP/1\.1 101"):
        await answering(b"HTTP/1.1 101 Switching").read_message()


async def test_a_length_that_cannot_be_one_is_rejected():
    with pytest.raises(RelayError, match="2147483647 bytes was announced"):
        await answering(b"\x7f\xff\xff\xff").read_message()
    with pytest.raises(RelayError, match="not the WeeChat protocol"):
        await answering(bytes(4)).read_message()


async def test_a_message_is_still_read_from_the_socket():
    body = bytes([0]) + (4).to_bytes(4, "big") + b"test"
    message = (len(body) + 4).to_bytes(4, "big") + body
    assert (await answering(message).read_message()).id == "test"


def test_the_url_says_how_the_relay_is_reached():
    assert client().url == "my.server:9000"
    over_websocket = client(websocket=True, websocket_path="/relay/weechat")
    over_websocket.websocket = True
    assert over_websocket.url == "wss://my.server:9000/relay/weechat"
    over_websocket.config.tls = False
    assert over_websocket.url == "ws://my.server:9000/relay/weechat"
