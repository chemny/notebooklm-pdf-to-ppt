#!/usr/bin/env python3
"""Parse slide page structure and enforce a pre-rebuild quality gate."""

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


APPROVED_FONTS = ["Noto Sans SC", "Inter", "Source Han Sans CN", "思源黑体 CN", "Arial", "Times New Roman"]
PAGE_TYPES = {"cover", "text", "card", "flow", "diagram", "table", "data", "image", "mixed"}
EDIT_POLICIES = {"editable", "background", "image", "shape", "ignore"}

SYSTEM_PROMPT = """You are a slide page-structure parser for editable PPT reconstruction.

Return only valid JSON. No markdown fences. No explanation.

Your job is not to design a new slide. Your job is to parse the existing slide
image into a structured layout contract. Downstream PPT rebuild is forbidden
unless this structure is clear.

Use the exact original image coordinate system supplied by the user. Do not use
a normalized 1024x1024 coordinate space. All x/y/width/height values must be in
the provided canvas pixel coordinates.

For wide 16:9 slides, check your coordinates against the canvas width. If the
visual content spans most of the slide, the rightmost groups/elements should
also reach the corresponding right-side pixel range. For example, on a
1376px-wide slide, a four-step horizontal flow that visually reaches the right
side must not end near x=1024.

Classify the page type as one of:
cover, text, card, flow, diagram, table, data, image, mixed.

Parse the slide into structureGroups. A group is a meaningful visual unit, for
example a card, flow step, timeline node, title region, table, chart, or image
panel. Each group must include a tight bbox and child element ids.

For each visible element, output:
- id: stable short id
- type: text|shape|image|icon|connector|group_background|unknown
- role: title|subtitle|body|label|number|icon|connector|card|flow_node|watermark|unknown
- groupId: id of the parent structure group
- text: visible text only for text elements
- x,y,width,height in original canvas pixels
- editPolicy: editable|background|image|shape|ignore
- backgroundPolicy: keep|remove_text|extract|flatten
- fontCategory: sans|serif|handwritten|monospace|decorative|unknown
- fontCandidates: 1-3 likely fonts from this approved pool only:
  Noto Sans SC, Inter, Source Han Sans CN, 思源黑体 CN, Arial, Times New Roman
- fontSize, fontWeight, color, align, styleConfidence for text elements
- confidence: 0.0-1.0 for the element detection

Rules:
- Text must be grouped under the visual unit it belongs to. Card text must stay
  inside the correct card. Flow-step text must stay under the correct flow node.
- Do not merge text across cards, flow nodes, columns, or table cells.
- For flow pages, each step group must cover the corresponding visual node,
  number, title, and description. The set of step groups should span the same
  horizontal range as the visible flow diagram.
- Keep difficult non-text visuals as background when decomposition is risky.
- For obvious icons, set editPolicy=image only if the icon boundary is clear.
- If the page structure is unclear, lower confidence instead of pretending.
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
    schema = {
        "pageType": "card|flow|diagram|text|mixed",
        "coordinateSpace": {"width": image.width, "height": image.height},
        "summary": "short structure summary",
        "structureGroups": [
            {
                "id": "group_1",
                "type": "card|flow_step|title_region|diagram|table|image_panel|other",
                "role": "main|step|card|title|unknown",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
                "children": ["text_1", "icon_1"],
                "confidence": 0.9,
            }
        ],
        "elements": [
            {
                "id": "text_1",
                "type": "text",
                "role": "title|subtitle|body|label|number|watermark|unknown",
                "groupId": "group_1",
                "text": "visible text",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "editPolicy": "editable",
                "backgroundPolicy": "remove_text",
                "fontCategory": "sans|serif|handwritten|monospace|decorative|unknown",
                "fontCandidates": ["Noto Sans SC", "Arial"],
                "fontSize": 24,
                "fontWeight": 400,
                "color": "#111111",
                "align": ["LEFT", "CENTER"],
                "styleConfidence": 0.8,
                "confidence": 0.9,
            }
        ],
        "quality": {
            "structureConfidence": 0.0,
            "textCompleteness": 0.0,
            "bboxConfidence": 0.0,
            "styleConfidence": 0.0,
            "notes": [],
        },
    }
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"
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
                                "task": "Parse page structure for editable PPT reconstruction. Return JSON matching schema.",
                                "canvas": {"width": image.width, "height": image.height},
                                "required_gate": "Downstream rebuild is blocked unless pageType, groups, elements, bboxes, edit policies, and style evidence are clear.",
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


def clamp_box(item: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    x = float(item.get("x", 0))
    y = float(item.get("y", 0))
    w = float(item.get("width", 0))
    h = float(item.get("height", 0))
    x2 = x + w
    y2 = y + h
    x, x2 = sorted((x, x2))
    y, y2 = sorted((y, y2))
    x = max(0.0, min(float(width), x))
    y = max(0.0, min(float(height), y))
    x2 = max(0.0, min(float(width), x2))
    y2 = max(0.0, min(float(height), y2))
    item["x"] = x
    item["y"] = y
    item["width"] = max(0.0, x2 - x)
    item["height"] = max(0.0, y2 - y)
    return item


def normalize_slide(raw: dict[str, Any], image_path: Path) -> dict[str, Any]:
    image = Image.open(image_path)
    slide = {
        "image": str(image_path),
        "width": image.width,
        "height": image.height,
        "pageType": str(raw.get("pageType") or raw.get("page_type") or "mixed").lower(),
        "summary": str(raw.get("summary") or ""),
        "coordinateSpace": raw.get("coordinateSpace") or raw.get("coordinate_space") or {},
        "structureGroups": [],
        "elements": [],
        "quality": raw.get("quality") or {},
    }
    if slide["pageType"] not in PAGE_TYPES:
        slide["pageType"] = "mixed"
    for idx, group in enumerate(raw.get("structureGroups") or raw.get("structure_groups") or [], start=1):
        item = dict(group)
        item.setdefault("id", f"group_{idx}")
        item.setdefault("type", "other")
        item.setdefault("role", "unknown")
        item.setdefault("children", [])
        item.setdefault("confidence", 0)
        slide["structureGroups"].append(clamp_box(item, image.width, image.height))
    for idx, element in enumerate(raw.get("elements") or [], start=1):
        item = dict(element)
        item.setdefault("id", f"element_{idx}")
        item["type"] = str(item.get("type") or "unknown").lower()
        item.setdefault("role", "unknown")
        item.setdefault("groupId", "")
        item.setdefault("editPolicy", "background")
        item.setdefault("backgroundPolicy", "keep")
        item.setdefault("confidence", 0)
        if str(item.get("role") or "").lower() == "watermark":
            item["editPolicy"] = "ignore"
            item["backgroundPolicy"] = "keep"
        if item["type"] == "text":
            item["text"] = str(item.get("text") or "").strip()
            item.setdefault("fontCategory", "unknown")
            item.setdefault("fontCandidates", [])
            item["fontCandidates"] = [f for f in item.get("fontCandidates", []) if f in APPROVED_FONTS]
            item.setdefault("fontSize", max(12, float(item.get("height", 24)) * 0.7))
            item.setdefault("fontWeight", 400)
            item.setdefault("color", "#111111")
            item.setdefault("align", ["LEFT", "CENTER"])
            item.setdefault("styleConfidence", 0)
        slide["elements"].append(clamp_box(item, image.width, image.height))
    return slide


def text_chars(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text or ""))


def validate_slide(slide: dict[str, Any], min_confidence: float) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    width = int(slide["width"])
    height = int(slide["height"])
    coord = slide.get("coordinateSpace") or {}
    cw = int(float(coord.get("width", 0) or 0))
    ch = int(float(coord.get("height", 0) or 0))
    if cw and ch and (abs(cw - width) > 2 or abs(ch - height) > 2):
        issues.append(f"coordinate_space_mismatch:{cw}x{ch}!={width}x{height}")
    if slide.get("pageType") not in PAGE_TYPES:
        issues.append("invalid_page_type")
    if not slide.get("structureGroups"):
        issues.append("missing_structure_groups")
    text_elements = [e for e in slide.get("elements", []) if e.get("type") == "text" and e.get("role") != "watermark"]
    editable_texts = [e for e in text_elements if e.get("editPolicy") == "editable"]
    if not text_elements:
        issues.append("missing_text_elements")
    if not editable_texts:
        issues.append("no_editable_text")
    group_ids = {g.get("id") for g in slide.get("structureGroups", [])}
    for element in text_elements:
        if not element.get("groupId") or element.get("groupId") not in group_ids:
            issues.append(f"ungrouped_text:{element.get('id')}")
        if text_chars(element.get("text", "")) == 0:
            issues.append(f"empty_text:{element.get('id')}")
        if element.get("width", 0) <= 2 or element.get("height", 0) <= 2:
            issues.append(f"invalid_bbox:{element.get('id')}")
        if float(element.get("confidence", 0) or 0) < min_confidence:
            warnings.append(f"low_element_confidence:{element.get('id')}")
        if float(element.get("styleConfidence", 0) or 0) < min_confidence:
            warnings.append(f"low_style_confidence:{element.get('id')}")
        if not element.get("fontCandidates"):
            warnings.append(f"missing_font_candidates:{element.get('id')}")
    page_type = slide.get("pageType")
    if page_type == "card":
        card_groups = [g for g in slide.get("structureGroups", []) if str(g.get("type", "")).lower() in {"card", "panel"}]
        if len(card_groups) < 2:
            issues.append("card_page_missing_card_groups")
    if page_type == "flow":
        flow_groups = [g for g in slide.get("structureGroups", []) if "flow" in str(g.get("type", "")).lower() or str(g.get("role", "")).lower() == "step"]
        if len(flow_groups) < 2:
            issues.append("flow_page_missing_step_groups")
        if len(flow_groups) >= 3:
            span_left = min(float(g.get("x", 0)) for g in flow_groups)
            span_right = max(float(g.get("x", 0)) + float(g.get("width", 0)) for g in flow_groups)
            span_ratio = (span_right - span_left) / max(1.0, float(width))
            if span_ratio < 0.75:
                issues.append(f"flow_span_too_narrow:{span_ratio:.2f}")
            max_right = max(float(g.get("x", 0)) + float(g.get("width", 0)) for g in flow_groups)
            if width > 1100 and max_right <= 1120:
                issues.append("coordinate_scale_suspect:flow_groups_fit_1024_space")
    if page_type == "card":
        card_groups = [g for g in slide.get("structureGroups", []) if str(g.get("type", "")).lower() in {"card", "panel"}]
        if len(card_groups) >= 3:
            span_left = min(float(g.get("x", 0)) for g in card_groups)
            span_right = max(float(g.get("x", 0)) + float(g.get("width", 0)) for g in card_groups)
            span_ratio = (span_right - span_left) / max(1.0, float(width))
            if span_ratio < 0.65:
                issues.append(f"card_span_too_narrow:{span_ratio:.2f}")
    quality = slide.get("quality") or {}
    for key in ("structureConfidence", "textCompleteness", "bboxConfidence", "styleConfidence"):
        value = float(quality.get(key, 0) or 0)
        if value and value < min_confidence:
            warnings.append(f"low_quality_{key}:{value:.2f}")
    return {"passed": not issues, "issues": issues, "warnings": warnings}


def repair_coordinate_scale(slide: dict[str, Any]) -> dict[str, Any]:
    """Repair common model mistake: wide slide x coordinates in 1024 space."""
    width = float(slide.get("width", 0) or 0)
    if width <= 1100:
        return slide
    groups = [g for g in slide.get("structureGroups", []) if str(g.get("role", "")).lower() != "watermark"]
    if not groups:
        return slide
    max_right = max(float(g.get("x", 0)) + float(g.get("width", 0)) for g in groups)
    if max_right > 1120:
        return slide
    page_type = slide.get("pageType")
    if page_type not in {"flow", "card", "diagram", "mixed"}:
        return slide
    scale = width / 1024.0
    for collection in (slide.get("structureGroups", []), slide.get("elements", [])):
        for item in collection:
            if str(item.get("role", "")).lower() == "watermark":
                continue
            item["x"] = float(item.get("x", 0)) * scale
            item["width"] = float(item.get("width", 0)) * scale
    repairs = slide.setdefault("parseRepairs", [])
    repairs.append({"type": "x_coordinate_scale", "from": 1024, "to": width, "scale": scale})
    return slide


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse page structure and run pre-rebuild gate")
    parser.add_argument("--image", action="append")
    parser.add_argument("--input-structure", help="Validate an existing structure JSON without calling the model")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--base-url", default=os.environ.get("VISION_API_BASE_URL") or "https://yunwu.ai")
    parser.add_argument("--api-key-env", default="VISION_API_KEY")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--auto-repair-coordinate-scale", action="store_true")
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    slides: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    if args.input_structure:
        data = json.loads(Path(args.input_structure).expanduser().read_text(encoding="utf-8"))
        slides = data.get("slides", [])
    else:
        if not args.image:
            raise SystemExit("missing --image unless --input-structure is provided")
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(f"missing API key env: {args.api_key_env}")
        for raw_path in args.image:
            path = Path(raw_path).expanduser().resolve()
            print(f"structure parse: {path.name}", file=sys.stderr)
            resp = call_chat(args.base_url, api_key, args.model, path, args.timeout, args.insecure)
            slides.append(normalize_slide(resp, path))
            time.sleep(args.sleep)

    normalized_slides: list[dict[str, Any]] = []
    for idx, slide in enumerate(slides, start=1):
        if args.auto_repair_coordinate_scale:
            slide = repair_coordinate_scale(slide)
        gate = validate_slide(slide, args.min_confidence)
        gate["page"] = idx
        gate["image"] = str(slide.get("image", ""))
        gate["pageType"] = slide.get("pageType")
        gate["groups"] = len(slide.get("structureGroups", []))
        gate["elements"] = len(slide.get("elements", []))
        gate["editableText"] = sum(
            1
            for e in slide.get("elements", [])
            if e.get("type") == "text" and e.get("role") != "watermark" and e.get("editPolicy") == "editable"
        )
        normalized_slides.append(slide)
        gates.append(gate)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "mode": "page-structure-parse",
        "model": args.model,
        "gatePassed": all(g["passed"] for g in gates),
        "minConfidence": args.min_confidence,
        "slides": normalized_slides,
        "gates": gates,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "gatePassed": result["gatePassed"], "slides": len(slides), "output": str(output), "gates": gates}, ensure_ascii=False, indent=2))
    return 0 if result["gatePassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
