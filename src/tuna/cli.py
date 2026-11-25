"""Command-line entry point."""

import sys

from tuna import __version__


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"tuna {__version__}")
    return 0
