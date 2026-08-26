"""Decoding of the WeeChat color codes carried by the strings of the relay."""

from __future__ import annotations

from rich.style import Style

from pywrc import colors


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


def test_a_theme_sets_the_colors_and_their_backgrounds():
    colors.theme({"weechat.color.chat_nick": "red", "chat_highlight_bg": "52"})
    assert colors.OPTIONS["chat_nick"] == ("red", None)
    assert colors.OPTIONS["chat_highlight"] == ("yellow", "52")  # WeeChat keeps them apart
    assert colors.style("chat_nick") == Style(color="red")


def test_a_theme_leaves_the_defaults_to_what_it_does_not_name():
    colors.theme({"chat_nick": "red"})
    colors.theme({"chat_host": "blue"})
    assert colors.OPTIONS["chat_nick"] == colors.DEFAULTS["chat_nick"]
    assert colors.OPTIONS["chat_host"] == ("blue", None)


def test_the_names_of_no_color_are_told_apart():
    assert colors.unknown(["chat_nick", "weechat.color.chat_nick", "chat_highlight_bg"]) == []
    assert colors.unknown(["chat_nicks", "look.buffer_time_format"]) == [
        "chat_nicks",
        "look.buffer_time_format",
    ]


def test_a_color_carries_the_attributes_of_weechat():
    colors.theme({"chat_nick": "*_yellow"})
    assert colors.style("chat_nick") == Style(color="bright_yellow", bold=True, underline=True)


def test_a_color_is_written_as_it_is_when_no_palette_number_stands_for_it():
    """A theme names the color it is really on with "#rrggbb", which WeeChat has no room for."""
    colors.theme({"chat_bg": "#303446", "chat_nick": "*#8caaee"})
    assert colors.style("chat") == Style(bgcolor="#303446")
    assert colors.style("chat_nick") == Style(color="#8caaee", bold=True)
    assert colors.color("#30344") is None  # too short to be one


def test_the_colors_textual_paints_itself_are_given_to_it_as_they_are():
    """A palette number is the color it stands for, a basic color the one of the terminal."""
    assert colors.painted("234").hex == "#1C1C1C"
    assert colors.painted("red").ansi == 1  # the red of the terminal, whatever it paints it
    assert colors.painted("default") == colors.TERMINAL
    assert colors.painted("#303446").hex == "#303446"  # the color of a theme, untouched
