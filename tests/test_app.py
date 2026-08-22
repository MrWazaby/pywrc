"""The application itself: the input line and what a lost connection leaves behind."""

from __future__ import annotations

from pywrc.app import Pywrc
from pywrc.config import Config

VALUE = "abcdefghij" * 8
"""Longer than the input line of a screen 40 columns wide."""


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
        assert input_.size.height == input_.rows() > 1
        assert "".join(rows(app)).rstrip() == VALUE  # the whole value is displayed


async def test_the_input_line_leaves_the_rest_of_the_screen_alone():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        input_ = app.query_one("#input")
        app.set_input("x" * 1000)
        await pilot.pause()
        assert input_.size.height == 12 - type(input_).KEPT_LINES
        assert input_.rows() > input_.size.height  # more lines than the bar can show
        assert input_.scroll_offset.y == input_.rows() - input_.size.height  # the cursor is seen


async def test_clicking_a_wrapped_line_moves_the_cursor_there():
    app = pywrc()
    async with app.run_test(size=(40, 12)) as pilot:
        input_ = app.query_one("#input")
        app.set_input(VALUE)
        await pilot.pause()
        await pilot.click("#input", offset=(3, 1))
        assert input_.cursor_position == input_.content_width + 3


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
