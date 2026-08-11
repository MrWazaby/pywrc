"""Configuration of the client, read from a TOML file, the environment and the CLI."""

from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass, fields
from getpass import getpass
from pathlib import Path

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
    lines: int = 200
    """Number of lines fetched for each buffer at startup."""

    @property
    def address(self) -> str:
        return f"{self.hostname}:{self.port}"


def from_file(path: Path) -> dict[str, object]:
    """Read the "[relay]" section of the configuration file, if it exists."""
    if not path.exists():
        return {}
    settings = tomllib.loads(path.read_text()).get("relay", {})
    known = {field.name for field in fields(Config)}
    unknown = set(settings) - known
    if unknown:
        raise SystemExit(f"{path}: unknown setting(s): {', '.join(sorted(unknown))}")
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
