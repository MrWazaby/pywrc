# gwrc

A [WeeChat](https://weechat.org/) relay client for the terminal, written in Python with
[Textual](https://textual.textualize.io/).

It connects to the relay of a running WeeChat (the `weechat` protocol) and shows your
buffers the way WeeChat does: buflist on the left, title on top, right aligned prefixes,
nicklist on the right, status bar with the hotlist, and the input line at the bottom.

```
1.weechat         │#weechat / WeeChat, the extensible chat client
2.libera          │12:24:31       │ Mode #weechat [+nt] by zirconium.libera.chat
3.#weechat        │12:26:02   -->  │ alice (~alice@libera/user/alice) has joined #weechat
                  │12:26:44 @alice │ hello, this line is long enough to be wrapped and it stays
                  │                │ aligned under the message, like in WeeChat
                  │12:27:05    bob │ hi!
                  │[12:27] [3] [irc/libera] 3:#weechat{42} [H: 2, 4:#gwrc(3)]
                  │[me]
```

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```console
git clone https://github.com/MrWazaby/gwrc && cd gwrc
uv sync
uv run gwrc --hostname my.server --port 9000
```

On the WeeChat side, a relay must be listening:

```
/set relay.network.password mypassword
/relay add tls.weechat 9000
```

## Configuration

Options are read from `~/.config/gwrc/gwrc.toml`, then from the environment, then from the
command line. The password can also be given in `$GWRC_PASSWORD`; without one, gwrc asks for
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
```

Run `uv run gwrc --help` for the command line options.

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

Anything typed is sent to the current buffer of WeeChat, so all WeeChat commands work
(`/join`, `/query`, `/msg`, `/close`, ...). Two commands are handled by gwrc itself:

- `/buffer <number|name>` switches the displayed buffer (it does not move the buffer of
  the remote WeeChat),
- `/quit` and `/disconnect` close gwrc, leaving WeeChat running.

## Development

```console
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pre-commit install  # ruff + commitizen hooks (commit messages)
uv run cz commit         # write a conventional commit
uv run cz bump           # bump the version and update the changelog
```

There is no fake relay in the tests: the unit tests cover the protocol codec, the color
codes and the rendering, and everything else is tried against a real WeeChat:

```console
weechat-headless --dir /tmp/wc --stdout \
  -r "/set relay.network.password test" \
  -r "/set relay.network.ipv6 off" \
  -r "/relay add weechat 9001" &
uv run gwrc --hostname 127.0.0.1 --port 9001 --no-tls
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
