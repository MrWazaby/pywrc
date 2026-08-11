"""Entry point of the client."""

from __future__ import annotations

from .app import Gwrc
from .config import load


def main() -> None:
    Gwrc(load()).run()


if __name__ == "__main__":
    main()
