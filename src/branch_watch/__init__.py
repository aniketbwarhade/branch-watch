"""Python implementation of the branch-watch CLI."""

def main() -> None:
	from .cli import main as cli_main

	cli_main()

__all__ = ["main"]
