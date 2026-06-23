#!/usr/bin/env python3
"""Create clean slide backgrounds with image generation/editing models."""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_PROMPT = (
    "Create a clean background version of this presentation slide. "
    "Keep the canvas, illustrations, icons, shapes, and non-text visual design. "
    "Omit all typography, captions, logos, and small footer marks. "
    "Return an edited image at the same aspect ratio."
)


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def write_image(out_dir: Path, name: str, mime: str, data: str) -> Path:
    ext = "jpg" if "jpeg" in mime.lower() or "jpg" in mime.lower() else "png"
    path = out_dir / f"{name}.{ext}"
    path.write_bytes(base64.b64decode(data))
    return path


def call_gemini_native(base_url: str, api_key: str, model: str, image: Path, prompt: str, timeout: int, insecure: bool) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64(image)}},
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


def extract_gemini_image(resp: dict[str, Any]) -> tuple[str, str]:
    parts = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return inline.get("mimeType") or inline.get("mime_type") or "image/png", inline["data"]
    raise RuntimeError("Gemini response did not include an image")


def multipart_body(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----notebooklm-pdf-to-ppt-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for name, (filename, data, mime) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {mime}\r\n\r\n".encode(),
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def image_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def call_openai_image(base_url: str, api_key: str, model: str, image: Path, prompt: str, size: str, timeout: int, insecure: bool) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1/images/edits"
    fields = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": "1",
        "response_format": "b64_json",
    }
    body, boundary = multipart_body(
        fields,
        {"image": (image.name, image.read_bytes(), image_mime(image))},
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    context = ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode())


def extract_openai_image(resp: dict[str, Any]) -> tuple[str, str]:
    item = (resp.get("data") or [{}])[0]
    if item.get("b64_json"):
        return "image/png", item["b64_json"]
    raise RuntimeError("OpenAI image response did not include b64_json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair slide background with an image model")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--provider", choices=["gemini-native", "openai-image"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("VISION_API_BASE_URL", "https://api.openai.com"))
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--size", default="1536x864")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for local debugging only")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"missing API key env: {args.api_key_env}")
    image = Path(args.image).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.provider == "gemini-native":
            resp = call_gemini_native(args.base_url, api_key, args.model, image, args.prompt, args.timeout, args.insecure)
            mime, data = extract_gemini_image(resp)
        else:
            resp = call_openai_image(args.base_url, api_key, args.model, image, args.prompt, args.size, args.timeout, args.insecure)
            mime, data = extract_openai_image(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc

    response_path = out_dir / f"{args.model}.response.json"
    response_path.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    image_path = write_image(out_dir, f"{args.model}.clean_background", mime, data)
    usage = resp.get("usageMetadata") or resp.get("usage_metadata") or resp.get("usage") or {}
    candidate = (resp.get("candidates") or [{}])[0]
    print(
        json.dumps(
            {
                "ok": True,
                "model": args.model,
                "provider": args.provider,
                "image": str(image_path),
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
