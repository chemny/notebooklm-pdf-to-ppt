#!/usr/bin/env python3
"""Smoke test for notebooklm-pdf-to-ppt release packaging.

This test validates repository structure and script syntax. It does not call
OCR engines, render PDFs, invoke image models, publish, commit, or mutate
GitHub state.
"""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "SKILL.md",
    "README.md",
    "README.en.md",
    "LICENSE",
    ".gitignore",
    "references/editable-ppt-rules.md",
    "references/editable-ppt-workflow.md",
    "references/fonts.md",
    "scripts/run_simple.py",
    "scripts/pdf_to_ppt_simple.py",
    "scripts/ocr_paddle_worker.py",
    "scripts/check_readiness.py",
    "scripts/publish_check.py",
]


def main() -> int:
    failures: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            failures.append(f"missing required file: {rel}")

    for script in sorted((ROOT / "scripts").glob("*.py")):
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"python syntax failed: {script.relative_to(ROOT)}: {exc.msg}")

    if failures:
        print("FAIL")
        for item in failures:
            print(f"- {item}")
        return 1

    print("PASS")
    print(f"checked {len(REQUIRED)} required files and Python script syntax")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
