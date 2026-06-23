#!/usr/bin/env python3
"""PaddleOCR worker for pdf_to_ppt_simple.py.

Input is JSON on stdin:
{
  "images": [{"page_number": 1, "image": "/abs/path.png"}]
}

Output is JSON on stdout:
{
  "ok": true,
  "slides": [...]
}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image
from paddleocr import PaddleOCR  # type: ignore

# Shared skill-side style probe (color/glyph recovery). Ensure the script's own
# directory is importable when this worker is launched as a standalone process.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_probe import analyze_text_region  # noqa: E402


DEFAULT_CJK_FONT = "Noto Sans SC"
DEFAULT_LATIN_FONT = "Inter"


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def font_for_text(text: str) -> str:
    return DEFAULT_CJK_FONT if contains_cjk(text) else DEFAULT_LATIN_FONT


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？：；、])", r"\1", text)
    return text


def useful_text(text: str, conf: float, width: float, height: float) -> bool:
    if not text:
        return False
    if width < 12 or height < 8:
        return False
    visible = re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text)
    if len(visible) < 2:
        # The old <2 rule silently dropped meaningful short tokens such as
        # section numerals ("\u56db"/"3") that belong to a heading. Keep a single
        # high-confidence CJK/digit token; still drop low-confidence noise like
        # a misread phonetic "/+S/".
        if conf >= 80 and re.search(r"[0-9\u3400-\u9fff]", text.strip()):
            return True
        return False
    if conf < 25 and len(visible) < 5:
        return False
    return True


def make_ocr() -> PaddleOCR:
    return PaddleOCR(
        text_detection_model_name="PP-OCRv6_small_det",
        text_recognition_model_name="PP-OCRv6_small_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_side_len=1920,
    )


def parse_result_json(result: Any) -> dict[str, Any]:
    data = getattr(result, "json", {})
    if callable(data):
        data = data()
    return data.get("res", data) if isinstance(data, dict) else {}


def ocr_image(ocr: PaddleOCR, item: dict[str, Any]) -> dict[str, Any]:
    image_path = Path(item["image"])
    image = Image.open(image_path).convert("RGB")
    result = ocr.predict(str(image_path))[0]
    data = parse_result_json(result)
    polys = data.get("dt_polys") or []
    texts = data.get("rec_texts") or []
    scores = data.get("rec_scores") or []
    lines: list[dict[str, Any]] = []
    for poly, raw_text, score in zip(polys, texts, scores):
        text = clean_text(raw_text)
        xs = [int(point[0]) for point in poly]
        ys = [int(point[1]) for point in poly]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        conf = float(score) * 100
        if not useful_text(text, conf, x2 - x1, y2 - y1):
            continue
        height = y2 - y1
        probe = analyze_text_region(image, (x1, y1, x2, y2))
        # Size from MEASURED ink height, not a flat bbox ratio. Convert the ink
        # span to an em size: CJK glyphs fill ~0.86em, Latin ascender ink ~0.72em.
        ink_h = float(probe.get("glyph_height") or 0) or height
        em_ratio = 0.86 if contains_cjk(text) else 0.72
        font_px = round(max(ink_h / em_ratio, 6.0), 2)
        lines.append(
            {
                "text": text,
                "confidence": round(conf, 2),
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": height,
                "font_size_px": font_px,
                "glyph_ink_height": round(ink_h, 2),
                "font_family": font_for_text(text),
                "color": probe["color"],
                "is_light_on_dark": bool(probe.get("is_light_on_dark")),
                "source": "paddle",
                "word_boxes": [
                    {
                        "text": text,
                        "x": x1,
                        "y": y1,
                        "width": x2 - x1,
                        "height": height,
                        "confidence": conf,
                    }
                ],
            }
        )
    return {
        "page_number": item.get("page_number"),
        "image": str(image_path),
        "width": image.width,
        "height": image.height,
        "texts": lines,
        "mask_words": lines,
    }


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    images = payload.get("images") or []
    ocr = make_ocr()
    slides = [ocr_image(ocr, item) for item in images]
    print(json.dumps({"ok": True, "slides": slides}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
