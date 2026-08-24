"""Codec for the WeeChat relay protocol ("weechat" protocol).

Commands (client to relay) are plain text lines, messages (relay to client) are
binary.  See the WeeChat Relay protocol documentation for the wire format.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any

HEADER_LENGTH = 4
"""Bytes holding the total length of a message (the length includes them)."""

COMPRESSION_OFF = 0
COMPRESSION_ZLIB = 1
COMPRESSION_ZSTD = 2


class ProtocolError(Exception):
    """A message could not be decoded."""


@dataclass
class Hdata:
    """A "hda" object: items of a hdata, with the pointers leading to them."""

    path: list[str] = field(default_factory=list)
    keys: dict[str, str] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Infolist:
    """An "inl" object: the items of an infolist, under the name it goes by."""

    name: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Message:
    """A message sent by the relay: an identifier and a list of objects."""

    id: str
    objects: list[Any] = field(default_factory=list)

    @property
    def hdata(self) -> Hdata | None:
        """The first hdata of the message, if any."""
        return next((obj for obj in self.objects if isinstance(obj, Hdata)), None)

    @property
    def infolist(self) -> Infolist | None:
        """The first infolist of the message, if any."""
        return next((obj for obj in self.objects if isinstance(obj, Infolist)), None)


class _Decoder:
    """Reads objects from the (uncompressed) body of a message."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    @property
    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if count < 0 or end > len(self.data):
            raise ProtocolError(f"truncated message ({count} bytes wanted at {self.pos})")
        self.pos = end
        return self.data[end - count : end]

    def char(self) -> int:
        return int.from_bytes(self.take(1), "big", signed=True)

    def integer(self) -> int:
        return int.from_bytes(self.take(4), "big", signed=True)

    def counted_string(self) -> str:
        """A string whose length is stored on a single byte (long, pointer, time)."""
        return self.take(self.take(1)[0]).decode("utf-8", "replace")

    def long(self) -> int:
        return int(self.counted_string())

    def time(self) -> int:
        return int(self.counted_string())

    def pointer(self) -> str:
        return "0x" + self.counted_string()

    def buffer(self) -> bytes | None:
        length = self.integer()
        return None if length < 0 else self.take(length)

    def string(self) -> str | None:
        raw = self.buffer()
        return None if raw is None else raw.decode("utf-8", "replace")

    def hashtable(self) -> dict[Any, Any]:
        keys_type, values_type = self.type(), self.type()
        count = self.integer()
        return {self.object(keys_type): self.object(values_type) for _ in range(count)}

    def hdata(self) -> Hdata:
        hpath, keys = self.string(), self.string()
        count = self.integer()
        path = hpath.split("/") if hpath else []
        types = dict(key.split(":", 1) for key in keys.split(",")) if keys else {}
        items = []
        for _ in range(count):
            item: dict[str, Any] = {"__path": [self.pointer() for _ in path]}
            item.update({name: self.object(type_) for name, type_ in types.items()})
            items.append(item)
        return Hdata(path, types, items)

    def info(self) -> tuple[str | None, str | None]:
        return self.string(), self.string()

    def infolist(self) -> Infolist:
        name = self.string()
        items = []
        for _ in range(self.integer()):
            item = {}
            for _ in range(self.integer()):
                variable = self.string()
                item[variable] = self.object(self.type())
            items.append(item)
        return Infolist(name or "", items)

    def array(self) -> list[Any]:
        type_ = self.type()
        return [self.object(type_) for _ in range(self.integer())]

    def type(self) -> str:
        return self.take(3).decode("ascii", "replace")

    def object(self, type_: str) -> Any:
        try:
            read = _OBJECTS[type_]
        except KeyError:
            raise ProtocolError(f"unknown object type {type_!r}") from None
        return read(self)


_OBJECTS = {
    "chr": _Decoder.char,
    "int": _Decoder.integer,
    "lon": _Decoder.long,
    "str": _Decoder.string,
    "buf": _Decoder.buffer,
    "ptr": _Decoder.pointer,
    "tim": _Decoder.time,
    "htb": _Decoder.hashtable,
    "hda": _Decoder.hdata,
    "inf": _Decoder.info,
    "inl": _Decoder.infolist,
    "arr": _Decoder.array,
}


def decode_message(body: bytes) -> Message:
    """Decode a message body, i.e. everything after the 4 bytes of length."""
    if not body:
        raise ProtocolError("empty message")
    compression, data = body[0], body[1:]
    if compression == COMPRESSION_ZLIB:
        data = zlib.decompress(data)
    elif compression == COMPRESSION_ZSTD:
        raise ProtocolError("zstd compressed message received but zstd was not negotiated")
    elif compression != COMPRESSION_OFF:
        raise ProtocolError(f"unknown compression flag {compression}")
    decoder = _Decoder(data)
    message = Message(decoder.string() or "")
    while not decoder.eof:
        message.objects.append(decoder.object(decoder.type()))
    return message


def encode_command(command: str, message_id: str = "") -> bytes:
    """Encode a command sent to the relay."""
    prefix = f"({message_id}) " if message_id else ""
    return f"{prefix}{command}\n".encode()
