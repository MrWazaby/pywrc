"""The application itself: the input line, copying, pasting, and a lost connection."""

from __future__ import annotations

import os

from textual.events import Paste
from textual.geometry import Offset
from textual.selection import Selection

from pywrc import colors
from pywrc.app import Pywrc
from pywrc.config import Config
from pywrc.protocol import Infolist, Message
from pywrc.state import Line

VALUE = "abcdefghij" * 8
"""Longer than the input line of a screen 40 columns wide."""

DATE = 1321993456


async def nothing() -> None:
    """What the relay worker does in the tests: there is no relay to talk to."""


def pywrc() -> Pywrc:
    app = Pywrc(Config())
    app.relay = nothing  # type: ignore[method-assign]
    return app


def rows(app: Pywrc) -> list[str]:
    """The lines the input line is displayed over."""
    input_ = app.query_one("#input")
    return [input_.render_line(y).text for y in range(input_.size.height)]


async def test_the_input_line_wraps_over_as_many_lines_as_it_needs():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        input_ = app.query_one("#input")
        app.set_input(VALUE)
        await pilot.pause()
        assert input_.size.height == len(input_.lines) > 1
        assert "".join(rows(app)).rstrip() == VALUE  # the whole value is displayed


async def test_the_input_line_leaves_the_rest_of_the_screen_alone():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        input_ = app.query_one("#input")
        app.set_input("x" * 1000)
        await pilot.pause()
        assert input_.size.height == 12 - type(input_).KEPT_LINES
        hidden = len(input_.lines) - input_.size.height
        assert hidden > 0  # more lines than the bar can show
        assert input_.scroll_offset.y == hidden  # scrolled to the last of them, where the cursor is


async def test_clicking_a_wrapped_line_moves_the_cursor_there():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        input_ = app.query_one("#input")
        app.set_input(VALUE)
        await pilot.pause()
        await pilot.click("#input", offset=(3, 1))
        assert input_.cursor_position == input_.content_width + 3


async def test_pasting_several_lines_keeps_them_all():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        input_ = app.query_one("#input")
        input_.post_message(Paste("first\nsecond\nthird"))
        await pilot.pause()
        assert input_.value == "first\nsecond\nthird"  # Input keeps the first line only
        assert [row.rstrip() for row in rows(app)] == ["first", "second", "third"]


async def test_the_chat_can_be_selected_and_copied():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        app.local.lines.append(Line(date=DATE, prefix="bob", message="hello there"))
        app.draw_chat()
        await pilot.pause()
        chat = app.query_one("#chat")
        line = chat.lines[-1].text.rstrip()
        selection = Selection(
            Offset(0, len(chat.lines) - 1), Offset(len(line), len(chat.lines) - 1)
        )
        text, _ = chat.get_selection(selection)
        assert text == line  # the line as it is displayed, prefix and time included


async def test_the_selected_part_of_the_chat_is_marked():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        for number in range(20):
            app.local.lines.append(Line(date=DATE, prefix="bob", message=f"message {number}"))
        app.draw_chat()
        await pilot.pause()
        chat = app.query_one("#chat")
        row = int(chat.scroll_offset.y) + 1
        app.screen.selections = {chat: Selection(Offset(0, row), Offset(6, row))}
        backgrounds = [
            segment.style.bgcolor for segment in chat.render_line(1) for _ in segment.text
        ]
        assert len(set(backgrounds[:6])) == 1  # the six cells under the selection stand out
        assert backgrounds[0] != backgrounds[10]


async def test_what_is_copied_goes_to_the_clipboard_of_the_system(tmp_path, monkeypatch):
    copied = tmp_path / "copied"
    clipboard = tmp_path / "wl-copy"
    clipboard.write_text(f'#!/bin/sh\ncat > "{copied}"\n')
    clipboard.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    app = pywrc()
    async with app.run_test(size=(40, 12)):
        app.copy_to_clipboard("hello there")
        assert copied.read_text() == "hello there"  # the terminal is written to as well


async def test_clicking_the_chat_leaves_the_focus_on_the_input():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        app.local.lines.append(Line(date=DATE, prefix="bob", message="hello there"))
        app.draw_chat()
        await pilot.pause()
        await pilot.click("#chat", offset=(4, 0))
        assert app.focused is app.query_one("#input")  # what is typed next still arrives


async def test_the_colors_of_the_remote_weechat_are_taken_as_they_come():
    app = pywrc()
    app.config.colors = {"chat_nick": "*lightblue"}  # the configuration wins over the relay
    async with app.run_test(size=(40, 12)) as pilot:
        app.handle(
            Message(
                "colors",
                [
                    Infolist(
                        "option",
                        [
                            {"full_name": "weechat.color.chat_nick", "value": "red"},
                            {"full_name": "weechat.color.chat_host", "value": "green"},
                        ],
                    )
                ],
            )
        )
        app.handle(Message("bars", [Infolist("bar", [{"name": "status", "color_bg": "53"}])]))
        await pilot.pause()
        assert colors.OPTIONS["chat_host"] == ("green", None)
        assert colors.OPTIONS["chat_nick"] == ("*lightblue", None)
        assert app.query_one("#status").styles.background.hex == "#5F005F"  # the 53 of WeeChat


async def test_a_lost_connection_leaves_the_buffer_to_come_back_to():
    app = pywrc()
    async with app.run_test():
        buffer = app.state.add_buffer({"__path": ["0x1"], "full_name": "irc.libera.#weechat"})
        app.state.current = buffer
        app.forget()  # the relay went away: its buffers may not come back the same
        assert app.previous == "irc.libera.#weechat"
        assert list(app.state.buffers) == [app.local.pointer]
        assert app.state.current is app.local


async def test_the_first_connection_has_no_buffer_to_come_back_to():
    app = pywrc()
    async with app.run_test():
        app.forget()
        assert app.previous == ""  # WeeChat is asked which buffer it displays instead
