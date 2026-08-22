"""Connection to a WeeChat relay."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from . import websocket
from .config import Config
from .protocol import HEADER_LENGTH, Message, decode_message, encode_command

HANDSHAKE_TIMEOUT = 5.0
"""WeeChat <= 2.8 silently ignores the handshake, so it is only waited for a while."""

PASSWORD_HASH_ALGORITHMS = ("pbkdf2+sha512", "pbkdf2+sha256", "sha512", "sha256", "plain")
COMPRESSION_TYPES = ("zlib", "off")

HTTP_ANSWER = b"HTTP"
"""First bytes of an HTTP answer, where the length of a message is expected."""

MAX_MESSAGE_LENGTH = 256 * 1024 * 1024
"""Above this, the length read is not a length but something else entirely."""

STATUS_LINE_LENGTH = 200
"""Bytes read at most to report the status line of an HTTP answer."""


class RelayError(Exception):
    """The relay could not be reached, or refused the connection."""


class HttpAnswer(RelayError):
    """The relay answered with HTTP: it is a web endpoint, expecting a WebSocket."""


class Transport(Protocol):
    """What the client needs to talk to the relay: a stream of bytes, both ways."""

    async def readexactly(self, count: int) -> bytes: ...

    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...


@dataclass
class Socket:
    """The relay socket itself: the "weechat" protocol is written on it as is."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    async def readexactly(self, count: int) -> bytes:
        return await self.reader.readexactly(count)

    def write(self, data: bytes) -> None:
        self.writer.write(data)

    async def drain(self) -> None:
        await self.writer.drain()

    def close(self) -> None:
        self.writer.close()


def hash_password(password: str, algorithm: str, salt: bytes, iterations: int) -> str:
    """Hash a password as expected by the "init" command."""
    if algorithm.startswith("pbkdf2+"):
        digest = hashlib.pbkdf2_hmac(
            algorithm.removeprefix("pbkdf2+"), password.encode(), salt, iterations
        )
    else:
        digest = hashlib.new(algorithm, salt + password.encode()).digest()
    return digest.hex()


class RelayClient:
    """Talks to a WeeChat relay: authenticates, sends commands, reads messages."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.transport: Transport | None = None
        self.websocket = False  # whether the connection goes through a WebSocket
        self.version = ""
        self.handshake: dict[str, str] = {}
        """What the relay answered to the handshake, empty for the WeeChat that ignores it."""

    @property
    def url(self) -> str:
        """Where the relay is reached, the way it is reached."""
        if not self.websocket:
            return self.config.address
        scheme = "wss" if self.config.tls else "ws"
        return f"{scheme}://{self.config.address}/{self.config.websocket_path.lstrip('/')}"

    async def connect(self) -> None:
        """Open the connection and authenticate, over a WebSocket if the relay wants one."""
        await self._open(use_websocket=self.config.websocket is True)
        try:
            await self._authenticate()
        except HttpAnswer:
            if self.config.websocket is not None:
                raise  # the transport was chosen by the user: do not guess another one
            self.abort()  # a web endpoint: connect the way a browser client does
            await self._open(use_websocket=True)
            await self._authenticate()

    async def _open(self, use_websocket: bool) -> None:
        """Connect the socket, and open a WebSocket on it when one is needed."""
        self.websocket = use_websocket
        try:
            reader, writer = await asyncio.open_connection(
                self.config.hostname, self.config.port, ssl=self._ssl_context()
            )
        except (OSError, ssl.SSLError) as error:
            raise RelayError(f"cannot connect to {self.config.address}: {error}") from error
        if not use_websocket:
            self.transport = Socket(reader, writer)
            return
        try:
            self.transport = await websocket.connect(
                reader,
                writer,
                host=self.config.address,
                path=self.config.websocket_path,
                origin=self.config.websocket_origin,
            )
        except (OSError, EOFError, websocket.WebSocketError) as error:
            writer.close()
            raise RelayError(f"cannot open {self.url}: {error}") from error

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self.config.tls:
            return None
        context = ssl.create_default_context(cafile=self.config.tls_cafile)
        if not self.config.tls_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context

    async def _authenticate(self) -> None:
        self.send(
            "handshake password_hash_algo={},compression={}".format(
                ":".join(PASSWORD_HASH_ALGORITHMS), ":".join(COMPRESSION_TYPES)
            ),
            message_id="handshake",
        )
        self.handshake = await self._handshake_answer()
        self.send(f"init {self._init_options(self.handshake)}", message_id="init")

    async def _handshake_answer(self) -> dict[str, str]:
        try:
            message = await asyncio.wait_for(self.read_message(), HANDSHAKE_TIMEOUT)
        except TimeoutError:
            return {}  # WeeChat <= 2.8: no handshake, the password is sent as plain text
        except (OSError, EOFError) as error:
            raise RelayError(f"connection lost during handshake: {error}") from error
        return next((obj for obj in message.objects if isinstance(obj, dict)), {})

    def _init_options(self, handshake: dict[str, str]) -> str:
        password = self.config.password
        options = []
        algorithm = handshake.get("password_hash_algo", "plain")
        if algorithm == "plain":
            options.append("password=" + password.replace(",", r"\,"))
        elif algorithm in PASSWORD_HASH_ALGORITHMS:
            iterations = int(handshake.get("password_hash_iterations", 100000))
            salt = bytes.fromhex(handshake.get("nonce", "")) + secrets.token_bytes(16)
            digest = hash_password(password, algorithm, salt, iterations)
            parts = [algorithm, salt.hex(), digest]
            if algorithm.startswith("pbkdf2+"):
                parts.insert(2, str(iterations))
            options.append("password_hash=" + ":".join(parts))
        else:
            raise RelayError("the relay does not support any password hash algorithm")
        if self.config.totp:
            options.append(f"totp={self.config.totp}")
        return ",".join(options)

    def send(self, command: str, message_id: str = "") -> None:
        """Send a command to the relay."""
        if self.transport is None:
            raise RelayError("not connected")
        self.transport.write(encode_command(command, message_id))

    async def read_message(self) -> Message:
        """Read the next message sent by the relay."""
        if self.transport is None:
            raise RelayError("not connected")
        header = await self.transport.readexactly(HEADER_LENGTH)
        if header == HTTP_ANSWER:
            raise HttpAnswer(
                f'{self.config.address} answered "{await self._status_line(header)}" instead of'
                " the WeeChat protocol: this is a web endpoint, waiting for a WebSocket"
                " (websocket = true, or --websocket)"
            )
        length = int.from_bytes(header, "big")
        if not HEADER_LENGTH <= length <= MAX_MESSAGE_LENGTH:
            raise RelayError(
                f"a message of {length} bytes was announced by {self.config.address}:"
                " this is not the WeeChat protocol"
            )
        return decode_message(await self.transport.readexactly(length - HEADER_LENGTH))

    async def _status_line(self, start: bytes) -> str:
        """Read the rest of the status line of an HTTP answer, to be able to report it."""
        line = bytearray(start)
        try:
            while not line.endswith(b"\r\n") and len(line) < STATUS_LINE_LENGTH:
                line += await self.transport.readexactly(1)  # type: ignore[union-attr]
        except (OSError, EOFError):
            pass  # the answer was cut short, report what was read
        return line.decode("latin-1", "replace").strip()

    async def messages(self) -> AsyncIterator[Message]:
        """Yield messages until the relay closes the connection."""
        try:
            while True:
                yield await self.read_message()
        except (asyncio.IncompleteReadError, EOFError, OSError) as error:
            raise RelayError(f"connection closed by {self.config.address}: {error}") from error

    async def close(self) -> None:
        """Tell the relay we are leaving and close the connection."""
        if self.transport is None:
            return
        transport, self.transport = self.transport, None
        try:
            transport.write(encode_command("quit"))
            await transport.drain()
        except (OSError, websocket.WebSocketError):
            pass
        transport.close()

    def abort(self) -> None:
        """Drop the connection without saying anything, and without waiting for the relay."""
        if self.transport is not None:
            transport, self.transport = self.transport, None
            transport.close()
