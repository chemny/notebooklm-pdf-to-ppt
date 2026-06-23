# Editable PPT Reconstruction

This reference defines the main technical path for turning image-based NotebookLM slide decks into editable PPTX files.

For the standard execution flow, follow `references/editable-ppt-workflow.md`. For execution rules, quality gates, and repair-pass behavior, follow `references/editable-ppt-rules.md`.

## Goal

Reconstruct a visual slide into a PowerPoint-native deck that preserves the approved NotebookLM visual result while making the most valuable parts editable.

The first stable target is not perfect full decomposition. The target is:

- editable text;
- stable text position, size, color, and alignment;
- a background layer with old replacement text removed;
- optional separate image elements when the model can identify them reliably;
- deterministic PPTX rebuild from layout JSON.

## Main Pipeline

1. Export or provide a flattened NotebookLM deck, PDF, or slide image set.
2. Render representative pages into PNG images.
3. Run PaddleOCR through `scripts/ocr_paddle_worker.py`.
4. Recover text color, ink size, ink width, and density through `scripts/style_probe.py`.
5. Group and normalize OCR text into editable text blocks in `scripts/pdf_to_ppt_simple.py`.
6. Create a clean background per page with local cleanup or optional image-model cleanup.
7. Rebuild PPTX with python-pptx from the layout JSON and clean backgrounds.
8. Render and compare representative pages before full-deck conversion.

During development, use representative pages such as `1,2,3,5,10`. Do not run full decks until representative pages pass review.

## Layout JSON Contract

The rebuild script accepts either OCR-first pages:

```json
{
  "slides": [
    {
      "image": "/absolute/path/slide_001.png",
      "width": 2752,
      "height": 1536,
      "texts": [
        {
          "text": "Unit 1 Helping at home",
          "x": 1060,
          "y": 98,
          "width": 1731,
          "height": 188,
          "font_family": "Inter",
          "font_size_px": 149.4,
          "color": "#42362A",
          "fill_color": "#FFFFFF",
          "align": "LEFT",
          "bold": true
        }
      ]
    }
  ]
}
```

Or a Codia-like element list:

```json
{
  "slides": [
    {
      "image": "/absolute/path/slide_001.png",
      "width": 2752,
      "height": 1536,
      "elements": [
        {
          "type": "text",
          "text": "Unit 1 Helping at home",
          "x": 1060,
          "y": 98,
          "width": 1731,
          "height": 188,
          "fontFamily": "Inter",
          "fontSize": 149.4,
          "color": "#42362A",
          "align": ["LEFT", "CENTER"],
          "bold": true
        },
        {
          "type": "image",
          "src": "/absolute/path/cutout.png",
          "x": 1149,
          "y": 522,
          "width": 596,
          "height": 426
        },
        {
          "type": "shape",
          "x": 744,
          "y": 282,
          "width": 270,
          "height": 8,
          "fill_color": "#0B72CE"
        }
      ]
    }
  ]
}
```

Remote image URLs are preserved in JSON but are not fetched implicitly by the rebuild script. Download assets first when separate image elements need to be rendered.

Explicit line breaks in text elements are preserved. Use them when wrapping is semantically important, such as labels, captions, table cells, diagram labels, or multi-line text blocks.

## Model Roles

- Codex or the calling agent: orchestrates files, conversion commands, QA, and packaging.
- PaddleOCR: provides text recognition, confidence, and coordinate anchors.
- Style probe: recovers visual style evidence from the original rendered page.
- Image model: optionally removes old text from complex backgrounds when local cleanup is insufficient.
- PPTX renderer: converts layout JSON into editable PowerPoint elements.

Current default model choices:

- OCR: `PP-OCRv6_small_det` + `PP-OCRv6_small_rec`.
- Background repair: `gpt-image-2` through an OpenAI-compatible image-edit endpoint when `--background model-clean` is used.

Current practical reconstruction default:

- Use `scripts/run_simple.py` as the user-facing launcher.
- Use `scripts/pdf_to_ppt_simple.py` as the maintained conversion pipeline.
- Use `scripts/ocr_paddle_worker.py` for OCR.
- Use `scripts/style_probe.py` for measured color, ink height, ink width, and density.
- Use `scripts/repair_background_with_image_model.py` only for optional model-clean backgrounds.
- Preserve key visuals for image, diagram, chart, and mixed pages even if fewer non-text elements become editable.
- Split symbols, labels, numbers, or markers into separate editable elements only when it improves editability, alignment, or styling.

## Font Policy

Use `references/fonts.md` and `references/codia-google-fonts-list.json` for font selection.

Defaults:

- Chinese text: `Noto Sans SC`
- Latin text: `Inter`
- Approved fallback pool when defaults are unavailable: `Source Han Sans CN` / `思源黑体 CN`, `Arial`, `Times New Roman`

Do not overfit decorative fonts in the first pass. Preserve visual hierarchy first; refine exact font matching after layout accuracy is acceptable.

## Quality Gates

Representative-page reconstruction must pass these checks before full conversion:

- PPTX opens without repair warnings.
- Every intended text block is selectable in PowerPoint.
- No duplicate old text remains behind editable replacement text.
- `background_text_qa.json` is clean, or failed pages are explicitly routed to image-model repair.
- Text does not overlap unrelated visual elements.
- Important visual media, diagrams, charts, and tables are not damaged by cleanup.
- Title, body, captions, labels, and other roles are differentiated enough by size and position.
- At least one screenshot comparison is inspected for representative pages.

## Known Limits

- OCR-only text extraction is not enough for complex NotebookLM slides.
- Local text masking can leave artifacts or damage illustrations; use it as the baseline mask step, then repair failed regions with the image model.
- `cover-text` mode is only a quick prototype. Complex card/layout pages should use image-model background repair before editable text is added.
- Full editable decomposition of every icon, decoration, and background object requires segmentation/layering beyond the first stable version.
- Font availability in PowerPoint depends on the target machine unless fonts are embedded or installed.
