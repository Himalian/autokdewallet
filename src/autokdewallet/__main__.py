"""Command-line entry point: ``python -m autokdewallet``."""

from .unlock import main

if __name__ == "__main__":
    raise SystemExit(main())
