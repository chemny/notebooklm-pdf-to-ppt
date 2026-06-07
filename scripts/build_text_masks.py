#!/usr/bin/env python3
"""Build text-removal masks, cleaned backgrounds, and residual-text QA.

This is a workflow step, not a final-quality inpainting engine. It enforces the
core reconstruction contract: visible editable text should not sit on top of the
same old text in the flattened background.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

from editable_deck import create_clean_background, page_text_items


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def visible_text_score(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text or ""))


def clean_ocr_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return text


def background_residual_qa(image_path: Path, lang: str, psm: int, min_chars: int) -> dict[str, Any]:
    image = Image.open(image_path).convert("RGB")
    raw = pytesseract.image_to_string(image, lang=lang, config=f"--psm {psm}")
    text = clean_ocr_text(raw)
    score = visible_text_score(text)
    return {
        "image": str(image_path),
        "residual_text": text[:600],
        "residual_char_score": score,
        "residual_text_detected": score >= min_chars,
    }


def ensure_mask_items(slide: dict[str, Any]) -> None:
    """Ensure cleanup covers both model text boxes and raw OCR word boxes."""
    mask_items = list(slide.get("mask_texts") or [])
    for item in page_text_items(slide):
        mask_items.append(
            {
                "x": item["x"],
                "y": item["y"],
                "width": item["width"],
                "height": item["height"],
                "text": item.get("text", ""),
            }
        )
    slide["mask_texts"] = mask_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Build text masks and cleaned backgrounds from a repaired layout")
    parser.add_argument("--layout", required=True, help="Layout JSON with slides/elements or slides/texts")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mask-expand", type=int, default=18)
    parser.add_argument("--lang", default="chi_sim+eng")
    parser.add_argument("--psm", type=int, default=11)
    parser.add_argument("--residual-min-chars", type=int, default=12)
    args = parser.parse_args()

    layout_path = Path(args.layout).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    layout = load_json(layout_path)
    layout["mode"] = "clean-required"
    qa_rows: list[dict[str, Any]] = []
    for idx, slide in enumerate(layout.get("slides", []), start=1):
        ensure_mask_items(slide)
        create_clean_background(slide, out_dir, args.mask_expand)
        qa = background_residual_qa(Path(slide["clean_background"]), args.lang, args.psm, args.residual_min_chars)
        qa["page"] = idx
        qa["source_image"] = slide.get("image")
        qa["text_nodes_masked"] = len(page_text_items(slide))
        qa["mask_items"] = len(slide.get("mask_texts") or [])
        qa["text_mask"] = slide.get("text_mask")
        qa_rows.append(qa)

    clean_layout = out_dir / "layout.clean.json"
    qa_path = out_dir / "background_text_qa.json"
    write_json(clean_layout, layout)
    write_json(
        qa_path,
        {
            "ok": not any(row["residual_text_detected"] for row in qa_rows),
            "layout": str(clean_layout),
            "residual_min_chars": args.residual_min_chars,
            "pages": qa_rows,
        },
    )
    print(
        json.dumps(
            {
                "ok": True,
                "layout": str(clean_layout),
                "background_text_qa": str(qa_path),
                "residual_pages": [row["page"] for row in qa_rows if row["residual_text_detected"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
