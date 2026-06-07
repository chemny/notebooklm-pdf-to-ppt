#!/usr/bin/env python3
"""Create layout JSON by combining model semantics with OCR coordinates."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from statistics import median


SYSTEM_PROMPT = """You repair slide OCR into semantic editable PowerPoint text blocks.

Return only valid JSON. No markdown fences. No explanation.

The image is the source of truth for reading and grouping, but OCR coordinates are the source of truth for positions.
Do not invent coordinates.
Use OCR item ids to form editable text groups.

Rules:
- Merge OCR items into natural text blocks.
- Preserve Chinese text exactly as visible.
- Correct obvious OCR errors.
- Keep bullets/checkmarks/cross marks as separate label text blocks when visually separate.
- Do not prefix long body text with emoji checkmarks, crosses, bullets, or decorative markers. Keep markers separate or omit them when they are already graphical.
- Assign role: title, subtitle, body, caption, watermark, label, unknown.
- Do not estimate final font size, font family, color, alignment, or coordinates. These are measured later from OCR/visual anchors.
- If important visible text is missing from OCR, include it with estimated pixel coordinates.
- Use the approved reconstruction font pool only: Noto Sans SC, Inter, Source Han Sans CN, 思源黑体 CN, Arial, Times New Roman.
- Use #RRGGBB colors.
- If unsure, keep OCR text rather than inventing new text.
"""


def data_url(path: Path) -> str:
    mime = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def strip_json(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if match:
        text = match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def call_chat(base_url: str, api_key: str, model: str, slide: dict[str, Any], timeout: int, insecure: bool) -> dict[str, Any]:
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"
    ocr_items = []
    for idx, item in enumerate(slide.get("ocr_texts", [])):
        ocr_items.append({"id": idx, **item})
    schema = {
        "blocks": [
            {
                "source_ids": [0],
                "text": "corrected visible text",
                "role": "title|subtitle|body|caption|watermark|label|unknown",
                "fontFamily": "Noto Sans SC",
                "fontSize": 48,
                "color": "#111111",
                "bold": True,
                "align": ["LEFT", "CENTER"],
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
            }
        ]
    }
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "task": "Group OCR items into semantic editable text blocks. Return JSON matching schema.",
                                "canvas": {"width": slide["width"], "height": slide["height"]},
                                "schema": schema,
                                "ocr_items": ocr_items,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url(Path(slide["image"]))}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    return json.loads(strip_json(data["choices"][0]["message"]["content"]))


def union_box(items: list[dict[str, Any]]) -> dict[str, float]:
    x1 = min(float(i["x"]) for i in items)
    y1 = min(float(i["y"]) for i in items)
    x2 = max(float(i["x"]) + float(i["width"]) for i in items)
    y2 = max(float(i["y"]) + float(i["height"]) for i in items)
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


LEADING_MARKER_RE = re.compile(r"^\s*(?:[❌✔✓✕✖✗×✅☑■□◆◇●•\-–—]+\s*)+")
OCR_MARKER_RE = re.compile(r"^(?:[兴叉勾]|[A-Z]{1,2}|[xX])$")


def sanitize_model_text(text: str, role: str | None = None) -> str:
    """Keep decorative markers out of editable body text boxes."""
    cleaned = str(text or "").strip()
    if role not in {"title", "subtitle"}:
        cleaned = LEADING_MARKER_RE.sub("", cleaned).strip()
    return cleaned


def item_body_box(item: dict[str, Any]) -> dict[str, float]:
    """Use word boxes to avoid OCR marker/icon artifacts becoming text origin."""
    words = item.get("word_boxes") or []
    usable = []
    for word in words:
        text = str(word.get("text") or "").strip()
        if not text or OCR_MARKER_RE.match(text):
            continue
        usable.append(word)
    if len(usable) >= 2:
        return union_box(usable)
    return {
        "x": float(item["x"]),
        "y": float(item["y"]),
        "width": float(item["width"]),
        "height": float(item["height"]),
    }


def usable_word_boxes(item: dict[str, Any]) -> list[dict[str, Any]]:
    words = item.get("word_boxes") or []
    usable = []
    for word in words:
        text = str(word.get("text") or "").strip()
        if not text or OCR_MARKER_RE.match(text):
            continue
        usable.append(word)
    return usable


def measured_font_px(items: list[dict[str, Any]], role: str | None, fallback: float = 18.0) -> float:
    """Estimate font size from original word boxes, not model guesses."""
    heights: list[float] = []
    for item in items:
        words = usable_word_boxes(item)
        if words:
            heights.extend(float(w.get("height") or 0) for w in words if float(w.get("height") or 0) > 0)
        elif item.get("font_size_px"):
            heights.append(float(item["font_size_px"]))
    if not heights:
        return fallback
    if role in {"body", "label", "unknown"}:
        values = sorted(heights)
        # Body OCR boxes often include punctuation overshoot. Use the lower
        # middle of real glyph heights so rows do not jump size.
        idx = max(0, min(len(values) - 1, len(values) // 2 - 1))
        return max(12.0, values[idx])
    return max(14.0, float(median(heights)))


def union_text_box(items: list[dict[str, Any]], role: str | None, text: str) -> dict[str, float]:
    if role in {"body", "label", "unknown"}:
        boxes = [item_body_box(item) for item in items]
        return union_box(boxes)
    return union_box(items)


def element_column(element: dict[str, Any], slide_width: float) -> str:
    center = float(element["x"]) + float(element["width"]) / 2
    return "left" if center < slide_width / 2 else "right"


def normalize_by_hierarchy(slide: dict[str, Any], elements: list[dict[str, Any]]) -> None:
    """Make position/style deterministic after model text repair."""
    if not elements:
        return
    slide_width = float(slide["width"])
    bodies = [e for e in elements if e.get("role") in {"body", "label", "unknown"}]

    for column in ("left", "right"):
        col_bodies = [e for e in bodies if element_column(e, slide_width) == column and e.get("source_ids")]
        if not col_bodies:
            continue
        anchor_x = float(median([float(e["x"]) for e in col_bodies]))
        max_right = max(float(e["x"]) + float(e["width"]) for e in col_bodies)
        font_values = [float(e["fontSize"]) for e in col_bodies if e.get("fontSize")]
        body_font = float(median(font_values)) if font_values else 24.0
        for element in [e for e in bodies if element_column(e, slide_width) == column]:
            old_right = float(element["x"]) + float(element["width"])
            element["x"] = anchor_x
            element["width"] = max(80.0, max(old_right, max_right) - anchor_x)
            element["fontSize"] = body_font
            element["color"] = "#2A2A2A"
            element["bold"] = False
            element["align"] = ["LEFT", "CENTER"]

    subtitles = [e for e in elements if e.get("role") == "subtitle"]
    source_subtitles = [e for e in subtitles if e.get("source_ids")]
    if source_subtitles:
        subtitle_font = float(median([float(e["fontSize"]) for e in source_subtitles if e.get("fontSize")]))
        subtitle_h = float(median([float(e["height"]) for e in source_subtitles if e.get("height")]))
        left_subs = [e for e in source_subtitles if element_column(e, slide_width) == "left"]
        right_subs = [e for e in source_subtitles if element_column(e, slide_width) == "right"]
        right_body_anchor = None
        right_bodies = [e for e in bodies if element_column(e, slide_width) == "right"]
        if right_bodies:
            right_body_anchor = float(median([float(e["x"]) for e in right_bodies]))
        for element in subtitles:
            if not element.get("source_ids"):
                peers = right_subs or left_subs or source_subtitles
                element["fontSize"] = subtitle_font
                element["height"] = max(float(element.get("height") or 0), subtitle_h)
                element["bold"] = True
                element["color"] = "#111111"
                if not right_subs and right_body_anchor and element_column(element, slide_width) == "left":
                    # A missing right-card heading is often placed near the
                    # middle by the model. Anchor it to the right body column.
                    element["x"] = max(slide_width / 2, right_body_anchor - 30)
                if peers:
                    same_col = [e for e in peers if element_column(e, slide_width) == element_column(element, slide_width)]
                    ref = same_col[0] if same_col else peers[0]
                    element["y"] = float(ref["y"])
            else:
                element["fontSize"] = subtitle_font
                element["bold"] = True


def raw_word_masks(slide: dict[str, Any]) -> list[dict[str, Any]]:
    masks: list[dict[str, Any]] = []
    for word in slide.get("ocr_words", []):
        text = str(word.get("text") or "").strip()
        if not text or OCR_MARKER_RE.match(text):
            continue
        try:
            masks.append(
                {
                    "x": float(word["x"]),
                    "y": float(word["y"]),
                    "width": float(word["width"]),
                    "height": float(word["height"]),
                    "text": text,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return masks


def build_slide(slide: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    ocr_items = {idx: item for idx, item in enumerate(slide.get("ocr_texts", []))}
    elements: list[dict[str, Any]] = []
    used: set[int] = set()
    for block in semantic.get("blocks", []):
        ids = [int(i) for i in block.get("source_ids", []) if int(i) in ocr_items]
        items = [ocr_items[i] for i in ids]
        text = block.get("text") or " ".join(str(i.get("text", "")) for i in items)
        text = sanitize_model_text(text, block.get("role") or "unknown")
        if ids:
            used.update(ids)
            box = union_text_box(items, block.get("role") or "unknown", text)
            avg_font = measured_font_px(items, block.get("role") or "unknown")
        else:
            if not all(k in block for k in ("x", "y", "width", "height")):
                continue
            box = {
                "x": float(block["x"]),
                "y": float(block["y"]),
                "width": float(block["width"]),
                "height": float(block["height"]),
            }
            avg_font = float(block.get("fontSize") or max(18, box["height"] * 0.7))
        elements.append(
            {
                "type": "text",
                "text": text,
                **box,
                "fontFamily": block.get("fontFamily") or ("Noto Sans SC" if re.search(r"[\u4e00-\u9fff]", text) else "Inter"),
                "fontSize": avg_font if ids else block.get("fontSize") or avg_font,
                "color": (
                    items[0].get("color")
                    if ids and items and (block.get("role") or "unknown") in {"title", "subtitle", "caption", "watermark"}
                    else None
                )
                or block.get("color")
                or "#111111",
                "fillColor": "#FFFFFF",
                "align": block.get("align") or ["LEFT", "CENTER"],
                "bold": bool(block.get("bold", False)),
                "role": block.get("role") or "unknown",
                "source_ids": ids,
            }
        )
    # Preserve any omitted OCR text as fallback blocks so the page is not lossy.
    for idx, item in ocr_items.items():
        if idx in used:
            continue
        text = sanitize_model_text(str(item.get("text") or ""), "unknown")
        if not text.strip():
            continue
        box = item_body_box(item)
        font_px = measured_font_px([item], "unknown", float(item.get("font_size_px") or 18))
        elements.append(
            {
                "type": "text",
                "text": text,
                **box,
                "fontFamily": item.get("font_family") or ("Noto Sans SC" if re.search(r"[\u4e00-\u9fff]", text) else "Inter"),
                "fontSize": font_px,
                "color": item.get("color") or "#111111",
                "fillColor": "#FFFFFF",
                "align": ["LEFT", "CENTER"],
                "bold": False,
                "role": "unknown",
                "source_ids": [idx],
            }
        )
    normalize_by_hierarchy(slide, elements)
    output = {"image": slide["image"], "width": slide["width"], "height": slide["height"], "elements": elements}
    masks = raw_word_masks(slide)
    if masks:
        output["mask_texts"] = masks
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build semantic layout JSON using model grouping plus OCR coordinates")
    parser.add_argument("--package", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("VISION_API_BASE_URL") or "https://api.openai.com/v1")
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--pages", help="Comma-separated 1-based package slide indices")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"missing API key env: {args.api_key_env}", file=sys.stderr)
        return 2
    package = json.loads(Path(args.package).expanduser().read_text(encoding="utf-8"))
    slides = package["slides"]
    if args.pages:
        wanted = {int(x.strip()) for x in args.pages.split(",") if x.strip()}
        selected = [slide for idx, slide in enumerate(slides, start=1) if idx in wanted]
    else:
        selected = slides[: args.limit] if args.limit else slides

    output = {"source": package.get("source"), "mode": "semantic-ocr-anchored", "model": args.model, "slides": []}
    for idx, slide in enumerate(selected, start=1):
        print(f"semantic repair slide {idx}/{len(selected)} with {args.model}", file=sys.stderr)
        semantic = call_chat(args.base_url, api_key, args.model, slide, args.timeout, args.insecure)
        output["slides"].append(build_slide(slide, semantic))
        time.sleep(args.sleep)
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "model": args.model, "slides": len(output["slides"]), "output": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
