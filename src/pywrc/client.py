"""Connection to a WeeChat relay."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import ssl
from collections.abc import AsyncIterator

from .config import Config
from .protocol import HEADER_LENGTH, Message, decode_message, encode_command

HANDSHAKE_TIMEOUT = 5.0
"""WeeChat <= 2.8 silently ignores the handshake, so it is only waited for a while."""

PASSWORD_HASH_ALGORITHMS = ("pbkdf2+sha512", "pbkdf2+sha256", "sha512", "sha256", "plain")
COMPRESSION_TYPES = ("zlib", "off")


class RelayError(Exception):
    """The relay could not be reached, or refused the connection."""


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
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.version = ""

    async def connect(self) -> None:
        """Open the connection and authenticate."""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.config.hostname, self.config.port, ssl=self._ssl_context()
            )
        except (OSError, ssl.SSLError) as error:
            raise RelayError(f"cannot connect to {self.config.address}: {error}") from error
        await self._authenticate()

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
        handshake = await self._handshake_answer()
        self.send(f"init {self._init_options(handshake)}", message_id="init")

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
        if self.writer is None:
            raise RelayError("not connected")
        self.writer.write(encode_command(command, message_id))

    async def read_message(self) -> Message:
        """Read the next message sent by the relay."""
        if self.reader is None:
            raise RelayError("not connected")
        header = await self.reader.readexactly(HEADER_LENGTH)
        length = int.from_bytes(header, "big")
        return decode_message(await self.reader.readexactly(length - HEADER_LENGTH))

    async def messages(self) -> AsyncIterator[Message]:
        """Yield messages until the relay closes the connection."""
        try:
            while True:
                yield await self.read_message()
        except (asyncio.IncompleteReadError, EOFError, OSError) as error:
            raise RelayError(f"connection closed by {self.config.address}: {error}") from error

    async def close(self) -> None:
        """Tell the relay we are leaving and close the connection."""
        if self.writer is None:
            return
        writer, self.writer, self.reader = self.writer, None, None
        try:
            writer.write(encode_command("quit"))
            await writer.drain()
        except OSError:
            pass
        writer.close()
