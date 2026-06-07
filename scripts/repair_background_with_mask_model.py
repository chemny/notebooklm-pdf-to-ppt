#!/usr/bin/env python3
"""Repair masked text regions in a slide background with an image model."""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_PROMPT = (
    "You are editing a presentation slide background. The first image is the original slide. "
    "The second image is a black-and-white mask: white regions mark old text/typography that must be removed. "
    "Remove the old text only inside the white masked regions and fill those regions naturally with the surrounding "
    "background, panels, gradients, or visual texture. Keep non-text visuals, icons, shapes, cards, photos, colors, "
    "layout, and canvas size unchanged. Do not add any new text."
)


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def call_gemini_native(
    base_url: str,
    api_key: str,
    model: str,
    image: Path,
    mask: Path,
    prompt: str,
    timeout: int,
    insecure: bool,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64(image)}},
                    {"inline_data": {"mime_type": "image/png", "data": b64(mask)}},
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    context = ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode())


def extract_image(resp: dict[str, Any]) -> tuple[str, str]:
    parts = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return inline.get("mimeType") or inline.get("mime_type") or "image/png", inline["data"]
    raise RuntimeError("response did not include an image")


def save_image(data: str, output: Path, reference: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(data)
    temp = output.with_suffix(".raw.png")
    temp.write_bytes(raw)
    ref = Image.open(reference).convert("RGB")
    img = Image.open(temp).convert("RGB")
    if img.size != ref.size:
        img = img.resize(ref.size, Image.Resampling.LANCZOS)
    img.save(output)
    temp.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair masked slide text regions with an image model")
    parser.add_argument("--image", required=True)
    parser.add_argument("--mask", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="gemini-3.1-flash-image-preview")
    parser.add_argument("--base-url", default="https://yunwu.ai")
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"missing API key env: {args.api_key_env}")
    image = Path(args.image).expanduser().resolve()
    mask = Path(args.mask).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    try:
        resp = call_gemini_native(args.base_url, api_key, args.model, image, mask, args.prompt, args.timeout, args.insecure)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    _, data = extract_image(resp)
    output.parent.mkdir(parents=True, exist_ok=True)
    response_path = output.with_suffix(".response.json")
    response_path.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    save_image(data, output, image)
    usage = resp.get("usageMetadata") or resp.get("usage_metadata") or {}
    candidate = (resp.get("candidates") or [{}])[0]
    print(
        json.dumps(
            {
                "ok": True,
                "image": str(output),
                "response": str(response_path),
                "finishReason": candidate.get("finishReason") or candidate.get("finish_reason"),
                "usage": usage,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
