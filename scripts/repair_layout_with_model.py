#!/usr/bin/env python3
"""Repair slide layout JSON with an OpenAI-compatible vision chat API."""

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

from prepare_vision_layout import SCHEMA


SYSTEM_PROMPT = """You reconstruct image-based slide screenshots into editable PowerPoint layout JSON.

Return only valid JSON. No markdown fences. No explanation.
Use OCR hints only as rough hints. The attached image is the source of truth.
Merge broken OCR fragments into natural editable text boxes.
Use absolute pixel coordinates in the original image coordinate system.
All coordinates must fit inside the slide canvas: x >= 0, y >= 0, x + width <= slide.width, y + height <= slide.height.
For text boxes, prefer the OCR hint coordinates when the OCR text is correct, then adjust only enough to merge lines or improve visual fit.
Preserve visible Chinese text exactly.
Estimate fontSize in source-image pixels.
Use #RRGGBB color strings.
Use the approved reconstruction font pool only: Noto Sans SC, Inter, Source Han Sans CN, 思源黑体 CN, Arial, Times New Roman.
Do not include the full-slide background as an element.
Include separate image regions only when they are obvious independent illustrations/icons and can be bounded cleanly.
"""


def norm_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def overlap_score(a: str, b: str) -> float:
    a_n = norm_text(a)
    b_n = norm_text(b)
    if not a_n or not b_n:
        return 0.0
    if a_n in b_n or b_n in a_n:
        return min(len(a_n), len(b_n)) / max(len(a_n), len(b_n))
    common = sum(1 for ch in set(a_n) if ch in b_n)
    return common / max(len(set(a_n)), 1)


def snap_text_elements_to_ocr(parsed: dict[str, Any], ocr_texts: list[dict[str, Any]]) -> None:
    used: set[int] = set()
    for element in parsed.get("elements", []):
        if element.get("type") != "text":
            continue
        text = element.get("text", "")
        best_idx = -1
        best_score = 0.0
        for idx, hint in enumerate(ocr_texts):
            if idx in used:
                continue
            score = overlap_score(text, hint.get("text", ""))
            if score > best_score:
                best_idx = idx
                best_score = score
        if best_idx < 0 or best_score < 0.55:
            continue
        hint = ocr_texts[best_idx]
        used.add(best_idx)
        element["x"] = hint["x"]
        element["y"] = hint["y"]
        element["width"] = hint["width"]
        element["height"] = hint["height"]
        element.setdefault("fontSize", hint.get("font_size_px"))
        element.setdefault("color", hint.get("color"))


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


def call_chat(base_url: str, api_key: str, model: str, slide: dict[str, Any], timeout: int, insecure: bool = False, snap_ocr: bool = True) -> dict[str, Any]:
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"

    image_path = Path(slide["image"]).expanduser().resolve()
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
                                "task": "Return a single-slide layout JSON object with image, width, height, elements.",
                                "schema": SCHEMA["properties"]["slides"]["items"],
                                "slide": slide,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url(image_path)}},
                ],
            },
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {err}") from exc
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(strip_json(content))
    if "slides" in parsed:
        parsed = parsed["slides"][0]
    parsed.setdefault("image", slide["image"])
    parsed.setdefault("width", slide["width"])
    parsed.setdefault("height", slide["height"])
    parsed.setdefault("elements", [])
    if snap_ocr:
        snap_text_elements_to_ocr(parsed, slide.get("ocr_texts", []))
    for element in parsed["elements"]:
        element["x"] = max(0, min(float(element.get("x", 0)), float(parsed["width"])))
        element["y"] = max(0, min(float(element.get("y", 0)), float(parsed["height"])))
        element["width"] = max(1, min(float(element.get("width", 1)), float(parsed["width"]) - element["x"]))
        element["height"] = max(1, min(float(element.get("height", 1)), float(parsed["height"]) - element["y"]))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair layout JSON with a vision model")
    parser.add_argument("--package", required=True, help="vision_layout_package.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("VISION_API_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1")
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pages", help="Comma-separated 1-based package slide indices")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for local debugging only")
    parser.add_argument("--no-snap-ocr", action="store_true", help="Do not snap matching model text boxes back to OCR coordinates")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env) or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(f"Missing API key env: {args.api_key_env}", file=sys.stderr)
        return 2

    package = json.loads(Path(args.package).expanduser().read_text(encoding="utf-8"))
    slides = package["slides"]
    if args.pages:
        wanted = {int(x.strip()) for x in args.pages.split(",") if x.strip()}
        selected = [slide for idx, slide in enumerate(slides, start=1) if idx in wanted]
    else:
        selected = slides[: args.limit] if args.limit else slides

    repaired: dict[str, Any] = {
        "source": package.get("source"),
        "mode": "vision-model",
        "model": args.model,
        "slides": [],
    }
    for idx, slide in enumerate(selected, start=1):
        print(f"repairing slide {idx}/{len(selected)} with {args.model}", file=sys.stderr)
        repaired["slides"].append(call_chat(args.base_url, api_key, args.model, slide, args.timeout, args.insecure, not args.no_snap_ocr))
        time.sleep(args.sleep)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "model": args.model, "slides": len(repaired["slides"]), "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
