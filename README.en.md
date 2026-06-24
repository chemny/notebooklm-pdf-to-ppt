# NotebookLM PDF To PPT

[中文](README.md) | English

Convert flattened NotebookLM-style slide PDFs into editable PowerPoint decks. This skill focuses on post-export reconstruction: OCR, background text cleanup, editable PPTX rebuild, and quality diagnosis.

This is a **v0.1.8 preview** skill. It is useful for representative-page testing and workflow iteration, but it is not yet a guaranteed high-fidelity full-deck converter.

## Who Should Use It

- Users who want to turn NotebookLM slide PDF exports into editable PPTX files.
- Developers studying image-based PDF/PPT reconstruction.
- Agent users who want to trigger a local conversion workflow through chat.
- Workflow designers who need representative-page diagnostics before processing a full deck.

## Core Capabilities

| Capability | What it helps you do |
| --- | --- |
| Representative-page conversion | Test a few typical pages before spending time on a full deck |
| PaddleOCR text parsing | Extract text, coordinates, estimated font size, color, and grouping metadata |
| Background text cleanup | Remove old flattened text so editable replacement text is not duplicated |
| Editable PPTX rebuild | Generate a PowerPoint deck with clean backgrounds and editable text boxes |
| Diagnostic output | Write `layout.json` / `qa_summary.json` to separate OCR issues from rebuild issues |

## Requirements

Required for the core conversion flow:

- Python 3.10+
- Python packages: `Pillow`, `python-pptx`, `numpy`
- Poppler tools: `pdftoppm`, `pdfinfo`
- PaddleOCR in a separate virtual environment, configured with `PADDLEOCR_PYTHON`
- Preferred PaddleOCR models: `PP-OCRv6_small_det` + `PP-OCRv6_small_rec`
- If the installed PaddleOCR version does not support v6 small, the worker falls back to official `PP-OCRv5_mobile_det` + `PP-OCRv5_mobile_rec`

Optional:

- Image model API credentials for unattended `--background model-clean`

## Install

Clone this repository, then place or symlink the repository folder into your agent skills directory so that `SKILL.md` is at the skill root.

```bash
git clone https://github.com/<owner>/notebooklm-pdf-to-ppt.git
```

Start a fresh agent session after installation if your agent runtime caches the skill list.

Verification prompt:

```text
Use notebooklm-pdf-to-ppt to check readiness and tell me which dependencies are missing.
```

## Quick Start

Run the default representative-page flow:

```bash
PYTHONDONTWRITEBYTECODE=1 python scripts/run_simple.py \
  --pdf /path/to/source.pdf \
  --pages 1,2 \
  --output-dir /path/to/output \
  --ocr auto \
  --background local-clean
```

## Core Workflows

### Representative-Page Test

Run one or two representative pages first. Pick pages by visual structure, such as title pages, text pages, illustration pages, tables, or speech-bubble dialogue pages. Use `02_ocr/qa_summary.json` and the generated PPTX to decide whether the issue belongs to OCR/parsing, background cleanup, or PPTX rebuild.

### Local Background Cleanup

Use `--background local-clean` for white, flat, or simple card backgrounds. It is fast and deterministic, but it may leave visible fill blocks on illustrated pages.

### Model Background Cleanup

Use `--background model-clean` when old text is embedded in illustrations, textured backgrounds, cards, or speech bubbles. In Codex chat, the default backend is `codex-image`: the script writes a Codex image-clean request package, and Codex should use the built-in image tool to edit the original image. For unattended CLI/API runs, explicitly switch to `openai-image` or `gemini-native`. The model should remove only text pixels and preserve containers, icons, illustrations, composition, and aspect ratio.

### QA Diagnosis

When the PPTX differs from the source, inspect `layout.json` first. If text, coordinates, font size, or grouping are wrong, fix OCR/parsing. If layout JSON is correct but the PPTX output is wrong, fix PPTX rebuild.

For illustrated or textured pages, use model background cleanup:

```bash
VISION_API_KEY=<your-key> PYTHONDONTWRITEBYTECODE=1 python scripts/run_simple.py \
  --pdf /path/to/source.pdf \
  --pages 1 \
  --output-dir /path/to/output \
  --ocr auto \
  --background model-clean \
  --model-provider openai-image \
  --model-clean-model gpt-image-2-all \
  --model-clean-base-url https://yunwu.ai
```

## Command Reference

| Option | Purpose |
| --- | --- |
| `--pdf` | Input PDF path |
| `--pages` | Page selection, such as `1,2` or `3-5` |
| `--output-dir` | Output directory |
| `--ocr` | `auto` or `paddle`; the current main flow uses PaddleOCR only |
| `--ocr-batch-size` | Pages per PaddleOCR worker batch; default `0` means one worker handles all selected pages; set `3` or `1` on memory-constrained machines |
| `--background` | `original`, `local-clean`, or `model-clean` |
| `--model-provider` | Background cleanup backend; default `codex-image`, also supports `openai-image` or `gemini-native` |
| `--model-clean-model` | Background cleanup model name |
| `--model-clean-base-url` | Model API base URL |
| `--model-clean-api-key-env` | Environment variable that stores the API key |
| `--model-clean-fallback` | Fallback behavior when model cleanup fails |

## Output Structure

```text
output/
├── 01_rendered/        # rendered source pages
├── 02_ocr/             # layout.json and qa_summary.json
├── 03_cleaned/         # local-clean backgrounds
├── 03_model_cleaned/   # model-clean backgrounds
└── 04_pptx/            # editable_text_overlay.pptx
```

## Readiness Check

```bash
python scripts/check_readiness.py
```

This check is read-only. It reports local dependencies and does not install packages or call external APIs.

For public release checks:

```bash
python scripts/smoke_test.py
python scripts/publish_check.py
```

## Repository Structure

```text
notebooklm-pdf-to-ppt/
├── SKILL.md
├── README.md
├── README.en.md
├── LICENSE
├── agents/
├── references/
└── scripts/
```

## Compatibility

Designed to be portable across Codex, Claude Code, and OpenClaw. Current local validation has been performed in Codex; Claude Code and OpenClaw should treat scripts as standard local command helpers and may require their own Python, OCR, Poppler, and optional model API setup.

## License

MIT
