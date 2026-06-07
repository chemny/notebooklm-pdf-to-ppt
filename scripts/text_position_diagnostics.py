#!/usr/bin/env python3
"""Diagnose text-position drift across source OCR, fused layout, and rendered PPT preview."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency
    pytesseract = None


COLORS = {
    "ocr": "#00A6D6",
    "fused": "#FF8A00",
    "rendered": "#38B000",
    "bad": "#E60023",
    "label": "#111111",
    "fill": "#FFFFFF",
}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def normalize_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u3400-\u9fff]+", "", text or "").lower()


def similarity(a: str, b: str) -> float:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return min(len(na), len(nb)) / max(len(na), len(nb))
    return SequenceMatcher(None, na, nb).ratio()


def box_center(box: dict[str, Any]) -> tuple[float, float]:
    return float(box.get("x", 0)) + float(box.get("width", 0)) / 2, float(box.get("y", 0)) + float(box.get("height", 0)) / 2


def center_delta(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, float] | None:
    if not a or not b:
        return None
    ax, ay = box_center(a)
    bx, by = box_center(b)
    return {"dx": round(bx - ax, 1), "dy": round(by - ay, 1)}


def rect(box: dict[str, Any]) -> tuple[int, int, int, int]:
    x = int(round(float(box.get("x", 0))))
    y = int(round(float(box.get("y", 0))))
    w = int(round(float(box.get("width", 0))))
    h = int(round(float(box.get("height", 0))))
    return x, y, x + w, y + h


def draw_box(draw: ImageDraw.ImageDraw, box: dict[str, Any], color: str, label: str, width: int = 5) -> None:
    x1, y1, x2, y2 = rect(box)
    draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
    label_y = max(0, y1 - 28)
    draw.rectangle((x1, label_y, x1 + max(90, len(label) * 13), label_y + 26), fill=COLORS["fill"], outline=color, width=2)
    draw.text((x1 + 5, label_y + 3), label, fill=COLORS["label"])


def group_tesseract_lines(image_path: Path, lang: str, psm: int, scale_to: tuple[int, int] | None = None) -> list[dict[str, Any]]:
    if pytesseract is None:
        return []
    image = Image.open(image_path).convert("RGB")
    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=f"--psm {psm}",
        output_type=pytesseract.Output.DICT,
    )
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for idx, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][idx])
        except ValueError:
            conf = -1
        if conf < 25:
            continue
        x, y, w, h = (int(data[k][idx]) for k in ("left", "top", "width", "height"))
        key = (data["block_num"][idx], data["par_num"][idx], data["line_num"][idx])
        grouped.setdefault(key, []).append({"text": text, "x": x, "y": y, "width": w, "height": h, "confidence": conf})
    sx = sy = 1.0
    if scale_to:
        sx = scale_to[0] / image.width
        sy = scale_to[1] / image.height
    lines: list[dict[str, Any]] = []
    for words in grouped.values():
        words.sort(key=lambda w: w["x"])
        text = " ".join(w["text"] for w in words)
        x1 = min(w["x"] for w in words)
        y1 = min(w["y"] for w in words)
        x2 = max(w["x"] + w["width"] for w in words)
        y2 = max(w["y"] + w["height"] for w in words)
        lines.append(
            {
                "text": text,
                "x": x1 * sx,
                "y": y1 * sy,
                "width": (x2 - x1) * sx,
                "height": (y2 - y1) * sy,
                "confidence": round(sum(w["confidence"] for w in words) / len(words), 1),
            }
        )
    return lines


def best_text_match(target: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for item in candidates:
        score = similarity(target, str(item.get("text") or ""))
        if score > best[1]:
            best = (item, score)
    return best


def find_source_box(element: dict[str, Any], raw_texts: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    ids = element.get("source_ids") or []
    picked = [raw_texts[int(i)] for i in ids if isinstance(i, int) and 0 <= int(i) < len(raw_texts)]
    if picked:
        x1 = min(float(i["x"]) for i in picked)
        y1 = min(float(i["y"]) for i in picked)
        x2 = max(float(i["x"]) + float(i["width"]) for i in picked)
        y2 = max(float(i["y"]) + float(i["height"]) for i in picked)
        return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1, "text": "\n".join(str(i.get("text") or "") for i in picked)}, 1.0
    return best_text_match(str(element.get("text") or ""), raw_texts)


def diagnose_slide(
    slide_idx: int,
    raw_slide: dict[str, Any],
    fused_slide: dict[str, Any],
    preview_image: Path | None,
    out_dir: Path,
    lang: str,
    psm: int,
) -> dict[str, Any]:
    image_path = Path(raw_slide["image"]).expanduser().resolve()
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    raw_texts = raw_slide.get("texts", [])
    elements = [e for e in fused_slide.get("elements", []) if e.get("type") == "text"]
    rendered_lines = group_tesseract_lines(preview_image, lang, psm, (int(raw_slide["width"]), int(raw_slide["height"]))) if preview_image else []

    rows: list[dict[str, Any]] = []
    for idx, element in enumerate(elements, start=1):
        source_box, source_score = find_source_box(element, raw_texts)
        rendered_box, rendered_score = best_text_match(str(element.get("text") or ""), rendered_lines)
        fused_box = {k: element.get(k) for k in ("x", "y", "width", "height")}
        parse_delta = center_delta(source_box, fused_box)
        render_delta = center_delta(fused_box, rendered_box)
        source_bad = source_box is None or source_score < 0.70
        parse_bad = bool(parse_delta and (abs(parse_delta["dx"]) > 30 or abs(parse_delta["dy"]) > 30))
        render_bad = bool(render_delta and (abs(render_delta["dx"]) > 30 or abs(render_delta["dy"]) > 30))

        if source_box:
            draw_box(draw, source_box, COLORS["ocr"], f"OCR {idx}", 4)
        draw_box(draw, fused_box, COLORS["bad"] if parse_bad or source_bad else COLORS["fused"], f"LAY {idx}", 5)
        if rendered_box:
            draw_box(draw, rendered_box, COLORS["bad"] if render_bad else COLORS["rendered"], f"REN {idx}", 3)
        rows.append(
            {
                "index": idx,
                "text": element.get("text"),
                "positionSource": element.get("positionSource"),
                "fontSizeSource": element.get("fontSizeSource"),
                "sourceMatchScore": round(source_score, 3),
                "renderedMatchScore": round(rendered_score, 3),
                "sourceToLayoutDelta": parse_delta,
                "layoutToRenderedDelta": render_delta,
                "diagnosis": (
                    "ocr_or_parse_untrusted"
                    if source_bad
                    else "parse_fusion_drift"
                    if parse_bad
                    else "ppt_render_drift"
                    if render_bad
                    else "aligned"
                ),
            }
        )
    out_image = out_dir / f"slide_{slide_idx:03d}_position_overlay.png"
    image.save(out_image)
    return {
        "slide": slide_idx,
        "sourceImage": str(image_path),
        "previewImage": str(preview_image) if preview_image else None,
        "overlay": str(out_image),
        "elements": rows,
        "summary": {
            "aligned": sum(1 for r in rows if r["diagnosis"] == "aligned"),
            "ocr_or_parse_untrusted": sum(1 for r in rows if r["diagnosis"] == "ocr_or_parse_untrusted"),
            "parse_fusion_drift": sum(1 for r in rows if r["diagnosis"] == "parse_fusion_drift"),
            "ppt_render_drift": sum(1 for r in rows if r["diagnosis"] == "ppt_render_drift"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create text-position diagnostic overlays")
    parser.add_argument("--raw-layout", required=True)
    parser.add_argument("--fused-layout", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--preview-image", action="append", help="Rendered PPT preview image, one per slide")
    parser.add_argument("--first-page", type=int, default=1)
    parser.add_argument("--lang", default="eng+chi_sim")
    parser.add_argument("--psm", type=int, default=6)
    args = parser.parse_args()

    raw = load_json(args.raw_layout)
    fused = load_json(args.fused_layout)
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_paths = [Path(p).expanduser().resolve() for p in (args.preview_image or [])]

    slides = []
    for idx, (raw_slide, fused_slide) in enumerate(zip(raw.get("slides", []), fused.get("slides", []))):
        preview = preview_paths[idx] if idx < len(preview_paths) else None
        slides.append(diagnose_slide(args.first_page + idx, raw_slide, fused_slide, preview, out_dir, args.lang, args.psm))

    result = {"mode": "text-position-diagnostics", "slides": slides}
    report_path = out_dir / "text_position_diagnostics.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), "overlays": [s["overlay"] for s in slides], "summary": [s["summary"] for s in slides]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
