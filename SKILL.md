---
name: notebooklm-pdf-to-ppt
description: Convert image-based NotebookLM slide PDFs/PPTX exports into editable PowerPoint decks. Use when the user wants PDF/PPT image slides reconstructed as editable PPTX with clean backgrounds and editable text, separate from NotebookLM content generation.
version: 0.1.0
---

# NotebookLM PDF To PPT

Use this skill for the **editable reconstruction** problem: converting flattened NotebookLM slide exports, PDFs, or image-based PPTX files into editable PowerPoint decks.

This skill is separate from `notebooklm-course-studio`:

- `notebooklm-course-studio` owns NotebookLM content workflow: source import, content generation, artifact revision, and export.
- `notebooklm-pdf-to-ppt` owns post-export reconstruction: parse pages, clean backgrounds, rebuild editable PPTX, preview, and diagnose fidelity problems.

Do not use this skill to ask NotebookLM to generate course content, podcasts, study guides, or new slide artifacts. Use it only after a PDF/PPTX/image export already exists or when the user explicitly asks for editable reconstruction.

## Current Status

This skill is under active development. The default path is now a small, inspectable PDF-to-editable-PPTX tool rather than the older multi-model fusion stack. It can run representative-page experiments, but it is not yet a reliable 90%+ full-deck converter.

Known current conclusions:

- PaddleOCR is stronger than the previous OCR for text recognition and many text boxes, but the latest Paddle/style fusion experiment was not visually better because fusion rules broke grouping, titles, and style placement.
- Use PaddleOCR as the preferred OCR engine when available, with Tesseract as fallback. Do not promote the older Paddle/style fusion experiment to the default main flow until representative pages show clear visual improvement.
- PPTXGenJS and LibreOffice rendering differences are secondary. When structure, text, coordinates, or grouping are wrong, the root cause is the layout/fusion layer, not the PPTX renderer.
- LibreOffice is useful for preview, conversion, and round-trip validation. PPTXGenJS is useful for deterministic PPTX generation from layout JSON.

## Operating Principle

The user should interact by chat. Internally, run scripts and models as needed, but present the result as visual previews and concise diagnoses.

Always separate the two failure domains:

- **OCR / parsing / fusion** owns text content, reading order, grouping, coordinates, font size, color, style evidence, and whether text should be editable.
- **PPTX rebuild** owns unit conversion, font substitution, text-box margins, line spacing, paragraph spacing, and renderer-specific output.

Do not let one layer compensate for the other. If OCR is wrong, fix OCR/parsing/fusion. If layout JSON is right but preview is wrong, fix the renderer.

## Default Workflow

Use `scripts/run_simple.py` as the default entrypoint for normal PDF-to-PPTX conversion tests. It launches `scripts/pdf_to_ppt_simple.py` through a stable wrapper because direct script startup can stall on this local macOS Python environment.

Default command shape:

```bash
PYTHONDONTWRITEBYTECODE=1 python scripts/run_simple.py \
  --pdf /path/to/source.pdf \
  --pages 1,2 \
  --output-dir /path/to/output \
  --ocr auto \
  --background local-clean
```

This default path is intentionally simple:

1. Render selected PDF pages into PNGs.
2. OCR text lines and coordinates with PaddleOCR worker by default.
3. Create a local clean background by covering OCR text regions.
4. Rebuild a PPTX with the clean background and editable text boxes.
5. Use LibreOffice + `pdftoppm` to generate preview PNGs when available.

Background modes:

- `original`: keep the original page image as background and overlay editable text.
- `local-clean`: fast local background cleanup by covering text regions with sampled neighboring colors. This is stable but can leave visible pale blocks on illustrated pages.
- `model-clean`: high-quality background cleanup through an image model. It sends the original page image plus a text-removal prompt listing OCR text. Use it for illustrated/textured pages where local cleanup is visibly insufficient.

Follow `references/editable-ppt-workflow.md` for the broader staged process and `references/editable-ppt-rules.md` for quality rules.

Use `references/development-roadmap.md` for the current development direction and promotion criteria. When an experiment regresses visually, stop and diagnose the responsible layer before trying another prompt or model.

Practical execution order:

1. **Input and scope**
   - Accept a PDF, flattened PPTX, or slide image set.
   - Create a work directory under the user's project output folder.
   - Record source path, selected pages, model names, and output paths.

2. **Representative pages first**
   - Do not start with a full deck.
   - Pick pages by visual type and complexity.
   - Use a small set such as `1,2`, `3,4`, `5,6`, or `9,10` depending on the current test.

3. **Render source pages**
   - Render pages to PNG.
   - Keep the original image pixel coordinate space as the layout coordinate system.

4. **OCR before rebuild**
   - Run OCR before background cleanup or PPTX rebuild.
   - Extract text, confidence, bbox, estimated font size, font family policy, color, and mask boxes.
   - Keep the layout JSON as the source of truth for rebuild.

5. **OCR / visual accuracy gate**
   - Verify text content, grouping, x/y/width/height, font size, and color before rebuild.
   - If these fields are wrong, stop and fix OCR/parsing first.
   - Merge adjacent same-baseline OCR fragments into one editable line when they share font policy and vertical overlap.
   - Same-baseline OCR fragments may have overlapping boxes because OCR over-expands glyph regions. If the second fragment still advances in reading direction and shares style/vertical overlap, treat the negative gap as bbox overlap and merge it in OCR normalization.
   - Filter footer/watermark brand text from editable text and text masks.
   - Apply renderer-calibrated OCR font-size estimates before PPTX generation.
   - Classify text role (`title`, `body`, `label`) before font and size normalization.
   - Use style-appropriate fonts only from the approved pool or explicit playful classroom fallbacks.
   - For high-value top-band headings, use a narrow secondary OCR check when the primary OCR misses prefixes, punctuation, or fragments. Record any repair in `ocr_repairs`; do not hide heading repairs in PPTX rendering.
   - Secondary top-band OCR must pass a strict heading-format gate before it can replace primary OCR. Reject noisy candidates with stray symbols, malformed `Key...` text, or trailing artifacts; record rejected candidates in `ocr_repair_candidates`.
   - When primary OCR splits a top heading into adjacent fragments, merge those fragments by x-order into one heading before typography and rebuild. Record this deterministic repair in `layout_repairs`.
   - When OCR splits a continuous paragraph into multiple visible rows inside the same visual region, column, card, bubble, or panel, rebuild it as one editable paragraph while preserving the original visible row breaks. Record `paragraphGroup`, `textSource=ocr_paragraph_group`, and `lineBreakSource=ocr_visible_rows`.
   - Paragraph grouping must be column/region aware, not only global reading-order based. Interleaved text from another column must not prevent same-region continuation lines from being grouped.
   - Do not merge titles, table cells, glossary/list rows, Q/A pairs, or separate cards just because they are visually near each other. Group only rows with compatible font policy, size, alignment, and local geometry.
   - Derive `font_bold` from original-slide visual evidence, such as title role and tight ink-density in the OCR text region. The PPTX renderer must only execute the recorded style fields; it must not invent bold or regular weight during rendering.
   - For repeated same-column lists, glossaries, or table-like rows, normalize sibling font size and font weight from group-level evidence. Record `fontSizeSource`, `fontSizeLocked`, `typographyGroup`, `textBoxHeightScale`, and `lineSpacing` in layout JSON before PPTX rendering.
   - Run font render-fit after typography grouping. Choose `font_family` only from the approved pool by comparing rendered candidate width and ink density against the original OCR region. Record `fontFit`, `fontFamilySource`, and any size compensation in layout JSON.
   - Do not aggressively font-fit Chinese or mixed Chinese/Latin glossary/list groups. For these groups, preserve the approved CJK default font and group typography unless repeated evidence proves a better candidate. Font fitting is safer for titles and homogeneous Latin text.

6. **Background cleanup**
   - Editable replacement text requires old text to be removed from the background.
   - Default to local clean-text background for a fast first pass.
   - Use `model-clean` when local cleanup leaves visible blocks, damages illustrations, or cannot preserve textured backgrounds.
   - For `model-clean`, prompt the model to edit the original image directly and remove only the OCR-listed text. Do not describe or reinterpret the scene.
   - For `gpt-image-2-all`, use `/v1/images/edits` with `multipart/form-data`; do not use `/v1/images/generations` for background repair because it can regenerate a different scene.
   - If a model-clean background changes composition, size, or text container positions, diagnose it as a background/OCR alignment issue before judging PPTX rendering.
   - If a model-clean background preserves aspect ratio and composition but returns a different pixel size, normalize it back to the original input canvas and record the geometry QA. Do not treat this as a coordinate failure.
   - After model-clean normalization, run visual-diff QA outside OCR text-mask regions. Text regions are expected to change; non-text regions such as containers, icons, illustrations, cards, panels, and composition should remain stable.
   - In representative batch runs, one model-clean failure must not hide the rest of the diagnostic signal. Record `model_clean_error`, mark background QA as `fail`, and continue with the configured fallback such as `local-clean` unless the run explicitly uses `--model-clean-fallback fail`.
   - Preserve non-text containers, speech bubbles, cards, panels, icons, illustrations, charts, and composition.

7. **PPTX rebuild**
   - Use `clean_background` when available.
   - Add editable text/shapes/images from layout JSON.
   - Rebuild deterministically.
   - Do not shrink, move, or rewrite OCR fields during rendering. If the OCR coordinates or font size are wrong, fix OCR/parsing rather than moving text in the renderer.
   - Text-box height and line spacing must come from layout metrics, not a renderer-wide constant. The renderer executes `textBoxHeightScale` and `lineSpacing` without additional fitting.
   - The renderer must not silently replace fitted fonts. If a fitted font is unavailable, diagnose the font environment or rerun font fitting; do not hide substitution inside PPTX generation.

8. **Preview QA**
   - Export to preview images.
   - Compare against the original page.
   - Attribute differences to OCR/parsing/fusion or renderer before changing anything.

9. **Only then consider full-deck**
   - Promote to wider page batches only after representative pages pass review.

## Readiness Check

Before a new reconstruction run on a fresh machine or after major script changes, run:

```bash
python scripts/check_readiness.py
```

This is a read-only check. It verifies local files, required Python modules, key binaries such as Tesseract and LibreOffice, optional PaddleOCR availability, and model-related environment variables. It does not install dependencies or call external model APIs.

## Script Map

Core scripts:

- `scripts/check_readiness.py`: read-only local readiness and dependency check.
- `scripts/run_simple.py`: stable launcher for the simple flow.
- `scripts/pdf_to_ppt_simple.py`: default simple PDF -> OCR -> clean background -> python-pptx -> preview flow.
- `scripts/ocr_paddle_worker.py`: PaddleOCR batch worker called by the simple flow.
- `scripts/editable_deck.py`: original local OCR + editable PPTX prototype flow. Keep for reference and comparisons.
- `scripts/editable_ppt_v2.py`: representative-page orchestrator for the v2 reconstruction pipeline.
- `scripts/page_structure_parse.py`: page type, groups, element bboxes, edit policies, and style evidence.
- `scripts/fuse_model_ocr_with_boxes.py`: OCR/model text-box fusion.
- `scripts/build_text_masks.py`: text mask generation.
- `scripts/repair_background_with_image_model.py`: image-model background text removal.
- `scripts/extract_obvious_icons.py`: extract obvious icons only when reliable.
- `scripts/text_position_diagnostics.py`: compare OCR, fused layout, and rendered preview positions.

Experimental scripts:

- `scripts/experimental_paddle_style_fusion.py`: PaddleOCR text/bbox plus existing OCR style-probe experiment. This is not a default main flow.
- `scripts/experimental_layout_to_pptx.mjs`: minimal PPTXGenJS renderer for experimental layouts.
- `scripts/experimental_layout_to_pptx.py`: minimal python-pptx renderer for experimental layouts.
- `scripts/experimental_layout_to_pptx_libreoffice.py`: attempted LibreOffice UNO renderer. Use only for investigation; UNO may be unstable in this local environment.
- `scripts/experimental_layout_to_odp.mjs`: attempted ODP renderer. Use only for investigation; hand-written ODP was not accepted by LibreOffice in the latest test.

## Fonts

Use `references/fonts.md` as the practical font guide and `references/codia-google-fonts-list.json` as the machine-readable font catalog.

Default font policy:

- Chinese: `Noto Sans SC`.
- Latin: `Inter`.
- Approved fallbacks: `Source Han Sans CN` / `思源黑体 CN`, `Arial`, `Times New Roman`.
- Classroom/playful title fallback when visually appropriate: `Comic Sans MS`, `Chalkboard SE`, `Marker Felt`, `ZCOOL KuaiLe`.

Do not freely match arbitrary fonts. If font mismatch causes line-spacing or size drift, diagnose it as style/font evidence or renderer mapping, not as a reason to move OCR boxes.

## PaddleOCR Policy

PaddleOCR may be used as the primary OCR engine for the simple default flow when it is available and stable on the machine.

Current policy:

- Use PaddleOCR to compare and improve text recognition and bbox quality.
- Call PaddleOCR through `scripts/ocr_paddle_worker.py`, not by importing PaddleOCR inside the main script.
- Use Tesseract only as a fallback engine when PaddleOCR is unavailable. Tesseract is not the preferred default because it was too slow on representative page tests.
- Do not dump every PaddleOCR result into the final PPTX layout.
- Filter low-confidence fragments, logo text, decorative background text, and short signage.
- Treat OCR as the source for text and bbox evidence; detailed typography is still estimated unless a separate style probe is explicitly added.

## Renderer Policy

Use the renderer that best supports the current experiment:

- python-pptx: preferred default for the simple flow because it is easy to inspect and patch.
- PPTXGenJS: preferred for fast deterministic generation from layout JSON.
- LibreOffice: preferred for converting PPTX to PDF/PNG previews and round-trip validation.
- PowerPoint/Keynote: final human visual validation when available.

If a PPTX preview looks wrong, first inspect the layout JSON. Renderer changes cannot fix wrong text grouping, wrong title structure, wrong coordinates, or decorative OCR leakage.

## Boundaries

- Do not promise full element decomposition.
- Do not run full decks while representative pages still fail.
- Do not treat a model-generated clean background as valid without visual QA.
- Do not let one model-clean page failure abort representative-page diagnostics unless the user explicitly asks for fail-fast behavior.
- Do not keep old background text behind editable replacement text.
- Do not hardcode a single test deck's wording, page structure, or visual style into general rules.
- Do not store project-specific reconstruction rules in global memory.

## Outputs

For every representative run, return clickable paths for:

- work directory;
- layout JSON;
- PPTX;
- preview images;
- diagnostics or QA reports when produced.

Keep the user-facing summary blunt: what improved, what got worse, and which layer owns the remaining problem.
