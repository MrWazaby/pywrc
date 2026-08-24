"""Reading of the configuration file: the relay to reach, and the colors to paint with."""

from __future__ import annotations

import pytest

from pywrc import config


def write(tmp_path, text: str):
    path = tmp_path / "pywrc.toml"
    path.write_text(text)
    return path


def test_the_relay_section_gives_the_settings(tmp_path):
    path = write(tmp_path, '[relay]\nhostname = "my.server"\nport = 9001\ntls = false\n')
    assert config.from_file(path) == {"hostname": "my.server", "port": 9001, "tls": False}
    assert config.from_file(tmp_path / "nothing.toml") == {}


def test_the_colors_section_gives_a_theme(tmp_path):
    path = write(tmp_path, '[relay]\nport = 9001\n\n[colors]\nchat_nick = "*lightblue"\n')
    assert config.from_file(path) == {"port": 9001, "colors": {"chat_nick": "*lightblue"}}


def test_what_is_no_setting_and_no_color_is_reported(tmp_path):
    path = write(tmp_path, '[relay]\nhostnam = "my.server"\n')
    with pytest.raises(SystemExit, match="unknown setting"):
        config.from_file(path)
    path = write(tmp_path, '[colors]\nchat_nicks = "red"\n')
    with pytest.raises(SystemExit, match="unknown color"):
        config.from_file(path)
