"""Decoding of the WeeChat color codes carried by the strings of the relay."""

from __future__ import annotations

from gwrc import colors


def styles(text) -> list[tuple[str, str]]:
    return [(text.plain[span.start : span.end], str(span.style)) for span in text.spans]


def test_basic_and_extended_colors():
    """The prefix of a nick, as sent by WeeChat: "@" in green then the nick in 142."""
    text = colors.parse("\x19F06@\x19F@00142FlashCode")
    assert text.plain == "@FlashCode"
    assert styles(text) == [("@", "bright_green"), ("FlashCode", "color(142)")]


def test_foreground_and_background():
    text = colors.parse("\x19*08,01alert\x1cplain")
    assert text.plain == "alertplain"
    assert styles(text) == [("alert", "bright_yellow on black")]  # "plain" has no style


def test_color_of_a_weechat_option():
    """A two digit code selects a "weechat.color.*" option (03: chat_time_delimiters)."""
    assert styles(colors.parse("\x1903:")) == [(":", "yellow")]
    assert styles(colors.parse("\x1929highlight")) == [("highlight", "bright_yellow on color(124)")]


def test_attributes():
    text = colors.parse("\x1a\x01bold\x1b\x01normal")
    assert text.plain == "boldnormal"
    assert styles(text) == [("bold", "bold")]


def test_reset_clears_colors_and_attributes():
    assert styles(colors.parse("\x1a\x04\x19F05under\x1cplain")) == [("under", "underline green")]


def test_plain_removes_every_code():
    assert colors.plain("\x19F06@\x19F@00142FlashCode\x1c!") == "@FlashCode!"
    assert colors.plain(None) == ""


def test_color_names():
    assert colors.color("lightblue") == "bright_blue"
    assert colors.color("142") == "color(142)"
    assert colors.color("weechat.color.chat_nick_self") == "bright_white"
    assert colors.color("default") is None


def test_code_of_an_option_can_be_parsed_back():
    assert styles(colors.parse(colors.code("chat_prefix_error") + "=!=")) == [
        ("=!=", "bright_yellow")
    ]
