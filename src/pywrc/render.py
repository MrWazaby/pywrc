"""Rendering of the WeeChat screen: chat lines, buflist, nicklist and bars.

The layout follows the WeeChat defaults: right aligned prefixes separated from
the messages by "|", messages of wrapped lines aligned under each other, and
the same bar items as the default status bar.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable

from rich.console import Console
from rich.text import Text

from . import colors
from .state import HIGHLIGHT, LOW, MESSAGE, PRIVATE, Buffer, Line, State

TIME_FORMAT = "%H:%M:%S"
"""weechat.look.buffer_time_format"""

ITEM_TIME_FORMAT = "%H:%M"
"""weechat.look.item_time_format"""

PREFIX_SUFFIX = "│"
"""weechat.look.prefix_suffix"""

HOTLIST_PREFIX = "H: "
"""weechat.look.hotlist_prefix"""

HOTLIST_NAMES_COUNT = 3
"""weechat.look.hotlist_names_count"""

HOTLIST_COUNT_MIN = 2
"""weechat.look.hotlist_count_min_msg"""

PREFIX_ALIGN_MAX = 24
"""Prefixes are never given more room than this, whatever weechat.look says."""

_HOTLIST_NAMES = {LOW: "other", MESSAGE: "msg", PRIVATE: "private", HIGHLIGHT: "highlight"}
_BUFLIST_COLORS = {LOW: "white", MESSAGE: "brown", PRIVATE: "green", HIGHLIGHT: "magenta"}

_CONSOLE = Console()
"""Only used to measure text while wrapping."""


def _time(date: int) -> Text:
    """The time of a line, with delimiters colored like WeeChat does."""
    text = Text()
    for part in re.split(r"(\d+)", time.strftime(TIME_FORMAT, time.localtime(date))):
        text.append(part, colors.style("chat_time" if part.isdigit() else "chat_time_delimiters"))
    return text


def prefix_width(lines: Iterable[Line]) -> int:
    """Width of the prefix column, the longest prefix of the buffer."""
    widths = (colors.parse(line.prefix).cell_len for line in lines if line.date)
    return min(max(widths, default=0), PREFIX_ALIGN_MAX)


def line(item: Line, width: int, align: int) -> list[Text]:
    """Render a line as the list of screen lines it takes."""
    message = colors.parse(item.message)
    if not item.date:  # a line without time is not aligned
        return list(message.wrap(_CONSOLE, max(width, 1), overflow="fold"))
    prefix = colors.parse(item.prefix)
    if item.highlight:
        prefix.stylize(colors.style("chat_highlight"))
    prefix.align("right", align)
    when = _time(item.date)
    suffix = Text(PREFIX_SUFFIX + " ", colors.style("chat_prefix_suffix"))
    indent = when.cell_len + 1 + align + (1 if align else 0)
    wrapped = message.wrap(_CONSOLE, max(width - indent - suffix.cell_len, 1), overflow="fold")
    head = Text.assemble(when, " ", prefix, " " if align else "", suffix)
    screen_lines = []
    for index, chunk in enumerate(wrapped or [Text()]):
        chunk.rstrip()  # spaces at the end of a wrapped chunk are not displayed
        screen_lines.append((head if index == 0 else Text(" " * indent) + suffix) + chunk)
    return screen_lines


def chat(buffer: Buffer, width: int) -> list[Text]:
    """Render all the lines of a buffer."""
    align = prefix_width(buffer.lines)
    return [screen_line for item in buffer.lines for screen_line in line(item, width, align)]


def title(buffer: Buffer | None) -> Text:
    """The title bar: the title of the current buffer."""
    return colors.parse(buffer.title) if buffer else Text()


def buflist(state: State) -> list[Text]:
    """The buflist bar: one line per buffer, the current one highlighted."""
    lines = []
    for buffer in state.sorted_buffers():
        color = _BUFLIST_COLORS.get(buffer.hotlist_level, "default")
        indent = "  " if buffer.local_variables.get("type") in ("channel", "private") else ""
        text = Text.assemble(
            (f"{buffer.number}.", colors.color("green") or ""),
            indent,
            (buffer.name, colors.color(color) or ""),
        )
        if buffer is state.current:
            text.stylize("on color(17)")
        lines.append(text)
    return lines


def nicklist(buffer: Buffer | None) -> list[Text]:
    """The nicklist bar: the nicks of the current buffer."""
    if buffer is None:
        return []
    return [
        Text.assemble(
            (nick.prefix, colors.color(nick.prefix_color) or ""),
            (nick.name, colors.color(nick.color) or ""),
        )
        for nick in buffer.sorted_nicks()
    ]


def _item(text: Text | str, brackets: bool = False) -> Text:
    """A status bar item, optionally enclosed in delimiters."""
    delimiter = colors.style("chat_delimiters")
    item = Text(text) if isinstance(text, str) else text
    return Text.assemble(("[", delimiter), item, ("]", delimiter)) if brackets else item


def hotlist(state: State) -> Text:
    """The hotlist item: buffers with activity, sorted by priority then number."""
    buffers = [buffer for buffer in state.sorted_buffers() if buffer.hotlist_level >= 0]
    buffers.sort(key=lambda buffer: (-buffer.hotlist_level, buffer.number))
    delimiter = colors.style("chat_delimiters")
    items = []
    for index, buffer in enumerate(buffers):
        level = _HOTLIST_NAMES[buffer.hotlist_level]
        item = Text(str(buffer.number), colors.style("status_number"))
        if buffer.hotlist_level >= PRIVATE and index < HOTLIST_NAMES_COUNT:
            item.append(":", delimiter)
            item.append(buffer.name, colors.style(f"status_data_{level}"))
        if (count := buffer.hotlist[buffer.hotlist_level]) >= HOTLIST_COUNT_MIN:
            item.append("(", delimiter)
            item.append(str(count), colors.style(f"status_count_{level}"))
            item.append(")", delimiter)
        items.append(item)
    if not items:
        return Text()
    return _item(Text(HOTLIST_PREFIX) + Text(", ", delimiter).join(items), True)


def status(state: State, connection: str = "") -> Text:
    """The status bar, with the same items as the default WeeChat one.

    A connection that is not up is said there too: WeeChat has no such item, but a
    client that lost its relay has to say so somewhere.
    """
    buffer = state.current
    items = [
        _item(time.strftime(ITEM_TIME_FORMAT), True),
        _item(str(max((item.number for item in state.buffers.values()), default=0)), True),
    ]
    if buffer is not None:
        items.append(_item(buffer.plugin, True))
        current = Text.assemble(
            (str(buffer.number), colors.style("status_number")),
            (":", colors.style("chat_delimiters")),
            (buffer.name, colors.style("status_name")),
        )
        if buffer.nicks:
            current.append("{", colors.style("chat_delimiters"))
            current.append(str(len(buffer.nicks)), colors.style("status_number"))
            current.append("}", colors.style("chat_delimiters"))
        items.append(current)
    if hot := hotlist(state):
        items.append(hot)
    if connection:
        items.append(_item(Text(connection, colors.style("chat_status_disabled")), True))
    return Text(" ").join(items)


def prompt(buffer: Buffer | None) -> Text:
    """The input prompt: the nick used on the current buffer, like WeeChat."""
    nick = buffer.local_variables.get("nick", "") if buffer else ""
    if not nick:
        return Text()
    delimiter = colors.style("chat_delimiters")
    return Text.assemble(("[", delimiter), (nick, colors.style("chat_nick_self")), ("]", delimiter))
