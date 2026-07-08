"""Enable `python -m bridge ...` without installing the package.

This is the invocation the README uses so a fresh clone works with zero install
steps (the `bridge` console script from pyproject is the installed equivalent).
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
