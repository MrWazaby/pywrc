"""Configuration of the client, read from a TOML file, the environment and the CLI."""

from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass, field, fields
from getpass import getpass
from pathlib import Path

from . import colors

CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "pywrc" / "pywrc.toml"
)
PASSWORD_VARIABLE = "PYWRC_PASSWORD"


@dataclass
class Config:
    """Everything needed to reach a relay."""

    hostname: str = "localhost"
    port: int = 9000
    password: str = ""
    totp: str = ""
    tls: bool = True
    tls_verify: bool = True
    tls_cafile: str | None = None
    websocket: bool | None = None
    """Talk WebSocket, like a browser client; None tries the relay socket first."""
    websocket_path: str = "weechat"
    """Path of the WebSocket URL, the one Glowing Bear uses by default."""
    websocket_origin: str = ""
    """Origin sent with the WebSocket handshake, for relay.network.websocket_allowed_origins."""
    lines: int = 200
    """Number of lines fetched for each buffer at startup."""
    colors: dict[str, str] = field(default_factory=dict)
    """Colors of the "[colors]" section, which win over those of the remote WeeChat."""

    @property
    def address(self) -> str:
        return f"{self.hostname}:{self.port}"


def from_file(path: Path) -> dict[str, object]:
    """Read the "[relay]" and "[colors]" sections of the configuration file, if it exists."""
    if not path.exists():
        return {}
    document = tomllib.loads(path.read_text())
    settings = dict(document.get("relay", {}))
    unknown = set(settings) - {item.name for item in fields(Config)}
    if unknown:
        raise SystemExit(f"{path}: unknown setting(s): {', '.join(sorted(unknown))}")
    if theme := document.get("colors", {}):
        if unknown_colors := colors.unknown(theme):
            raise SystemExit(f"{path}: unknown color(s): {', '.join(unknown_colors)}")
        settings["colors"] = theme
    return settings


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pywrc", description="A WeeChat relay client.")
    parser.add_argument("-H", "--hostname", help="relay hostname (default: localhost)")
    parser.add_argument("-p", "--port", type=int, help="relay port (default: 9000)")
    parser.add_argument("-t", "--totp", help="time-based one-time password")
    parser.add_argument("-l", "--lines", type=int, help="lines fetched per buffer at startup")
    parser.add_argument(
        "--no-tls", dest="tls", action="store_false", default=None, help="disable TLS"
    )
    parser.add_argument(
        "--no-tls-verify",
        dest="tls_verify",
        action="store_false",
        default=None,
        help="do not verify the relay certificate (self-signed certificates)",
    )
    parser.add_argument(
        "-w",
        "--websocket",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="talk WebSocket, like a browser client (default: try the relay socket first)",
    )
    parser.add_argument("--websocket-path", help='path of the WebSocket URL (default: "weechat")')
    parser.add_argument("--websocket-origin", help="origin sent with the WebSocket handshake")
    parser.add_argument("-c", "--config", type=Path, default=CONFIG_PATH, help="configuration file")
    return parser.parse_args(argv)


def load(argv: list[str] | None = None) -> Config:
    """Build the configuration: defaults, then file, then environment, then options."""
    arguments = parse_arguments(argv)
    settings = dict(from_file(arguments.config))
    if password := os.environ.get(PASSWORD_VARIABLE):
        settings["password"] = password
    settings.update(
        {
            name: value
            for name, value in vars(arguments).items()
            if value is not None and name != "config"
        }
    )
    config = Config(**settings)
    if not config.password:
        config.password = getpass(f"Password for {config.address}: ")
    return config
