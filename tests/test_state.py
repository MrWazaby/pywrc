"""Buffers of the session, as the messages of the relay change them."""

from __future__ import annotations

from typing import Any

from pywrc.protocol import Hdata, Message
from pywrc.state import NUMBERS, State


def buffer(pointer: str, number: int, full_name: str) -> dict[str, Any]:
    return {"__path": [pointer], "number": number, "full_name": full_name}


def message(message_id: str, *items: dict[str, Any]) -> Message:
    """A message carrying a "buffer" hdata, the way the relay sends it."""
    return Message(message_id, [Hdata(["buffer"], {}, list(items))])


def opened() -> State:
    """A session with the three buffers of a WeeChat connected to one server."""
    state = State()
    state.handle(
        message(
            "listbuffers",
            buffer("0x1", 1, "core.weechat"),
            buffer("0x2", 2, "irc.server.libera"),
            buffer("0x3", 3, "irc.libera.#weechat"),
        )
    )
    return state


def numbers(state: State) -> list[int]:
    return [item.number for item in state.sorted_buffers()]


def test_closing_a_buffer_asks_the_numbers_of_the_others_again():
    state = opened()
    changed = state.handle(message("_buffer_closing", buffer("0x2", 2, "irc.server.libera")))
    assert NUMBERS in changed
    assert "0x2" not in state.buffers


def test_moving_a_buffer_asks_the_numbers_of_the_others_again():
    state = opened()
    changed = state.handle(message("_buffer_moved", buffer("0x3", 1, "irc.libera.#weechat")))
    assert NUMBERS in changed
    assert state.buffers["0x3"].number == 1


def test_a_renamed_buffer_leaves_the_numbers_alone():
    state = opened()
    changed = state.handle(message("_buffer_renamed", buffer("0x3", 3, "irc.libera.#pywrc")))
    assert NUMBERS not in changed


def test_the_answer_renumbers_the_buffers():
    state = opened()
    state.handle(message("_buffer_closing", buffer("0x2", 2, "irc.server.libera")))
    state.handle(
        message(
            "renumber",
            buffer("0x1", 1, "core.weechat"),
            buffer("0x3", 2, "irc.libera.#weechat"),
        )
    )
    assert numbers(state) == [1, 2]


def test_the_answer_ignores_the_buffers_it_does_not_know():
    state = opened()
    state.handle(message("renumber", buffer("0x4", 4, "irc.libera.#pywrc")))
    assert "0x4" not in state.buffers


def test_a_buffer_opened_after_a_close_does_not_reuse_a_number():
    state = opened()
    state.handle(message("_buffer_closing", buffer("0x2", 2, "irc.server.libera")))
    state.handle(
        message(
            "renumber",
            buffer("0x1", 1, "core.weechat"),
            buffer("0x3", 2, "irc.libera.#weechat"),
        )
    )
    state.handle(message("_buffer_opened", buffer("0x4", 3, "irc.libera.#pywrc")))
    assert numbers(state) == [1, 2, 3]
