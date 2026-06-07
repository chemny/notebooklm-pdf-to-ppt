#!/usr/bin/env python3
"""Stable launcher for pdf_to_ppt_simple.py on local macOS Python.

Direct `python path/to/pdf_to_ppt_simple.py ...` can occasionally stall on this
machine during script startup or bytecode handling. This wrapper loads the
script text explicitly and calls main(), which has been stable in tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    script = Path(__file__).with_name("pdf_to_ppt_simple.py")
    namespace = {"__name__": "not_main", "__file__": str(script)}
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)
    sys.argv = [str(script), *sys.argv[1:]]
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
