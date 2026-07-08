"""Compatibility wrapper around the application-layer workflow."""

from ..application.workflow import AIWorkflow, load_generate_all_figures
from ..cli import build_parser, main

__all__ = ["AIWorkflow", "build_parser", "load_generate_all_figures", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
