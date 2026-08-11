"""State of the WeeChat session: buffers, lines, nicks and hotlist."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .protocol import Message

LOW, MESSAGE, PRIVATE, HIGHLIGHT = range(4)
"""Hotlist levels, as used by the "notify_level" of a line."""

BUFFERS, LINES, NICKLIST, TITLE = "buffers", "lines", "nicklist", "title"
"""What changed in the state, as returned by :meth:`State.handle`."""


@dataclass
class Line:
    """A line displayed in a buffer, with the WeeChat color codes it carries."""

    date: int = 0
    prefix: str = ""
    message: str = ""
    highlight: bool = False


@dataclass
class Nick:
    """A nick of a nicklist (groups are only kept to sort the nicks)."""

    name: str
    prefix: str = ""
    prefix_color: str = ""
    color: str = ""
    group: str = ""

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.group, self.name.lower()


@dataclass(eq=False)
class Buffer:
    """A buffer of the remote WeeChat (compared by identity, never by content)."""

    pointer: str
    number: int = 0
    full_name: str = ""
    short_name: str = ""
    title: str = ""
    nicklist: bool = False
    local_variables: dict[str, str] = field(default_factory=dict)
    lines: deque[Line] = field(default_factory=deque)
    nicks: dict[str, Nick] = field(default_factory=dict)
    hotlist: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    history: list[str] = field(default_factory=list)
    nicklist_requested: bool = False

    @property
    def name(self) -> str:
        return self.short_name or self.full_name

    @property
    def plugin(self) -> str:
        """The "irc/libera" part of the status bar."""
        plugin = self.local_variables.get("plugin", "core")
        server = self.local_variables.get("server")
        return f"{plugin}/{server}" if server else plugin

    @property
    def hotlist_level(self) -> int:
        """Highest level with pending activity, -1 when the buffer is read."""
        return max((level for level, count in enumerate(self.hotlist) if count), default=-1)

    def sorted_nicks(self) -> list[Nick]:
        return sorted(self.nicks.values(), key=lambda nick: nick.sort_key)


class State:
    """Buffers of the session, updated from the messages sent by the relay."""

    def __init__(self, max_lines: int = 4096) -> None:
        self.max_lines = max_lines
        self.buffers: dict[str, Buffer] = {}
        self.current: Buffer | None = None

    def sorted_buffers(self) -> list[Buffer]:
        return sorted(self.buffers.values(), key=lambda buffer: (buffer.number, buffer.full_name))

    def find(self, name: str) -> Buffer | None:
        """Find a buffer by full name, short name or number."""
        for buffer in self.sorted_buffers():
            if name in (buffer.full_name, buffer.short_name) or name == str(buffer.number):
                return buffer
        return None

    def add_buffer(self, item: dict[str, Any]) -> Buffer:
        pointer = item["__path"][-1]
        if pointer not in self.buffers:
            self.buffers[pointer] = Buffer(pointer, lines=deque(maxlen=self.max_lines))
        buffer = self.buffers[pointer]
        self.update_buffer(buffer, item)
        return buffer

    def update_buffer(self, buffer: Buffer, item: dict[str, Any]) -> None:
        for key in ("number", "full_name", "short_name", "title", "nicklist", "local_variables"):
            if (value := item.get(key)) is not None:
                setattr(buffer, key, value)

    def add_line(self, buffer: Buffer, item: dict[str, Any], newest: bool = True) -> None:
        line = Line(
            date=item.get("date") or 0,
            prefix=item.get("prefix") or "",
            message=item.get("message") or "",
            highlight=bool(item.get("highlight")),
        )
        # the deque drops the line at the other end once the buffer is full
        buffer.lines.append(line) if newest else buffer.lines.appendleft(line)

    def notify(self, buffer: Buffer, item: dict[str, Any]) -> None:
        """Add a buffer to the hotlist, like WeeChat does for the status bar."""
        if buffer is self.current:
            return
        level = HIGHLIGHT if item.get("highlight") else item.get("notify_level", MESSAGE)
        if 0 <= level <= HIGHLIGHT:
            buffer.hotlist[level] += 1

    def mark_read(self, buffer: Buffer) -> None:
        """Remove a buffer from the hotlist (it became the current one)."""
        buffer.hotlist = [0, 0, 0, 0]

    def set_nicks(self, buffer: Buffer, items: list[dict[str, Any]], clear: bool) -> None:
        """Apply a nicklist or a nicklist diff to a buffer."""
        if clear:
            buffer.nicks.clear()
        group = ""
        for item in items:
            pointer = item["__path"][-1]
            diff = chr(item["_diff"]) if "_diff" in item else "+"
            if item.get("group"):
                group = item.get("name") or ""
                continue
            if diff == "-":
                buffer.nicks.pop(pointer, None)
            elif item.get("visible"):
                buffer.nicks[pointer] = Nick(
                    name=item.get("name") or "",
                    prefix=item.get("prefix") or "",
                    prefix_color=item.get("prefix_color") or "",
                    color=item.get("color") or "",
                    group=group,
                )

    def handle(self, message: Message) -> set[str]:
        """Update the state with a message, and tell what has changed."""
        hdata = message.hdata
        if hdata is None:
            return set()
        items = hdata.items
        changed: set[str] = set()
        match message.id:
            case "listbuffers" | "_buffer_opened":
                for item in items:
                    self.add_buffer(item)
                changed.add(BUFFERS)
            case "listlines":
                for item in items:  # lines are received from the newest to the oldest
                    buffer = self.buffers.get(item["__path"][0])
                    if buffer is not None and item.get("displayed", 1):
                        self.add_line(buffer, item, newest=False)
                changed.add(LINES)
            case "_buffer_line_added":
                for item in items:
                    buffer = self.buffers.get(item.get("buffer") or item["__path"][0])
                    if buffer is None or not item.get("displayed", 1):
                        continue
                    self.add_line(buffer, item)
                    self.notify(buffer, item)
                changed.update([LINES, BUFFERS])
            case "_buffer_closing":
                for item in items:
                    self.buffers.pop(item["__path"][-1], None)
                changed.add(BUFFERS)
            case "_buffer_cleared":
                for item in items:
                    if buffer := self.buffers.get(item["__path"][-1]):
                        buffer.lines.clear()
                changed.add(LINES)
            case "_buffer_title_changed":
                for item in items:
                    if buffer := self.buffers.get(item["__path"][-1]):
                        self.update_buffer(buffer, item)
                changed.add(TITLE)
            case "nicklist" | "_nicklist" | "_nicklist_diff":
                for buffer, buffer_items in self._by_buffer(items):
                    self.set_nicks(buffer, buffer_items, clear=message.id != "_nicklist_diff")
                changed.add(NICKLIST)
            case _ if message.id.startswith("_buffer_"):
                for item in items:
                    if buffer := self.buffers.get(item["__path"][-1]):
                        self.update_buffer(buffer, item)
                changed.add(BUFFERS)
        return changed

    def _by_buffer(self, items: list[dict[str, Any]]) -> list[tuple[Buffer, list[dict[str, Any]]]]:
        """Group the items of a nicklist hdata by buffer, keeping their order."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(item["__path"][0], []).append(item)
        return [
            (buffer, buffer_items)
            for pointer, buffer_items in grouped.items()
            if (buffer := self.buffers.get(pointer))
        ]
