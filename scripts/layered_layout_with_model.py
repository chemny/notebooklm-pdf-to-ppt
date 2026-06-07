#!/usr/bin/env python3
"""Create layered slide layout JSON with text, shape, and image elements."""

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


SYSTEM_PROMPT = """You reconstruct slide screenshots into layered editable PowerPoint layout JSON.

Return only valid JSON. No markdown fences. No explanation.

The attached image is the source of truth. OCR hints are only coordinate and text hints.
Use absolute pixel coordinates in the original image coordinate system.

Goal:
- Identify the slide page_type.
- Reconstruct high-value editable text.
- Add simple stable shape elements such as rectangles, rounded cards, lines, underlines, badges, separators, and highlight bars.
- Add image elements only for obvious independent visual regions that can be cropped cleanly.
- Keep complex photos, charts, diagrams, illustrations, or fused decorations in the background when uncertain.

Rules:
- Do not include the full-slide background as an element.
- Do not over-decompose tiny decorations.
- Keep coordinates inside the canvas.
- Preserve visible Chinese text exactly.
- Correct obvious OCR errors.
- Preserve meaningful line breaks in text with \\n.
- Use #RRGGBB colors.
- Use the approved reconstruction font pool only: Noto Sans SC, Inter, Source Han Sans CN, 思源黑体 CN, Arial, Times New Roman.
- For shapes, output fillColor, radius when useful, and role when useful.
- For image elements, output crop_role and notes; src can be empty because local cropping will happen later.
"""


def data_url(path: Path) -> str:
    mime = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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


def schema() -> dict[str, Any]:
    return {
        "page_type": "cover|text|card|diagram|data|image|mixed",
        "image": "/absolute/path/to/source-slide.png",
        "width": 1376,
        "height": 768,
        "elements": [
            {
                "type": "text",
                "role": "title|subtitle|body|caption|label|table_cell|watermark|unknown",
                "text": "visible text",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "fontFamily": "Noto Sans SC",
                "fontSize": 32,
                "color": "#111111",
                "bold": False,
                "align": ["LEFT", "CENTER"],
                "source_ids": [0],
            },
            {
                "type": "shape",
                "shape": "rect|rounded_rect|line|circle|badge|highlight",
                "role": "panel|underline|separator|highlight|decoration|unknown",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "fillColor": "#FFFFFF",
                "radius": 8,
                "opacity": 1.0,
            },
            {
                "type": "image",
                "role": "photo|icon|logo|screenshot|illustration|chart|diagram|unknown",
                "crop_role": "local_crop_needed",
                "src": "",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
                "notes": "crop this region from source image",
            },
        ],
    }


def call_chat(base_url: str, api_key: str, model: str, slide: dict[str, Any], timeout: int, insecure: bool) -> dict[str, Any]:
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"

    ocr_items = [{"id": idx, **item} for idx, item in enumerate(slide.get("ocr_texts", []))]
    user_payload = {
        "task": "Return one layered slide layout JSON object matching the schema. Include page_type, text elements, simple stable shape elements, and obvious independent image regions.",
        "canvas": {"width": slide["width"], "height": slide["height"]},
        "schema": schema(),
        "ocr_items": ocr_items,
    }
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)},
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
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(strip_json(content))
    if "slides" in parsed:
        parsed = parsed["slides"][0]
    parsed.setdefault("image", slide["image"])
    parsed.setdefault("width", slide["width"])
    parsed.setdefault("height", slide["height"])
    parsed.setdefault("page_type", "mixed")
    parsed.setdefault("elements", [])
    return normalize_slide(parsed, slide)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def normalize_slide(parsed: dict[str, Any], source_slide: dict[str, Any]) -> dict[str, Any]:
    width = float(parsed.get("width") or source_slide["width"])
    height = float(parsed.get("height") or source_slide["height"])
    out = {
        "image": source_slide["image"],
        "width": int(width),
        "height": int(height),
        "page_type": parsed.get("page_type") or "mixed",
        "elements": [],
    }
    for element in parsed.get("elements", []):
        typ = str(element.get("type") or "").lower()
        if typ not in {"text", "shape", "image"}:
            continue
        x = clamp(float(element.get("x", 0)), 0, width - 1)
        y = clamp(float(element.get("y", 0)), 0, height - 1)
        w = clamp(float(element.get("width", 1)), 1, width - x)
        h = clamp(float(element.get("height", 1)), 1, height - y)
        item = {**element, "type": typ, "x": x, "y": y, "width": w, "height": h}
        if typ == "text":
            if not str(item.get("text") or "").strip():
                continue
            item.setdefault("fontFamily", "Noto Sans SC")
            item.setdefault("fontSize", max(12, h * 0.7))
            item.setdefault("color", "#111111")
            item.setdefault("align", ["LEFT", "CENTER"])
            item.setdefault("role", "unknown")
        elif typ == "shape":
            item.setdefault("shape", "rect")
            item.setdefault("fillColor", item.get("fill_color") or "#FFFFFF")
            item.setdefault("role", "unknown")
        elif typ == "image":
            # The current rebuild path only renders local image src files. Keep
            # proposed image regions in JSON for v2.3 cropping, but do not
            # render empty/remote sources yet.
            item.setdefault("src", "")
            item.setdefault("role", "unknown")
        out["elements"].append(item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build layered layout JSON from a vision model")
    parser.add_argument("--package", required=True, help="vision_layout_package.json")
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

    output = {"source": package.get("source"), "mode": "layered-model", "model": args.model, "slides": []}
    for idx, slide in enumerate(selected, start=1):
        print(f"layered repair slide {idx}/{len(selected)} with {args.model}", file=sys.stderr)
        output["slides"].append(call_chat(args.base_url, api_key, args.model, slide, args.timeout, args.insecure))
        time.sleep(args.sleep)

    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "model": args.model, "slides": len(output["slides"]), "output": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
