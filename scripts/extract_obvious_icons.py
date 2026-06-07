#!/usr/bin/env python3
"""Extract obvious saturated red/blue icons and remove them from backgrounds."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from editable_deck import sample_fill_color


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def text_boxes(slide: dict[str, Any], pad: int = 8) -> list[tuple[int, int, int, int]]:
    boxes = []
    for element in slide.get("elements", []):
        if str(element.get("type") or "").lower() != "text":
            continue
        x1 = max(0, int(float(element.get("x", 0))) - pad)
        y1 = max(0, int(float(element.get("y", 0))) - pad)
        x2 = int(float(element.get("x", 0)) + float(element.get("width", 0))) + pad
        y2 = int(float(element.get("y", 0)) + float(element.get("height", 0))) + pad
        boxes.append((x1, y1, x2, y2))
    return boxes


def is_icon_color(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    blue = b > 120 and g > 70 and b > r + 45 and g > r + 20
    red = r > 180 and r > g + 45 and r > b + 45
    return blue or red


def connected_components(mask: list[list[bool]], width: int, height: int) -> list[tuple[int, int, int, int, int]]:
    seen = [[False] * width for _ in range(height)]
    comps: list[tuple[int, int, int, int, int]] = []
    for y in range(height):
        for x in range(width):
            if seen[y][x] or not mask[y][x]:
                continue
            q = deque([(x, y)])
            seen[y][x] = True
            xs: list[int] = []
            ys: list[int] = []
            while q:
                cx, cy = q.popleft()
                xs.append(cx)
                ys.append(cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if seen[ny][nx] or not mask[ny][nx]:
                        continue
                    seen[ny][nx] = True
                    q.append((nx, ny))
            comps.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(xs)))
    return comps


def transparent_crop(image: Image.Image, bbox: tuple[int, int, int, int], pad: int = 6) -> Image.Image:
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(image.width, x2 + pad)
    y2 = min(image.height, y2 + pad)
    crop = image.crop((x1, y1, x2, y2)).convert("RGBA")
    pix = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b, _ = pix[x, y]
            if is_icon_color((r, g, b)):
                pix[x, y] = (r, g, b, 255)
            else:
                pix[x, y] = (255, 255, 255, 0)
    return crop


def extract_for_slide(
    slide: dict[str, Any],
    out_dir: Path,
    idx: int,
    min_area: int,
    max_area_ratio: float,
    base_background_dir: Path | None,
) -> tuple[list[dict[str, Any]], str]:
    image = Image.open(slide["image"]).convert("RGB")
    avoid = text_boxes(slide)
    pix = image.load()
    mask = [[False] * image.width for _ in range(image.height)]
    for y in range(image.height):
        for x in range(image.width):
            if is_icon_color(pix[x, y]):
                mask[y][x] = True

    page_area = image.width * image.height
    icon_elements: list[dict[str, Any]] = []
    if base_background_dir:
        candidate = base_background_dir / Path(slide["image"]).name
        clean = Image.open(candidate).convert("RGB") if candidate.exists() else image.copy()
    else:
        clean = image.copy()
    draw = ImageDraw.Draw(clean)
    asset_dir = out_dir / "icons"
    asset_dir.mkdir(parents=True, exist_ok=True)
    clean_dir = out_dir / "cleaned"
    clean_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for x1, y1, x2, y2, area in connected_components(mask, image.width, image.height):
        w, h = x2 - x1, y2 - y1
        if area < min_area or w < 10 or h < 10:
            continue
        if area > page_area * max_area_ratio:
            continue
        bbox = (x1, y1, x2, y2)
        if any(overlaps(bbox, box) for box in avoid):
            continue
        count += 1
        crop = transparent_crop(image, bbox)
        icon_path = asset_dir / f"slide_{idx:03d}_icon_{count:02d}.png"
        crop.save(icon_path)
        pad = 8
        rx1, ry1 = max(0, x1 - pad), max(0, y1 - pad)
        rx2, ry2 = min(image.width, x2 + pad), min(image.height, y2 + pad)
        fill = sample_fill_color(clean, (rx1, ry1, rx2, ry2))
        draw.rounded_rectangle((rx1, ry1, rx2, ry2), radius=4, fill=fill)
        icon_elements.append(
            {
                "type": "image",
                "src": str(icon_path),
                "x": max(0, x1 - 6),
                "y": max(0, y1 - 6),
                "width": crop.width,
                "height": crop.height,
                "role": "icon",
            }
        )
    clean_path = clean_dir / Path(slide["image"]).name
    clean.save(clean_path)
    return icon_elements, str(clean_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract obvious red/blue icons from slide images")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-area", type=int, default=80)
    parser.add_argument("--max-area-ratio", type=float, default=0.035)
    parser.add_argument("--base-background-dir", help="Optional directory of text-clean backgrounds to remove icons from")
    args = parser.parse_args()

    layout = load_json(args.layout)
    out_dir = Path(args.output_dir).expanduser().resolve()
    base_background_dir = Path(args.base_background_dir).expanduser().resolve() if args.base_background_dir else None
    for idx, slide in enumerate(layout.get("slides", []), start=1):
        icons, clean_bg = extract_for_slide(slide, out_dir, idx, args.min_area, args.max_area_ratio, base_background_dir)
        existing = slide.get("elements") or []
        text = [e for e in existing if str(e.get("type") or "").lower() == "text"]
        slide["elements"] = icons + text
        slide["clean_background"] = clean_bg
    output = Path(args.output).expanduser().resolve()
    write_json(output, layout)
    total = sum(1 for s in layout.get("slides", []) for e in s.get("elements", []) if e.get("type") == "image")
    print(json.dumps({"ok": True, "icons": total, "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
