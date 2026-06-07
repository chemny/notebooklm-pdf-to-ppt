#!/usr/bin/env python3
"""Fuse model OCR text with OCR/visual boxes for stable PPT reconstruction."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any


OCR_MARKER_RE = re.compile(r"^(?:[兴叉勾]|[A-Z]{1,2}|[xX]|[✓✔✕✖×❌✅•●■□◆◇])$")
CJK_FONT_CANDIDATES = ("Noto Sans SC", "Source Han Sans CN", "思源黑体 CN", "Arial", "Times New Roman")
LATIN_FONT_CANDIDATES = ("Inter", "Arial", "Times New Roman")
DEFAULT_CJK_FONT = CJK_FONT_CANDIDATES[0]
DEFAULT_LATIN_FONT = LATIN_FONT_CANDIDATES[0]


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def normalize_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u3400-\u9fff]+", "", text or "").lower()


def font_family_for(text: str) -> str:
    return DEFAULT_CJK_FONT if re.search(r"[\u3400-\u9fff]", text or "") else DEFAULT_LATIN_FONT


def approved_font_from_style(text: str, block: dict[str, Any]) -> str:
    candidates = block.get("fontCandidates") or block.get("font_candidates") or []
    pool = CJK_FONT_CANDIDATES if re.search(r"[\u3400-\u9fff]", text or "") else LATIN_FONT_CANDIDATES
    for family in candidates:
        if family in pool:
            return family
    category = str(block.get("fontCategory") or block.get("font_category") or "").lower()
    if not re.search(r"[\u3400-\u9fff]", text or "") and category == "serif":
        return "Times New Roman"
    return font_family_for(text)


def style_evidence(block: dict[str, Any], matched: bool) -> dict[str, Any]:
    """Separate visual style evidence from geometry/font-size locks."""
    raw_weight = block.get("fontWeight") or block.get("font_weight")
    try:
        font_weight = int(raw_weight) if raw_weight is not None else None
    except (TypeError, ValueError):
        font_weight = None
    role = str(block.get("role") or "unknown")
    confidence = float(block.get("styleConfidence") or block.get("style_confidence") or 0.0)
    explicit_bold = block.get("bold")
    evidence: list[str] = []
    source = "unknown"
    locked = False

    if explicit_bold is not None:
        source = "explicit_model_style"
        evidence.append(f"explicit_bold={bool(explicit_bold)}")
        locked = confidence >= 0.70
    elif font_weight is not None:
        source = "model_style_evidence"
        evidence.append(f"model_fontWeight={font_weight}")
        locked = role in {"title", "subtitle"} and confidence >= 0.75
    elif role in {"title", "subtitle"}:
        source = "role_default"
        font_weight = 700
        evidence.append(f"role={role}")
        locked = False
    else:
        font_weight = 400
        evidence.append("fallback_regular")

    if font_weight is None:
        font_weight = 700 if bool(explicit_bold) else 400
    if role in {"title", "subtitle"}:
        bold = True
    elif locked:
        bold = bool(explicit_bold) if explicit_bold is not None else font_weight >= 600
    else:
        bold = False
    return {
        "fontWeight": font_weight,
        "bold": bold,
        "fontWeightSource": source,
        "fontWeightLocked": bool(locked),
        "fontWeightConfidence": confidence,
        "styleEvidence": evidence,
        "styleSource": "ocr_matched_with_model_style" if matched else "model_style_only",
    }


def similarity(a: str, b: str) -> float:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return min(len(na), len(nb)) / max(len(na), len(nb))
    return SequenceMatcher(None, na, nb).ratio()


def qa_prefix(text: str) -> str:
    stripped = str(text or "").lstrip()
    if re.match(r"^Q\s*[:：]", stripped, re.IGNORECASE):
        return "q"
    if re.match(r"^A\s*[:：]", stripped, re.IGNORECASE):
        return "a"
    return ""


def union_box(items: list[dict[str, Any]]) -> dict[str, float]:
    x1 = min(float(i["x"]) for i in items)
    y1 = min(float(i["y"]) for i in items)
    x2 = max(float(i["x"]) + float(i["width"]) for i in items)
    y2 = max(float(i["y"]) + float(i["height"]) for i in items)
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def usable_words(item: dict[str, Any]) -> list[dict[str, Any]]:
    words = item.get("word_boxes") or []
    out = []
    for word in words:
        text = str(word.get("text") or "").strip()
        if not text or OCR_MARKER_RE.match(text):
            continue
        out.append(word)
    return out


def body_box(item: dict[str, Any]) -> dict[str, float]:
    words = usable_words(item)
    if len(words) >= 2:
        return union_box(words)
    return {
        "x": float(item["x"]),
        "y": float(item["y"]),
        "width": float(item["width"]),
        "height": float(item["height"]),
    }


def measured_font(items: list[dict[str, Any]], role: str, fallback: float) -> float:
    line_fonts: list[float] = []
    for item in items:
        if item.get("font_size_px"):
            value = float(item["font_size_px"])
            if value > 0:
                line_fonts.append(value)
    if line_fonts:
        return max(8.0, float(median(line_fonts)))

    heights: list[float] = []
    for item in items:
        words = usable_words(item)
        if words:
            heights.extend(float(w.get("height") or 0) for w in words if float(w.get("height") or 0) > 0)
    if not heights:
        return fallback
    values = sorted(heights)
    if role in {"body", "label", "unknown"}:
        return max(12.0, values[max(0, len(values) // 2 - 1)])
    return max(14.0, float(median(values)))


def center(item: dict[str, Any]) -> tuple[float, float]:
    return (
        float(item.get("x", 0)) + float(item.get("width", 0)) / 2,
        float(item.get("y", 0)) + float(item.get("height", 0)) / 2,
    )


def spatial_score(block: dict[str, Any], item: dict[str, Any], slide_width: float, slide_height: float) -> float:
    bx, by = center(block)
    ix, iy = center(item)
    bw = max(float(block.get("width", 1)), 1.0)
    bh = max(float(block.get("height", 1)), 1.0)
    dx = abs(bx - ix) / max(bw, slide_width * 0.12)
    dy = abs(by - iy) / max(bh, slide_height * 0.10)
    score = max(0.0, 1.0 - min(1.0, (dx * 0.55 + dy * 0.45)))
    # Same side of the slide matters more than exact y when a model places a
    # list row too low/high but still identifies the correct column.
    if column(block, slide_width) == column(item, slide_width):
        score = max(score, 0.35)
    return score


def best_match(
    block: dict[str, Any],
    ocr_texts: list[dict[str, Any]],
    role: str,
    slide_width: float,
    slide_height: float,
    used_indices: set[int] | None = None,
) -> tuple[list[int], float]:
    used_indices = used_indices or set()
    candidates = [(idx, item) for idx, item in enumerate(ocr_texts) if idx not in used_indices]
    if not candidates:
        candidates = list(enumerate(ocr_texts))
    target = normalize_text(block.get("text", ""))
    if len(target) <= 2:
        for idx, item in candidates:
            if normalize_text(item.get("text", "")) == target:
                return [idx], 1.0
        return [], 0.0

    prefix = qa_prefix(block.get("text", ""))
    if prefix:
        prefix_rows: list[tuple[int, dict[str, Any], float]] = []
        for idx, item in candidates:
            if qa_prefix(item.get("text", "")) != prefix:
                continue
            pos = spatial_score(block, item, slide_width, slide_height)
            if column(block, slide_width) == column(item, slide_width) and pos >= 0.25:
                prefix_rows.append((idx, item, pos))
        prefix_rows.sort(key=lambda row: (row[2], -float(row[1].get("y", 0))), reverse=True)
        if prefix_rows:
            first_idx, first_item, _ = prefix_rows[0]
            ids = [first_idx]
            first_y = float(first_item.get("y", 0))
            block_bottom = float(block.get("y", 0)) + float(block.get("height", 0)) + slide_height * 0.06
            block_col = column(block, slide_width)
            for idx, item in sorted(candidates, key=lambda row: float(row[1].get("y", 0))):
                if idx == first_idx:
                    continue
                y = float(item.get("y", 0))
                if y <= first_y:
                    continue
                if y > block_bottom:
                    break
                item_prefix = qa_prefix(item.get("text", ""))
                if item_prefix and item_prefix != prefix:
                    break
                if column(item, slide_width) != block_col:
                    continue
                if spatial_score(block, item, slide_width, slide_height) < 0.18:
                    continue
                ids.append(idx)
                if len(ids) >= 5:
                    break
            joined = "".join(str(ocr_texts[i].get("text", "")) for i in ids)
            score = max(similarity(block.get("text", ""), joined), 0.72)
            return ids, score

    contained: list[tuple[int, float, float]] = []
    for idx, item in candidates:
        text = normalize_text(item.get("text", ""))
        if text and text in target and len(text) >= 3:
            contained.append((idx, similarity(block.get("text", ""), item.get("text", "")), spatial_score(block, item, slide_width, slide_height)))
    if contained and role not in {"title", "subtitle"}:
        contained.sort(key=lambda row: (row[2], row[1]), reverse=True)
        # Keep nearby contained lines first. This prevents a body paragraph from
        # stealing a glossary row just because they share a phrase.
        selected = [idx for idx, sim, pos in contained if pos >= 0.28 or sim >= 0.70]
        selected = selected[:6]
        joined = "".join(str(ocr_texts[i].get("text", "")) for i in selected)
        score = similarity(block.get("text", ""), joined)
        threshold = 0.78 if role in {"title", "subtitle", "label"} else 0.65
        if score >= threshold:
            return selected, score

    scores = []
    for idx, item in candidates:
        sim = similarity(block.get("text", ""), item.get("text", ""))
        pos = spatial_score(block, item, slide_width, slide_height)
        scores.append((idx, sim, pos, sim * 0.78 + pos * 0.22))
    scores.sort(key=lambda row: row[3], reverse=True)
    threshold = 0.88 if role in {"title", "subtitle"} else (0.72 if role == "label" else 0.45)
    if scores and scores[0][1] >= threshold:
        return [scores[0][0]], scores[0][1]

    # Some model blocks merge two OCR lines; greedily join top nearby matches.
    top = [] if role in {"title", "subtitle"} else [row for row in scores[:5] if row[1] >= 0.25 and row[2] >= 0.25]
    if len(top) >= 2:
        ids = [row[0] for row in top]
        joined = "".join(str(ocr_texts[i].get("text", "")) for i in ids)
        score = similarity(block.get("text", ""), joined)
        if score >= 0.7:
            return ids, score
    return [], scores[0][1] if scores else 0.0


def scale_model_blocks(model_slide: dict[str, Any], raw_slide: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [dict(block) for block in model_slide.get("elements", [])]
    visible = [b for b in blocks if str(b.get("role") or "").lower() != "watermark"]
    if not visible:
        return blocks
    max_x = max(float(b.get("x", 0)) + float(b.get("width", 0)) for b in visible)
    max_y = max(float(b.get("y", 0)) + float(b.get("height", 0)) for b in visible)
    raw_w = float(raw_slide.get("width", 0) or 0)
    raw_h = float(raw_slide.get("height", 0) or 0)
    if raw_w > 1100 and raw_h < raw_w and max_x <= 1120 and max_y <= 1120:
        sx = raw_w / 1024.0
        sy = raw_h / 1024.0
        for block in blocks:
            if str(block.get("role") or "").lower() == "watermark":
                continue
            block["x"] = float(block.get("x", 0)) * sx
            block["width"] = float(block.get("width", 0)) * sx
            block["y"] = float(block.get("y", 0)) * sy
            block["height"] = float(block.get("height", 0)) * sy
            if block.get("fontSize"):
                block["fontSize"] = float(block["fontSize"]) * sy
    return blocks


def column(element: dict[str, Any], width: float) -> str:
    return "left" if float(element["x"]) + float(element["width"]) / 2 < width / 2 else "right"


def normalize_layout(slide: dict[str, Any], elements: list[dict[str, Any]]) -> None:
    width = float(slide["width"])
    bullet_rows = [
        e
        for e in elements
        if e.get("role") in {"body", "label", "unknown"}
        and re.match(r"^\s*[•●]", str(e.get("text") or ""))
    ]
    for side in ("left", "right"):
        rows = [e for e in bullet_rows if column(e, width) == side]
        if len(rows) < 2:
            continue
        font = float(median([float(e.get("fontSize") or 0) for e in rows if float(e.get("fontSize") or 0) > 0]))
        anchor_x = float(median([float(e["x"]) for e in rows]))
        row_width = max(float(e.get("width") or 0) for e in rows)
        for e in rows:
            e["x"] = anchor_x
            e["width"] = row_width
            e["fontSize"] = font
            lines = max(1, len(str(e.get("text") or "").splitlines()))
            e["height"] = max(float(e.get("height") or 0), lines * font * 1.22)
            e["align"] = ["LEFT", "CENTER"]
    for e in elements:
        e.pop("_matched", None)


def starts_with_list_marker(element: dict[str, Any]) -> bool:
    text = str(element.get("text") or "").lstrip()
    model_text = str(element.get("modelText") or "").lstrip()
    return bool(re.match(r"^[*＊•●]\s*", text) or re.match(r"^[*＊•●]\s*", model_text))


def representative_group_font(items: list[dict[str, Any]], group_type: str) -> float:
    values = sorted(float(item.get("fontSize") or 0) for item in items if float(item.get("fontSize") or 0) > 0)
    if not values:
        return 24.0
    med = float(median(values))
    filtered = [v for v in values if med * 0.65 <= v <= med * 1.45]
    values = filtered or values
    if group_type == "marker_list":
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * 0.68))))
        return float(values[index])
    if group_type == "panel_body":
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * 0.25))))
        return min(float(values[index]), med * 0.86)
    return float(median(values))


def merge_text_group(items: list[dict[str, Any]], group_type: str) -> dict[str, Any]:
    items = sorted(items, key=lambda item: (float(item.get("y", 0)), float(item.get("x", 0))))
    box = union_box(items)
    font = representative_group_font(items, group_type)
    merged = dict(items[0])
    lines: list[str] = []
    for item in items:
        line = str(item.get("text") or "")
        if group_type == "marker_list" and starts_with_list_marker(item) and not re.match(r"^\s*[*＊•●]", line):
            line = "* " + line.lstrip()
        lines.append(line)
    merged.update(
        {
            "text": "\n".join(lines),
            "modelText": "\n".join(str(item.get("modelText") or item.get("text") or "") for item in items),
            **box,
            "fontSize": font,
            "height": float(box["height"]),
            "fontSizeLocked": True,
            "positionLocked": True,
            "textSource": "ocr_group",
            "lineBreakSource": f"{group_type}_assembler",
            "fontSizeSource": "ocr_group_typography",
            "positionSource": "ocr_group_union",
            "lineSpacing": 1.10 if group_type == "marker_list" else 0.98,
            "source_ids": [idx for item in items for idx in (item.get("source_ids") or [])],
            "groupAssembly": {
                "type": group_type,
                "count": len(items),
                "policy": "merge_related_lines_into_one_editable_text_box",
            },
            "layoutConflict": None,
        }
    )
    return merged


def group_related_text_elements(slide: dict[str, Any], elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge obvious list/panel text rows into stable editable text groups."""
    width = float(slide["width"])
    remaining = list(elements)
    grouped_ids: set[int] = set()
    output: list[dict[str, Any]] = []

    # Star/bullet vocabulary lists are easier to edit and more stable as one
    # text box than as independent rows.
    for side in ("left", "right"):
        candidates = [
            (idx, item)
            for idx, item in enumerate(remaining)
            if idx not in grouped_ids
            and item.get("type") == "text"
            and item.get("role") in {"body", "label", "unknown"}
            and starts_with_list_marker(item)
            and column(item, width) == side
        ]
        if len(candidates) >= 2:
            candidates.sort(key=lambda row: float(row[1].get("y", 0)))
            cluster: list[tuple[int, dict[str, Any]]] = []
            for row in candidates:
                if not cluster:
                    cluster = [row]
                    continue
                prev = cluster[-1][1]
                gap = float(row[1].get("y", 0)) - (float(prev.get("y", 0)) + float(prev.get("height", 0)))
                if gap <= float(slide["height"]) * 0.12:
                    cluster.append(row)
                else:
                    if len(cluster) >= 2:
                        output.append(merge_text_group([item for _, item in cluster], "marker_list"))
                        grouped_ids.update(idx for idx, _ in cluster)
                    cluster = [row]
            if len(cluster) >= 2:
                output.append(merge_text_group([item for _, item in cluster], "marker_list"))
                grouped_ids.update(idx for idx, _ in cluster)

    # Continuous body rows in the same left/right panel should stay editable as
    # one paragraph block instead of drifting line by line.
    for side in ("left", "right"):
        candidates = [
            (idx, item)
            for idx, item in enumerate(remaining)
            if idx not in grouped_ids
            and item.get("type") == "text"
            and item.get("role") in {"body", "label", "unknown"}
            and item.get("textSource") == "ocr_exact"
            and column(item, width) == side
        ]
        candidates.sort(key=lambda row: float(row[1].get("y", 0)))
        cluster = []
        for row in candidates:
            if not cluster:
                cluster = [row]
                continue
            prev = cluster[-1][1]
            gap = float(row[1].get("y", 0)) - (float(prev.get("y", 0)) + float(prev.get("height", 0)))
            same_x_band = abs(float(row[1].get("x", 0)) - float(prev.get("x", 0))) <= float(slide["width"]) * 0.12
            if gap <= float(slide["height"]) * 0.08 and same_x_band:
                cluster.append(row)
            else:
                if len(cluster) >= 2:
                    output.append(merge_text_group([item for _, item in cluster], "panel_body"))
                    grouped_ids.update(idx for idx, _ in cluster)
                cluster = [row]
        if len(cluster) >= 2:
            output.append(merge_text_group([item for _, item in cluster], "panel_body"))
            grouped_ids.update(idx for idx, _ in cluster)

    for idx, item in enumerate(remaining):
        if idx not in grouped_ids:
            output.append(item)
    output.sort(key=lambda item: (float(item.get("y", 0)), float(item.get("x", 0))))
    return output


def raw_word_masks(raw_slide: dict[str, Any]) -> list[dict[str, Any]]:
    masks = []
    for word in raw_slide.get("words", []):
        text = str(word.get("text") or "").strip()
        if not text or OCR_MARKER_RE.match(text):
            continue
        masks.append({"x": word["x"], "y": word["y"], "width": word["width"], "height": word["height"], "text": text})
    return masks


def estimate_text_size(text: str, font_size: float) -> tuple[float, float]:
    lines = str(text or "").splitlines() or [""]
    max_chars = max((len(line) for line in lines), default=0)
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", text or ""))
    char_w = font_size * (0.88 if has_cjk else 0.56)
    width = max_chars * char_w
    height = len(lines) * font_size * 1.15
    return width, height


def render_fit_passes(text: str, box: dict[str, Any], font_size: float, matched_items: list[dict[str, Any]] | None = None) -> bool:
    if matched_items and len(matched_items) > 1:
        fit_text = "\n".join(str(item.get("text") or "") for item in matched_items)
    else:
        fit_text = text
    measured_w, measured_h = estimate_text_size(fit_text, font_size)
    return measured_w <= float(box.get("width", 0)) * 1.08 and measured_h <= float(box.get("height", 0)) * 1.20


def fit_font_to_box(text: str, box: dict[str, Any], requested_font: float, matched_items: list[dict[str, Any]] | None = None) -> float:
    fit_text = "\n".join(str(item.get("text") or "") for item in matched_items) if matched_items and len(matched_items) > 1 else text
    font = max(8.0, float(requested_font))
    max_w = max(float(box.get("width", 0)) * 1.02, 8.0)
    max_h = max(float(box.get("height", 0)) * 1.12, 8.0)
    for _ in range(24):
        measured_w, measured_h = estimate_text_size(fit_text, font)
        if measured_w <= max_w and measured_h <= max_h:
            return font
        ratio_w = max_w / measured_w if measured_w else 1.0
        ratio_h = max_h / measured_h if measured_h else 1.0
        font *= max(0.55, min(ratio_w, ratio_h, 0.96))
    return max(8.0, font)


def display_text_from_evidence(block_text: str, matched_items: list[dict[str, Any]]) -> tuple[str, str, str]:
    """Use trusted OCR text as the reconstruction contract."""
    text = str(block_text or "")
    if not matched_items:
        return text, "model_semantic", "not_applicable"

    ocr_lines = [str(item.get("text") or "").strip() for item in matched_items if str(item.get("text") or "").strip()]
    if not ocr_lines:
        return text, "model_semantic", "not_applicable"
    if len(ocr_lines) == 1:
        return ocr_lines[0], "ocr_exact", "single_ocr_anchor"
    return "\n".join(ocr_lines), "ocr_exact", "trusted_multiline_ocr_anchor"


def match_trust_threshold(role: str) -> float:
    if role in {"title", "subtitle"}:
        return 0.75
    if role in {"caption", "watermark"}:
        return 0.80
    return 0.70


def fuse(model: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    output = {"mode": "model-ocr-plus-measured-boxes", "model": model.get("model"), "slides": []}
    for model_slide, raw_slide in zip(model.get("slides", []), raw.get("slides", [])):
        ocr_texts = raw_slide.get("texts", [])
        elements = []
        used_indices: set[int] = set()
        for block in scale_model_blocks(model_slide, raw_slide):
            role = str(block.get("role") or "unknown")
            if role == "watermark":
                continue
            if not str(block.get("text") or "").strip():
                continue
            ids, score = best_match(block, ocr_texts, role, float(raw_slide["width"]), float(raw_slide["height"]), used_indices)
            trusted_match = bool(ids) and score >= match_trust_threshold(role)
            matched_items = [ocr_texts[i] for i in ids] if trusted_match else []
            if matched_items:
                used_indices.update(ids)
                matched_box = union_box([body_box(item) if role in {"body", "label", "unknown"} else item for item in matched_items])
                matched_spatial = spatial_score(block, matched_box, float(raw_slide["width"]), float(raw_slide["height"]))
                box = matched_box
                fallback_font = float(block.get("fontSize") or 24)
                font = max(measured_font(matched_items, role, fallback_font), fallback_font * 0.75)
                font_fit_passed = render_fit_passes(str(block.get("text", "")), box, font, matched_items)
                color = block.get("color") or matched_items[0].get("color") or "#2A2A2A"
                matched = True
                position_source = "ocr_visual_anchor"
                font_size_source = "ocr_measured"
                layout_conflict = None if font_fit_passed else {
                    "type": "trusted_ocr_render_fit_failed",
                    "policy": "preserve_ocr_position_and_font_size",
                    "note": "Trusted OCR geometry/font size is preserved; overflow must be diagnosed instead of auto-fitting.",
                    "matchedSpatialScore": round(matched_spatial, 3),
                }
            else:
                box = {k: float(block.get(k, 0 if k in {"x", "y"} else 100)) for k in ("x", "y", "width", "height")}
                font = float(block.get("fontSize") or max(14, box["height"] * 0.7))
                color = block.get("color") or ("#2A2A2A" if role == "body" else "#111111")
                matched = False
                font_fit_passed = True
                position_source = "model_semantic"
                font_size_source = "model_semantic"
                layout_conflict = None
            style = style_evidence(block, matched)
            display_text, text_source, line_break_source = display_text_from_evidence(str(block.get("text", "")), matched_items)
            elements.append(
                {
                    "type": "text",
                    "text": display_text,
                    "modelText": block.get("text", ""),
                    "textSource": text_source,
                    "lineBreakSource": line_break_source,
                    "role": role,
                    **box,
                    "fontFamily": approved_font_from_style(display_text, block),
                    "fontSize": font,
                    "fontSizeSource": font_size_source,
                    "fontSizeLocked": matched,
                    "color": color,
                    "bold": style["bold"],
                    "align": block.get("align") or ["LEFT", "CENTER"],
                    "fontCategory": block.get("fontCategory") or block.get("font_category") or "unknown",
                    "fontCandidates": block.get("fontCandidates") or block.get("font_candidates") or [],
                    "fontWeight": style["fontWeight"],
                    "fontWeightSource": style["fontWeightSource"],
                    "fontWeightLocked": style["fontWeightLocked"],
                    "fontWeightConfidence": style["fontWeightConfidence"],
                    "styleEvidence": style["styleEvidence"],
                    "styleSource": style["styleSource"],
                    "styleConfidence": block.get("styleConfidence") or block.get("style_confidence") or 0,
                    "positionSource": position_source,
                    "positionLocked": matched,
                    "source_ids": ids,
                    "_matched": matched,
                    "matchTrusted": trusted_match,
                    "matchTrustThreshold": match_trust_threshold(role),
                    "renderFitPassed": font_fit_passed,
                    "layoutConflict": layout_conflict,
                    "match_score": round(score, 3),
                }
            )
        normalize_layout(raw_slide, elements)
        elements = group_related_text_elements(raw_slide, elements)
        output["slides"].append(
            {
                "image": raw_slide["image"],
                "width": raw_slide["width"],
                "height": raw_slide["height"],
                "elements": elements,
                "mask_texts": raw_word_masks(raw_slide),
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuse model OCR with measured OCR boxes")
    parser.add_argument("--model-layout", required=True)
    parser.add_argument("--raw-layout", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = fuse(load_json(args.model_layout), load_json(args.raw_layout))
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "slides": len(result["slides"]), "output": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
