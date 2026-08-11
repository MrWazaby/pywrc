"""Entry point of the client."""

from __future__ import annotations

from .app import Pywrc
from .config import load


def main() -> None:
    Pywrc(load()).run()


if __name__ == "__main__":
    main()
