#!/usr/bin/env python3
"""Create a PPTX from experimental layout JSON using LibreOffice UNO."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import uno
import officehelper
from com.sun.star.awt import Point, Size
from com.sun.star.beans import PropertyValue
from com.sun.star.drawing import TextVerticalAdjust
from com.sun.star.style import ParagraphAdjust


SLIDE_W_CM = 33.8667
SLIDE_H_CM = 19.05
SLIDE_W_100MM = int(SLIDE_W_CM * 1000)
SLIDE_H_100MM = int(SLIDE_H_CM * 1000)
FONT_SCALE = 1.03


def prop(name: str, value: Any) -> PropertyValue:
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def file_url(path: str | Path) -> str:
    return uno.systemPathToFileUrl(str(Path(path).expanduser().resolve()))


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def font_for(text: str, item: dict[str, Any]) -> str:
    return str(item.get("font_family") or item.get("fontFamily") or ("Noto Sans SC" if contains_cjk(text) else "Inter"))


def color_int(value: str | None, default: str = "#111111") -> int:
    raw = str(value or default)
    if not re.match(r"^#[0-9A-Fa-f]{6}$", raw):
        raw = default
    return int(raw[1:], 16)


def to_x(px: float, img_w: float) -> int:
    return int(float(px or 0) / img_w * SLIDE_W_100MM)


def to_y(px: float, img_h: float) -> int:
    return int(float(px or 0) / img_h * SLIDE_H_100MM)


def font_pt(item: dict[str, Any], img_h: float) -> float:
    return max(1.0, float(item.get("font_size_px") or 28) * 7.5 / img_h * 72 * FONT_SCALE)


def paragraph_adjust(value: Any) -> Any:
    raw = value[0] if isinstance(value, list) and value else value
    text = str(raw or "LEFT").lower()
    if text == "center":
        return ParagraphAdjust.CENTER
    if text == "right":
        return ParagraphAdjust.RIGHT
    if text in {"justify", "justified"}:
        return ParagraphAdjust.BLOCK
    return ParagraphAdjust.LEFT


def add_background(doc: Any, page: Any, image_path: str) -> None:
    shape = doc.createInstance("com.sun.star.drawing.GraphicObjectShape")
    shape.Position = Point(0, 0)
    shape.Size = Size(SLIDE_W_100MM, SLIDE_H_100MM)
    shape.GraphicURL = file_url(image_path)
    page.add(shape)
    shape.ZOrder = 0


def add_text(doc: Any, page: Any, item: dict[str, Any], img_w: float, img_h: float) -> None:
    text = str(item.get("text") or "")
    shape = doc.createInstance("com.sun.star.drawing.TextShape")
    shape.Position = Point(to_x(item.get("x", 0), img_w), to_y(item.get("y", 0), img_h))
    shape.Size = Size(max(200, to_x(item.get("width", 100), img_w)), max(200, to_y(item.get("height", 30), img_h)))
    shape.TextAutoGrowHeight = False
    shape.TextAutoGrowWidth = False
    shape.TextWordWrap = True
    shape.TextLeftDistance = 0
    shape.TextRightDistance = 0
    shape.TextUpperDistance = 0
    shape.TextLowerDistance = 0
    shape.TextVerticalAdjust = TextVerticalAdjust.TOP
    shape.FillStyle = 0
    shape.LineStyle = 0
    page.add(shape)
    shape.String = text
    shape.CharFontName = font_for(text, item)
    shape.CharFontNameAsian = font_for(text, item)
    shape.CharHeight = font_pt(item, img_h)
    shape.CharHeightAsian = font_pt(item, img_h)
    shape.CharColor = color_int(item.get("color"))
    shape.CharWeight = 150.0 if item.get("bold") else 100.0
    shape.CharWeightAsian = 150.0 if item.get("bold") else 100.0
    shape.ParaAdjust = paragraph_adjust(item.get("align"))
    shape.ZOrder = 10


def build(layout: dict[str, Any], output: Path, background_key: str) -> None:
    ctx = officehelper.bootstrap()
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    doc = desktop.loadComponentFromURL("private:factory/simpress", "_blank", 0, ())
    doc.Width = SLIDE_W_100MM
    doc.Height = SLIDE_H_100MM
    pages = doc.DrawPages
    while pages.Count > 1:
        pages.remove(pages.getByIndex(pages.Count - 1))
    slides = layout.get("slides", [])
    for idx, page_data in enumerate(slides):
        if idx == 0:
            page = pages.getByIndex(0)
        else:
            page = pages.insertNewByIndex(idx)
        img_w = float(page_data.get("width") or 3440)
        img_h = float(page_data.get("height") or 1920)
        add_background(doc, page, page_data.get(background_key) or page_data.get("image"))
        for item in page_data.get("texts", []):
            add_text(doc, page, item, img_w, img_h)
    output.parent.mkdir(parents=True, exist_ok=True)
    out_url = file_url(output)
    doc.storeAsURL(out_url, (prop("FilterName", "Impress MS PowerPoint 2007 XML"), prop("Overwrite", True)))
    doc.close(True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render layout JSON to PPTX through LibreOffice UNO")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--background-key", default="clean_background")
    args = parser.parse_args()
    layout = json.loads(Path(args.layout).expanduser().read_text(encoding="utf-8"))
    build(layout, Path(args.output).expanduser(), args.background_key)
    print(json.dumps({"ok": True, "pptx": str(Path(args.output).expanduser().resolve()), "slides": len(layout.get("slides", []))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
