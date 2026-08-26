# pywrc

Python WeeChat Relay Client: a client for the relay of [WeeChat](https://weechat.org/),
in the terminal, written with [Textual](https://textual.textualize.io/).

It connects to the relay of a running WeeChat (the `weechat` protocol) and shows your
buffers the way WeeChat does: buflist on the left, title on top, right aligned prefixes,
nicklist on the right, status bar with the hotlist, and the input line at the bottom.

```
1.weechat         │#weechat / WeeChat, the extensible chat client
2.libera          │12:24:31        │ Mode #weechat [+nt] by zirconium.libera.chat
3.#weechat        │12:26:02   -->  │ alice (~alice@libera/user/alice) has joined #weechat
                  │12:26:44 @alice │ hello, this line is long enough to be wrapped and it stays
                  │                │ aligned under the message, like in WeeChat
                  │12:27:05    bob │ hi!
                  │[12:27] [3] [irc/libera] 3:#weechat{42} [H: 2, 4:#pywrc(3)]
                  │[me]
```

> [!NOTE]
> This is a personal project, vibecoded with [Claude](https://claude.com/claude-code): I wrote
> it for my own use, and the code is written by an LLM from my prompts. Use it if it is useful
> to you, but expect no support and no stability.

## Install

Requires Python 3.11+ and [pipx](https://pipx.pypa.io/).

```console
pipx install git+https://github.com/MrWazaby/pywrc.git
pywrc --hostname my.server --port 9000
```

Anything installing a Python application works the same way, for instance
`uv tool install git+https://github.com/MrWazaby/pywrc.git` or, from a clone,
`pipx install .`. Upgrade with `pipx upgrade pywrc` and remove it with
`pipx uninstall pywrc`.

On the WeeChat side, a relay must be listening:

```
/set relay.network.password mypassword
/relay add tls.weechat 9000
```

## Configuration

Options are read from `~/.config/pywrc/pywrc.toml`, then from the environment, then from the
command line. The password can also be given in `$PYWRC_PASSWORD`; without one, pywrc asks for
it at startup.

```toml
[relay]
hostname = "my.server"
port = 9000
password = "mypassword"
totp = ""           # if relay.network.totp_secret is set in WeeChat
tls = true
tls_verify = true   # false for the self-signed certificate of a relay
tls_cafile = ""     # or the certificate to check the relay against
lines = 200         # lines fetched per buffer at startup

websocket = true            # for a relay published by a web server (detected on its own)
websocket_path = "weechat"  # path of the URL: "wss://my.server:9000/weechat"
websocket_origin = ""       # if relay.network.websocket_allowed_origins is set in WeeChat
```

Run `pywrc --help` for the command line options.

### Relays behind a web server

A relay is often published by a web server, at an URL such as `wss://my.server/weechat`: this
is what browser clients like [Glowing Bear](https://www.glowing-bear.org/) connect to. Such an
endpoint speaks HTTP and WebSocket, never the raw relay socket, so pywrc opens a WebSocket too,
exactly like a browser does.

It is detected on its own: when the relay answers with HTTP instead of the WeeChat protocol,
pywrc reconnects through a WebSocket, on `websocket_path` (`weechat`, the path Glowing Bear
uses by default). The buffer of pywrc says which way the connection went:

```
[me] Connected to wss://my.server:9000/weechat
```

Set `websocket = true` (or `--websocket`) to go straight to it, `websocket = false` to never
do it, and `websocket_path` for another URL. If WeeChat restricts the origins of the WebSocket
clients (`/set relay.network.websocket_allowed_origins`), `websocket_origin` must be one of
them, since pywrc sends no origin by default.

## Colors

pywrc paints its screen with the colors of the WeeChat it connects to: the
`weechat.color.*` options and the colors of the title and status bars are read from the
relay, so the client looks like the WeeChat it is a client of. They are read again after
a reconnection, since the relay may be another WeeChat by then.

Any of them is set locally in `~/.config/pywrc/pywrc.toml`, where it wins over what the
relay says:

```toml
[colors]
chat_nick = "lightblue"   # any "weechat.color.*" option, with or without its prefix
chat_bg = "#303446"       # backgrounds are options of their own, as in WeeChat
status_number = "*yellow" # "*" is bold, "_" underlined, "/" italic, like in WeeChat
```

A color is a name or a palette number, as in WeeChat, or `#rrggbb` for a color no number of
the palette stands for.

### Themes

A whole `[colors]` section is a theme, and `themes/` holds a few of them, taken from the
palettes the themes publish:

| Theme | Files |
| ----- | ----- |
| [Catppuccin](https://github.com/catppuccin/catppuccin) | [Latte](themes/catppuccin-latte.toml) (light), [Frappé](themes/catppuccin-frappe.toml), [Macchiato](themes/catppuccin-macchiato.toml), [Mocha](themes/catppuccin-mocha.toml) |
| [Dracula](https://draculatheme.com/) | [dracula.toml](themes/dracula.toml) |
| [Gruvbox](https://github.com/morhetz/gruvbox) | [gruvbox-dark.toml](themes/gruvbox-dark.toml) |
| [Nord](https://www.nordtheme.com/) | [nord.toml](themes/nord.toml) |
| [Solarized](https://ethanschoonover.com/solarized/) | [solarized-dark.toml](themes/solarized-dark.toml) |
| [Tokyo Night](https://github.com/folke/tokyonight.nvim) | [tokyo-night.toml](themes/tokyo-night.toml) |

Each file is the `[colors]` section on its own, so it is copied into
`~/.config/pywrc/pywrc.toml`, or appended to a file that has no colors of its own yet:

```console
curl -fsSL https://raw.githubusercontent.com/MrWazaby/pywrc/main/themes/catppuccin-frappe.toml \
  >> ~/.config/pywrc/pywrc.toml
```

Colors are palette numbers, as they are in WeeChat: each one is the color of the terminal
closest to a color of the theme, and the comment beside it says which one it stands for, so
a color that does not please is changed by hand. The 16 basic colors are never used, since
a terminal paints those as it likes.

The background of the chat is the one color written as it is, `chat_bg = "#303446"`: the
colors of the text have the palette of the terminal to be close to, while the background of
the chat meets the background of the terminal, which no palette number is close enough to --
the 256 colors hold no dark color as colored as the background of a theme. Any color is
written that way, `#rrggbb`, where a palette number does not please; a terminal without true
colors paints the closest of the 256 it has.

The chat is painted with that background the way WeeChat paints its own with
`weechat.color.chat_bg`, and a theme that names none leaves the chat to the terminal. The
terminal is still the one to be on the background of the theme, since what is around the chat
is left to it: the title and status bars keep the colors of the bars of the remote WeeChat,
which `/set weechat.bar.title.color_bg` and `/set weechat.bar.status.color_bg` change, and the
buflist is left out of the theme, painted with the basic colors of the terminal like the
buflist of WeeChat.

## Keys

The keys are the WeeChat ones:

| Key                                  | Action                                  |
| ------------------------------------ | --------------------------------------- |
| `alt+1` … `alt+0`                    | go to buffer 1 … 10                     |
| `ctrl+n` / `ctrl+p`, `f6` / `f5`     | next / previous buffer                  |
| `alt+right` / `alt+left`             | next / previous buffer                  |
| `alt+a`                              | go to the buffer with the most activity |
| `alt+h`                              | clear the hotlist                       |
| `page up` / `page down`              | scroll the buffer                       |
| `alt+home` / `alt+end`               | scroll to the beginning / end           |
| `up` / `down`                        | previous / next command                 |
| `tab`                                | completion (done by WeeChat)            |
| `ctrl+l`                             | redraw the screen                       |
| `ctrl+c`                             | copy the selected text                  |
| `alt+enter`, `shift+enter`           | new line in the input                   |
| `ctrl+a`, `ctrl+e`, `ctrl+w`, `ctrl+u`, `ctrl+k` | edit the input line          |

The input line wraps over as many lines as it needs, like the input bar of WeeChat, and
the URLs of the chat are marked as hyperlinks: a link split over two lines stays one link
for the terminal, which opens it whole (with the modifier your terminal asks for).

Anything typed is sent to the current buffer of WeeChat, so all WeeChat commands work
(`/join`, `/query`, `/msg`, `/close`, ...). Three commands are handled by pywrc itself:

- `/buffer <number|name>` switches the displayed buffer (it does not move the buffer of
  the remote WeeChat),
- `/reconnect` drops the connection to the relay and takes it up again,
- `/quit` and `/disconnect` close pywrc, leaving WeeChat running.

## Copying and pasting

Dragging the mouse over the chat selects text, which `ctrl+c` copies: what is copied is
the line as it is displayed, time and prefix included. It goes to the clipboard of the
terminal, which works over ssh but which a number of terminals ignore, and to the one of
the system when `wl-copy`, `xclip`, `xsel` or `pbcopy` is around. The selection of the
terminal itself still works too, with the modifier it asks for, usually shift.

A paste of several lines is kept whole: the input line grows to show it and each of its
lines is sent as its own message, the way WeeChat does it. A new line can be typed with
`alt+enter` (or `shift+enter`), in the terminals that tell them apart from `enter`.

## Connection

pywrc pings the relay every 30 seconds and connects again on its own whenever the relay
goes away, waiting a little longer after each attempt (1, 2, 5, 10, 30, then 60 seconds).
The status bar says where things stand, and the buffers stay readable in the meantime:

```
[12:27] [3] [irc/libera] 3:#weechat{42} [not connected]
```

The buffers are asked again once the relay answers, since it may be another WeeChat by
then, and the buffer that was displayed comes back.

## Development

The project is managed with [uv](https://docs.astral.sh/uv/).

```console
git clone https://github.com/MrWazaby/pywrc && cd pywrc
uv sync                    # install the dependencies
uv run pywrc               # run from the sources
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pre-commit install  # install the ruff and commitizen hooks
```

Commits follow the [conventional commits](https://www.conventionalcommits.org/): commitizen
is configured in `.cz.toml` and its `commit-msg` hook rejects the messages that do not.

```console
uv run cz commit         # write a commit message with the prompt
uv run cz changelog      # regenerate CHANGELOG.md from the commits
uv run cz bump           # tag a release: version, changelog and tag
```

There is no fake relay in the tests: the unit tests cover the protocol codec, the color
codes, the state, the rendering, the configuration and the input line, and everything
else is tried against a real WeeChat:

```console
weechat-headless --dir /tmp/wc --stdout \
  -r "/set relay.network.password test" \
  -r "/set relay.network.ipv6 off" \
  -r "/relay add weechat 9001" &
uv run pywrc --hostname 127.0.0.1 --port 9001 --no-tls
```

## Layout of the code

| File          | Role                                                             |
| ------------- | ---------------------------------------------------------------- |
| `protocol.py` | decoding of the binary messages of the relay, encoding of commands |
| `client.py`   | connection, handshake, authentication, message stream             |
| `state.py`    | buffers, lines, nicks and hotlist, updated from the messages      |
| `colors.py`   | WeeChat color codes and color options, as Rich styles                                |
| `render.py`   | chat lines, buflist, nicklist and bars, laid out like WeeChat     |
| `app.py`      | the Textual application: layout, keys, input                      |
| `config.py`   | configuration file, environment and command line                  |

## License

MIT
