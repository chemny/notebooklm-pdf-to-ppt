# NotebookLM PDF To PPT

中文 | [English](README.en.md)

把 NotebookLM、课件工具或其他来源导出的图片型 PDF，重建成带有可编辑文字层的 PowerPoint 文件。

这是一个 **v0.1.8 preview** 版本。它适合做代表页测试、PDF 转可编辑 PPTX 的工作流实验、OCR/背景清理/重建效果诊断；还不应该被包装成成熟的全量高保真转换器。

## 适合谁

- 想把 NotebookLM 导出的图片型课件 PDF 变成可编辑 PPTX 的用户；
- 想研究“图片型 PPT/PDF -> 可编辑文字层 + 干净背景”的开发者；
- 想用 agent skill 通过聊天触发本地转换流程的人；
- 需要先跑几页代表页，看 OCR、背景清理和 PPTX 重建哪里出问题的工作流设计者。

## 核心能力

| 能力 | 帮你完成什么 |
| --- | --- |
| 代表页转换 | 先处理少量典型页面，快速判断整套课件是否值得继续转换 |
| PaddleOCR 文字解析 | 提取文字、坐标、字号估计、颜色和分组信息 |
| 背景文字清理 | 移除扁平背景里的旧文字，避免和可编辑文字重复 |
| 可编辑 PPTX 重建 | 用 `python-pptx` 生成带背景图和可编辑文字框的 PowerPoint |
| 诊断输出 | 输出 `layout.json`、`qa_summary.json`，用于定位问题归属 |

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

安装后可以用一句话验证 skill 是否被识别：

```text
使用 notebooklm-pdf-to-ppt，检查这个 skill 的 readiness，并告诉我还缺哪些依赖。
```

## 依赖

核心转换流程需要：

- Python 3.10+
- Python 包：`Pillow`、`python-pptx`、`numpy`
- Poppler 工具：`pdftoppm`、`pdfinfo`
- PaddleOCR，并通过 `PADDLEOCR_PYTHON` 指向单独虚拟环境里的 Python
- 当前优先 PaddleOCR 模型：`PP-OCRv6_small_det` + `PP-OCRv6_small_rec`
- 如果当前 PaddleOCR 版本不支持 v6 small，自动 fallback 到官方 `PP-OCRv5_mobile_det` + `PP-OCRv5_mobile_rec`

可选：

- 图像模型 API，用于无人值守的 `--background model-clean`

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
└── 04_pptx/            # editable_text_overlay.pptx
```

## 核心工作流

### 代表页测试

先选 1-2 页代表页运行，不要一开始处理整套文件。优先覆盖不同页面类型，例如标题页、纯文字页、插画页、表格页或气泡对话页。输出后根据 `02_ocr/qa_summary.json` 和生成的 PPTX 判断问题属于 OCR、背景清理还是 PPTX 重建。

### 本地背景清理

当页面是白底、纯色背景或简单卡片时，使用 `--background local-clean`。它速度快、可重复，但复杂插画页可能留下浅色遮挡块。

### 模型背景清理

当旧文字嵌在插画、纹理、气泡或卡片里时，使用 `--background model-clean`。在 Codex 对话中，默认使用 `codex-image`：脚本会生成 Codex 图像清理请求包，由 Codex 内置图像工具编辑原图；无人值守 CLI/API 场景可显式切换到 `openai-image` 或 `gemini-native`。模型只应移除文字像素，保留容器、插画、图标、构图和比例。

### QA 诊断

如果预览和原稿差距明显，先看 `layout.json`：文字、坐标、字号、分组是否正确。layout 错就修 OCR/解析；layout 对但预览错，再修 PPTX 重建。

## 命令参考

| 参数 | 作用 |
| --- | --- |
| `--pdf` | 输入 PDF 路径 |
| `--pages` | 页码范围，例如 `1,2`、`3-5` |
| `--output-dir` | 输出目录 |
| `--ocr` | `auto` 或 `paddle`；当前主流程只走 PaddleOCR |
| `--ocr-batch-size` | PaddleOCR 每批处理页数；默认 `0` 表示一次 worker 处理全部选中页；内存紧张时可设为 `3` 或 `1` |
| `--background` | `original`、`local-clean` 或 `model-clean` |
| `--model-provider` | 图像清理后端；默认 `codex-image`，也可用 `openai-image` 或 `gemini-native` |
| `--model-clean-model` | 背景清理模型名称 |
| `--model-clean-base-url` | 模型 API base URL |
| `--model-clean-api-key-env` | API key 所在环境变量名 |
| `--model-clean-fallback` | 模型清理失败后的回退策略 |

## 背景模式

- `original`：保留原图，只叠加可编辑文字，适合调试文字位置；
- `local-clean`：本地快速填充旧文字区域，适合白底或简单背景；
- `model-clean`：调用图像清理后端移除旧文字，适合插画、纹理、气泡、卡片等复杂背景。Codex 中默认生成 `codex_image_request` 供内置图像工具处理；无人值守运行时显式使用 API 后端。

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
  --model-clean-base-url https://yunwu.ai
```

图像模型只应做“基于原图移除文字”的编辑任务，不应该重新设计、重绘或改动非文字元素。

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

设计上面向 Codex、Claude Code 和 OpenClaw 的通用 skill 结构。当前本地验证主要在 Codex 中完成；Claude Code 和 OpenClaw 可按普通本地脚本 skill 使用，但需要自行配置 Python、OCR、Poppler 和可选的模型 API 环境。

## 许可证

MIT
