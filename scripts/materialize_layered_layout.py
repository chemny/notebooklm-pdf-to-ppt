#!/usr/bin/env python3
"""Filter and materialize layered layout candidates for PPTX rebuild.

This step is intentionally conservative: uncertain visual elements stay in the
background instead of becoming brittle editable/cropped objects.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def slide_key(path: str) -> str:
    return Path(path).name


def clean_map(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"clean background mapping must be page=image: {item}")
        key, value = item.split("=", 1)
        mapping[key.strip()] = str(Path(value).expanduser().resolve())
    return mapping


def shape_is_safe(element: dict[str, Any], page_area: float) -> bool:
    role = str(element.get("role") or "").lower()
    shape = str(element.get("shape") or "").lower()
    area = float(element.get("width", 0)) * float(element.get("height", 0))
    if role in {"underline", "separator", "highlight"}:
        return True
    if shape in {"line", "highlight"}:
        return True
    # Large panels/cards are often already preserved in clean backgrounds. Keep
    # them flattened unless a later page-specific strategy promotes them.
    if area > page_area * 0.025:
        return False
    return role in {"badge", "decoration"} and area > 0


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def target_color(element: dict[str, Any]) -> tuple[int, int, int] | None:
    text = f"{element.get('role','')} {element.get('notes','')}".lower()
    if "red" in text or "cross" in text:
        return (239, 68, 68)
    if "blue" in text or "check" in text:
        return (11, 114, 206)
    return None


def find_colored_bbox(image: Image.Image, element: dict[str, Any], search_pad: int = 42) -> tuple[int, int, int, int] | None:
    target = target_color(element)
    if target is None:
        return None
    x = int(float(element.get("x", 0)))
    y = int(float(element.get("y", 0)))
    w = int(float(element.get("width", 0)))
    h = int(float(element.get("height", 0)))
    x1 = max(0, x - search_pad)
    y1 = max(0, y - search_pad)
    x2 = min(image.width, x + w + search_pad)
    y2 = min(image.height, y + h + search_pad)
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    pixels = crop.load()
    xs: list[int] = []
    ys: list[int] = []
    for yy in range(crop.height):
        for xx in range(crop.width):
            r, g, b = pixels[xx, yy]
            if max(r, g, b) - min(r, g, b) < 45:
                continue
            if color_distance((r, g, b), target) < 105:
                xs.append(x1 + xx)
                ys.append(y1 + yy)
    if len(xs) < 20:
        return None
    bx1, by1, bx2, by2 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    if bx2 - bx1 < 8 or by2 - by1 < 8:
        return None
    pad = 4
    return max(0, bx1 - pad), max(0, by1 - pad), min(image.width, bx2 + pad), min(image.height, by2 + pad)


def transparent_symbol_crop(image: Image.Image, bbox: tuple[int, int, int, int], element: dict[str, Any]) -> Image.Image | None:
    target = target_color(element)
    if target is None:
        return None
    crop = image.crop(bbox).convert("RGBA")
    pix = crop.load()
    kept = 0
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b, _ = pix[x, y]
            keep = color_distance((r, g, b), target) < 120 and max(r, g, b) - min(r, g, b) > 35
            if keep:
                pix[x, y] = (r, g, b, 255)
                kept += 1
            else:
                pix[x, y] = (255, 255, 255, 0)
    if kept < 20:
        return None
    return crop


def image_is_safe(element: dict[str, Any]) -> bool:
    role = str(element.get("role") or "").lower()
    notes = str(element.get("notes") or "").lower()
    if role in {"photo", "screenshot", "chart", "diagram", "illustration"}:
        return False
    if "illustration" in notes or "chart" in notes or "diagram" in notes or "photo" in notes:
        return False
    return role in {"icon"} or "icon" in notes


def materialize(
    layout: dict[str, Any],
    base_layout: dict[str, Any] | None,
    clean_backgrounds: dict[str, str],
    out_dir: Path,
    materialize_visuals: bool = False,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base_by_key = {slide_key(s["image"]): s for s in (base_layout or {}).get("slides", [])}
    output = {
        "source": layout.get("source") or (base_layout or {}).get("source"),
        "mode": "layered-materialized-conservative",
        "model": layout.get("model"),
        "slides": [],
    }
    for idx, slide in enumerate(layout.get("slides", []), start=1):
        key = slide_key(slide["image"])
        base_slide = base_by_key.get(key)
        new_slide = {
            "image": slide["image"],
            "width": slide["width"],
            "height": slide["height"],
            "page_type": slide.get("page_type"),
            "elements": [],
        }
        if key in clean_backgrounds:
            new_slide["clean_background"] = clean_backgrounds[key]
        elif slide.get("clean_background"):
            new_slide["clean_background"] = slide["clean_background"]

        # Prefer the stable base text layout when provided; layered model output
        # contributes only conservative shape/image candidates.
        if base_slide:
            for element in base_slide.get("elements", []):
                if str(element.get("type") or "").lower() == "text":
                    new_slide["elements"].append(element)
        else:
            for element in slide.get("elements", []):
                if str(element.get("type") or "").lower() == "text":
                    new_slide["elements"].append(element)

        if not materialize_visuals:
            output["slides"].append(new_slide)
            continue

        page_area = float(slide["width"]) * float(slide["height"])
        for element in slide.get("elements", []):
            if str(element.get("type") or "").lower() == "shape" and shape_is_safe(element, page_area):
                new_slide["elements"].append(element)

        source_image = Image.open(slide["image"]).convert("RGB")
        asset_dir = out_dir / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        for element in slide.get("elements", []):
            if str(element.get("type") or "").lower() != "image" or not image_is_safe(element):
                continue
            bbox = find_colored_bbox(source_image, element)
            if bbox is None:
                continue
            crop = transparent_symbol_crop(source_image, bbox, element)
            if crop is None:
                continue
            asset_path = asset_dir / f"slide_{idx:03d}_image_{len(list(asset_dir.glob(f'slide_{idx:03d}_image_*.png'))) + 1:02d}.png"
            crop.save(asset_path)
            x1, y1, x2, y2 = bbox
            new_slide["elements"].append(
                {
                    **element,
                    "type": "image",
                    "src": str(asset_path),
                    "x": x1,
                    "y": y1,
                    "width": x2 - x1,
                    "height": y2 - y1,
                    "materialized": True,
                }
            )
        output["slides"].append(new_slide)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Conservatively materialize layered layout candidates")
    parser.add_argument("--layered-layout", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-layout", help="Stable layout whose text elements should be reused")
    parser.add_argument("--clean-background", action="append", default=[], help="Mapping like slide_001.png=/abs/clean.jpg")
    parser.add_argument(
        "--materialize-visuals",
        action="store_true",
        help="Promote selected shape/icon candidates to PPTX elements. Off by default to avoid duplicate visuals.",
    )
    args = parser.parse_args()

    layered_path = Path(args.layered_layout).expanduser().resolve()
    out_path = Path(args.output).expanduser().resolve()
    layered = load_json(layered_path)
    base = load_json(args.base_layout) if args.base_layout else None
    output = materialize(layered, base, clean_map(args.clean_background), out_path.parent, args.materialize_visuals)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "slides": len(output["slides"]), "output": str(out_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
