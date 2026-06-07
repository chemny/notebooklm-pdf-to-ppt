#!/usr/bin/env python3
"""Use a vision model as OCR/layout extractor for slide images."""

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

from PIL import Image


SYSTEM_PROMPT = """You are a slide OCR and layout extraction engine.

Return only valid JSON. No markdown fences. No explanation.

Extract visible text blocks from the slide image. Include all important visible
text. Exclude non-text icons such as red crosses, blue checkmarks, bullets,
decorative diamonds, logos, and background shapes.

For each text block, output approximate pixel coordinates in the original image
coordinate system. Keep coordinates tight around the text, not around icons.

Do not create duplicate blocks: if a phrase is part of a full sentence, output
the sentence as one text block, not an extra heading fragment unless it is
visually separate.

Estimate role only: title, subtitle, body, caption, watermark, label, unknown.
Estimate font size from the visual appearance, but keep same-level text
consistent.

Also estimate text style evidence for each block. This is not a final font
decision; it is evidence for later font mapping. Output:
- fontCategory: sans|serif|handwritten|monospace|decorative|unknown
- fontCandidates: 1-3 likely families from the approved pool only:
  Noto Sans SC, Inter, Source Han Sans CN, 思源黑体 CN, Arial, Times New Roman
- fontWeight: one of 300, 400, 500, 600, 700, 800
- styleConfidence: 0.0-1.0
"""


def data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() not in {".jpg", ".jpeg"} else "image/jpeg"
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


def call_chat(base_url: str, api_key: str, model: str, image_path: Path, timeout: int, insecure: bool) -> dict[str, Any]:
    image = Image.open(image_path)
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"
    schema = {
        "blocks": [
            {
                "text": "visible text",
                "role": "title|subtitle|body|caption|watermark|label|unknown",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "fontSize": 24,
                "color": "#111111",
                "bold": False,
                "align": ["LEFT", "CENTER"],
                "fontCategory": "sans|serif|handwritten|monospace|decorative|unknown",
                "fontCandidates": ["Noto Sans SC", "Arial"],
                "fontWeight": 400,
                "styleConfidence": 0.75,
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
                                "task": "Extract slide text blocks and approximate layout. Return JSON matching schema.",
                                "canvas": {"width": image.width, "height": image.height},
                                "schema": schema,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url(image_path)}},
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


def normalize_block(block: dict[str, Any]) -> dict[str, Any] | None:
    text = str(block.get("text") or "").strip()
    if not text:
        return None
    role = str(block.get("role") or "unknown")
    color = block.get("color") or "#111111"
    if role == "body":
        color = "#2A2A2A"
    return {
        "type": "text",
        "text": text,
        "role": role,
        "x": float(block.get("x", 0)),
        "y": float(block.get("y", 0)),
        "width": float(block.get("width", 100)),
        "height": float(block.get("height", max(24, float(block.get("fontSize", 24))))),
        "fontFamily": "Noto Sans SC" if re.search(r"[\u3400-\u9fff]", text) else "Inter",
        "fontSize": float(block.get("fontSize") or 24),
        "color": color,
        "bold": bool(block.get("bold", role in {"title", "subtitle"})),
        "align": block.get("align") or ["LEFT", "CENTER"],
        "fontCategory": block.get("fontCategory") or block.get("font_category") or "unknown",
        "fontCandidates": block.get("fontCandidates") or block.get("font_candidates") or [],
        "fontWeight": int(block.get("fontWeight") or block.get("font_weight") or (700 if block.get("bold", role in {"title", "subtitle"}) else 400)),
        "styleConfidence": float(block.get("styleConfidence") or block.get("style_confidence") or 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Model-only OCR/layout extraction for slide images")
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--base-url", default=os.environ.get("VISION_API_BASE_URL") or "https://yunwu.ai")
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"missing API key env: {args.api_key_env}")
    slides: list[dict[str, Any]] = []
    for raw_path in args.image:
        path = Path(raw_path).expanduser().resolve()
        image = Image.open(path)
        print(f"model OCR: {path.name}", file=sys.stderr)
        resp = call_chat(args.base_url, api_key, args.model, path, args.timeout, args.insecure)
        elements = []
        for block in resp.get("blocks", []):
            item = normalize_block(block)
            if item:
                elements.append(item)
        slides.append({"image": str(path), "width": image.width, "height": image.height, "elements": elements})
        time.sleep(args.sleep)
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "model-ocr-layout", "model": args.model, "slides": slides}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "slides": len(slides), "output": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
