"""Minimal WebSocket client (RFC 6455), enough to carry the "weechat" protocol.

A relay is often published by a web server, at an URL such as "wss://my.server/weechat":
this is what browser clients like Glowing Bear connect to.  Such an endpoint speaks HTTP
and WebSocket, never the raw relay socket, so pywrc has to open a WebSocket too.  Only
what the relay needs is implemented here: the client handshake, masked frames going out,
and data, ping and close frames coming in (fragmented messages are simply concatenated,
the relay protocol has its own framing).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import secrets

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
"""Appended to the key of the client to build "Sec-WebSocket-Accept" (RFC 6455)."""

CONTINUATION, TEXT, BINARY, CLOSE, PING, PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
DATA_OPCODES = (CONTINUATION, TEXT, BINARY)

FINAL = 0x80
"""First bit of a frame: this is the last frame of a message."""

MASKED = 0x80
"""First bit of the second byte of a frame: the payload is masked."""

RESERVED = 0x70
"""Bits of the extensions, which are never negotiated here."""

GOING_AWAY = 1001


class WebSocketError(Exception):
    """The WebSocket could not be opened, or a frame could not be read."""


def key() -> str:
    """A new "Sec-WebSocket-Key": 16 random bytes, in base64."""
    return base64.b64encode(secrets.token_bytes(16)).decode()


def accept_key(client_key: str) -> str:
    """The "Sec-WebSocket-Accept" a server must answer to a "Sec-WebSocket-Key"."""
    return base64.b64encode(hashlib.sha1(client_key.encode() + GUID).digest()).decode()


def request(host: str, path: str, client_key: str, origin: str = "") -> bytes:
    """The HTTP request opening a WebSocket."""
    lines = [
        f"GET /{path.lstrip('/')} HTTP/1.1",
        f"Host: {host}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {client_key}",
        "Sec-WebSocket-Version: 13",
    ]
    if origin:
        lines.append(f"Origin: {origin}")  # relay.network.websocket_allowed_origins
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def check_answer(answer: bytes, client_key: str) -> None:
    """Raise unless the server accepted the handshake with a "101 Switching Protocols"."""
    status, *header_lines = answer.decode("latin-1").strip().split("\r\n")
    fields = (line.partition(":") for line in header_lines)
    headers = {name.strip().lower(): value.strip() for name, _, value in fields}
    if status.split()[1:2] != ["101"]:
        raise WebSocketError(f"the server answered {status!r} to the WebSocket handshake")
    if headers.get("upgrade", "").lower() != "websocket":
        raise WebSocketError(f"the server did not upgrade the connection: {status!r}")
    if headers.get("sec-websocket-accept") != accept_key(client_key):
        raise WebSocketError("the server answered with a wrong WebSocket key")


def frame(opcode: int, payload: bytes) -> bytes:
    """Encode a whole message in one frame, masked as a client must do."""
    length = len(payload)
    header = bytes([FINAL | opcode])
    if length < 126:
        header += bytes([MASKED | length])
    elif length < 1 << 16:
        header += bytes([MASKED | 126]) + length.to_bytes(2, "big")
    else:
        header += bytes([MASKED | 127]) + length.to_bytes(8, "big")
    mask = secrets.token_bytes(4)
    return header + mask + unmask(payload, mask)


def unmask(payload: bytes, mask: bytes) -> bytes:
    """Apply the mask of a frame, which is its own inverse."""
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


class WebSocketStream:
    """The bytes of the relay protocol, read from and written to WebSocket frames."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.buffer = bytearray()  # payloads received and not read yet

    async def readexactly(self, count: int) -> bytes:
        """Read bytes, receiving as many frames as needed to get them."""
        while len(self.buffer) < count:
            await self.receive()
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    async def receive(self) -> None:
        """Read one frame: keep its data, answer the pings, stop on a close."""
        opcode, payload = await self.read_frame()
        if opcode in DATA_OPCODES:
            self.buffer += payload
        elif opcode == PING:
            self.send(PONG, payload)
        elif opcode == CLOSE:
            raise EOFError(f"the relay closed the WebSocket ({close_reason(payload)})")
        elif opcode != PONG:
            raise WebSocketError(f"unknown WebSocket opcode {opcode:#x}")

    async def read_frame(self) -> tuple[int, bytes]:
        """Read a frame and return its opcode and its payload."""
        first, second = await self.reader.readexactly(2)
        if first & RESERVED:
            raise WebSocketError("the relay used a WebSocket extension that was not negotiated")
        length = second & ~MASKED
        if length == 126:
            length = int.from_bytes(await self.reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await self.reader.readexactly(8), "big")
        mask = await self.reader.readexactly(4) if second & MASKED else b""
        payload = await self.reader.readexactly(length) if length else b""
        return first & 0x0F, unmask(payload, mask) if mask else payload

    def send(self, opcode: int, payload: bytes) -> None:
        try:
            self.writer.write(frame(opcode, payload))
        except OSError as error:
            raise WebSocketError(f"cannot write to the WebSocket: {error}") from error

    def write(self, data: bytes) -> None:
        """Send data as a text frame: the client only sends command lines."""
        self.send(TEXT, data)

    async def drain(self) -> None:
        await self.writer.drain()

    def close(self) -> None:
        """Say goodbye the WebSocket way, then close the socket."""
        with contextlib.suppress(WebSocketError, OSError):
            self.send(CLOSE, GOING_AWAY.to_bytes(2, "big"))
        self.writer.close()


def close_reason(payload: bytes) -> str:
    """The status code and the message of a close frame, for an error message."""
    if len(payload) < 2:
        return "no reason given"
    return f"{int.from_bytes(payload[:2], 'big')} {payload[2:].decode('utf-8', 'replace')}".strip()


async def connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    host: str,
    path: str,
    origin: str = "",
) -> WebSocketStream:
    """Do the opening handshake on a connected socket and return the stream."""
    client_key = key()
    writer.write(request(host, path, client_key, origin))
    await writer.drain()
    try:
        answer = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError as error:
        raise WebSocketError(
            "the server closed the connection during the WebSocket handshake"
            f" ({len(error.partial)} bytes read)"
        ) from error
    except asyncio.LimitOverrunError as error:
        raise WebSocketError(
            f"the answer to the WebSocket handshake is too long: {error}"
        ) from error
    check_answer(answer, client_key)
    return WebSocketStream(reader, writer)
