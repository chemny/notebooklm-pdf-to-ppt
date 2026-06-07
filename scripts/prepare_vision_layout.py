#!/usr/bin/env python3
"""Prepare a vision-model layout repair package for representative slides."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["slides"],
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["image", "width", "height", "elements"],
                "properties": {
                    "image": {"type": "string"},
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                    "elements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "x", "y", "width", "height"],
                            "properties": {
                                "type": {"type": "string", "enum": ["text", "image", "shape"]},
                                "text": {"type": "string"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                                "fontFamily": {"type": "string"},
                                "fontSize": {"type": "number"},
                                "color": {"type": "string"},
                                "fillColor": {"type": "string"},
                                "align": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                    "maxItems": 2,
                                },
                                "bold": {"type": "boolean"},
                                "role": {
                                    "type": "string",
                                    "enum": ["title", "subtitle", "body", "caption", "watermark", "label", "unknown"],
                                },
                                "src": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}


def load_layout(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_heavy_fields(layout: dict[str, Any]) -> dict[str, Any]:
    stripped = {"source": layout.get("source"), "mode": "vision-repair", "slides": []}
    for slide in layout.get("slides", []):
        stripped_slide = {
            "image": slide.get("image"),
            "width": slide.get("width"),
            "height": slide.get("height"),
            "ocr_texts": [],
            "ocr_words": [],
        }
        for word in slide.get("words", []):
            stripped_slide["ocr_words"].append(
                {
                    "text": word.get("text"),
                    "x": word.get("x"),
                    "y": word.get("y"),
                    "width": word.get("width"),
                    "height": word.get("height"),
                    "confidence": word.get("confidence"),
                }
            )
        for text in slide.get("texts", []):
            stripped_slide["ocr_texts"].append(
                {
                    "text": text.get("text"),
                    "x": text.get("x"),
                    "y": text.get("y"),
                    "width": text.get("width"),
                    "height": text.get("height"),
                    "font_size_px": text.get("font_size_px"),
                    "font_family": text.get("font_family"),
                    "color": text.get("color"),
                    "confidence": text.get("confidence"),
                    "word_boxes": text.get("word_boxes") or [],
                }
            )
        stripped["slides"].append(stripped_slide)
    return stripped


def write_prompt(package: dict[str, Any], out_dir: Path) -> Path:
    prompt = f"""You are reconstructing an image-based slide deck into editable PowerPoint layout JSON.

Use the attached slide images as the source of truth. Use the OCR hints only as rough hints; fix OCR errors, merge broken text lines, remove false positives, and estimate layout from the image.

Return only valid JSON matching the schema below. Do not include markdown fences.

Important rules:
- Keep the original canvas width and height.
- Use absolute pixel coordinates in the original image coordinate system.
- Preserve Chinese text exactly when visible.
- Merge text into natural editable text boxes, not one word per box.
- Assign roles: title, subtitle, body, caption, watermark, label, or unknown.
- Use the approved reconstruction font pool only: Noto Sans SC, Inter, Source Han Sans CN, 思源黑体 CN, Arial, Times New Roman.
- Estimate fontSize in source-image pixels.
- Use #RRGGBB colors.
- Include obvious independent image regions only if they are not the full-page background.
- Do not include a full-slide background image as an element; the rebuild script already uses the slide image as background.

Schema:
{json.dumps(SCHEMA, ensure_ascii=False, indent=2)}

Input package:
{json.dumps(package, ensure_ascii=False, indent=2)}
"""
    path = out_dir / "vision_layout_prompt.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a vision layout repair package")
    parser.add_argument("--raw-layout", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_layout = load_layout(Path(args.raw_layout).expanduser().resolve())
    package = strip_heavy_fields(raw_layout)
    package_path = out_dir / "vision_layout_package.json"
    schema_path = out_dir / "vision_layout_schema.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    schema_path.write_text(json.dumps(SCHEMA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_path = write_prompt(package, out_dir)
    print(json.dumps({"ok": True, "package": str(package_path), "schema": str(schema_path), "prompt": str(prompt_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
