"""Translation of WeeChat color codes into Rich styles.

Strings sent by the relay (prefixes, messages, ...) carry the color codes used
internally by WeeChat: 0x19 introduces a color, 0x1A/0x1B set/remove an
attribute and 0x1C resets everything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from rich.color import Color
from rich.style import Style
from rich.text import Text

COLOR = "\x19"
SET_ATTR = "\x1a"
REMOVE_ATTR = "\x1b"
RESET = "\x1c"

# The 17 basic WeeChat colors, in the order used by the two digits of a color code.
BASIC_COLORS = (
    "default",
    "black",
    "darkgray",
    "red",
    "lightred",
    "green",
    "lightgreen",
    "brown",
    "yellow",
    "blue",
    "lightblue",
    "magenta",
    "lightmagenta",
    "cyan",
    "lightcyan",
    "gray",
    "white",
)

_RICH_COLORS = {
    "default": None,
    "black": "black",
    "darkgray": "bright_black",
    "red": "red",
    "lightred": "bright_red",
    "green": "green",
    "lightgreen": "bright_green",
    "brown": "yellow",
    "yellow": "bright_yellow",
    "blue": "blue",
    "lightblue": "bright_blue",
    "magenta": "magenta",
    "lightmagenta": "bright_magenta",
    "cyan": "cyan",
    "lightcyan": "bright_cyan",
    "gray": "white",
    "white": "bright_white",
}

# Default value of the "weechat.color.*" options, as (foreground, background).
DEFAULTS: dict[str, tuple[str, str | None]] = {
    "separator": ("236", None),
    "chat": ("default", None),
    "chat_time": ("default", None),
    "chat_time_delimiters": ("brown", None),
    "chat_prefix_error": ("yellow", None),
    "chat_prefix_network": ("magenta", None),
    "chat_prefix_action": ("white", None),
    "chat_prefix_join": ("lightgreen", None),
    "chat_prefix_quit": ("lightred", None),
    "chat_prefix_more": ("lightmagenta", None),
    "chat_prefix_suffix": ("24", None),
    "chat_buffer": ("white", None),
    "chat_server": ("brown", None),
    "chat_channel": ("white", None),
    "chat_nick": ("lightcyan", None),
    "chat_nick_self": ("white", None),
    "chat_nick_other": ("cyan", None),
    "chat_host": ("cyan", None),
    "chat_delimiters": ("22", None),
    "chat_highlight": ("yellow", "124"),
    "chat_read_marker": ("magenta", None),
    "chat_text_found": ("yellow", None),
    "chat_value": ("cyan", None),
    "chat_prefix_buffer": ("180", None),
    "chat_tags": ("red", None),
    "chat_inactive_window": ("240", None),
    "chat_inactive_buffer": ("default", None),
    "chat_prefix_buffer_inactive_buffer": ("default", None),
    "chat_nick_offline": ("242", None),
    "chat_nick_offline_highlight": ("default", None),
    "chat_nick_prefix": ("green", None),
    "chat_nick_suffix": ("green", None),
    "emphasized": ("yellow", "236"),
    "chat_day_change": ("cyan", None),
    "chat_value_null": ("blue", None),
    "chat_status_disabled": ("red", None),
    "chat_status_enabled": ("green", None),
    "nicklist_group": ("green", None),
    "status_number": ("yellow", None),
    "status_name": ("white", None),
    "status_data_msg": ("yellow", None),
    "status_data_private": ("lightgreen", None),
    "status_data_highlight": ("lightmagenta", None),
    "status_data_other": ("default", None),
    "status_count_msg": ("brown", None),
    "status_count_private": ("green", None),
    "status_count_highlight": ("magenta", None),
    "status_count_other": ("default", None),
    "status_more": ("yellow", None),
}

OPTIONS = dict(DEFAULTS)
"""The colors in use: the defaults, until WeeChat and the configuration say otherwise."""


def _option(name: str) -> tuple[str, bool] | None:
    """The option a name points at, and whether it holds its background."""
    name = name.removeprefix("weechat.color.")
    if name.endswith("_bg") and name.removesuffix("_bg") in DEFAULTS:
        return name.removesuffix("_bg"), True
    return (name, False) if name in DEFAULTS else None


def unknown(names: Iterable[str]) -> list[str]:
    """The names that are no color of WeeChat, among those given."""
    return sorted(name for name in names if _option(name) is None)


def theme(values: Mapping[str, str]) -> None:
    """Set the colors to those values, the WeeChat defaults holding for the rest.

    Names are the "weechat.color.*" options, with or without their prefix. WeeChat keeps
    the background of an option in an option of its own, "chat_highlight_bg" holding the
    background of "chat_highlight"; the names of no interest to pywrc are left out.
    """
    OPTIONS.update(DEFAULTS)
    for name, value in values.items():
        if (option := _option(name)) is None:
            continue
        key, background = option
        foreground, bg = OPTIONS[key]
        OPTIONS[key] = (foreground, value) if background else (value, bg)


# Options addressed by the two digits of a color code, in the order of the
# t_gui_color_enum enumeration (10 obsolete nick colors sit between
# chat_nick_other and chat_host).
_INDEXED_OPTIONS = (
    "separator",
    "chat",
    "chat_time",
    "chat_time_delimiters",
    "chat_prefix_error",
    "chat_prefix_network",
    "chat_prefix_action",
    "chat_prefix_join",
    "chat_prefix_quit",
    "chat_prefix_more",
    "chat_prefix_suffix",
    "chat_buffer",
    "chat_server",
    "chat_channel",
    "chat_nick",
    "chat_nick_self",
    "chat_nick_other",
    *("chat_nick",) * 10,
    "chat_host",
    "chat_delimiters",
    "chat_highlight",
    "chat_read_marker",
    "chat_text_found",
    "chat_value",
    "chat_prefix_buffer",
    "chat_tags",
    "chat_inactive_window",
    "chat_inactive_buffer",
    "chat_prefix_buffer_inactive_buffer",
    "chat_nick_offline",
    "chat_nick_offline_highlight",
    "chat_nick_prefix",
    "chat_nick_suffix",
    "emphasized",
    "chat_day_change",
    "chat_value_null",
    "chat_status_disabled",
    "chat_status_enabled",
)

# Attributes, as the single char used in color codes or its control char.
_ATTRIBUTES = {
    "*": "bold",
    "\x01": "bold",
    "!": "reverse",
    "\x02": "reverse",
    "/": "italic",
    "\x03": "italic",
    "_": "underline",
    "\x04": "underline",
    "%": "blink",
    "\x05": "blink",
    ".": "dim",
    "\x06": "dim",
    "|": "",  # keep attributes
}


def color(spec: str | None) -> str | None:
    """Resolve a WeeChat color (name, number or option name) to a Rich color."""
    if not spec:
        return None
    if spec.startswith("weechat.color."):
        option = OPTIONS.get(spec[len("weechat.color.") :])
        return color(option[0]) if option else None
    spec = spec.lstrip("".join(_ATTRIBUTES))
    if spec.isdigit():
        number = int(spec)
        return None if number < 0 else f"color({number})"
    return _RICH_COLORS.get(spec)


def attributes(spec: str | None) -> dict[str, bool]:
    """The attributes a color carries: "*white" is bold, "_cyan" is underlined."""
    found = {}
    for char in spec or "":
        if char not in _ATTRIBUTES:
            break
        if attribute := _ATTRIBUTES[char]:
            found[attribute] = True
    return found


def style(option: str, **extra: bool) -> Style:
    """The Rich style of a "weechat.color.*" option."""
    foreground, background = OPTIONS.get(option, ("default", None))
    return Style(
        color=color(foreground), bgcolor=color(background), **{**attributes(foreground), **extra}
    )


def hexadecimal(spec: str | None) -> str | None:
    """A WeeChat color as "#rrggbb", for the parts of the screen Textual paints itself."""
    name = color(spec)
    return Color.parse(name).get_truecolor().hex if name else None


def code(option: str) -> str:
    """The color code switching to a "weechat.color.*" option."""
    return f"{COLOR}{_INDEXED_OPTIONS.index(option):02d}"


class _Parser:
    """Turns a string with WeeChat color codes into a Rich text."""

    def __init__(self, string: str) -> None:
        self.string = string
        self.pos = 0
        self.foreground: str | None = None
        self.background: str | None = None
        self.attributes: dict[str, bool] = {}

    def peek(self, count: int = 1) -> str:
        return self.string[self.pos : self.pos + count]

    def take(self, count: int) -> str:
        chars = self.peek(count)
        self.pos += len(chars)
        return chars

    def take_attributes(self) -> None:
        while self.peek() in _ATTRIBUTES:
            attribute = _ATTRIBUTES[self.take(1)]
            if attribute:
                self.attributes[attribute] = True

    def take_color(self, with_attributes: bool) -> str | None:
        """Read a color: "@" plus 5 digits (extended) or 2 digits (basic)."""
        if with_attributes:
            self.take_attributes()
        if self.peek() == "@":
            self.take(1)
            if with_attributes:
                self.take_attributes()
            return color(self.take(5))
        digits = self.take(2)
        index = int(digits) if digits.isdigit() else 0
        return color(BASIC_COLORS[index]) if index < len(BASIC_COLORS) else None

    def take_code(self) -> None:
        """Read the color code that follows a 0x19 char."""
        code = self.take(1)
        if code == "F":
            self.foreground = self.take_color(with_attributes=True)
        elif code == "B":
            self.background = self.take_color(with_attributes=False)
        elif code == "*":
            self.foreground = self.take_color(with_attributes=True)
            if self.peek() in (",", "~"):
                self.take(1)
                self.background = self.take_color(with_attributes=False)
        elif code == "@":
            self.foreground = color(self.take(5))
        elif code == "b":  # bar color, only meaningful inside bars
            self.take(1)
        elif code == RESET:
            self.foreground = self.background = None
        elif code == "E":
            self.foreground, self.background = (color(spec) for spec in OPTIONS["emphasized"])
        elif code.isdigit() and self.peek().isdigit():
            index = int(code + self.take(1))
            if index < len(_INDEXED_OPTIONS):
                foreground, background = OPTIONS[_INDEXED_OPTIONS[index]]
                self.foreground, self.background = color(foreground), color(background)

    def style(self) -> Style:
        return Style(color=self.foreground, bgcolor=self.background, **self.attributes)

    def parse(self) -> Text:
        text = Text()
        plain = []
        while self.pos < len(self.string):
            char = self.take(1)
            if char in (COLOR, SET_ATTR, REMOVE_ATTR, RESET):
                text.append("".join(plain), self.style())
                plain.clear()
            if char == COLOR:
                self.take_code()
            elif char == SET_ATTR:
                if attribute := _ATTRIBUTES.get(self.take(1)):
                    self.attributes[attribute] = True
            elif char == REMOVE_ATTR:
                self.attributes.pop(_ATTRIBUTES.get(self.take(1), ""), None)
            elif char == RESET:
                self.foreground = self.background = None
                self.attributes.clear()
            else:
                plain.append(char)
        text.append("".join(plain), self.style())
        return text


def parse(string: str | None) -> Text:
    """Convert a string with WeeChat color codes into a Rich text."""
    return _Parser(string).parse() if string else Text()


def plain(string: str | None) -> str:
    """The text of a string, without its WeeChat color codes."""
    return parse(string).plain
