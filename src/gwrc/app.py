"""The gwrc user interface, laid out like the default WeeChat screen."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.widgets import Input, RichLog, Static

from . import colors, render
from .client import RelayClient, RelayError
from .config import Config
from .protocol import Message
from .state import LINES, NICKLIST, TITLE, Buffer, Line, State

LOCAL_BUFFER = "gwrc"
"""Buffer holding the messages of the client itself, before/without a connection."""

BUFFER_KEYS = "number,full_name,short_name,title,nicklist,local_variables"
LINE_KEYS = "date,displayed,highlight,prefix,message"


class Chat(RichLog):
    """The chat area: gwrc wraps the lines itself, so it is redrawn when its width changes."""

    width = 0

    def on_resize(self, event: Resize) -> None:
        if event.size.width != self.width:
            self.width = event.size.width
            self.app.call_after_refresh(self.app.draw_chat)  # type: ignore[attr-defined]


@dataclass
class Completion:
    """The words proposed by WeeChat for the word being completed."""

    words: list[str] = field(default_factory=list)
    start: int = 0
    end: int = 0
    text: str = ""
    """Input value produced by the completion, to detect that the user typed."""


class Gwrc(App[None]):
    """A WeeChat relay client."""

    CSS = """
    Screen { background: ansi_default; }
    #title, #status { height: 1; background: #1c1c1c; }
    #body { height: 1fr; }
    #buflist, #nicklist, #chat { scrollbar-size: 0 0; }
    #buflist, #nicklist { width: auto; max-width: 25%; }
    #buflist-items, #nicklist-items { width: auto; }
    #buflist { border-right: solid #303030; }
    #nicklist { border-left: solid #303030; }
    #chat { width: 1fr; }
    #bar { height: 1; }
    #prompt { width: auto; margin-right: 1; }
    #input, #input:focus { border: none; padding: 0; height: 1; background: ansi_default; }
    """

    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar = [
        Binding("tab", "complete", "Complete", priority=True, show=False),
        Binding("ctrl+n,alt+right,alt+down,f6", "switch(1)", "Next buffer", show=False),
        Binding("ctrl+p,alt+left,alt+up,f5", "switch(-1)", "Previous buffer", show=False),
        *(
            Binding(f"alt+{key}", f"goto({number})", "Go to buffer", show=False)
            for number, key in enumerate("1234567890", 1)
        ),
        Binding("alt+a", "activity", "Next buffer with activity", show=False),
        Binding("alt+h", "read", "Clear the hotlist", show=False),
        Binding("pageup", "scroll(-1)", "Scroll up", show=False),
        Binding("pagedown", "scroll(1)", "Scroll down", show=False),
        Binding("alt+home", "scroll_end(0)", "Scroll to the top", show=False),
        Binding("alt+end", "scroll_end(1)", "Scroll to the bottom", show=False),
        Binding("up", "history(-1)", "Previous command", show=False),
        Binding("down", "history(1)", "Next command", show=False),
        Binding("ctrl+l", "redraw", "Refresh the screen", show=False),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__(ansi_color=True)  # keep the colors and the background of the terminal
        self.config = config
        self.client = RelayClient(config)
        self.state = State()
        self.local = self.state.add_buffer({"__path": [LOCAL_BUFFER], "full_name": LOCAL_BUFFER})
        self.state.current = self.local
        self.history_index = 0
        self.completion: Completion | None = None
        self.messages_received = 0

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield VerticalScroll(Static(id="buflist-items"), id="buflist")
            with Vertical(id="window"):
                yield Static(id="title")
                with Horizontal(id="body"):
                    yield Chat(id="chat", min_width=0)
                    yield VerticalScroll(Static(id="nicklist-items"), id="nicklist")
                yield Static(id="status")
                with Horizontal(id="bar"):
                    yield Static(id="prompt")
                    yield Input(id="input")

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        self.set_interval(15, self.draw_bars)
        self.draw()
        self.echo(f"Connecting to {self.config.address}...")
        self.run_worker(self.relay(), name="relay", exclusive=True)

    # -- relay ---------------------------------------------------------------

    async def relay(self) -> None:
        """Connect to the relay, then dispatch its messages until it closes."""
        try:
            await self.client.connect()
            self.request_buffers()
            async for message in self.client.messages():
                self.messages_received += 1
                self.handle(message)
        except RelayError as error:
            self.echo(str(error), error=True)
            if not self.messages_received:
                self.echo("the relay refused the connection: wrong password?", error=True)

    def send(self, command: str, message_id: str = "") -> None:
        """Send a command to the relay, saying so when the connection is gone."""
        try:
            self.client.send(command, message_id)
        except RelayError as error:
            self.echo(str(error), error=True)

    def request_buffers(self) -> None:
        """Ask for the buffers and their last lines, then keep in sync."""
        self.send(f"hdata buffer:gui_buffers(*) {BUFFER_KEYS}", "listbuffers")
        self.send(
            f"hdata buffer:gui_buffers(*)/own_lines/last_line(-{self.config.lines})/data"
            f" {LINE_KEYS}",
            "listlines",
        )
        self.send("hdata window:gui_current_window/buffer full_name", "currentbuffer")
        self.send("sync")

    def handle(self, message: Message) -> None:
        """Update the state with a message from the relay, and redraw what changed."""
        if message.id == "completion":
            self.complete(message)
            return
        if message.id == "_upgrade_ended":
            self.request_buffers()
            return
        if message.id == "currentbuffer":  # the buffer displayed by WeeChat itself
            items = message.hdata.items if message.hdata else []
            self.switch_to(self.state.buffers.get(items[0]["__path"][-1]) if items else None)
            return
        added = self.added_lines(message)
        changed = self.state.handle(message)
        if message.id == "listbuffers" and self.state.current is self.local:
            self.switch_to(self.first_buffer())
        elif added:
            self.append_lines(added)
        elif LINES in changed:
            self.draw_chat()
        if changed:
            self.draw_bars()
        if NICKLIST in changed:
            self.draw_nicklist()
        if TITLE in changed:
            self.draw_title()

    def added_lines(self, message: Message) -> int:
        """Number of lines this message appends to the current buffer."""
        if message.id != "_buffer_line_added" or message.hdata is None:
            return 0
        return sum(
            self.buffer_of(item) is self.state.current and bool(item.get("displayed", 1))
            for item in message.hdata.items
        )

    def buffer_of(self, item: dict[str, Any]) -> Buffer | None:
        return self.state.buffers.get(item.get("buffer") or item["__path"][0])

    def first_buffer(self) -> Buffer | None:
        """The first buffer of WeeChat, the local one excluded."""
        return next(
            (buffer for buffer in self.state.sorted_buffers() if buffer is not self.local), None
        )

    def echo(self, text: str, error: bool = False) -> None:
        """Write a message of the client itself in the local buffer."""
        prefix = "=!=" if error else "--"
        option = "chat_prefix_error" if error else "chat_prefix_network"
        self.local.lines.append(
            Line(date=int(time.time()), prefix=colors.code(option) + prefix, message=text)
        )
        if self.state.current is self.local and self.is_running:
            self.draw_chat()

    # -- drawing -------------------------------------------------------------

    def draw(self) -> None:
        self.draw_title()
        self.draw_chat()
        self.draw_nicklist()
        self.draw_bars()

    def draw_title(self) -> None:
        self.query_one("#title", Static).update(render.title(self.state.current))

    def draw_bars(self) -> None:
        self.query_one("#buflist-items", Static).update(_join(render.buflist(self.state)))
        self.query_one("#status", Static).update(render.status(self.state))
        self.query_one("#prompt", Static).update(render.prompt(self.state.current))

    def draw_nicklist(self) -> None:
        buffer = self.state.current
        self.query_one("#nicklist-items", Static).update(_join(render.nicklist(buffer)))
        self.query_one("#nicklist").display = bool(buffer and buffer.nicks)

    def draw_chat(self) -> None:
        """Redraw the whole chat area (buffer switch, resize, ...)."""
        chat = self.query_one("#chat", Chat)
        chat.clear()
        chat.auto_scroll = True
        if self.state.current is not None:
            self.write(chat, render.chat(self.state.current, self.chat_width))

    def append_lines(self, count: int) -> None:
        """Add the last lines of the current buffer at the end of the chat area."""
        buffer = self.state.current
        if buffer is None:
            return
        lines = list(buffer.lines)[-count:]
        align = render.prefix_width(buffer.lines)
        if any(colors.parse(item.prefix).cell_len > align for item in lines):
            self.draw_chat()  # the prefix column grew: every line moves
            return
        chat = self.query_one("#chat", Chat)
        chat.auto_scroll = chat.is_vertical_scroll_end
        for item in lines:
            self.write(chat, render.line(item, self.chat_width, align))

    def write(self, chat: Chat, lines: list[Text]) -> None:
        if lines:
            chat.write(_join(lines), width=self.chat_width)

    @property
    def chat_width(self) -> int:
        return max(self.query_one("#chat", Chat).scrollable_content_region.width, 1)

    # -- buffers -------------------------------------------------------------

    def switch_to(self, buffer: Buffer | None) -> None:
        if buffer is None or buffer is self.state.current:
            return
        self.state.current = buffer
        self.state.mark_read(buffer)
        if buffer.nicklist and not buffer.nicklist_requested:
            buffer.nicklist_requested = True
            self.send(f"nicklist {buffer.full_name}", "nicklist")
        self.history_index = len(buffer.history)
        self.draw()

    def action_switch(self, offset: int) -> None:
        buffers = self.state.sorted_buffers()
        if self.state.current in buffers:
            self.switch_to(buffers[(buffers.index(self.state.current) + offset) % len(buffers)])

    def action_goto(self, number: int) -> None:
        self.switch_to(self.state.find(str(number)))

    def action_activity(self) -> None:
        """Jump to the buffer with the highest activity, like alt+a in WeeChat."""
        buffers = [buffer for buffer in self.state.sorted_buffers() if buffer.hotlist_level >= 0]
        if buffers:
            self.switch_to(max(buffers, key=lambda buffer: (buffer.hotlist_level, -buffer.number)))

    def action_read(self) -> None:
        for buffer in self.state.buffers.values():
            self.state.mark_read(buffer)
        self.draw_bars()

    def action_scroll(self, direction: int) -> None:
        chat = self.query_one("#chat", Chat)
        chat.scroll_page_down() if direction > 0 else chat.scroll_page_up()

    def action_scroll_end(self, end: int) -> None:
        chat = self.query_one("#chat", Chat)
        chat.scroll_end() if end else chat.scroll_home()

    def action_redraw(self) -> None:
        self.draw()

    # -- input ---------------------------------------------------------------

    def action_history(self, direction: int) -> None:
        buffer = self.state.current
        if buffer is None or not buffer.history:
            return
        self.history_index = max(0, min(len(buffer.history), self.history_index + direction))
        history = [*buffer.history, ""]
        self.set_input(history[self.history_index])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        self.set_input("")
        self.completion = None
        buffer = self.state.current
        if not text or buffer is None:
            return
        buffer.history.append(text)
        self.history_index = len(buffer.history)
        command, _, argument = text.partition(" ")
        if command in ("/quit", "/disconnect"):
            self.exit()
        elif command == "/buffer" and (target := self.state.find(argument.strip())):
            self.switch_to(target)
        elif buffer is self.local:
            self.echo("local buffer: switch to a WeeChat buffer to send messages", error=True)
        else:
            self.send(f"input {buffer.full_name} {text}")

    def action_complete(self) -> None:
        """Complete the word before the cursor, using the completion of WeeChat."""
        input_ = self.query_one("#input", Input)
        buffer = self.state.current
        if buffer is None or buffer is self.local:
            return
        if self.completion is not None:  # cycle through the words, like WeeChat does
            self.completion.words.append(self.completion.words.pop(0))
            self.insert(self.completion.words[0])
            return
        self.send(
            f"completion {buffer.full_name} {input_.cursor_position} {input_.value}", "completion"
        )

    def complete(self, message: Message) -> None:
        """Apply the completion sent by the relay."""
        items = message.hdata.items if message.hdata else []
        if not items or not (words := items[0].get("list") or []):
            return
        item = items[0]
        start, end = item.get("pos_start", 0), item.get("pos_end", -1) + 1
        if start == 0 and item.get("context") == "auto":
            words = [f"{word}: " for word in words]  # weechat.completion.nick_completer
        elif item.get("add_space", 1):
            words = [f"{word} " for word in words]
        self.completion = Completion(words, start, end)
        self.insert(words[0])

    def insert(self, word: str) -> None:
        """Replace the word being completed with one of the proposed words."""
        completion = self.completion
        if completion is None:
            return
        input_ = self.query_one("#input", Input)
        value = input_.value[: completion.start] + word + input_.value[completion.end :]
        completion.end = completion.start + len(word)
        completion.text = value
        self.set_input(value)

    def set_input(self, value: str) -> None:
        input_ = self.query_one("#input", Input)
        input_.value = value
        input_.cursor_position = len(value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.completion is not None and event.value != self.completion.text:
            self.completion = None

    async def on_unmount(self) -> None:
        await self.client.close()


def _join(lines: list[Text]) -> Text:
    """Gather rendered lines into a single renderable."""
    return Text("\n").join(lines)
