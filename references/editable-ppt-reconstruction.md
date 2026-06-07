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

1. Export NotebookLM deck with notebooklm-py.
2. Extract representative slide images from the PPTX or PDF.
3. Run local OCR to create `layout.raw.json`.
4. Use a vision model to create an OCR-anchored semantic layout.
5. Build text masks from OCR word boxes plus model-repaired text boxes.
6. Create a clean background per page and run OCR residual-text QA.
7. Repair failed masked regions with the image model when local cleanup leaves old text or visible artifacts.
8. Rebuild PPTX from the repaired layout JSON with clean backgrounds and selected editable elements.
9. Render and compare representative pages before full-deck conversion.

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

- Codex: orchestrates files, layout repair prompts, deterministic PPTX rebuild, QA, and packaging.
- Vision model: extracts or repairs text, layout, hierarchy, font size, color, alignment, and obvious image regions.
- Image model: removes text from backgrounds or repairs local regions when local masking is insufficient.
- PPTX renderer: converts layout JSON into editable PowerPoint elements.

Current default model choices:

- Layout reconstruction: start with `gemini-3.5-flash` for representative-page experiments.
- Low-cost layout baseline: `gemini-2.5-flash`, but do not use it directly for final PPT rebuild when complex pages are involved.
- Background repair: default to `gemini-3.1-flash-image-preview` through the Gemini native `generateContent` endpoint.
- Background repair comparison model: `gpt-image-2-all` through OpenAI-compatible `/v1/images/edits` when the provider supports image editing.

Current practical reconstruction default:

- Use `semantic_layout_with_model.py` for layout. The model repairs text and grouping, but coordinates stay anchored to OCR boxes.
- Use `scripts/build_text_masks.py` to create mask images, clean backgrounds, and `background_text_qa.json`.
- Add raw OCR text/word boxes as `mask_texts` when text removal is needed. These mask hints are for cleanup only and should not become duplicate editable text.
- Use page-specific clean backgrounds based on the slide classification. Preserve key visuals for image, diagram, chart, and mixed pages even if fewer non-text elements become editable.
- Treat any residual old text in `background_text_qa.json` as a repair task before final delivery.
- Build with `text-overlay` and `--background-key clean_background` after the clean background is ready.
- Split symbols, labels, numbers, or markers into separate editable elements only when it improves editability, alignment, or styling.

Layered reconstruction experiment:

- Use `scripts/layered_layout_with_model.py` when testing higher-fidelity reconstruction with page classification plus `text`, `shape`, and `image` regions.
- Treat model-proposed `shape` and `image` regions as candidates, not truth. They must pass screenshot QA before replacing the default OCR-anchored text workflow.
- Image/icon regions need materialization into local crops or a later mask/inpainting step before they can improve final PPTX quality.
- Use `scripts/materialize_layered_layout.py` for conservative candidate materialization. Visual candidates are off by default; enable `--materialize-visuals` only after representative-page QA proves the extraction is stable.

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
