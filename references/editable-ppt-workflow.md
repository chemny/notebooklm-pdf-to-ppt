# Editable PPT Reconstruction Workflow

This workflow is the standard execution path for converting image-based NotebookLM PPT/PDF exports into editable PPTX files. It is intentionally general and should be refined as more slide types are tested.

## Workflow Summary

`Input export -> representative pages -> page-structure parse -> structure gate -> text/style/coordinate extraction -> model text and style evidence repair -> font mapping -> text masks -> image-model background cleanup -> deterministic layout assembly -> PPTX rebuild -> preview QA -> representative repair -> full conversion`

## Stage 1: Input And Scope

Inputs:

- NotebookLM-exported PPTX or PDF.
- Optional source PDF/images when the PPTX only contains flattened slide images.
- Target output directory.
- Optional model configuration for layout and image repair.

Actions:

- Verify the input file exists and can be rendered or unpacked.
- Create a reconstruction work directory under the course output folder.
- Record input path, selected pages, model names, and output paths.

Output:

- A stable work directory for rendered images, layout JSON, previews, and final PPTX.

## Stage 2: Representative Page Selection

Actions:

- Do not start with the full deck.
- Select representative pages by visual type and complexity.
- Include at least one simple page and one complex page when available.
- Start with a small set such as `1,2,3,5,10`, then adjust based on the actual deck.

Decision point:

- If representative pages do not cover the visual diversity of the deck, add more representative pages before model repair.

Output:

- A page list for the first reconstruction run.

## Stage 3: Render Slides To Images

Actions:

- Render or extract each selected slide into a page image.
- Keep original pixel dimensions as the coordinate system for downstream layout.

Output:

- `rendered/slide_###.png` or equivalent image files.

## Stage 4: Page Structure Parse

Actions:

- Parse each representative page before selecting the reconstruction strategy.
- Use the page types from `references/editable-ppt-rules.md`: `cover`, `text`, `card`, `flow`, `diagram`, `table`, `data`, `image`, `mixed`.
- Extract structure groups such as title regions, cards, flow steps, tables, diagrams, image panels, and grouped callouts.
- Extract element-level fields: `type`, `role`, `groupId`, `bbox`, `editPolicy`, `backgroundPolicy`, text content, and style evidence.
- Save the page structure layout as `layout.structure.json`.

Decision point:

- If page type, groups, bboxes, edit policies, or style evidence are unclear, stop before OCR fusion, mask cleanup, or PPTX rebuild.
- If a page is `flow`, `diagram`, `data`, `image`, or `mixed`, preserve key visuals over aggressive decomposition.
- If a page is mostly `text`, `card`, or `table`, prioritize text editability and background cleanup inside confirmed groups.

Output:

- `layout.structure.json` with page type, groups, elements, and quality scores.

## Stage 5: Structure Gate

Actions:

- Validate structure before any expensive downstream reconstruction.
- Confirm every important text element belongs to a group.
- Confirm group bboxes and element bboxes are in the original slide coordinate system.
- Detect common model coordinate-space failures, such as wide slides whose horizontal structure is compressed into a 1024px coordinate range.
- Confirm page-type expectations:
  - `card`: card/panel groups are present;
  - `flow`: step groups and number/label/body relationships are present;
  - `table`: cells/rows/columns are present;
  - `diagram`: labels and connectors are separated or intentionally flattened.
- Confirm each editable text element has style evidence: font category, candidates, weight, color, and confidence.

Decision point:

- If the gate fails, do not run background cleanup, icon extraction, or PPTX rebuild.
- Repair the parser prompt, switch model, add OCR hints, apply deterministic parse-stage coordinate repair, or manually calibrate the representative page first.

Output:

- Gate report with `passed`, `issues`, `warnings`, page type, group count, element count, and editable text count.
- Optional repaired structure JSON when the failure is a deterministic parse-stage issue such as x-axis coordinate scaling.

## Stage 5.5: OCR/Parsing Accuracy Gate

Actions:

- Verify the OCR/visual parser output before background cleanup or PPTX rebuild.
- Check text content, reading order, grouping, `x`, `y`, `width`, `height`, `fontSize`, color, and style evidence against the original page image.
- Mark trusted OCR/visual fields as locked only after this check.

Decision point:

- If text, coordinates, font size, color, or grouping are visibly wrong, stop and repair OCR/parsing/fusion first. Do not continue to rebuild and then compensate in PPTX rendering.

Output:

- `layout.*.json` with trusted fields marked by `positionLocked`, `fontSizeLocked`, `positionSource`, and `fontSizeSource`.

## Stage 5.6: Style Evidence Gate

Actions:

- Separate style evidence from geometry and font-size evidence.
- For each editable text element, record available provenance for font weight, font family, color, and line spacing. At minimum, font weight should carry `fontWeightSource`, `fontWeightLocked`, `fontWeightConfidence`, `styleEvidence`, and `styleSource`.
- Use structure labels such as `Q:` / `A:`, table cell, card, or callout only for matching and grouping. Do not use those labels alone to infer bold, font family, or line spacing.

Decision point:

- If style evidence is low-confidence or contradicted by the preview, keep geometry and font-size locks intact and repair the style evidence layer or font fitter. Do not alter OCR coordinates to compensate for style mismatch.

Output:

- Style-aware layout JSON whose style decisions can be traced separately from OCR coordinates and font-size measurements.

## Stage 6: OCR Anchor Extraction

Actions:

- Run OCR on selected page images.
- Extract text, word boxes, line boxes, confidence, and estimated text color/size when possible.
- Extract visual style evidence when possible: font category, likely font candidates, weight, color, and style confidence.
- Save the raw OCR layout.

Output:

- `layout.raw.json`.

Notes:

- OCR is not the source of truth for text content.
- OCR is primarily used for coordinates, masks, and local alignment hints.
- OCR-derived style data is an anchor, not the final font decision.

## Stage 7: Semantic Layout Repair

Actions:

- Send page image plus OCR hints to the layout model.
- Ask the model to repair text content, semantic structure, grouping, element roles, and reading order.
- Ask the model to output style evidence: `fontCategory`, `fontCandidates`, `fontWeight`, and `styleConfidence`.
- Do not let the model directly control final coordinates. Font family must be mapped from style evidence to the approved local font pool.
- Keep model output as semantic and style guidance only. For trusted OCR matches, final text content, coordinates, and font size must come from OCR/visual anchors exactly as recorded in the OCR layout. Model text may be stored as advisory `modelText`, but it must not replace trusted OCR text during fusion or rebuild.

Output:

- `layout.semantic.json` or equivalent repaired layout.

Decision point:

- If the model invents unstable coordinates, ignore those coordinates. Keep the model text only and fall back to OCR/visual anchors.
- If OCR misses important text, let model output the missing text and assign coordinates through repair heuristics or manual representative-page repair.
- Missing text should be aligned to nearby same-level anchors, not placed by arbitrary model coordinates.

## Stage 8: Strategy Selection Per Page

Actions:

- Choose a per-page reconstruction strategy based on classification:
  - `cover`: preserve primary visual, make title/subtitle editable.
  - `text`: rebuild text boxes accurately; clean old text from background.
  - `card`: preserve panel geometry; place editable text and stable shapes.
  - `diagram`: preserve diagram structure; make labels editable when reliable.
  - `data`: preserve charts/tables unless extractable with high confidence.
  - `image`: preserve visual media; make captions and titles editable.
  - `mixed`: use hybrid cleanup and rebuild only high-value editable elements.

Output:

- Page-specific decisions for background cleanup and element decomposition.

## Stage 9: Background Cleanup

Actions:

- Create `clean_background` for every page that will receive editable replacement text.
- Generate text masks from OCR word boxes plus model-repaired text boxes.
- Treat local mask fill as a QA/debug baseline only. It is not the default final background cleanup path for illustrated, image-heavy, diagram, mixed, or non-flat pages.
- Use image-model cleanup by default when old text is embedded in visual backgrounds, speech bubbles, photos, diagrams, screenshots, charts, or textured panels.
- For `gpt-image-2-all` / Image 2 cleanup, use no-mask editing by default: send the original page image plus a prompt that removes text glyphs and preserves non-text containers. Do not send OCR masks to Image 2 unless a verified edit endpoint explicitly supports masks.
- Keep OCR/model masks as internal artifacts for layout, coverage, residual-text QA, and possible manual debugging.
- Check the model response usage before accepting a background. If an image-reference/edit request reports `image_tokens = 0`, the model did not consume the source image and the result must be rejected.
- Prefer mask-assisted image-model repair when the mask is reliable. Use full-background image-model cleanup when the provider does not support masked editing or when masked editing is blocked.
- If the primary image model is blocked, rate-limited, or damages key visuals, route to an alternate configured image model and record the model choice in the page layout.
- If the image-model response includes `PROHIBITED_CONTENT`, treat it as a hard model-routing failure. Do not spend the main workflow on prompt rewrites; switch to the configured alternate image model.
- Image cleanup prompts must preserve non-text containers. Ask the model to remove text glyphs only and keep blank text containers, speech bubbles, list panels, borders, frames, icons, illustrations, colors, positions, and composition.
- API success is not enough. Every model-clean background must pass a visual similarity gate before PPTX rebuild: no unrelated scene generation, no missing major containers, no removed primary visuals, and no severe layout drift.
- If a clean background passes text removal but loses text containers, either regenerate with a container-preservation prompt or rebuild the missing containers as PPTX shapes before adding editable text.
- Run residual-text QA on every `clean_background`; for illustrated pages, combine OCR residual checks with visual inspection or text-match checks against the known source text because OCR can misread drawing strokes as gibberish text.
- Avoid aggressive cleanup when it damages photos, charts, diagrams, screenshots, or illustrations.
- Do not apply local `clean-text` globally across all page types. It can destroy complex backgrounds, diagrams, data pages, and image-heavy pages, and it is not considered final cleanup unless explicitly approved for a flat/simple page.
- The workflow default is `clean-required`: editable text requires old background text to be removed or explicitly flagged as failed QA.

Output:

- Clean background images.
- Text masks.
- Background OCR residual QA report.

Fallback:

- If cleanup damages non-text visuals, repair the masked region with the image model rather than reverting to old text in the background.
- If a visual element is hard to separate and is not text, keep it flattened in the background.
- `original` background mode is only for debugging/comparison, not the normal editable PPT deliverable.

## Stage 10: Layout Assembly

Actions:

- Build the final layout JSON using supported element types:
  - `text`;
  - `shape`;
  - local `image`.
- Fuse semantic text blocks with OCR/visual anchors before rebuild. Explicit anchor patterns such as `Q:` / `A:`, numbered steps, table cells, cards, and callouts should use the original top line as the final `x/y` anchor.
- For multi-line repaired text, use OCR/visual anchors for placement and semantic block dimensions for clipping safety. Do not move a block down just because the model parser proposed a lower bbox.
- Mark trusted OCR/visual placement and typography fields as locked, including `positionLocked` and `fontSizeLocked`. Locked fields are the rebuild contract and should be converted to PPT units directly. A render-fit failure on a trusted OCR match must create a diagnostic `layoutConflict`; it must not trigger font shrink, bbox expansion, or fallback to model coordinates.
- Mark trusted OCR text content as locked with `textSource=ocr_exact`. The PPTX rebuild step must write this text as-is and must not run additional cleanup, punctuation repair, whitespace normalization, or model-text substitution on it.
- Preserve explicit line breaks when they affect visual or semantic structure.
- Add `mask_texts` only for cleanup, not for editable duplicate text.
- Split symbols, labels, markers, or numbers into separate elements only when useful.

Output:

- Final page layout JSON ready for PPTX rebuild.

## Stage 11: PPTX Rebuild

Actions:

- Use `clean_background` as the page background when available.
- Add editable text, shapes, and reliable local images on top.
- Default mode: `text-overlay` with `--background-key clean_background` from the `clean-required` flow.
- Render text boxes with deterministic top anchoring, zero paragraph spacing, controlled line spacing, and a calibrated source-pixel-to-PPT-point font scale.
- Do not run shrink-to-fit, automatic bbox expansion, hard point-size caps, or model-style overrides on locked OCR/visual fields. Automatic fitting is only for low-confidence model-only elements.
- For unlocked text, run a max-fit pass inside the candidate text box so the text uses the largest practical font size without overflow. Keep this fitting inside the box; do not move OCR-locked elements to compensate.
- If grouped text still looks wrong after max-fit, repair group-level typography next: row spacing, sibling alignment, English/Chinese ratio, and shared line spacing.
- If preview drift appears after layout JSON is correct, fix the rebuild renderer first. Do not keep changing OCR boxes to compensate for PowerPoint paragraph or font-scale behavior.
- If preview differs from the original, assign the issue to either OCR/parsing or rebuild rendering before changing anything. OCR/parsing owns bad content, bad boxes, bad font size, bad color, and bad grouping; rebuild owns unit conversion, font substitution, line spacing, paragraph spacing, and PowerPoint text box behavior.
- Keep the rebuild deterministic.

Output:

- `editable_text_overlay.pptx` or equivalent editable PPTX.

## Stage 12: Preview Rendering

Actions:

- Render the rebuilt PPTX to PDF/PNG previews.
- Inspect representative pages visually before full-deck conversion.

Output:

- Preview screenshots for QA.

## Stage 13: QA And Repair

Actions:

- Apply the quality gates from `references/editable-ppt-rules.md`.
- Check for missing content, damaged visuals, text clipping, old text ghosts, bad grouping, and obvious style mismatches.
- Check `background_text_qa.json`; residual old text means the page needs mask/image-model repair before final conversion.
- Compare `original` only as a debugging reference when the page type is uncertain.
- Repair the layout JSON for representative pages.
- Keep repairs page-type aware.

Decision point:

- If the issue is local to one page, repair that page.
- If the issue repeats across page types, promote it to a script or workflow rule.
- If cleanup repeatedly damages a page type, choose a less aggressive strategy for that type.

Output:

- Approved representative-page reconstruction.

## Stage 14: Full-Deck Conversion

Actions:

- Run the same pipeline across all pages only after representative pages pass QA.
- Apply page classification and strategy selection per page.
- Do not assume one strategy fits the entire deck.

Output:

- Full editable PPTX draft.

## Stage 15: Final Review And Export

Actions:

- Render final preview pages.
- Report known limitations by page type.
- Save final PPTX and supporting layout/preview artifacts.

Output:

- Editable PPTX.
- Layout JSON.
- Preview screenshots.
- Summary of limitations and recommended follow-up fixes.

## Operating Principle

Keep the workflow stable before optimizing details. When results are poor, identify which stage failed instead of changing everything at once:

- wrong page classification;
- weak OCR anchors;
- bad semantic layout;
- wrong cleanup strategy;
- damaged background;
- incomplete layout assembly;
- PPTX rendering/font issue;
- missing QA repair.
