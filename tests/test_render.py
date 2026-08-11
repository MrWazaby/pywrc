"""Layout of the chat area and of the bars."""

from __future__ import annotations

import time

from pywrc import render
from pywrc.state import HIGHLIGHT, MESSAGE, Buffer, Line, State

DATE = 1321993456


def when() -> str:
    return time.strftime(render.TIME_FORMAT, time.localtime(DATE))


def test_line_is_aligned_on_the_prefix():
    [text] = render.line(Line(date=DATE, prefix="nick", message="hello"), width=80, align=8)
    assert text.plain == f"{when()}     nick │ hello"


def test_wrapped_lines_are_aligned_under_the_message():
    item = Line(date=DATE, prefix="nick", message="aaa bbb ccc")
    lines = render.line(item, width=len(when()) + 1 + 8 + 1 + 2 + 4, align=8)
    assert [text.plain for text in lines] == [
        f"{when()}     nick │ aaa",
        " " * (len(when()) + 1 + 8 + 1) + "│ bbb",
        " " * (len(when()) + 1 + 8 + 1) + "│ ccc",
    ]


def test_line_without_date_is_not_aligned():
    [text] = render.line(Line(message="no time here"), width=80, align=8)
    assert text.plain == "no time here"


def test_prefix_column_is_the_widest_prefix():
    lines = [Line(date=DATE, prefix="a"), Line(date=DATE, prefix="\x19F05longer")]
    assert render.prefix_width(lines) == len("longer")
    assert render.prefix_width([Line(date=DATE, prefix="x" * 40)]) == render.PREFIX_ALIGN_MAX


def buffers() -> State:
    state = State()
    state.add_buffer({"__path": ["0x1"], "number": 1, "full_name": "core.weechat"})
    state.add_buffer(
        {
            "__path": ["0x2"],
            "number": 3,
            "full_name": "irc.libera.#weechat",
            "short_name": "#weechat",
            "local_variables": {"plugin": "irc", "server": "libera", "type": "channel"},
        }
    )
    state.current = state.buffers["0x1"]
    return state


def test_buflist_indents_channels_and_marks_the_current_buffer():
    lines = render.buflist(buffers())
    assert [text.plain for text in lines] == ["1.core.weechat", "3.  #weechat"]
    assert "on color(17)" in str(lines[0].spans[-1].style)


def test_status_bar_shows_the_current_buffer_and_the_hotlist():
    state = buffers()
    channel = state.buffers["0x2"]
    channel.hotlist[HIGHLIGHT] = 2
    text = render.status(state).plain
    assert f"[{time.strftime(render.ITEM_TIME_FORMAT)}] [3] [core] 1:core.weechat" in text
    assert "[H: 3:#weechat(2)]" in text


def test_hotlist_shows_only_numbers_for_messages():
    state = buffers()
    state.buffers["0x2"].hotlist[MESSAGE] = 1
    assert render.hotlist(state).plain == "[H: 3]"
    assert render.hotlist(buffers()).plain == ""


def test_nicklist_and_prompt():
    buffer = Buffer("0x2", local_variables={"nick": "me"})
    state = State()
    state.set_nicks(
        buffer,
        [
            {"__path": ["0x2", "0xg"], "group": 1, "visible": 1, "name": "000|o"},
            {"__path": ["0x2", "0xa"], "group": 0, "visible": 1, "name": "op", "prefix": "@"},
            {"__path": ["0x2", "0xb"], "group": 0, "visible": 1, "name": "Bob"},
        ],
        clear=True,
    )
    assert [text.plain for text in render.nicklist(buffer)] == ["Bob", "@op"]
    assert render.prompt(buffer).plain == "[me]"
