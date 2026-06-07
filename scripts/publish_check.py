#!/usr/bin/env python3
"""Pre-publish safety check for notebooklm-pdf-to-ppt.

This script is a reporting gate only. It does not publish, push, commit,
delete files, or mutate GitHub state.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["SKILL.md", "README.md", "README.en.md", "LICENSE", ".gitignore"]
TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".mjs",
    ".js",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
}
IGNORE_DIRS = {".git", "__pycache__", ".venv", ".venv-paddleocr", "node_modules"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9._~/-]{16,}"),
]


def text_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in TEXT_EXTENSIONS:
            paths.append(path)
    return paths


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            failures.append(f"missing required release file: {rel}")

    skill_md = (ROOT / "SKILL.md").read_text(encoding="utf-8") if (ROOT / "SKILL.md").exists() else ""
    frontmatter = ""
    if skill_md.startswith("---") and skill_md.count("---") >= 2:
        frontmatter = skill_md.split("---", 2)[1]
    if "version:" not in frontmatter:
        warnings.append("SKILL.md frontmatter has no version field")

    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8") if (ROOT / "README.en.md").exists() else ""
    if "README.en.md" not in readme and "English" not in readme:
        warnings.append("README.md does not clearly link to README.en.md")
    if "README.md" not in readme_en and "中文" not in readme_en:
        warnings.append("README.en.md does not clearly link back to README.md")

    private_path_marker = "/" + "Users" + "/"
    private_project_marker = "Documents" + "/" + "projects"
    private_email_pattern = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

    for path in text_files():
        rel = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"skip non-utf8 file: {rel}")
            continue
        if private_path_marker in text or private_project_marker in text:
            failures.append(f"private/local path found: {rel}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible secret found: {rel}")
                break
        for email in private_email_pattern.findall(text):
            if not email.endswith("@example.com"):
                warnings.append(f"email-like value found, review manually: {rel}: {email}")

    status = "FAIL" if failures else "PASS"
    print(status)
    if failures:
        print("\nFailures:")
        for item in sorted(set(failures)):
            print(f"- {item}")
    if warnings:
        print("\nWarnings:")
        for item in sorted(set(warnings)):
            print(f"- {item}")
    if not failures and not warnings:
        print("No release blockers found.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
