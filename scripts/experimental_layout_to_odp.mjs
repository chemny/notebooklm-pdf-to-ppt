#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const SLIDE_W_IN = 13.333333;
const SLIDE_H_IN = 7.5;
const SLIDE_W_CM = 33.8667;
const SLIDE_H_CM = 19.05;
const FONT_SCALE = 1.03;

function argValue(name, fallback = null) {
  const idx = process.argv.indexOf(name);
  return idx >= 0 && idx + 1 < process.argv.length ? process.argv[idx + 1] : fallback;
}

function esc(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function colorFor(value, fallback = '#111111') {
  const raw = String(value || fallback);
  return /^#[0-9A-Fa-f]{6}$/.test(raw) ? raw : fallback;
}

function containsCjk(text) {
  return /[\u3400-\u9fff]/.test(text || '');
}

function fontFor(text, item) {
  return item.font_family || item.fontFamily || (containsCjk(text) ? 'Noto Sans SC' : 'Inter');
}

function cmX(px, imgW) {
  return Number(px || 0) / imgW * SLIDE_W_CM;
}

function cmY(px, imgH) {
  return Number(px || 0) / imgH * SLIDE_H_CM;
}

function fontPt(item, imgH) {
  return Math.max(1, Number(item.font_size_px || 28) * SLIDE_H_IN / imgH * 72 * FONT_SCALE);
}

function textContent(text) {
  const lines = String(text || '').split(/\n/);
  return lines.map(esc).join('<text:line-break/>');
}

function copyImage(src, picturesDir, imageMap) {
  const abs = path.resolve(src);
  if (imageMap.has(abs)) return imageMap.get(abs);
  const ext = path.extname(abs).toLowerCase() || '.png';
  const name = `Pictures/image_${String(imageMap.size + 1).padStart(3, '0')}${ext}`;
  fs.copyFileSync(abs, path.join(picturesDir, path.basename(name)));
  imageMap.set(abs, name);
  return name;
}

function buildContent(layout, picturesDir, backgroundKey) {
  const imageMap = new Map();
  const autoStyles = [];
  const pages = [];
  let styleId = 1;
  let frameId = 1;

  autoStyles.push(`
    <style:style style:name="dp1" style:family="drawing-page">
      <style:drawing-page-properties presentation:background-visible="true" presentation:background-objects-visible="true" presentation:display-header="false" presentation:display-footer="false" presentation:display-page-number="false"/>
    </style:style>
    <style:style style:name="gr1" style:family="graphic">
      <style:graphic-properties draw:fill="none" draw:stroke="none"/>
    </style:style>`);

  for (const [pageIdx, page] of (layout.slides || []).entries()) {
    const imgW = Number(page.width || 3440);
    const imgH = Number(page.height || 1920);
    const bg = copyImage(page[backgroundKey] || page.image, picturesDir, imageMap);
    const frames = [];
    frames.push(`
      <draw:frame draw:name="background_${pageIdx + 1}" draw:style-name="gr1" draw:z-index="0" svg:x="0cm" svg:y="0cm" svg:width="${SLIDE_W_CM}cm" svg:height="${SLIDE_H_CM}cm">
        <draw:image xlink:href="${esc(bg)}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>
      </draw:frame>`);

    for (const item of page.texts || []) {
      const text = String(item.text || '');
      const family = fontFor(text, item);
      const tStyle = `T${styleId}`;
      const pStyle = `P${styleId}`;
      const gStyle = `G${styleId}`;
      styleId += 1;
      const pt = fontPt(item, imgH).toFixed(2);
      const bold = item.bold ? 'bold' : 'normal';
      const alignRaw = Array.isArray(item.align) ? item.align[0] : item.align;
      const align = String(alignRaw || 'left').toLowerCase() === 'center' ? 'center' : String(alignRaw || 'left').toLowerCase() === 'right' ? 'end' : 'start';
      autoStyles.push(`
        <style:style style:name="${gStyle}" style:family="graphic">
          <style:graphic-properties draw:fill="none" draw:stroke="none" fo:padding="0cm" fo:margin="0cm" style:vertical-pos="top"/>
        </style:style>
        <style:style style:name="${pStyle}" style:family="paragraph">
          <style:paragraph-properties fo:text-align="${align}" fo:margin-top="0cm" fo:margin-bottom="0cm" fo:line-height="92%"/>
        </style:style>
        <style:style style:name="${tStyle}" style:family="text">
          <style:text-properties fo:font-size="${pt}pt" fo:font-weight="${bold}" fo:color="${colorFor(item.color)}" style:font-name="${esc(family)}" style:font-name-asian="${esc(family)}"/>
        </style:style>`);
      frames.push(`
        <draw:frame draw:name="text_${frameId++}" draw:style-name="${gStyle}" draw:z-index="${frameId}" svg:x="${cmX(item.x, imgW).toFixed(4)}cm" svg:y="${cmY(item.y, imgH).toFixed(4)}cm" svg:width="${Math.max(cmX(item.width, imgW), 0.2).toFixed(4)}cm" svg:height="${Math.max(cmY(item.height, imgH), 0.2).toFixed(4)}cm">
          <draw:text-box>
            <text:p text:style-name="${pStyle}"><text:span text:style-name="${tStyle}">${textContent(text)}</text:span></text:p>
          </draw:text-box>
        </draw:frame>`);
    }

    pages.push(`
      <draw:page draw:name="page${pageIdx + 1}" draw:style-name="dp1" draw:master-page-name="Default">
        ${frames.join('\n')}
      </draw:page>`);
  }

  return `<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
  xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.3">
  <office:automatic-styles>
    <style:style style:name="PM1" style:family="presentation" style:parent-style-name="Default-title"/>
    <style:page-layout style:name="PM0"><style:page-layout-properties fo:margin="0cm" fo:page-width="${SLIDE_W_CM}cm" fo:page-height="${SLIDE_H_CM}cm" style:print-orientation="landscape"/></style:page-layout>
    ${autoStyles.join('\n')}
  </office:automatic-styles>
  <office:body>
    <office:presentation>
      ${pages.join('\n')}
    </office:presentation>
  </office:body>
</office:document-content>`;
}

function writeStaticFiles(root) {
  fs.writeFileSync(path.join(root, 'mimetype'), 'application/vnd.oasis.opendocument.presentation');
  fs.writeFileSync(path.join(root, 'meta.xml'), `<?xml version="1.0" encoding="UTF-8"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" office:version="1.3"><office:meta/></office:document-meta>`);
  fs.writeFileSync(path.join(root, 'styles.xml'), `<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" office:version="1.3">
  <office:styles/>
  <office:automatic-styles>
    <style:page-layout style:name="PM0">
      <style:page-layout-properties fo:margin="0cm" fo:page-width="${SLIDE_W_CM}cm" fo:page-height="${SLIDE_H_CM}cm" style:print-orientation="landscape"/>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Default" style:page-layout-name="PM0"/>
  </office:master-styles>
</office:document-styles>`);
  fs.mkdirSync(path.join(root, 'META-INF'), { recursive: true });
  fs.writeFileSync(path.join(root, 'META-INF', 'manifest.xml'), `<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="Pictures/" manifest:media-type=""/>
</manifest:manifest>`);
}

function main() {
  const layoutPath = argValue('--layout');
  const output = argValue('--output');
  const backgroundKey = argValue('--background-key', 'clean_background');
  if (!layoutPath || !output) {
    console.error('Usage: experimental_layout_to_odp.mjs --layout layout.json --output deck.odp');
    process.exit(2);
  }
  const layout = JSON.parse(fs.readFileSync(layoutPath, 'utf8'));
  const out = path.resolve(output);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const tmp = fs.mkdtempSync(path.join(path.dirname(out), '.odp-build-'));
  const pictures = path.join(tmp, 'Pictures');
  fs.mkdirSync(pictures, { recursive: true });
  writeStaticFiles(tmp);
  fs.writeFileSync(path.join(tmp, 'content.xml'), buildContent(layout, pictures, backgroundKey));
  fs.rmSync(out, { force: true });
  execFileSync('zip', ['-0Xq', out, 'mimetype'], { cwd: tmp });
  execFileSync('zip', ['-Xqr', out, 'content.xml', 'styles.xml', 'meta.xml', 'META-INF', 'Pictures'], { cwd: tmp });
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(JSON.stringify({ ok: true, odp: out, slides: (layout.slides || []).length }, null, 2));
}

main();
