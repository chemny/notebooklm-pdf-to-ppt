# Editable PPT Reconstruction Rules

These rules define general behavior for reconstructing image-based slide decks into editable PPTX files. They must apply across different slide styles, not only text-heavy teaching pages.

## Reconstruction Goal

- Reconstruct the slide as editable PowerPoint objects where practical, while preserving the approved visual result.
- Do not promise full element-level decomposition in the first stable pass.
- Prioritize editable text, clean background, stable layout, and deterministic rebuild.
- Preserve the original visual intent even when some elements remain flattened into the background.
- Treat each slide as its own layout problem; do not force a rule from one example onto the whole deck.

## Page Classification First

Before choosing a reconstruction strategy, classify each representative slide by visual type:

- `cover`: hero title, large image, or simple focal visual.
- `text`: mostly headings, paragraphs, bullets, or tables.
- `card`: multiple panels, callouts, comparison blocks, or grouped content areas.
- `flow`: process routes, timelines, numbered steps, journey maps, or roadmap diagrams.
- `diagram`: flowcharts, process maps, timelines, mind maps, or relationship diagrams.
- `table`: rows, columns, matrix layouts, or structured cell content.
- `data`: charts, tables, numbers, dashboards, or KPI layouts.
- `image`: photo-heavy, illustration-heavy, product screenshots, or visual storytelling pages.
- `mixed`: substantial overlap between text, images, shapes, and decorative effects.

Use the classification to select the strategy. Do not assume a deck is primarily text-based.

## Representative Pages

- Run representative pages before full-deck conversion.
- Pick pages by visual type and complexity, not just by page number.
- Include at least one simple page and one complex page when available.
- Render preview screenshots for every representative reconstruction.
- Promote a strategy to full-deck conversion only after the representative set passes review.

## Model Division Of Labor

- Page-structure parser: identify page type, visual groups, element boundaries, edit policies, background policies, and style evidence before any rebuild step.
- Vision/layout model: identify semantic structure, text content, element roles, grouping, and visual hierarchy.
- OCR: provide coordinate anchors, detect text regions, and supply mask hints for text removal.
- Image model: repair or regenerate backgrounds after text/element removal. This is the default background-cleaning engine for non-flat pages.
- PPTX rebuild script: produce deterministic PowerPoint objects from layout JSON.
- Do not ask a model to directly create the final PPTX as the default path.
- Models may propose semantic text repairs and add missing visible text only when OCR is missing or untrusted. When a text element has a trusted OCR match, the final editable `text` must use the OCR text exactly as recorded in the OCR layout; model text must remain advisory metadata such as `modelText`.
- Fusion and rebuild must not rewrite trusted OCR content, punctuation, spacing, line breaks, coordinates, font size, font family, color, or alignment. If OCR is wrong, fix the OCR/parsing module and regenerate the layout; do not repair it inside fusion or PPTX rendering.
- Final coordinates, typography, and alignment must be derived from the original slide and deterministic layout rules.
- Do not enter background cleanup or PPTX rebuild until the page-structure gate passes.

## Page-Structure Gate

Before OCR fusion, mask cleanup, icon extraction, or PPTX generation, every representative page must pass a page-structure gate:

- Page type is explicit: `cover`, `text`, `card`, `flow`, `diagram`, `table`, `data`, `image`, or `mixed`.
- Important visual groups are identified, such as cards, flow steps, title regions, tables, diagrams, and image panels.
- Every editable text element has a `groupId`; text may not float across cards, columns, flow steps, or table cells.
- Every important element has a bbox in the original slide pixel coordinate system, not a normalized model coordinate system.
- Wide-slide coordinate compression, such as a 1376px slide whose horizontal groups end near x=1024, must be detected before rebuild.
- Every editable text element has style evidence: `fontCategory`, `fontCandidates`, `fontWeight`, `color`, and `styleConfidence`.
- Every element has an edit policy: `editable`, `background`, `image`, `shape`, or `ignore`.
- If a page is `card`, card/panel groups must be present.
- If a page is `flow`, step groups must be present and numbers, titles, and descriptions must belong to the correct step.
- If a page is `table`, row/column/cell grouping must be present before any table text is rebuilt.
- If the gate fails, stop and repair parsing first. Do not try to fix broken structure in background cleanup or PPTX rendering.
- Deterministic parse-stage repairs are allowed for clearly diagnosed issues such as x-axis 1024-to-canvas scaling. They must be recorded in the structure JSON as parse repairs.

## Strategy Selection

Choose the reconstruction method per page:

- For simple `cover` pages, direct image-model background cleanup may be enough.
- For `text` pages, prioritize accurate text boxes, font hierarchy, wrapping, and spacing.
- For `card` pages, preserve panel geometry first, then place editable content inside each region.
- For `flow` pages, preserve the route/connector geometry first; make step numbers, labels, and descriptions editable only after step grouping is correct.
- For `diagram` pages, keep connectors/shapes editable only when their geometry is reliable; otherwise keep the diagram as background and make labels editable.
- For `table` pages, keep the table grid/cells aligned; do not merge text across cells.
- For `data` pages, do not invent chart data. Keep charts/tables as background unless structure can be extracted with high confidence.
- For `image` pages, avoid damaging the primary image; make captions/titles editable and keep visual media flattened if necessary.
- For `mixed` pages, use hybrid reconstruction: clean background + editable high-value text + selected shapes.

## Background Rules

- Use page-specific background cleanup.
- If text is rebuilt as an editable PPT object, the same old text must be removed from the flattened background.
- Backgrounds must pass a residual-text QA check before they are treated as final-ready.
- Preserve important images, diagrams, charts, and illustrations even if that means fewer editable non-text elements.
- For model-based background cleanup, lock the source image geometry: preserve canvas size, aspect ratio, composition, object positions, visual hierarchy, container positions, and non-text element placement.
- Model-based background cleanup must protect non-text pixels. Characters, icons, illustrations, diagrams, charts, decorations, containers, panels, cards, bubbles, borders, shadows, and background texture are protected objects unless the page strategy explicitly rebuilds them separately.
- Model-based cleanup should be a minimal text-pixel edit. Remove readable glyphs and perform only the smallest necessary local repair around those glyphs. Do not redraw whole containers when only text pixels need removal.
- Do not use semantic scene descriptions in background-clean prompts when the task is text removal. Prompts should frame the work as image editing on the exact input image, not as recreating a scene.
- Reject model-clean outputs when geometry changes: visible crop/zoom, shifted subjects, moved containers, changed panel/bubble positions, missing protected objects, style drift, or regenerated alternative scenes.
- If a model-clean output preserves aspect ratio and visual composition but changes pixel dimensions, normalize it back to the original canvas size before PPTX rebuild and record `normalizedToInputSize=true` in geometry QA. This is acceptable only for pure canvas-size normalization; it does not excuse crop, zoom, shifted containers, or composition drift.
- After model-clean normalization, run visual-diff QA outside OCR text-mask regions. Text regions are expected to change; non-text regions are protected. Record `meanAbsDiff`, `p95AbsDiff`, `changedPixelRatio`, `textMaskRatio`, and `status`.
- Treat visual-diff QA as a routing gate: `pass` can continue to rebuild, `review` needs visual inspection or a stricter retry, and `fail` should not be used as a final background unless the user explicitly accepts the drift.
- Original OCR coordinates remain trusted only if the model-clean background preserves source geometry. If geometry drifts, do not judge PPTX rendering yet; either retry model-clean with stricter constraints, fall back to local-clean, or run a separate alignment step.
- Use OCR/model masks before image-model repair when text is embedded in complex backgrounds.
- Local mask fill is a mask/QA/debug baseline only. Do not treat it as the default final background cleanup path for illustrated, image-heavy, diagram, mixed, or textured pages.
- For Image 2 cleanup, do not pass OCR masks by default. Send the original page image and ask the model to remove text glyphs while preserving all non-text elements. Masks remain internal QA/layout artifacts unless a verified edit endpoint supports them.
- Reject image-model outputs when the response shows the source image was not consumed, such as `image_tokens = 0` on a reference-image request.
- If direct image-model cleanup rewrites important visuals, fall back to mask-assisted image-model repair or route to an alternate image model. Do not fall back to a background that still contains old text.
- If the primary image model is blocked, rate-limited, or visually damages the page, try the configured alternate image model and record the route used.
- Image-model cleanup must remove text glyphs, not text containers. Preserve blank speech bubbles, list panels, cards, borders, frames, and other non-text containers unless the page strategy explicitly rebuilds those containers as PPTX shapes.
- API success does not mean background success. Reject any model background that generates an unrelated scene, removes major containers, changes primary visuals, or drifts from the source layout.
- Background cleanup must remove old text where editable replacement text will be placed; it does not need to make every decorative artifact perfect.
- The original flattened page image can be used for debugging/comparison, but it is not an acceptable final background when editable text would duplicate old text.

## Element Rules

Supported baseline elements:

- `text`: titles, subtitles, body text, labels, captions, table text, diagram labels.
- `shape`: simple rectangles, lines, highlights, underlines, badges, and panel fills.
- `image`: local extracted or cropped image elements when reliable.

General element decisions:

- Make text editable whenever it is important to the user.
- Keep decorative, uncertain, or highly fused visual elements in the background.
- If a graphic is hard to identify, hard to crop cleanly, or likely to break visual fidelity, keep it in the background instead of forcing extraction.
- Small icons, badges, and markers should be split into editable/image elements only when extraction is reliable; otherwise keep them flattened, as long as they are not old text.
- Do not merge decorative markers such as checks, crosses, bullets, or badges into long body text boxes. Keep them as separate elements when reliable, or leave them flattened in the background.
- Obvious high-confidence icons should be extracted as local transparent PNG image elements when their color boundary is clear and they do not overlap text. Examples: red crosses, blue checks, simple blue line icons, equality marks, package icons, globe/gift/robot/book/palette symbols.
- When extracting icons, first clean text from the background, then remove icon regions from that text-clean background, then layer icon PNGs back above the background and below editable text. Do not use an icon-only-cleaned original background as the final background, or old text will return.
- Do not extract blue/red text headings as icons. Icon extraction must exclude text boxes and use size/area thresholds.
- Split symbols, labels, numbers, or markers into separate elements only when it improves editability, alignment, or styling.
- Preserve explicit line breaks when they are part of the original layout.
- When a model text block matches multiple trusted visible OCR rows, preserve the OCR-visible row text and row breaks in the final editable text. The model may only remain as advisory `modelText`; it must not repair, collapse, expand, or rewrite trusted OCR rows during fusion.
- For any trusted OCR match, the final editable `text` must be sourced from OCR rows, not from the model block. Use `textSource=ocr_exact` and keep any model wording in `modelText` only. If the OCR text is wrong or incomplete, mark the element for OCR/parsing repair instead of silently replacing the text during fusion.
- Related OCR rows may be assembled into a larger editable text group when the grouping is visually and semantically clear. Examples include star/bullet vocabulary lists, numbered lists, and continuous body rows inside the same card, speech bubble, or panel. Group assembly must preserve OCR row text and row order, use a group-level font size, and record provenance such as `textSource=ocr_group` and `groupAssembly`.
- Continuous body text that appears as multiple OCR rows in the same visual container, column, card, speech bubble, or panel should be rebuilt as one editable paragraph, not as isolated sentence boxes. Preserve the visible OCR row breaks inside that paragraph and record `paragraphGroup`, `textSource=ocr_paragraph_group`, and `lineBreakSource=ocr_visible_rows`.
- Paragraph grouping must use local region/column continuity rather than only global reading order. A continuation line in the left column may still belong to the previous left-column paragraph even when a right-column line appears between them in y-order.
- Do not use paragraph grouping to merge separate semantic units. Titles, table cells, glossary/list rows, marker lists, Q/A pairs, separate cards, and unrelated captions should remain separate unless a page-structure group explicitly proves they are one editable text block.
- Add shape elements only for simple, stable geometry.
- Avoid over-decomposition when it creates brittle layout or many low-value objects.
- Empty semantic containers, such as card/panel bboxes with no text content, must not enter the rebuild as `text` elements. Keep them as structure groups, shape candidates, or background regions.

## Layout Rules

- Prefer OCR-anchored coordinates for text placement.
- Use model output to repair OCR errors, add missing visible text, group related elements, infer hierarchy, and choose roles.
- Do not use model-proposed free coordinates as final coordinates when OCR or visual anchors exist.
- Derive final `x`, `y`, `width`, and `height` from original OCR/visual detection boxes plus block-level alignment rules.
- For structured text blocks with explicit visual anchors, such as `Q:` / `A:` prompts, numbered steps, table cells, cards, or callouts, first match the anchor line in the original slide, then absorb nearby same-column/same-group continuation lines. Do not keep a model block's lower `y` coordinate when OCR has already found the true top line.
- For multi-line blocks, use the original OCR/visual top-left anchor for placement and keep the semantic/model block size only to prevent clipping. This prevents model-repaired text from drifting downward while still allowing missing OCR text to fit.
- Multi-line fit checks must use the matched OCR row sequence, not only the model's merged semantic sentence. If the model collapses visible rows, the fusion step must record `textSource` / `lineBreakSource` and restore visible line breaks before PPTX rebuild.
- When OCR/visual anchors provide trusted `x`, `y`, `width`, `height`, or `fontSize`, mark those fields as locked in layout JSON, such as `positionLocked` and `fontSizeLocked`. The PPTX rebuild step must reproduce locked values by deterministic unit conversion and must not run automatic shrink-to-fit, arbitrary bbox expansion, or model-style overrides on locked fields.
- For trusted OCR matches, use the OCR line-level `font_size_px` as the authoritative font size. Do not recompute the font size from individual word boxes when line-level font size exists, because bullets, stars, punctuation, or short words can make word-box statistics smaller than the actual rendered line.
- For trusted OCR groups, use a representative group-level font size after excluding obvious outliers. `marker_list` groups may use a slightly higher representative size to match list emphasis, while `panel_body` groups should use a lower stable representative size and tighter line spacing to avoid overfilling large explanation panels. Record the decision as `fontSizeSource=ocr_group_typography`.
- For repeated same-column lists, glossaries, table-like rows, or sibling card rows, normalize font size with group-level typography evidence. Record `fontSizeSource=group_typography_consistency`, `fontSizeLocked=true`, and `typographyGroup`; do not let each OCR row independently choose size from its own bbox height.
- OCR line construction must filter obvious word-level outliers before publishing `text`, bbox, and `font_size_px`. If the OCR engine merges a large isolated background glyph, symbol, or illustration fragment into a real text line, remove that outlier in the OCR module instead of shrinking, moving, or rewriting the line during fusion/rebuild.
- OCR line construction must tolerate same-baseline bbox overlap. When adjacent fragments share vertical overlap, font policy, and reading direction, a negative horizontal gap may mean OCR over-expanded one box rather than two separate text objects. Merge those fragments during OCR normalization and record the merged text before paragraph grouping.
- OCR text repairs must be small, explicit, and recorded in OCR output. Keep `raw_text` and `text_repairs` so later stages can distinguish OCR recognition from OCR-layer correction. Do not hide corrections inside fusion or PPTX rebuild.
- Do not use a secondary OCR fallback for heading repair in the default flow. If primary OCR finds trustworthy adjacent top-heading fragments but splits Chinese and English pieces, merge them by x-order into one heading and record `layout_repairs`.
- Missing heading markers should not be guessed. Add or repair section numbers only from reliable primary OCR evidence or a future dedicated numbering module.
- When a trusted OCR match provides text content, mark it with `textSource=ocr_exact`. The PPTX rebuild step must write that text as-is and must not run additional text cleanup, punctuation repair, translation repair, or whitespace normalization on the trusted OCR text.
- OCR/visual anchors are trusted only after text matching passes a role-specific threshold. Low-confidence matches must not lock coordinates or font size, because a wrong OCR match is worse than a model-only semantic box.
- A trusted text match still needs a render-fit check, but this check is diagnostic only. If the matched OCR font size cannot fit the rebuilt text inside the candidate box, preserve the trusted OCR `x`, `y`, `width`, `height`, and `fontSize`; record a `layoutConflict` instead of downgrading the lock, changing the font size, expanding the bbox, or falling back to model coordinates.
- If render-fit fails because OCR captured only part of a visible line but the matched OCR anchor is trusted, keep the OCR geometry and OCR-measured font size. Fix the upstream text grouping/OCR/content issue or inspect it in the diagnostic overlay. Do not silently apply `fit_adjusted` geometry or typography to trusted OCR fields.
- Automatic font fitting is allowed only for model-only or low-confidence text blocks that lack trusted original-slide style measurements. It must never silently change a trusted OCR-measured font size.
- For unlocked text, fit the largest practical font size that stays inside the text box instead of only shrinking from the model's proposed size. This prevents conservative fallback layouts from becoming visibly too small.
- Grouped text such as speech bubbles, word lists, tables, and cards should eventually be fitted as a group: preserve row rhythm, English/Chinese size ratio, and line spacing across sibling elements instead of optimizing each text box in isolation.
- Same visual block, card, column, table column, or bullet group must share stable alignment anchors. Do not let each line drift independently.
- Body text must start at the first real text glyph. Marker icons such as checks, crosses, bullets, badges, and numbers should not define the body text `x`.
- Missing text added by the model must be positioned from nearby same-level anchors, such as the opposing card title or sibling bullet row, not arbitrary model coordinates.
- Use raw OCR text/word boxes as `mask_texts` for cleanup only; do not create duplicate editable text from mask hints.
- Build text masks from both raw OCR word boxes and model-repaired text boxes so missing OCR regions still get cleanup coverage.
- For large hero text, quote blocks, oversized decorative text, or low-contrast gray typography, do not rely only on word-level masks. Use a broad block-level mask covering the full text region so old glyph edges do not remain behind the editable replacement.
- Preserve slide coordinate space in source pixels, then convert deterministically to PPTX units.
- Keep page-specific manual/rule-based layout repair allowed during representative-page development.
- Promote recurring repairs into scripts only after the same pattern appears across multiple pages.

## Repair Pass

After model output and before final preview, inspect representative pages for:

- missing important text, labels, titles, captions, table cells, or diagram labels;
- hallucinated or duplicated text;
- broken reading order or grouping;
- text clipped by PowerPoint/LibreOffice rendering;
- text placed over important visual content;
- old text remnants in the background;
- residual-text QA failures in `background_text_qa.json`;
- false positive residual OCR on illustrated pages. If OCR output is gibberish from drawing strokes rather than source text, verify visually or by matching against known source text before marking the background failed;
- simple shapes/highlights overlapping text incorrectly;
- charts, tables, diagrams, or images damaged by cleanup;
- obvious font, size, color, or alignment mismatches.

The repair pass should be based on the classified page type. For example, a data page needs table/chart integrity checks; a diagram page needs connector/label checks; an image page needs media preservation checks.

## PPTX Generation Defaults

- Default final rebuild mode: `text-overlay` with `--background-key clean_background`.
- Default orchestrated workflow mode: `clean-required`.
- Use `cover-text` only for quick prototypes, debugging, or pages where background cleanup would damage the visual result.
- Use `clean-text` as an intermediate cleanup step, not as the default final deliverable.
- Remote image URLs may stay in JSON but should not be fetched implicitly during rebuild.
- Use stable reconstruction fonts: default to `Noto Sans SC` for Chinese and `Inter` for Latin text. If the machine lacks those fonts, choose only from `Source Han Sans CN` / `思源黑体 CN`, `Arial`, and `Times New Roman`.
- Font size, font family, color, and weight must be estimated from the original slide, then normalized by visual hierarchy. Do not let a model's guessed style values override original-slide measurements.
- Treat style as a separate evidence layer from geometry. `positionLocked` and `fontSizeLocked` do not imply `fontWeightLocked`, `fontFamilyLocked`, or `lineSpacingLocked`.
- Every rebuilt text element should carry style provenance where possible: `fontWeightSource`, `fontWeightLocked`, `fontWeightConfidence`, `styleEvidence`, and `styleSource`. The same pattern should be extended to font family and line spacing when their fitters are implemented.
- Model-only `fontWeight` evidence is advisory for body text until it is corroborated by OCR/visual evidence or a font fitter. Do not turn ordinary body text bold solely because a model estimated `fontWeight=600`.
- Derive final `font_bold` from original-slide visual evidence, such as role, tight ink-density, and corroborated style parsing. Record `styleEvidence`, `fontWeightSource`, and `fontWeightConfidence` in layout JSON. The PPTX renderer must execute those recorded fields and must not choose bold/regular on its own.
- Same visual list, glossary, table column, card, or repeated text group should use group-level style consistency. If sibling rows share column alignment, role, and comparable size, normalize their font weight from group evidence instead of letting each OCR row independently flip between bold and regular.
- Font family selection must be a render-fit step, not a model guess. Candidate fonts must come from the approved pool and be scored against the original OCR region by rendered width and ink density. Record `fontFit`, `fontFamilySource`, previous font, selected font, score, width ratio, and size compensation in layout JSON.
- For fitted groups, normalize sibling rows to the same selected font family and median fitted size. Do not let each row in a glossary/list independently pick a different font family.
- Mixed Chinese/Latin glossary and list groups are high-risk for font substitution because CJK and Latin glyph metrics can diverge sharply. Preserve the approved CJK default font and group typography for these groups unless a candidate repeatedly improves preview quality across representative pages.
- Font weight fitting may change weight for titles and high-confidence style groups, but ordinary body/dialogue text must not become bold solely because a bold candidate matches width better.
- Same-level text should use consistent typography. Titles, card headings, body rows, captions, and labels should not randomly vary in size or alignment.
- PowerPoint text boxes must be top-anchored, with explicit zero paragraph spacing and controlled line spacing. Do not rely on default PowerPoint/LibreOffice paragraph spacing, because it can make a correctly positioned text box render as if the text moved downward.
- Text-box height and line spacing must be explicit layout fields, such as `textBoxHeightScale` and `lineSpacing`. Avoid renderer-wide height padding constants; they create excess blank space and hide real typography problems.
- PPTX generation must not silently substitute fonts selected by the font-fit stage. If the selected font is unavailable, treat it as an environment/font-pool issue and fix upstream.
- Calibrate source-pixel font size to PPT point size with a stable render scale and preview verification. If the coordinate is correct but the rendered size is wrong, fix the PPTX render mapping before changing OCR coordinates. Do not clamp trusted OCR font sizes to a fixed maximum point size during PPTX generation.
- Treat the OCR/visual layout JSON as the reconstruction contract. If a locked text box renders incorrectly, diagnose unit conversion, font substitution, or PowerPoint paragraph behavior first; do not mutate locked OCR coordinates or font sizes to compensate.
- Infer bold only from reliable original-slide evidence: title role, explicit OCR/visual style evidence, or high-confidence style parsing. Do not infer bold from structure labels such as `Q:` / `A:` alone, and do not globally bold all large body text, because speech bubbles, captions, and list rows may become too heavy.
- If a style decision is visually wrong, debug the style evidence layer first. Do not fix style errors by changing OCR coordinates, font sizes, or text box geometry.

## Two-Module Diagnosis

When the rebuilt PPTX differs noticeably from the original slide, diagnose the failure through two modules before changing prompts or applying page-specific patches:

- **OCR / parsing module**: verify text content, reading order, element grouping, `x`, `y`, `width`, `height`, `fontSize`, color, and style evidence against the original image. This module is the prerequisite for every downstream step; if its output is wrong, stop and improve OCR, visual parsing, or semantic fusion first.
- **Rebuild module**: verify that the PPTX renderer reproduced the locked OCR/visual layout JSON by deterministic unit conversion. If layout JSON is correct but preview is wrong, fix font substitution, source-pixel-to-PPT-point scaling, line spacing, paragraph spacing, or PowerPoint text box behavior.
- Do not let the two modules compensate for each other's errors. Do not move OCR boxes to hide renderer drift, and do not use renderer shrink-to-fit to hide bad OCR boxes.
- Final quality improvement should be an iterative cross-check: original image -> OCR/visual layout contract -> rebuilt PPTX preview -> difference diagnosis -> update the responsible module only.

## Quality Gate

A representative reconstruction is acceptable when:

- the PPTX opens and renders without fatal errors;
- important text is editable;
- visual hierarchy is close enough for the target use;
- no important content is missing;
- background cleanup does not damage key visuals;
- no duplicated old text remains behind editable replacement text;
- residual-text QA is clean, or the page is explicitly marked for image-model repair before final delivery;
- element count remains manageable;
- screenshot previews have been inspected.
- when visual differences remain, the issue has been attributed to either OCR/parsing or rebuild rendering, with the next repair assigned to the responsible module.

If any quality gate fails, fix the representative layout or choose a less aggressive reconstruction strategy before full-deck conversion.

## Case-Specific Learning Policy

- Specific fixes from one deck are examples, not global defaults.
- Do not hardcode a deck's structure, wording, icon pattern, or visual style into general rules.
- Extract only transferable patterns, such as page classification, mask-assisted cleanup, explicit line-break preservation, or element-type selection.
- Keep case-specific layout JSON outside the skill rules unless it has become a repeated cross-deck pattern.
