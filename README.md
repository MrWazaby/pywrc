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
| `ctrl+a`, `ctrl+e`, `ctrl+w`, `ctrl+u`, `ctrl+k` | edit the input line          |

The input line wraps over as many lines as it needs, like the input bar of WeeChat.

Anything typed is sent to the current buffer of WeeChat, so all WeeChat commands work
(`/join`, `/query`, `/msg`, `/close`, ...). Two commands are handled by pywrc itself:

- `/buffer <number|name>` switches the displayed buffer (it does not move the buffer of
  the remote WeeChat),
- `/quit` and `/disconnect` close pywrc, leaving WeeChat running.

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
codes, the state, the rendering and the input line, and everything else is tried against
a real WeeChat:

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
| `colors.py`   | WeeChat color codes to Rich styles                                |
| `render.py`   | chat lines, buflist, nicklist and bars, laid out like WeeChat     |
| `app.py`      | the Textual application: layout, keys, input                      |
| `config.py`   | configuration file, environment and command line                  |

## License

MIT
