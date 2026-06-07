#!/usr/bin/env python3
"""Run the editable PPT v2 representative-page pipeline end to end."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageChops, ImageStat


SCRIPT_DIR = Path(__file__).resolve().parent


def run(cmd: list[str], env: dict[str, str] | None = None) -> dict[str, Any] | None:
    print("+ " + " ".join(cmd), file=sys.stderr)
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if proc.stdout:
        print(proc.stdout, file=sys.stderr)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    text = proc.stdout.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_args(args: argparse.Namespace) -> list[str]:
    if args.pptx:
        return ["--pptx", str(Path(args.pptx).expanduser().resolve())]
    return ["--pdf", str(Path(args.pdf).expanduser().resolve())]


def clean_map(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"clean background mapping must be slide=image: {value}")
        key, path = value.split("=", 1)
        mapping[key.strip()] = str(Path(path).expanduser().resolve())
    return mapping


def slide_name(path: str) -> str:
    return Path(path).name


def build_clean_background_maps(clean_layout: Path, overrides: dict[str, str]) -> list[str]:
    layout = load_json(clean_layout)
    mappings: dict[str, str] = {}
    for slide in layout.get("slides", []):
        key = slide_name(slide["image"])
        if slide.get("clean_background"):
            mappings[key] = slide["clean_background"]
    mappings.update(overrides)
    return [f"{key}={value}" for key, value in sorted(mappings.items())]


def render_pptx_to_previews(pptx: Path, preview_dir: Path) -> Path:
    preview_dir.mkdir(parents=True, exist_ok=True)
    run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(preview_dir), str(pptx)])
    pdf = preview_dir / f"{pptx.stem}.pdf"
    if not pdf.exists():
        candidates = sorted(preview_dir.glob("*.pdf"))
        if not candidates:
            raise FileNotFoundError(f"no PDF produced in {preview_dir}")
        pdf = candidates[-1]
    with fitz.open(pdf) as doc:
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(preview_dir / f"preview_{idx:03d}.png")
    return pdf


def diff_score(original: Path, preview: Path) -> dict[str, Any]:
    base = Image.open(original).convert("RGB")
    img = Image.open(preview).convert("RGB").resize(base.size)
    diff = ImageChops.difference(base, img)
    stat = ImageStat.Stat(diff)
    mae = sum(stat.mean) / 3
    rms = (sum(v * v for v in stat.rms) / 3) ** 0.5
    hist = diff.convert("L").histogram()
    total = base.size[0] * base.size[1]
    changed = sum(hist[25:]) / total * 100
    return {
        "original": str(original),
        "preview": str(preview),
        "width": base.size[0],
        "height": base.size[1],
        "mae": round(mae, 4),
        "rms": round(rms, 4),
        "changed_pixels_gt_25_pct": round(changed, 4),
    }


def element_counts(layout_path: Path) -> list[dict[str, Any]]:
    layout = load_json(layout_path)
    rows = []
    for idx, slide in enumerate(layout.get("slides", []), start=1):
        counts = {"text": 0, "shape": 0, "image": 0}
        for element in slide.get("elements", []):
            typ = str(element.get("type") or "").lower()
            if typ in counts:
                counts[typ] += 1
        rows.append(
            {
                "index": idx,
                "image": slide.get("image"),
                "page_type": slide.get("page_type"),
                "text_nodes": counts["text"],
                "shape_nodes": counts["shape"],
                "image_nodes": counts["image"],
            }
        )
    return rows


def background_qa_by_page(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    qa = report.get("background_text_qa") or {}
    return {int(row["page"]): row for row in qa.get("pages", []) if row.get("page") is not None}


def build_recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    by_page = {row["index"]: row for row in report.get("element_counts", [])}
    bg_qa = background_qa_by_page(report)
    recommendations: list[dict[str, Any]] = []
    mode = report.get("background_mode")
    for score in report.get("scores", []):
        page = int(score["page"])
        info = by_page.get(page, {})
        page_type = info.get("page_type") or "unknown"
        changed = float(score.get("changed_pixels_gt_25_pct", 0))
        mae = float(score.get("mae", 0))
        issues: list[str] = []
        actions: list[str] = []

        if changed >= 15 or mae >= 22:
            issues.append("high visual difference")
        elif changed >= 10 or mae >= 16:
            issues.append("medium visual difference")

        residual = bg_qa.get(page)
        if residual and residual.get("residual_text_detected"):
            issues.append("background still contains OCR-detectable old text")
            actions.append("run image-model local repair for masked text regions before final conversion")

        if mode in {"original", "original-debug"}:
            issues.append("visible editable text may duplicate existing background text")
            if page_type in {"text", "card"}:
                actions.append("try page-specific clean_background before visible text overlay")
            if page_type in {"diagram", "data", "image", "mixed"}:
                actions.append("preserve key visuals; avoid global clean-text; use local masks or keep fewer visible overlays")
        elif mode == "local-clean":
            if page_type in {"diagram", "data", "image", "mixed"}:
                issues.append("local clean-text may damage complex visuals")
                actions.append("prefer mask-based clean-required plus image-model local repair for this page type")
            if changed >= 12:
                actions.append("inspect clean_background for damaged visuals or text remnants")
        elif mode == "clean-required":
            if changed >= 12 or mae >= 18:
                actions.append("inspect mask coverage and repair only failed text regions with image model")

        if info.get("shape_nodes", 0) > 0:
            actions.append("verify materialized shapes are simple/high-confidence and do not cover background details")
        if info.get("image_nodes", 0) > 0:
            actions.append("verify cropped image/icon elements have clean transparent edges and correct alignment")

        if not actions:
            actions.append("representative page likely acceptable; inspect preview before full conversion")
        recommendations.append({"page": page, "page_type": page_type, "issues": issues, "recommended_actions": actions})
    return recommendations


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Editable PPT v2 QA Report",
        "",
        f"- Source: `{report['source']}`",
        f"- Pages: `{report['pages']}`",
        f"- Model: `{report['model']}`",
        f"- Output PPTX: `{report['outputs']['pptx']}`",
        "",
        "## Scores",
        "",
        "| Page | MAE | RMS | Changed >25 | Preview |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in report["scores"]:
        lines.append(
            f"| {row['page']} | {row['mae']} | {row['rms']} | {row['changed_pixels_gt_25_pct']}% | `{row['preview']}` |"
        )
    lines.extend(["", "## Element Counts", "", "| Page | Type | Text | Shape | Image |", "| --- | --- | ---: | ---: | ---: |"])
    for row in report["element_counts"]:
        lines.append(
            f"| {row['index']} | {row.get('page_type') or ''} | {row['text_nodes']} | {row['shape_nodes']} | {row['image_nodes']} |"
        )
    bg_qa = report.get("background_text_qa")
    if bg_qa:
        lines.extend(["", "## Background Text QA", "", "| Page | Residual Text | Score | Mask |", "| --- | --- | ---: | --- |"])
        for row in bg_qa.get("pages", []):
            residual = "yes" if row.get("residual_text_detected") else "no"
            lines.append(
                f"| {row['page']} | {residual} | {row.get('residual_char_score', 0)} | `{row.get('text_mask') or ''}` |"
            )
    lines.extend(["", "## Recommendations", ""])
    for row in report.get("recommendations", []):
        issues = "; ".join(row.get("issues") or ["none"])
        actions = "; ".join(row.get("recommended_actions") or [])
        lines.append(f"- Page {row['page']} (`{row.get('page_type')}`): issues: {issues}. actions: {actions}")
    lines.extend(["", "## Artifacts", ""])
    for key, value in report["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run editable PPT v2 representative-page pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pptx")
    source.add_argument("--pdf")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pages", default="1,2")
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--base-url", default=os.environ.get("VISION_API_BASE_URL") or "https://yunwu.ai")
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument(
        "--background-mode",
        choices=["clean-required", "local-clean", "original", "original-debug"],
        default="clean-required",
        help="clean-required is the normal workflow; original/original-debug are only for comparison",
    )
    parser.add_argument("--clean-background", action="append", default=[], help="Override mapping like slide_001.png=/abs/clean.jpg")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"missing API key env: {args.api_key_env}")

    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env[args.api_key_env] = api_key

    raw_dir = out / "01_raw"
    vision_dir = out / "02_vision_package"
    semantic_dir = out / "03_semantic_layout"
    layered_dir = out / "04_layered_layout"
    clean_dir = out / "05_clean_background"
    materialized_dir = out / "06_materialized"
    pptx_dir = out / "07_pptx"
    preview_dir = out / "08_previews"
    qa_dir = out / "09_qa"

    raw_result = run(
        [
            sys.executable,
            str(SCRIPT_DIR / "editable_deck.py"),
            *source_args(args),
            "--output-dir",
            str(raw_dir),
            "--pages",
            args.pages,
            "--mode",
            "text-overlay",
            "--write-raw",
        ]
    )
    raw_layout = Path(raw_result["raw_layout"]) if raw_result and raw_result.get("raw_layout") else raw_dir / "layout.raw.json"

    run([sys.executable, str(SCRIPT_DIR / "prepare_vision_layout.py"), "--raw-layout", str(raw_layout), "--output-dir", str(vision_dir)])
    package = vision_dir / "vision_layout_package.json"

    semantic_layout = semantic_dir / "layout.semantic.json"
    run(
        [
            sys.executable,
            str(SCRIPT_DIR / "semantic_layout_with_model.py"),
            "--package",
            str(package),
            "--output",
            str(semantic_layout),
            "--model",
            args.model,
            "--base-url",
            args.base_url,
            "--pages",
            ",".join(str(i + 1) for i, _ in enumerate(load_json(package)["slides"])),
            "--timeout",
            str(args.timeout),
            *(["--insecure"] if args.insecure else []),
        ],
        env=env,
    )

    layered_layout = layered_dir / "layout.layered.json"
    run(
        [
            sys.executable,
            str(SCRIPT_DIR / "layered_layout_with_model.py"),
            "--package",
            str(package),
            "--output",
            str(layered_layout),
            "--model",
            args.model,
            "--base-url",
            args.base_url,
            "--pages",
            ",".join(str(i + 1) for i, _ in enumerate(load_json(package)["slides"])),
            "--timeout",
            str(args.timeout),
            *(["--insecure"] if args.insecure else []),
        ],
        env=env,
    )

    clean_overrides = clean_map(args.clean_background)
    clean_args: list[str] = []
    clean_layout = None
    background_text_qa = None
    if args.background_mode == "clean-required":
        clean_result = run(
            [
                sys.executable,
                str(SCRIPT_DIR / "build_text_masks.py"),
                "--layout",
                str(semantic_layout),
                "--output-dir",
                str(clean_dir),
                "--mask-expand",
                "18",
            ]
        )
        clean_layout = Path(clean_result["layout"]) if clean_result and clean_result.get("layout") else clean_dir / "layout.clean.json"
        qa_path = (
            Path(clean_result["background_text_qa"])
            if clean_result and clean_result.get("background_text_qa")
            else clean_dir / "background_text_qa.json"
        )
        background_text_qa = load_json(qa_path) if qa_path.exists() else None
        clean_args = build_clean_background_maps(clean_layout, clean_overrides)
    elif args.background_mode == "local-clean":
        clean_result = run(
            [
                sys.executable,
                str(SCRIPT_DIR / "editable_deck.py"),
                *source_args(args),
                "--output-dir",
                str(clean_dir),
                "--pages",
                args.pages,
                "--mode",
                "clean-text",
                "--repair-layout",
                str(semantic_layout),
                "--mask-expand",
                "18",
            ]
        )
        clean_layout = Path(clean_result["layout"]) if clean_result and clean_result.get("layout") else clean_dir / "layout.json"
        clean_args = build_clean_background_maps(clean_layout, clean_overrides)
    else:
        clean_args = [f"{k}={v}" for k, v in clean_overrides.items()]

    materialized_layout = materialized_dir / "layout.materialized.json"
    materialize_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "materialize_layered_layout.py"),
        "--layered-layout",
        str(layered_layout),
        "--base-layout",
        str(semantic_layout),
        "--output",
        str(materialized_layout),
    ]
    for item in clean_args:
        materialize_cmd.extend(["--clean-background", item])
    run(materialize_cmd)

    rebuild = run(
        [
            sys.executable,
            str(SCRIPT_DIR / "editable_deck.py"),
            *source_args(args),
            "--output-dir",
            str(pptx_dir),
            "--pages",
            args.pages,
            "--mode",
            "text-overlay",
            "--repair-layout",
            str(materialized_layout),
            "--background-key",
            "clean_background",
        ]
    )
    pptx = Path(rebuild["pptx"]) if rebuild and rebuild.get("pptx") else pptx_dir / "editable_text_overlay.pptx"
    render_pptx_to_previews(pptx, preview_dir)

    raw = load_json(raw_layout)
    scores = []
    for idx, slide in enumerate(raw.get("slides", []), start=1):
        preview = preview_dir / f"preview_{idx:03d}.png"
        if preview.exists():
            row = diff_score(Path(slide["image"]), preview)
            row["page"] = idx
            scores.append(row)

    report = {
        "source": str(Path(args.pptx or args.pdf).expanduser().resolve()),
        "pages": args.pages,
        "model": args.model,
        "background_mode": args.background_mode,
        "background_text_qa": background_text_qa,
        "scores": scores,
        "element_counts": element_counts(materialized_layout),
        "outputs": {
            "raw_layout": str(raw_layout),
            "vision_package": str(package),
            "semantic_layout": str(semantic_layout),
            "layered_layout": str(layered_layout),
            "clean_layout": str(clean_layout) if clean_layout else None,
            "materialized_layout": str(materialized_layout),
            "pptx": str(pptx),
            "preview_dir": str(preview_dir),
        },
    }
    report["recommendations"] = build_recommendations(report)
    qa_dir.mkdir(parents=True, exist_ok=True)
    report_json = qa_dir / "qa_report.json"
    report_md = qa_dir / "qa_report.md"
    write_json(report_json, report)
    write_markdown_report(report_md, report)
    print(json.dumps({"ok": True, "pptx": str(pptx), "qa_report": str(report_json), "qa_markdown": str(report_md)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
