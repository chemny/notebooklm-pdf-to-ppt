#!/usr/bin/env python3
"""Read-only readiness check for notebooklm-pdf-to-ppt.

The check reports whether the local environment can run the current
representative-page reconstruction experiments. It does not install packages,
call external model APIs, or modify files.
"""

from __future__ import annotations

import argparse
import importlib.metadata
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
CORE_BINARIES = ["pdftoppm", "pdfinfo"]
OPTIONAL_PYTHON_MODULES = []
MODULE_DISTRIBUTIONS = {
    "PIL": "Pillow",
    "pptx": "python-pptx",
    "numpy": "numpy",
}


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
    if spec is None:
        return {"available": False, "module": name, "origin": None}
    version = ""
    distribution = MODULE_DISTRIBUTIONS.get(name, name)
    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = ""
    return {
        "available": True,
        "module": name,
        "origin": spec.origin,
        "distribution": distribution,
        "version": version,
    }


def subprocess_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def paddle_startup_check(python: Path, timeout: int) -> dict[str, Any]:
    if not python.exists():
        return {"ok": False, "reason": "missing", "timeout": timeout}
    try:
        completed = subprocess.run(
            [str(python), "-S", "-c", "import sys; print(sys.executable)"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "reason": "timeout",
            "timeout": timeout,
            "stderr": subprocess_text(exc.stderr)[-1000:],
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        return {"ok": False, "reason": "error", "timeout": timeout, "error": str(exc)}
    return {
        "ok": True,
        "timeout": timeout,
        "stdout": completed.stdout.strip(),
    }


def paddle_smoke_check(python: Path, image: Path, timeout: int) -> dict[str, Any]:
    if not image.exists():
        return {"ok": False, "reason": "missing_image", "image": str(image)}
    worker = ROOT / "scripts" / "ocr_paddle_worker.py"
    payload = json.dumps({"images": [{"page_number": 1, "image": str(image)}]}, ensure_ascii=False)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        completed = subprocess.run(
            [str(python), str(worker)],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "reason": "timeout",
            "timeout": timeout,
            "stderr": subprocess_text(exc.stderr)[-2000:],
        }
    except subprocess.CalledProcessError as exc:
        return {
            "ok": False,
            "reason": "worker_failed",
            "returncode": exc.returncode,
            "stderr": subprocess_text(exc.stderr)[-4000:],
            "stdout": subprocess_text(exc.stdout)[-1000:],
        }
    lines = completed.stdout.splitlines()
    json_line = next((line.strip() for line in reversed(lines) if line.strip().startswith("{")), "")
    if not json_line:
        return {
            "ok": False,
            "reason": "no_json",
            "stderr": completed.stderr[-2000:],
            "stdout": completed.stdout[-1000:],
        }
    try:
        data = json.loads(json_line)
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": "bad_json", "error": str(exc), "stdout": completed.stdout[-1000:]}
    slides = data.get("slides") or []
    text_count = sum(len(slide.get("texts") or []) for slide in slides)
    return {
        "ok": bool(data.get("ok")),
        "image": str(image),
        "timeout": timeout,
        "slides": len(slides),
        "text_nodes": text_count,
        "stderr_tail": completed.stderr[-1000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only readiness check for notebooklm-pdf-to-ppt")
    parser.add_argument("--ocr-startup-timeout", type=int, default=10)
    parser.add_argument("--ocr-smoke-image")
    parser.add_argument("--ocr-smoke-timeout", type=int, default=120)
    args = parser.parse_args()

    required_files = []
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        required_files.append({"path": str(path), "exists": path.exists()})

    binaries = {
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
    paddle_runtime["startup_check"] = paddle_startup_check(paddle_python, args.ocr_startup_timeout)
    if args.ocr_smoke_image:
        paddle_runtime["smoke_check"] = paddle_smoke_check(
            paddle_python,
            Path(args.ocr_smoke_image).expanduser().resolve(),
            args.ocr_smoke_timeout,
        )

    blockers = []
    for item in required_files:
        if not item["exists"]:
            blockers.append(f"missing file: {item['path']}")
    for name, result in python_modules.items():
        if not result["available"]:
            blockers.append(f"missing python module: {name}")
    for name in CORE_BINARIES:
        if not binaries[name]["available"]:
            blockers.append(f"missing binary: {name}")
    if not paddle_runtime["exists"]:
        blockers.append("missing PaddleOCR Python runtime: set PADDLEOCR_PYTHON or create .venv-paddleocr")
    elif not paddle_runtime["startup_check"]["ok"]:
        blockers.append(f"PaddleOCR Python runtime startup failed: {paddle_runtime['startup_check']}")
    if "smoke_check" in paddle_runtime and not paddle_runtime["smoke_check"]["ok"]:
        blockers.append(f"PaddleOCR smoke check failed: {paddle_runtime['smoke_check']}")

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
