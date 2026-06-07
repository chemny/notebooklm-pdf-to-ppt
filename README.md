# NotebookLM PDF To PPT

中文 | [English](README.en.md)

把 NotebookLM、课件工具或其他来源导出的图片型 PDF，重建成带有可编辑文字层的 PowerPoint 文件。

这是一个 **v0.1.0 preview** 版本。它适合做代表页测试、PDF 转可编辑 PPTX 的工作流实验、OCR/背景清理/重建效果诊断；还不应该被包装成成熟的全量高保真转换器。

## 适合谁

- 想把 NotebookLM 导出的图片型课件 PDF 变成可编辑 PPTX 的用户；
- 想研究“图片型 PPT/PDF -> 可编辑文字层 + 干净背景”的开发者；
- 想用 agent skill 通过聊天触发本地转换流程的人；
- 需要先跑几页代表页，看 OCR、背景清理和 PPTX 重建哪里出问题的工作流设计者。

不适合：

- 期望一次性把整套复杂 PPT 100% 还原的人；
- 需要把所有图标、图表、插画、形状都拆成可编辑对象的人；
- 想让 NotebookLM 生成课程、播客、讲义或测验的人。那些属于 NotebookLM 内容工作流，不属于这个 skill。

## 核心能力

- 渲染 PDF 指定页面为图片；
- 用 OCR 提取文字、坐标、字号估计、颜色和分组信息；
- 清理背景中的旧文字；
- 用 `python-pptx` 重建可编辑文字层；
- 用 LibreOffice 和 `pdftoppm` 生成预览图；
- 输出 `layout.json` 和 `qa_summary.json`，便于区分 OCR/解析问题和 PPTX 渲染问题；
- 支持代表页优先，而不是一开始就跑完整套文件。

## 设计原则

这个 skill 把问题拆成两个模块：

- **OCR / 解析层**：负责文字内容、坐标、分组、字号、颜色、样式证据；
- **PPTX 重建层**：负责单位换算、字体映射、文本框边距、行距、预览渲染。

如果 OCR 错了，就修 OCR/解析；如果 layout JSON 对但预览错了，就修 PPTX 重建。不要让渲染层通过随意移动、缩放、改字来掩盖 OCR 问题。

## 安装

克隆仓库后，把仓库文件夹放到你的 agent skills 目录中，确保 `SKILL.md` 位于 skill 根目录。

```bash
git clone https://github.com/<owner>/notebooklm-pdf-to-ppt.git
```

如果你的 agent 运行时会缓存 skill 列表，安装后重新打开一个会话。

## 依赖

默认本地流程需要：

- Python 3.10+
- Python 包：`Pillow`、`python-pptx`、`numpy`
- Poppler 工具：`pdftoppm`、`pdfinfo`
- LibreOffice：用于把 PPTX 转成预览图

推荐安装：

- Tesseract OCR
- PaddleOCR，并通过 `PADDLEOCR_PYTHON` 指向单独虚拟环境里的 Python

可选：

- 图像模型 API，用于 `--background model-clean`
- PyMuPDF / `fitz`，用于旧版或实验脚本
- `pptxgenjs`，用于实验 JS 渲染器

## 快速开始

先跑一两页代表页：

```bash
PYTHONDONTWRITEBYTECODE=1 python scripts/run_simple.py \
  --pdf /path/to/source.pdf \
  --pages 1,2 \
  --output-dir /path/to/output \
  --ocr auto \
  --background local-clean
```

输出目录结构：

```text
output/
├── 01_rendered/        # PDF 页面渲染图
├── 02_ocr/             # layout.json 和 qa_summary.json
├── 03_cleaned/         # local-clean 背景
├── 03_model_cleaned/   # model-clean 背景
├── 04_pptx/            # editable_text_overlay.pptx
└── 05_previews/        # 预览 PNG
```

## 背景模式

- `original`：保留原图，只叠加可编辑文字，适合调试文字位置；
- `local-clean`：本地快速填充旧文字区域，适合白底或简单背景；
- `model-clean`：调用图像模型移除旧文字，适合插画、纹理、气泡、卡片等复杂背景。

模型背景清理示例：

```bash
VISION_API_KEY=<your-key> PYTHONDONTWRITEBYTECODE=1 python scripts/run_simple.py \
  --pdf /path/to/source.pdf \
  --pages 1 \
  --output-dir /path/to/output \
  --ocr auto \
  --background model-clean \
  --model-provider openai-image \
  --model-clean-model gpt-image-2-all \
  --model-clean-base-url https://api.openai.com
```

图像模型只应做“基于原图移除文字”的编辑任务，不应该重新设计、重绘或改动非文字元素。

## 已沉淀的通用规则

- 同一基线、同一字体策略、垂直重叠充分的 OCR 片段应合并成一个可编辑文本框；
- OCR 框因为检测过宽产生水平重叠时，只要仍符合阅读方向和样式一致性，应在 OCR 规范化阶段合并；
- 同一视觉区域、同一列、同一卡片/气泡/面板里的连续正文行，可以合并成一个可编辑段落，并保留可见换行；
- 标题、表格单元格、词汇表/列表、Q/A 对、独立卡片或无关说明文字不应因为距离近而被误合并；
- 字体选择只从批准字体池中进行，不随意接受模型或 OCR 猜测；
- 背景清理必须移除旧文字，避免和可编辑文字层重叠。

## 检查

只读环境检查：

```bash
python scripts/check_readiness.py
```

发布前检查：

```bash
python scripts/smoke_test.py
python scripts/publish_check.py
```

这些检查不会发布、提交、推送或调用外部模型。

## 仓库结构

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

## 兼容性

设计上面向 Codex、Claude Code 和 OpenClaw 的通用 skill 结构。当前本地验证主要在 Codex 中完成；Claude Code 和 OpenClaw 可按普通本地脚本 skill 使用，但需要自行配置 Python、OCR、LibreOffice 和可选模型 API 环境。

## 许可证

MIT
