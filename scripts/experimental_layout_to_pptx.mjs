#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let PptxGenJS;
try {
  PptxGenJS = require('pptxgenjs');
} catch (_error) {
  console.error('Missing optional dependency: pptxgenjs. Install it with `npm install pptxgenjs` before using this experimental renderer.');
  process.exit(2);
}

const SLIDE_W = 13.333333;
const SLIDE_H = 7.5;
const FONT_SCALE = 1.03;

function argValue(name, fallback = null) {
  const idx = process.argv.indexOf(name);
  if (idx < 0 || idx + 1 >= process.argv.length) return fallback;
  return process.argv[idx + 1];
}

function containsCjk(text) {
  return /[\u3400-\u9fff]/.test(text || '');
}

function fontFor(text, item) {
  return item.font_family || item.fontFamily || (containsCjk(text) ? 'Noto Sans SC' : 'Inter');
}

function colorFor(value, fallback = '111111') {
  const text = String(value || fallback).replace(/^#/, '');
  return /^[0-9A-Fa-f]{6}$/.test(text) ? text.toUpperCase() : fallback;
}

function alignFor(value) {
  const raw = Array.isArray(value) ? value[0] : value;
  const text = String(raw || 'LEFT').toLowerCase();
  if (text === 'center') return 'center';
  if (text === 'right') return 'right';
  if (text === 'justify' || text === 'justified') return 'justify';
  return 'left';
}

function addTextbox(slide, item, imgW, imgH) {
  const text = String(item.text || '');
  const x = Number(item.x || 0) / imgW * SLIDE_W;
  const y = Number(item.y || 0) / imgH * SLIDE_H;
  const w = Math.max(Number(item.width || 100) / imgW * SLIDE_W, 0.15);
  const h = Math.max(Number(item.height || 30) / imgH * SLIDE_H, 0.12);
  const fontSize = Math.max(1, Number(item.font_size_px || 28) * SLIDE_H / imgH * 72 * FONT_SCALE);
  slide.addText(text, {
    x, y, w, h,
    fontFace: fontFor(text, item),
    fontSize,
    color: colorFor(item.color),
    bold: Boolean(item.bold),
    margin: 0,
    breakLine: false,
    fit: 'shrink',
    valign: 'top',
    align: alignFor(item.align),
    paraSpaceAfterPt: 0,
    paraSpaceBeforePt: 0,
    breakLine: false,
  });
}

async function main() {
  const layoutPath = argValue('--layout');
  const output = argValue('--output');
  const backgroundKey = argValue('--background-key', 'clean_background');
  if (!layoutPath || !output) {
    console.error('Usage: experimental_layout_to_pptx.mjs --layout layout.json --output deck.pptx [--background-key clean_background]');
    process.exit(2);
  }
  const layout = JSON.parse(fs.readFileSync(layoutPath, 'utf8'));
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.defineLayout({ name: 'CUSTOM_WIDE', width: SLIDE_W, height: SLIDE_H });
  pptx.layout = 'CUSTOM_WIDE';
  pptx.author = 'notebooklm-pdf-to-ppt';
  for (const page of layout.slides || []) {
    const slide = pptx.addSlide();
    const bg = page[backgroundKey] || page.image;
    slide.addImage({ path: bg, x: 0, y: 0, w: SLIDE_W, h: SLIDE_H });
    const imgW = Number(page.width || 3440);
    const imgH = Number(page.height || 1920);
    for (const item of page.texts || []) addTextbox(slide, item, imgW, imgH);
  }
  fs.mkdirSync(path.dirname(output), { recursive: true });
  await pptx.writeFile({ fileName: output });
  console.log(JSON.stringify({ ok: true, pptx: path.resolve(output), slides: (layout.slides || []).length }, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
