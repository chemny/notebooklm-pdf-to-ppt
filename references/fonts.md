# PPT Font Catalog

Use this reference when reconstructing editable PPT decks from image-based NotebookLM or Codia-like slide outputs.

## Source

- Codia NoteSlide font list snapshot: `references/codia-google-fonts-list.json`
- Source URL: https://codia.ai/noteslide/google-fonts-list.json
- Snapshot count: 1943 Google Fonts families
- Snapshot date: 2026-06-06

## Default Fallback Fonts

Approved reconstruction font pool:

- Inter
- Arial
- Times New Roman
- Noto Sans SC
- Source Han Sans CN / 思源黑体 CN
- Comic Sans MS
- Chalkboard SE
- Marker Felt
- ZCOOL KuaiLe

## Simplified Chinese Fonts

These families in the Codia/Google Fonts list advertise `chinese-simplified` support:

- Liu Jian Mao Cao
- Long Cang
- Ma Shan Zheng
- Noto Sans SC
- Noto Serif SC
- WDXL Lubrifont SC
- ZCOOL KuaiLe
- ZCOOL QingKe HuangYou
- ZCOOL XiaoWei
- Zhi Mang Xing

## Traditional Chinese Fonts

These families advertise `chinese-traditional` support:

- Bpmf Huninn
- Bpmf Iansui
- Bpmf Zihi Kai Std
- Cactus Classical Serif
- Chiron GoRound TC
- Chiron Hei HK
- Chocolate Classical Sans
- Huninn
- Iansui
- LXGW Marker Gothic
- LXGW WenKai Mono TC
- LXGW WenKai TC
- Noto Sans TC
- Noto Serif TC
- UoqMunThenKhung
- WDXL Lubrifont TC

## Hong Kong Chinese Fonts

These families advertise `chinese-hongkong` support:

- Chiron Sung HK
- Noto Sans HK
- Noto Serif HK

## Practical PPT Mapping Guidance

- For Chinese lesson body text, use `Noto Sans SC` by default.
- If `Noto Sans SC` is unavailable, use `Source Han Sans CN` / `思源黑体 CN`.
- For Chinese serif or editorial-style headings, prefer `Noto Serif SC`.
- For handwritten or playful lesson slides, consider `Ma Shan Zheng`, `Long Cang`, `ZCOOL KuaiLe`, or `Zhi Mang Xing`.
- For Latin-heavy slides, use `Inter` by default.
- If `Inter` is unavailable, use `Arial`, then `Times New Roman`.
- For classroom/playful English titles, prefer `Comic Sans MS`, `Chalkboard SE`, or `Marker Felt` when the source title is visibly handwritten or rounded.
- Do not apply playful fonts to body text by default. Limit them to clear title/label roles.
- Do not accept arbitrary model/OCR font guesses. Normalize all reconstructed text to the approved font pool before writing `layout.json` or PPTX XML.
