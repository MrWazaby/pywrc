"""The pywrc user interface, laid out like the default WeeChat screen."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from rich.cells import get_character_cell_size
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import MouseDown, MouseMove, Paste, Resize
from textual.geometry import Region, Size
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import Input, RichLog, Static
from textual.widgets.input import Selection as InputSelection

from . import colors, render
from .client import RelayClient, RelayError
from .config import Config
from .protocol import Message
from .state import LINES, NICKLIST, NUMBERS, TITLE, Buffer, Line, State

LOCAL_BUFFER = "pywrc"
"""Buffer holding the messages of the client itself, before/without a connection."""

BUFFER_KEYS = "number,full_name,short_name,title,nicklist,local_variables"
LINE_KEYS = "date,displayed,highlight,prefix,message"

RETRY_DELAYS = (1, 2, 5, 10, 30, 60)
"""Seconds waited before connecting again, growing with the attempts that failed."""

PING_INTERVAL = 30.0
"""Seconds between two pings: a quiet relay says nothing, a dead one says nothing either."""

PING_TIMEOUT = 3 * PING_INTERVAL
"""A relay that has not answered for that long is gone, whatever its socket says."""

CONNECTING = "connecting..."
DISCONNECTED = "not connected"
"""What the status bar says while the relay is out of reach."""


class Chat(RichLog, can_focus=False):
    """The chat area: pywrc wraps the lines itself, so it is redrawn when its width changes.

    A RichLog cannot be selected with the mouse, which a chat has to be: the lines it
    displays are given the offsets Textual selects on, and the text under a selection.
    """

    width = 0

    def on_resize(self, event: Resize) -> None:
        if event.size.width != self.width:
            self.width = event.size.width
            self.app.call_after_refresh(self.app.draw_chat)  # type: ignore[attr-defined]

    def render_line(self, y: int) -> Strip:
        """Render a line of the chat, marking the part of it that is selected."""
        scroll_x, scroll_y = self.scroll_offset
        row = int(scroll_y) + y
        strip = super().render_line(y).apply_offsets(int(scroll_x), row)
        selection = self.text_selection
        span = selection.get_span(row) if selection is not None else None
        if span is None:
            return strip
        start, end = span
        length = strip.cell_length
        start, end = min(start, length), length if end == -1 else min(end, length)
        if start >= end:
            return strip
        before, selected, after = strip.divide([start, end, length])
        style = self.screen.get_component_rich_style("screen--selection")
        return Strip.join([before, selected.apply_style(style), after])

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """The text under the selection: the lines of the chat as they are displayed."""
        return selection.extract("\n".join(strip.text for strip in self.lines)), "\n"


class InputBar(Input):
    """The input line, wrapped over as many lines as it needs, like the input bar of WeeChat.

    WeeChat lets its input bar grow until the window is full, then scrolls it to keep the
    cursor in sight; a value longer than the bar is never scrolled sideways. A value can
    hold newlines, which a paste of several lines brings in.
    """

    KEPT_LINES = 3
    """Lines left to the rest of the screen when the input grows: title, chat and status bar."""

    row = 0
    """Line of the input the mouse points at: Input itself only looks at the column."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._wrapped: tuple[tuple[str, int], list[tuple[int, int]]] = (("", 0), [(0, 0)])

    @property
    def content_width(self) -> int:
        """Width the value is wrapped over: the bar itself, since it never scrolls sideways."""
        return max(self.scrollable_content_region.width, 1)

    @property
    def lines(self) -> list[tuple[int, int]]:
        """The slice of the value each line of the bar displays."""
        key = (self.value, self.content_width)
        if self._wrapped[0] != key:
            self._wrapped = (key, render.wrap(*key))
        return self._wrapped[1]

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        rows = len(render.wrap(self.value, width))
        return min(rows, max(viewport.height - self.KEPT_LINES, 1))

    def cursor_row(self) -> int:
        """The line the cursor is on, the last one it can be when two lines meet."""
        cursor = self.cursor_position
        rows = (row for row, (start, end) in enumerate(self.lines) if start <= cursor <= end)
        return max(rows, default=0)

    def measure(self) -> None:
        """Tell the widget how many lines the value takes, so that it can scroll to them."""
        self.virtual_size = Size(self.content_width, len(self.lines))

    def show_cursor(self) -> None:
        """Scroll the bar to the line the cursor is on, the way WeeChat does when it is full."""
        self.scroll_to_region(Region(0, self.cursor_row(), 1, 1), force=True, animate=False)

    def on_resize(self) -> None:
        self.measure()

    def _watch_value(self, value: str) -> None:
        super()._watch_value(value)
        self.measure()
        self.show_cursor()

    def _watch_selection(self, selection: InputSelection) -> None:
        super()._watch_selection(selection)
        self.show_cursor()

    def _on_paste(self, event: Paste) -> None:
        """Paste everything that was pasted: Input keeps the first line and drops the rest."""
        if event.text:
            self.replace(event.text, *self.selection)
        event.prevent_default()  # Input would paste the first line of it once more
        event.stop()

    def on_mouse_down(self, event: MouseDown) -> None:
        self.row = event.get_content_offset_capture(self).y

    def on_mouse_move(self, event: MouseMove) -> None:
        self.row = event.get_content_offset_capture(self).y

    def _cell_offset_to_index(self, offset: int) -> int:
        """Where the mouse points at, on the line of the bar it points at."""
        lines = self.lines
        start, end = lines[min(self.row + int(self.scroll_offset.y), len(lines) - 1)]
        cells = 0
        for index in range(start, end):
            cells += get_character_cell_size(self.value[index])
            if cells > offset:
                return index
        return end

    def render_line(self, y: int) -> Strip:
        """Render one of the lines the value is wrapped over."""
        width = self.content_width
        lines = self.lines
        row = y + int(self.scroll_offset.y)
        if row >= len(lines):
            return Strip.blank(width, self.rich_style)
        start, end = lines[row]
        text = Text(self.value[start:end], no_wrap=True, overflow="ignore", end="")
        text.pad_right(1)  # where the cursor sits at the end of a line
        if self.has_focus:
            self.mark_selection(text, start, end)
            if self._cursor_visible and row == self.cursor_row():
                cursor = self.cursor_position - start
                text.stylize(self.get_component_rich_style("input--cursor"), cursor, cursor + 1)
        options = self.app.console_options.update_width(text.cell_len)
        strip = Strip(self.app.console.render(text, options))
        return strip.crop(0, width).extend_cell_length(width).apply_style(self.rich_style)

    def mark_selection(self, text: Text, start: int, end: int) -> None:
        """Mark the part of a line that is selected, for ctrl+c to take it."""
        first, last = sorted(self.selection)
        first, last = max(first, start) - start, min(last, end) - start
        if first < last:
            text.stylize_before(self.get_component_rich_style("input--selection"), first, last)


class Sidebar(VerticalScroll, can_focus=False):
    """A bar beside the chat: it scrolls, but the focus stays on the input line."""


@dataclass
class Completion:
    """The words proposed by WeeChat for the word being completed."""

    words: list[str] = field(default_factory=list)
    start: int = 0
    end: int = 0
    text: str = ""
    """Input value produced by the completion, to detect that the user typed."""


class Pywrc(App[None]):
    """A WeeChat relay client."""

    CSS = """
    Screen { background: ansi_default; }
    #title, #status { height: 1; background: #1c1c1c; }
    #body { height: 1fr; }
    #buflist, #nicklist, #chat, #input { scrollbar-size: 0 0; }
    #buflist, #nicklist { width: auto; max-width: 25%; }
    #buflist-items, #nicklist-items { width: auto; }
    #buflist { border-right: solid #303030; }
    #nicklist { border-left: solid #303030; }
    #chat { width: 1fr; }
    #bar { height: auto; }
    #prompt { width: auto; margin-right: 1; }
    #input, #input:focus {
        border: none; padding: 0; width: 1fr; height: auto; background: ansi_default;
    }
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
        Binding("alt+enter,shift+enter", "newline", "Insert a new line", priority=True, show=False),
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
        self.connection = CONNECTING
        """What the status bar says about the connection, empty while the relay answers."""
        self.previous = ""
        """Buffer displayed before the connection dropped, to come back to it."""
        self.answered = 0.0
        """When the relay was last heard from, to notice that it stopped answering."""
        self.wakeup = asyncio.Event()
        """Set by /reconnect, to try again without waiting for the next attempt."""

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Sidebar(Static(id="buflist-items"), id="buflist")
            with Vertical(id="window"):
                yield Static(id="title")
                with Horizontal(id="body"):
                    yield Chat(id="chat", min_width=0)
                    yield Sidebar(Static(id="nicklist-items"), id="nicklist")
                yield Static(id="status")
                with Horizontal(id="bar"):
                    yield Static(id="prompt")
                    yield InputBar(id="input")

    def on_mount(self) -> None:
        self.query_one("#input", InputBar).focus()
        self.set_interval(15, self.draw_bars)
        self.set_interval(PING_INTERVAL, self.check_connection)
        self.draw()
        self.run_worker(self.relay(), name="relay", exclusive=True)

    # -- relay ---------------------------------------------------------------

    async def relay(self) -> None:
        """Keep the session connected: a relay that goes away is waited for and tried again."""
        attempt = 0
        while True:
            if attempt:
                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                self.echo(f"connecting again in {delay}s...")
                await self.wait(delay)
            # a connection that worked starts the delays over, it does not skip them:
            # a relay that keeps dropping is not worth connecting to as fast as possible
            attempt = 1 if await self.session() else attempt + 1

    async def session(self) -> bool:
        """One connection, from the handshake to the end of the messages of the relay."""
        received = 0
        self.set_connection(CONNECTING)
        self.echo(f"Connecting to {self.config.address}...")
        try:
            await self.client.connect()
        except RelayError as error:
            self.set_connection(DISCONNECTED)
            self.echo(str(error), error=True)
            return False
        try:
            self.answered = time.monotonic()  # the relay is there: it answered the handshake
            self.set_connection("")
            self.echo(f"Connected to {self.client.url}")
            self.forget()
            self.request_buffers()
            async for message in self.client.messages():
                received += 1
                self.answered = time.monotonic()
                self.handle(message)
        except RelayError as error:
            self.echo(str(error), error=True)
        finally:
            self.set_connection(DISCONNECTED)
        if not received:
            self.echo("the relay refused the connection: wrong password?", error=True)
        return bool(received)

    async def wait(self, delay: float) -> None:
        """Wait between two attempts, unless /reconnect asks for one right away."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.wakeup.wait(), delay)
        self.wakeup.clear()

    def action_reconnect(self) -> None:
        """Drop the connection and take it up again, now."""
        self.wakeup.set()
        self.client.abort()

    def check_connection(self) -> None:
        """Ping the relay, and drop a connection it has stopped answering."""
        if self.connection or not self.client.handshake:
            return  # the relays that ignore the handshake have no ping command either
        if time.monotonic() - self.answered > PING_TIMEOUT:
            self.echo(f"no answer from {self.config.address}", error=True)
            self.client.abort()  # the messages stop, and the worker connects again
            return
        self.send("ping")

    def set_connection(self, connection: str) -> None:
        """Say in the status bar where the connection stands (nothing once it is up)."""
        self.connection = connection
        if self.is_running:
            self.draw_bars()

    def forget(self) -> None:
        """Forget the buffers of the previous connection: the relay may have restarted."""
        current = self.state.current
        self.previous = (
            current.full_name if current is not None and current is not self.local else ""
        )
        self.state.buffers = {self.local.pointer: self.local}
        self.state.current = self.local
        self.draw()

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
        if not self.previous:  # the buffer WeeChat displays, when there is no previous one
            self.send("hdata window:gui_current_window/buffer full_name", "currentbuffer")
        self.send("sync")

    def request_numbers(self) -> None:
        """Ask for the numbers of every buffer: the relay only sends the one that changed."""
        self.send("hdata buffer:gui_buffers(*) number,full_name", "renumber")

    def handle(self, message: Message) -> None:
        """Update the state with a message from the relay, and redraw what changed."""
        if message.id == "completion":
            self.complete(message)
            return
        if message.id == "_upgrade_ended":  # WeeChat restarted, with new buffer pointers
            self.forget()
            self.request_buffers()
            return
        if message.id == "currentbuffer":  # the buffer displayed by WeeChat itself
            items = message.hdata.items if message.hdata else []
            self.switch_to(self.state.buffers.get(items[0]["__path"][-1]) if items else None)
            return
        added = self.added_lines(message)
        changed = self.state.handle(message)
        if NUMBERS in changed:
            self.request_numbers()
        if message.id == "listbuffers" and self.state.current is self.local:
            self.switch_to(self.displayed_buffer())
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

    def displayed_buffer(self) -> Buffer | None:
        """The buffer to come back to once the buffers are known, or the first one."""
        previous = self.state.find(self.previous) if self.previous else None
        return previous or self.first_buffer()

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
        self.query_one("#status", Static).update(render.status(self.state, self.connection))
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

    def action_newline(self) -> None:
        """Insert a newline in the input, like alt+enter does in WeeChat."""
        self.query_one("#input", InputBar).insert_text_at_cursor("\n")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        self.set_input("")
        self.completion = None
        buffer = self.state.current
        if not text or buffer is None:
            return
        buffer.history.append(text)
        self.history_index = len(buffer.history)
        lines = text.split("\n")
        if len(lines) == 1 and self.command(text):
            return
        if buffer is self.local:
            self.echo("local buffer: switch to a WeeChat buffer to send messages", error=True)
            return
        for line in lines:  # a pasted text is sent line by line, as WeeChat sends it
            if line:
                self.send(f"input {buffer.full_name} {line}")

    def command(self, text: str) -> bool:
        """Run the commands pywrc handles itself, and say whether it did."""
        command, _, argument = text.partition(" ")
        if command in ("/quit", "/disconnect"):
            self.exit()
        elif command == "/reconnect":
            self.action_reconnect()
        elif command == "/buffer" and (target := self.state.find(argument.strip())):
            self.switch_to(target)
        else:
            return False
        return True

    def action_complete(self) -> None:
        """Complete the word before the cursor, using the completion of WeeChat."""
        input_ = self.query_one("#input", InputBar)
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
        # a nick completed at the start of the input already carries
        # weechat.completion.nick_completer, and "add_space" is 0 for it
        if item.get("add_space", 1):
            words = [f"{word} " for word in words]
        self.completion = Completion(words, start, end)
        self.insert(words[0])

    def insert(self, word: str) -> None:
        """Replace the word being completed with one of the proposed words."""
        completion = self.completion
        if completion is None:
            return
        input_ = self.query_one("#input", InputBar)
        value = input_.value[: completion.start] + word + input_.value[completion.end :]
        completion.end = completion.start + len(word)
        completion.text = value
        self.set_input(value)

    def set_input(self, value: str) -> None:
        input_ = self.query_one("#input", InputBar)
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
