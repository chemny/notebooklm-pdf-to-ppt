#!/usr/bin/env python3
"""Read-only readiness check for notebooklm-pdf-to-ppt.

The check reports whether the local environment can run the current
representative-page reconstruction experiments. It does not install packages,
call external model APIs, or modify files.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "README.en.md",
    "LICENSE",
    ".gitignore",
    "references/editable-ppt-workflow.md",
    "references/editable-ppt-rules.md",
    "references/fonts.md",
    "scripts/run_simple.py",
    "scripts/pdf_to_ppt_simple.py",
    "scripts/ocr_paddle_worker.py",
    "scripts/style_probe.py",
    "scripts/repair_background_with_image_model.py",
    "scripts/check_readiness.py",
    "scripts/publish_check.py",
    "scripts/smoke_test.py",
]
PYTHON_MODULES = ["PIL", "pptx", "numpy"]
OPTIONAL_PYTHON_MODULES = ["fitz", "paddleocr", "paddle"]
BINARIES = ["soffice", "pdftoppm", "pdfinfo"]


def paddle_python_candidates() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    if os.environ.get("PADDLEOCR_PYTHON"):
        candidates.append((Path(os.environ["PADDLEOCR_PYTHON"]).expanduser(), "PADDLEOCR_PYTHON"))
    candidates.extend(
        [
            (ROOT / ".venv" / "bin" / "python", "skill .venv"),
            (ROOT / ".venv-paddleocr" / "bin" / "python", "skill .venv-paddleocr"),
            (Path.cwd() / ".venv" / "bin" / "python", "cwd .venv"),
        ]
    )
    return candidates


def command_version(cmd: str, args: list[str]) -> dict[str, Any]:
    try:
        found = subprocess.run(
            ["/bin/zsh", "-lc", f"command -v {cmd}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        path = found.stdout.strip()
    except Exception:
        path = ""
    if not path:
        return {"available": False, "path": None}
    try:
        completed = subprocess.run(
            [path, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        return {"available": True, "path": path, "error": str(exc)}
    text = (completed.stdout or completed.stderr).strip().splitlines()
    return {
        "available": True,
        "path": path,
        "returncode": completed.returncode,
        "version": text[0] if text else "",
    }


def module_check(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    return {"available": spec is not None, "module": name, "origin": spec.origin if spec else None}


def main() -> int:
    required_files = []
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        required_files.append({"path": str(path), "exists": path.exists()})

    binaries = {
        "soffice": command_version("soffice", ["--version"]),
        "pdftoppm": command_version("pdftoppm", ["-v"]),
        "pdfinfo": command_version("pdfinfo", ["-v"]),
    }

    python_modules = {name: module_check(name) for name in PYTHON_MODULES}
    optional_python_modules = {name: module_check(name) for name in OPTIONAL_PYTHON_MODULES}

    model_env = {
        "VISION_API_KEY": bool(os.environ.get("VISION_API_KEY")),
        "VISION_API_BASE_URL": os.environ.get("VISION_API_BASE_URL") or "",
        "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL") or "",
    }
    paddle_candidates = paddle_python_candidates()
    paddle_python = next((path for path, _source in paddle_candidates if path.exists()), paddle_candidates[0][0])
    paddle_source = next((source for path, source in paddle_candidates if path == paddle_python), paddle_candidates[0][1])
    paddle_runtime = {
        "path": str(paddle_python),
        "exists": paddle_python.exists(),
        "source": paddle_source,
        "candidates": [{"path": str(path), "source": source, "exists": path.exists()} for path, source in paddle_candidates],
    }

    blockers = []
    for item in required_files:
        if not item["exists"]:
            blockers.append(f"missing file: {item['path']}")
    for name, result in python_modules.items():
        if not result["available"]:
            blockers.append(f"missing python module: {name}")
    for name in ("soffice", "pdftoppm"):
        if not binaries[name]["available"]:
            blockers.append(f"missing binary: {name}")

    payload = {
        "ok": not blockers,
        "skill_root": str(ROOT),
        "python": sys.executable,
        "required_files": required_files,
        "python_modules": python_modules,
        "optional_python_modules": optional_python_modules,
        "binaries": binaries,
        "paddle_runtime": paddle_runtime,
        "model_env": model_env,
        "blockers": blockers,
        "notes": [
            "Default simple flow uses run_simple.py -> pdf_to_ppt_simple.py -> ocr_paddle_worker.py.",
            "PaddleOCR is the default and only OCR path for the current main flow when paddle_runtime exists.",
            "VISION_API_KEY is required only for model-based parsing or background cleanup.",
            "This check is read-only and does not validate model API credentials.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
