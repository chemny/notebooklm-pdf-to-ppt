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
    visible = re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text)
    if len(visible) < 2:
        return False
    if width < 12 or height < 8:
        return False
    if conf < 25 and len(visible) < 5:
        return False
    return True


def text_color_from_region(image: Image.Image, box: tuple[int, int, int, int]) -> str:
    x1, y1, x2, y2 = box
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    dark = [p for p in crop.getdata() if sum(p) < 600]
    if not dark:
        return "#111111"
    avg = tuple(int(sum(p[i] for p in dark) / len(dark)) for i in range(3))
    return f"#{avg[0]:02X}{avg[1]:02X}{avg[2]:02X}"


def make_ocr() -> PaddleOCR:
    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="PP-OCRv5_mobile_rec",
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
        lines.append(
            {
                "text": text,
                "confidence": round(conf, 2),
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": height,
                "font_size_px": round(height * 0.84, 2),
                "font_family": font_for_text(text),
                "color": text_color_from_region(image, (x1, y1, x2, y2)),
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
