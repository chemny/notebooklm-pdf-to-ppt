#!/usr/bin/env python3
"""Experimental PaddleOCR + style-probe layout fusion.

This script is intentionally not wired into the normal editable-deck flow. It
uses PaddleOCR for text/bbox evidence and the existing OCR layout as the style
probe and inclusion filter, then writes one unified layout JSON that
editable_deck.py can render through --repair-layout.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from paddleocr import PaddleOCR


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u3400-\u9fff]+", "", text or "").lower()


def bbox(item: dict[str, Any]) -> list[float]:
    return [
        float(item.get("x", 0)),
        float(item.get("y", 0)),
        float(item.get("width", 0)),
        float(item.get("height", 0)),
    ]


def center(box: list[float]) -> tuple[float, float]:
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def similarity(a: str, b: str) -> float:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return min(len(na), len(nb)) / max(len(na), len(nb))
    matches = sum(1 for ch in na if ch in nb)
    return matches / max(len(na), len(nb))


def run_paddle(ocr: PaddleOCR, image: str) -> list[dict[str, Any]]:
    result = ocr.predict(image)[0]
    raw = result.json["res"] if isinstance(result.json, dict) and "res" in result.json else result.json
    polys = raw.get("dt_polys") or []
    texts = raw.get("rec_texts") or []
    scores = raw.get("rec_scores") or []
    items: list[dict[str, Any]] = []
    for idx, poly in enumerate(polys):
        text = texts[idx] if idx < len(texts) else ""
        if not str(text).strip():
            continue
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x, max(ys) - y
        score = float(scores[idx]) if idx < len(scores) else 0.0
        items.append(
            {
                "text": str(text).strip(),
                "confidence": score,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "poly": poly,
            }
        )
    return items


def is_decorative_probe(item: dict[str, Any], slide_w: float, slide_h: float) -> bool:
    text = str(item.get("text") or "").strip()
    x, y, w, h = bbox(item)
    norm = normalize_text(text)
    conf = float(item.get("confidence") or 0)
    if not norm:
        return True
    if y > slide_h * 0.94:
        return True
    if conf < 55 and len(norm) <= 5 and not re.search(r"[\u3400-\u9fff]", text):
        return True
    # Keep title/body/callout text; drop obvious background signage unless it
    # overlaps an existing OCR probe with substantial content.
    if len(norm) < 4 and w < slide_w * 0.12:
        return True
    return False


def best_paddle_match(probe: dict[str, Any], candidates: list[dict[str, Any]], used: set[int], slide_w: float, slide_h: float) -> tuple[int | None, dict[str, Any] | None, float]:
    pb = bbox(probe)
    pc = center(pb)
    probe_text = str(probe.get("text") or "")
    best: tuple[int | None, dict[str, Any] | None, float] = (None, None, -999.0)
    for idx, cand in enumerate(candidates):
        if idx in used:
            continue
        if float(cand.get("confidence") or 0) < 0.50:
            continue
        cb = bbox(cand)
        cc = center(cb)
        dist = math.hypot(pc[0] - cc[0], pc[1] - cc[1])
        distance_score = max(0.0, 1.0 - dist / max(slide_w * 0.18, 1.0))
        overlap = iou(pb, cb)
        text_score = similarity(probe_text, str(cand.get("text") or ""))
        if text_score < 0.18 and overlap < 0.12:
            continue
        score = overlap * 0.45 + distance_score * 0.35 + text_score * 0.20
        if score > best[2]:
            best = (idx, cand, score)
    idx, cand, score = best
    if cand is None:
        return None, None, 0.0
    cb = bbox(cand)
    dist = math.hypot(pc[0] - center(cb)[0], pc[1] - center(cb)[1])
    if iou(pb, cb) >= 0.25 or dist <= max(pb[3], cb[3]) * 1.4 or score >= 0.55:
        return idx, cand, score
    return None, None, score


def useful_unmatched_paddle(item: dict[str, Any], slide_w: float, slide_h: float) -> bool:
    text = str(item.get("text") or "").strip()
    norm = normalize_text(text)
    if not norm:
        return False
    if float(item.get("confidence") or 0) < 0.90:
        return False
    x, y, w, h = bbox(item)
    if y > slide_h * 0.94:
        return False
    if len(norm) <= 5 and w < slide_w * 0.16 and not re.search(r"[\u3400-\u9fff]", text):
        return False
    # Add likely title/large text missed by the style probe. Do not broadly add
    # every background label; this remains an experiment, not an OCR dump.
    if y < slide_h * 0.18 and (w > slide_w * 0.15 or h > slide_h * 0.055):
        return True
    return False


def fused_font_size(probe: dict[str, Any], cand: dict[str, Any] | None) -> float:
    raw = float(probe.get("font_size_px") or probe.get("height") or 32)
    if cand is None:
        return raw
    # PaddleOCR does not expose font size, but its text-line box height is a
    # better guardrail than a bad Tesseract word outlier. Keep the style probe
    # value unless it is visibly outside the Paddle line-height range.
    h = max(8.0, float(cand.get("height") or raw))
    upper = h * 1.08
    lower = h * 0.55
    return max(lower, min(raw, upper))


def fuse_slide(style_page: dict[str, Any], clean_page: dict[str, Any] | None, ocr: PaddleOCR) -> dict[str, Any]:
    image = str(style_page["image"])
    slide_w = float(style_page["width"])
    slide_h = float(style_page["height"])
    paddle_items = run_paddle(ocr, image)
    used: set[int] = set()
    texts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for probe in style_page.get("texts", []):
        if is_decorative_probe(probe, slide_w, slide_h):
            diagnostics.append({"probeText": probe.get("text"), "action": "drop_decorative_probe"})
            continue
        idx, cand, match_score = best_paddle_match(probe, paddle_items, used, slide_w, slide_h)
        if idx is not None:
            used.add(idx)
        source = cand if cand is not None else probe
        text = str(source.get("text") or probe.get("text") or "").strip()
        if not text:
            continue
        item = {
            "text": text,
            "x": float(source.get("x", probe.get("x", 0))),
            "y": float(source.get("y", probe.get("y", 0))),
            "width": float(source.get("width", probe.get("width", 100))),
            "height": float(source.get("height", probe.get("height", 30))),
            "font_size_px": fused_font_size(probe, cand),
            "font_family": probe.get("font_family") or probe.get("fontFamily") or ("Noto Sans SC" if re.search(r"[\u3400-\u9fff]", text) else "Inter"),
            "fontFamily": probe.get("fontFamily") or probe.get("font_family"),
            "color": probe.get("color") or "#111111",
            "fill_color": probe.get("fill_color") or "#FFFFFF",
            "align": probe.get("align") or ["LEFT", "CENTER"],
            "bold": bool(probe.get("bold", False)),
            "lineSpacing": probe.get("lineSpacing") or probe.get("line_spacing") or 0.92,
            "positionLocked": True,
            "fontSizeLocked": True,
            "textSource": "paddleocr_matched" if cand is not None else "style_probe_fallback",
            "positionSource": "paddleocr_matched" if cand is not None else "style_probe_fallback",
            "fontSizeSource": "style_probe_guarded_by_paddle_bbox" if cand is not None else "style_probe",
            "styleSource": "existing_ocr_style_probe",
            "matchScore": round(match_score, 3),
            "paddleConfidence": cand.get("confidence") if cand is not None else None,
            "styleProbeText": probe.get("text"),
            "styleProbeBox": bbox(probe),
        }
        texts.append(item)
        diagnostics.append(
            {
                "probeText": probe.get("text"),
                "finalText": text,
                "action": "matched_paddle" if cand is not None else "style_probe_fallback",
                "score": round(match_score, 3),
                "paddleConfidence": cand.get("confidence") if cand is not None else None,
            }
        )

    for idx, cand in enumerate(paddle_items):
        if idx in used or not useful_unmatched_paddle(cand, slide_w, slide_h):
            continue
        text = str(cand.get("text") or "").strip()
        item = {
            "text": text,
            "x": float(cand.get("x", 0)),
            "y": float(cand.get("y", 0)),
            "width": float(cand.get("width", 100)),
            "height": float(cand.get("height", 30)),
            "font_size_px": max(12.0, float(cand.get("height", 30)) * 0.72),
            "font_family": "Noto Sans SC" if re.search(r"[\u3400-\u9fff]", text) else "Inter",
            "fontFamily": "Noto Sans SC" if re.search(r"[\u3400-\u9fff]", text) else "Inter",
            "color": "#111111",
            "fill_color": "#FFFFFF",
            "align": ["LEFT", "CENTER"],
            "bold": False,
            "lineSpacing": 0.92,
            "positionLocked": True,
            "fontSizeLocked": True,
            "textSource": "paddleocr_unmatched_candidate",
            "positionSource": "paddleocr_unmatched_candidate",
            "fontSizeSource": "paddleocr_bbox_estimate",
            "styleSource": "paddleocr_fallback_no_style_probe",
            "paddleConfidence": cand.get("confidence"),
        }
        texts.append(item)
        diagnostics.append({"finalText": text, "action": "add_unmatched_paddle_candidate", "paddleConfidence": cand.get("confidence")})

    page = {
        "image": image,
        "width": int(slide_w),
        "height": int(slide_h),
        "texts": texts,
        "paddle_ocr": paddle_items,
        "fusionDiagnostics": diagnostics,
    }
    if clean_page and clean_page.get("clean_background"):
        page["clean_background"] = clean_page["clean_background"]
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuse PaddleOCR text/bboxes with existing OCR style probes")
    parser.add_argument("--style-layout", required=True, help="Existing raw OCR layout JSON with texts/style estimates")
    parser.add_argument("--clean-layout", help="Existing layout JSON with clean_background paths")
    parser.add_argument("--output", required=True, help="Output fused layout JSON")
    parser.add_argument("--det-model", default="PP-OCRv5_mobile_det")
    parser.add_argument("--rec-model", default="PP-OCRv5_mobile_rec")
    args = parser.parse_args()

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    style_layout = load_json(args.style_layout)
    clean_layout = load_json(args.clean_layout) if args.clean_layout else {}
    clean_slides = clean_layout.get("slides") or []
    ocr = PaddleOCR(
        text_detection_model_name=args.det_model,
        text_recognition_model_name=args.rec_model,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_side_len=1920,
        return_word_box=True,
    )

    slides: list[dict[str, Any]] = []
    for idx, style_page in enumerate(style_layout.get("slides", [])):
        clean_page = clean_slides[idx] if idx < len(clean_slides) else None
        slides.append(fuse_slide(style_page, clean_page, ocr))

    out = {
        "mode": "paddle-style-fusion-experiment",
        "model": {"ocr": {"det": args.det_model, "rec": args.rec_model}, "style": "existing_ocr_probe"},
        "source": style_layout.get("source"),
        "pages": style_layout.get("pages"),
        "slides": slides,
    }
    write_json(args.output, out)
    print(
        json.dumps(
            {
                "ok": True,
                "layout": str(Path(args.output).expanduser().resolve()),
                "slides": len(slides),
                "text_nodes": sum(len(s.get("texts", [])) for s in slides),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
