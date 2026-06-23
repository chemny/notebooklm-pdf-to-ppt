# Development Roadmap

This roadmap records the current engineering direction for `notebooklm-pdf-to-ppt`. It is intentionally practical: keep the main flow stable, test representative pages, and improve the responsible layer instead of changing everything at once.

## Current Product Boundary

The skill converts flattened NotebookLM PDF/PPTX/image exports into editable PPTX files. It does not generate NotebookLM course content.

`notebooklm-course-studio` owns source import, NotebookLM content generation, revision, and export.

`notebooklm-pdf-to-ppt` owns post-export reconstruction.

## Current Diagnosis

The maintained main flow is now intentionally small:

```text
run_simple.py -> pdf_to_ppt_simple.py -> ocr_paddle_worker.py -> style_probe.py -> background cleanup -> python-pptx rebuild
```

PaddleOCR is the only OCR engine in the default path. Older secondary OCR,
mask-edit, renderer comparison, and multi-model fusion prototypes were removed
from the release package because they did not improve the final representative
output and made failures harder to diagnose.

The remaining fidelity limits are concentrated in three places:

- OCR/parser quality: text content, grouping, coordinates, and line boxes.
- Style recovery: font family, size, weight, color, line spacing, and paragraph grouping.
- Background cleanup: old-text removal without damaging non-text visuals.

## Main Flow Stability Rule

Do not keep changing the main flow while representative pages still fail.

The stable development order is:

1. Verify input rendering.
2. Verify OCR/parser output.
3. Verify structure/grouping.
4. Verify clean background.
5. Verify deterministic PPTX rebuild.
6. Only then test more page types.

## Layer Ownership

Use this responsibility split for every visual mismatch:

- OCR/parser owns text content, reading order, grouping, bbox, font size, color, and style evidence.
- Fusion owns which evidence source wins and how rows/blocks are assembled.
- Background cleanup owns old-text removal and visual preservation.
- PPTX renderer owns unit conversion, font fallback, margin, line spacing, paragraph spacing, and export compatibility.

Do not fix a renderer symptom by moving OCR boxes. Do not hide bad OCR by shrinking text in the renderer.

## Recommended Next Work

### 1. Build A Better Parse QA Gate

Before cleanup or PPTX generation, produce a page-level QA report:

- text content differences;
- missing text;
- duplicated/decorative text;
- low-confidence boxes;
- suspicious title splits;
- coordinate outliers;
- font-size outliers;
- style evidence gaps.

The QA gate should fail before PPTX rebuild when the parsed layout is obviously wrong.

### 2. Stabilize Text Grouping

Group by visual containers and semantic role before matching text:

- title block;
- speech bubble;
- card/panel body;
- list group;
- table cell;
- caption/label;
- decorative/background text.

Do not allow independent line matching to break a title or body paragraph into random pieces.

### 3. Keep PaddleOCR Output Filtered And Structured

Use PaddleOCR as the primary OCR source, but do not dump every raw OCR fragment
into the final layout. Promotion rules must include:

- high enough confidence for the role;
- not a logo, watermark, decorative zone, or short background sign unless explicitly editable;
- consistent with nearby group role and visual container;
- mergeable with adjacent same-baseline or same-container text when appropriate;
- no conflict with an existing higher-confidence text group.

### 4. Improve Style Evidence Separately

Font family, weight, color, and line spacing should be estimated separately from text and bbox.

Do not infer style from PaddleOCR alone. PaddleOCR does not provide full typography.

### 5. Renderer Choice

Use python-pptx for the maintained default rebuild because it is easy to inspect
and patch.

Use LibreOffice for:

- PPTX to PDF/PNG previews;
- round-trip validation;
- compatibility checks.

Renderer changes are useful only after layout JSON passes QA.

## Stop Conditions

Stop and diagnose instead of continuing if:

- representative preview is worse than the previous stable output;
- title/body grouping is broken;
- decorative text enters the editable layer;
- clean background still contains duplicated old text;
- PPTX render differs from a correct layout JSON.

## Promotion Criteria

A change can be promoted into the default main flow only when:

- it improves at least two visually different representative pages;
- it does not regress the previous stable page set;
- the improvement is explainable as a general rule, not a page-specific patch;
- output paths include layout JSON, PPTX, previews, and diagnostics;
- the failure domain is documented if quality is still below target.
