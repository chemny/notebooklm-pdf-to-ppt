# Development Roadmap

This roadmap records the current engineering direction for `notebooklm-pdf-to-ppt`. It is intentionally practical: keep the main flow stable, test representative pages, and improve the responsible layer instead of changing everything at once.

## Current Product Boundary

The skill converts flattened NotebookLM PDF/PPTX/image exports into editable PPTX files. It does not generate NotebookLM course content.

`notebooklm-course-studio` owns source import, NotebookLM content generation, revision, and export.

`notebooklm-pdf-to-ppt` owns post-export reconstruction.

## Current Diagnosis

The latest PaddleOCR + style-probe fusion experiment did not beat the earlier stable output.

The failure was mainly in the fusion layer:

- title blocks were split or incorrectly reconstructed;
- decorative/background text leaked into editable PPT objects;
- PaddleOCR boxes were added too broadly;
- font size and style were estimated too roughly for unmatched PaddleOCR candidates;
- the renderer faithfully drew a bad layout.

PaddleOCR itself still showed value for text recognition and many text boxes, but it should remain experimental until fusion rules prove stable across representative pages.

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

### 3. Keep PaddleOCR As A Candidate Source

Use PaddleOCR for comparison and repair candidates, not as the default dump source.

Candidate promotion rules must include:

- high confidence;
- region allowed by page structure;
- not a logo/decorative zone;
- not a short background sign unless explicitly editable;
- consistent with nearby group role;
- no conflict with a higher-confidence existing text group.

### 4. Improve Style Evidence Separately

Font family, weight, color, and line spacing should be estimated separately from text and bbox.

Do not infer style from PaddleOCR alone. PaddleOCR does not provide full typography.

### 5. Renderer Choice

Use PPTXGenJS for fast deterministic generation from layout JSON.

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
