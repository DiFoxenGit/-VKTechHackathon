/// <reference types="vite/client" />
import type { Deck, Template, Layout } from '../types';
import { getSlideTypography } from '../algorithms/typography';
import { visualMarkup, visualStyles } from '../analytics';
import { addAnalyticSlide } from './analyticExport';

const escapeHtml = (text: string) => text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
const safeColor = (color: string, fallback: string) => /^#[0-9a-f]{6}$/i.test(color) ? color : fallback;
const safeFont = (font: string) => /^[\p{L}\p{N} _-]{1,80}$/u.test(font) ? font : 'Arial';
const safeFilename = (title: string) => (title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim().slice(0, 100) || 'Презентация');

// Export-only font data stays out of the first screen's JavaScript bundle.
async function embeddedPlayFonts(): Promise<string> {
  const [cyrillic400, cyrillic700, latin400, latin700] = await Promise.all([
    import('@fontsource/play/files/play-cyrillic-400-normal.woff2?inline'),
    import('@fontsource/play/files/play-cyrillic-700-normal.woff2?inline'),
    import('@fontsource/play/files/play-latin-400-normal.woff2?inline'),
    import('@fontsource/play/files/play-latin-700-normal.woff2?inline'),
  ]).catch(error => {
    throw new Error('Не удалось загрузить шрифты для экспорта. Проверьте подключение и повторите попытку.', { cause: error });
  });
  const [playCyrillic400, playCyrillic700, playLatin400, playLatin700] = [cyrillic400.default, cyrillic700.default, latin400.default, latin700.default];
  return `@font-face{font-family:Play;font-style:normal;font-weight:400;src:url('${playCyrillic400}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}@font-face{font-family:Play;font-style:normal;font-weight:700;src:url('${playCyrillic700}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}@font-face{font-family:Play;font-style:normal;font-weight:400;src:url('${playLatin400}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}@font-face{font-family:Play;font-style:normal;font-weight:700;src:url('${playLatin700}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}`;
}

async function htmlDocument(deck: Deck, template: Template): Promise<string> {
  const primary = safeColor(template.color, '#0077FF');
  const secondary = safeColor(template.secondary, '#FF3885');
  const layout: Layout = ['classic', 'story', 'focus'].includes(deck.layout) ? deck.layout : 'classic';
  const slideHtml = deck.slides.map((slide, index) => {
    if (slide.visual) return `<section class="analytic-export"><header>${escapeHtml(template.name)}</header><h2>${escapeHtml(slide.title)}</h2><div class="data-visual">${visualMarkup(slide.visual,primary)}</div><p class="data-source">Источник: ${escapeHtml(slide.visual.source)}</p><footer>${escapeHtml(slide.body)} <span>${index+1} / ${deck.slides.length}</span></footer></section>`;
    const sizes = getSlideTypography(slide, template, layout);
    const eyebrow = slide.kind === 'cover' ? 'ИДЕИ, КОТОРЫЕ ОБЪЕДИНЯЮТ' : `ЧАСТЬ ${String(index).padStart(2, '0')}`;
    return `<section class="slide-canvas layout-${layout} ${slide.kind === 'cover' ? 'is-cover' : ''}" aria-label="Слайд ${index + 1}" style="--body-size:${sizes.body}cqw;--title-size:${sizes.title}cqw"><div class="slide-brand"><span class="vk-mark">${template.custom ? 's' : 'vk'}</span><span>${escapeHtml(template.name.replace('VK ', ''))}</span></div><div class="slide-content"><div class="slide-eyebrow">${eyebrow}</div><h3>${escapeHtml(slide.title || 'Название слайда')}</h3>${slide.body ? `<p>${escapeHtml(slide.body)}</p>` : ''}</div><div class="slide-accent" aria-hidden="true"><div></div><div></div><div></div></div><div class="slide-bottom"><span>${escapeHtml(template.name)} · Презентация</span><span>${String(index + 1).padStart(2, '0')} / ${String(deck.slides.length).padStart(2, '0')}</span></div></section>`;
  }).join('\n');
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>${escapeHtml(deck.title)}</title><style>
${template.font === 'Play' ? await embeddedPlayFonts() : ''}
${visualStyles}
.analytic-export{width:min(1280px,calc(100vw - 32px));aspect-ratio:16/9;box-sizing:border-box;background:#fff;margin:0 auto 32px;padding:24px 48px;display:flex;flex-direction:column;break-after:page;color:#243149}.analytic-export header{font-size:18px;color:${primary}}.analytic-export h2{font-size:28px;margin:12px 0}.analytic-export .data-visual{flex:1;min-height:0}.analytic-export svg{height:100%;max-height:420px}.analytic-export footer{font-size:12px;display:flex;justify-content:space-between}.analytic-export .data-source{margin-bottom:10px}@media print{.analytic-export{width:13.333333in;height:7.5in;margin:0;padding:20px 40px;break-inside:avoid}.analytic-export:last-child{break-after:auto}.analytic-export svg{max-height:4.4in}}
*{box-sizing:border-box}body{margin:0;padding:32px 0;background:#e9edf3;font-family:'${escapeHtml(safeFont(template.font))}',Arial,sans-serif}h3,p{margin:0}.slide-canvas{--slide-color:${primary};--slide-secondary:${secondary};aspect-ratio:16/9;background:#fff;position:relative;overflow:hidden;container-type:inline-size;color:#243149;text-align:left;box-shadow:0 3px 18px #192e5610;width:min(1280px,calc(100vw - 32px));margin:0 auto 32px;break-after:page;page-break-after:always}.slide-brand{position:absolute;left:7%;top:8%;font-size:3cqw;display:flex;gap:1.2cqw;align-items:center;z-index:2;color:var(--slide-color)}.vk-mark{font-family:Arial,sans-serif;font-size:1.1em;letter-spacing:-.15em;padding-right:.2em;font-weight:900}.slide-content{position:absolute;left:7%;top:26%;width:66%;z-index:2}.slide-eyebrow{font-size:1.3cqw;letter-spacing:.22cqw;color:var(--slide-color);margin-bottom:3cqw;font-weight:650}.slide-content h3{font-size:var(--title-size);line-height:1.16;font-weight:750;letter-spacing:-.16cqw;overflow-wrap:anywhere;white-space:pre-wrap}.slide-content p{font-size:var(--body-size);line-height:1.55;font-weight:400;white-space:pre-wrap;overflow-wrap:anywhere;margin-top:2.5cqw;color:#64718a}.slide-bottom{position:absolute;left:7%;right:7%;bottom:6%;display:flex;justify-content:space-between;font-size:1.25cqw;letter-spacing:.03cqw;color:#91a0b5;z-index:2}.slide-accent{position:absolute;right:0;top:0;width:19%;height:100%;background:var(--slide-color)}.slide-accent>div{position:absolute;left:16%;right:16%;border:1px solid #ffffff45;height:15%;top:43%;border-radius:1.5cqw;transform:rotate(-25deg)}.slide-accent>div:nth-child(2){top:50%;background:#ffffff22}.slide-accent>div:nth-child(3){top:57%;background:#ffffff33}.layout-classic .slide-bottom{right:23%}.layout-classic.is-cover .slide-content{top:30%}.layout-story{background:var(--slide-color);color:#fff}.layout-story .slide-brand,.layout-story .slide-eyebrow{color:#ffffffc9}.layout-story .slide-content p{color:#ffffffc4}.layout-story .slide-content{width:65%;top:25%}.layout-story .slide-bottom{color:#ffffff90}.layout-story .slide-accent{background:#ffffff0e;right:-10%;top:10%;width:35%;height:90%;transform:rotate(23deg)}.layout-story .slide-accent>div{background:#ffffff0e;border-color:#ffffff32}.layout-focus .slide-accent{height:1.5%;top:0;width:100%}.layout-focus .slide-accent>div{display:none}.layout-focus .slide-content{text-align:center;width:82%;left:9%;top:30%}.layout-focus .slide-eyebrow{margin-bottom:2.4cqw}.layout-focus .slide-content p{margin-top:2cqw}.layout-focus .slide-brand{left:50%;transform:translateX(-50%);font-size:2.7cqw}.layout-focus .slide-bottom{color:#9da9ba}@page{size:13.333333in 7.5in;margin:0}@media print{html,body{margin:0;padding:0;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}.slide-canvas{width:13.333333in;height:7.5in;margin:0;box-shadow:none;page-break-inside:avoid;break-inside:avoid}.slide-canvas:last-child{break-after:auto;page-break-after:auto}}
</style></head><body>${slideHtml}</body></html>`;
}

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export async function exportHtml(deck: Deck, template: Template): Promise<void> {
  download(new Blob([await htmlDocument(deck, template)], { type: 'text/html;charset=utf-8' }), `${safeFilename(deck.title)}.html`);
}

export async function exportPrint(deck: Deck, template: Template): Promise<void> {
  // Reserve the window during the click so lazy font loading cannot lose user activation.
  const popup = window.open('', '_blank');
  if (!popup) throw new Error('Браузер заблокировал окно печати. Разрешите всплывающие окна для этого сайта и повторите.');
  popup.opener = null;
  try {
    popup.document.write('<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Подготовка PDF</title></head><body style="margin:0;padding:64px 24px;background:#f4f7fb;color:#243149;font:16px/1.6 Arial,sans-serif;text-align:center"><h1 style="font-size:24px">Подготавливаем презентацию…</h1><p role="status">Загружаем шрифты и готовим слайды к печати.</p></body></html>');
    popup.document.close();
    const html = await htmlDocument(deck, template);
    if (popup.closed) throw new Error('Окно печати закрыто. Повторите экспорт PDF, когда будете готовы.');
    popup.document.open();
    popup.document.write(html);
    popup.document.close();
    const toolbar = popup.document.createElement('div');
    toolbar.className = 'print-actions';
    toolbar.innerHTML = '<p>В окне печати выберите «Сохранить как PDF».</p><button type="button">Открыть окно печати</button>';
    popup.document.body.prepend(toolbar);
    const toolbarStyle = popup.document.createElement('style');
    toolbarStyle.textContent = '.print-actions{display:flex;justify-content:center;align-items:center;gap:20px;flex-wrap:wrap;padding:0 24px 24px;font:14px/1.5 Arial,sans-serif;color:#243149}.print-actions button{border:0;border-radius:10px;padding:12px 18px;background:#0077ff;color:#fff;font:600 14px Arial,sans-serif;cursor:pointer}.print-actions button:focus-visible{outline:3px solid #243149;outline-offset:3px}@media print{.print-actions{display:none!important}}';
    popup.document.head.appendChild(toolbarStyle);
    const print = () => { if (!popup.closed) { popup.focus(); popup.print(); } };
    toolbar.querySelector('button')!.addEventListener('click', print);
    await popup.document.fonts?.ready;
    await new Promise<void>(resolve => window.setTimeout(resolve, 200));
    if (popup.closed) throw new Error('Окно печати закрыто. Повторите экспорт PDF, когда будете готовы.');
    print();
  } catch (error) {
    if (!popup.closed) popup.close();
    throw error;
  }
}

/** Use the same font and approximate CSS wrapping to position editable text boxes. */
function textLineCount(text: string, width: number, size: number, font: string, bold = false, spacing = 0): number {
  const context = document.createElement('canvas').getContext('2d');
  if (context) context.font = `${bold ? 700 : 400} ${size * 96 / 72}px "${font}"`;
  const available = width * 96;
  const measure = (value: string) => (context?.measureText(value).width ?? value.length * size * 0.7) + Math.max(0, value.length - 1) * spacing * 96 / 72;
  let lines = 0;
  for (const paragraph of text.split('\n')) {
    let line = '';
    lines++;
    for (const word of paragraph.split(/\s+/)) {
      const candidate = line ? `${line} ${word}` : word;
      if (line && measure(candidate) > available) { lines++; line = word; }
      else line = candidate;
      if (measure(line) > available) { lines += Math.ceil(measure(line) / available) - 1; line = ''; }
    }
  }
  return lines;
}

export async function exportPptx(deck: Deck, template: Template): Promise<void> {
  const { default: PptxGenJS } = await import('pptxgenjs').catch(error => {
    throw new Error('Не удалось загрузить модуль экспорта PPTX. Проверьте подключение и повторите попытку.', { cause: error });
  });
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'Slide Studio';
  pptx.subject = 'Презентация из пользовательского текста';
  pptx.title = deck.title;
  pptx.company = '';
  const font = safeFont(template.font);
  pptx.theme = { headFontFace: font, bodyFontFace: font };
  const primary = safeColor(template.color, '#0077FF').slice(1);
  const width = 13.333333;
  const height = 7.5;
  const cqwInches = width / 100;
  const cqwPoints = cqwInches * 72;
  await document.fonts?.ready;
  for (let index = 0; index < deck.slides.length; index++) {
    const source = deck.slides[index];
    if (source.visual) {addAnalyticSlide(pptx,source,template,index,deck.slides.length);continue;}
    const slide = pptx.addSlide();
    if (source.notes) slide.addNotes(source.notes);
    const focus = deck.layout === 'focus';
    const story = deck.layout === 'story';
    slide.background = { color: story ? primary : 'FFFFFF' };
    if (story) {
      slide.addShape(pptx.ShapeType.rect, { x: width * 0.75, y: height * 0.1, w: width * 0.35, h: height * 0.9, rotate: 23, line: { color: 'FFFFFF', transparency: 100 }, fill: { color: 'FFFFFF', transparency: 94.5 } });
      const angle = 23 * Math.PI / 180;
      const centerX = width * 0.925;
      const centerY = height * 0.55;
      for (let item = 0; item < 3; item++) {
        const itemWidth = width * 0.35 * 0.68;
        const itemHeight = height * 0.9 * 0.15;
        const itemCenterY = height * 0.1 + height * 0.9 * (0.43 + item * 0.07 + 0.075);
        slide.addShape(pptx.ShapeType.roundRect, { x: centerX - (itemCenterY - centerY) * Math.sin(angle) - itemWidth / 2, y: centerY + (itemCenterY - centerY) * Math.cos(angle) - itemHeight / 2, w: itemWidth, h: itemHeight, rotate: 358, line: { color: 'FFFFFF', transparency: 80, width: 0.75 }, fill: { color: 'FFFFFF', transparency: 94.5 } });
      }
    } else if (focus) slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: width, h: height * 0.015, line: { color: primary, transparency: 100 }, fill: { color: primary } });
    else {
      slide.addShape(pptx.ShapeType.rect, { x: width * 0.81, y: 0, w: width * 0.19, h: height, line: { color: primary, transparency: 100 }, fill: { color: primary } });
      for (let item = 0; item < 3; item++) slide.addShape(pptx.ShapeType.roundRect, { x: width * (0.81 + 0.19 * 0.16), y: height * (0.43 + item * 0.07), w: width * 0.19 * 0.68, h: height * 0.15, rotate: 335, line: { color: 'FFFFFF', transparency: 73, width: 0.75 }, fill: { color: 'FFFFFF', transparency: [100, 86.7, 80][item] } });
    }
    const base = { fontFace: font, lang: 'ru-RU', margin: 0, breakLine: false, valign: 'top' as const };
    const brandSize = (focus ? 2.7 : 3) * cqwPoints;
    slide.addText([{ text: template.custom ? 's' : 'vk', options: { fontFace: 'Arial', fontSize: brandSize * 1.1, bold: true, charSpacing: -brandSize * 1.1 * 0.15 } }, { text: `  ${template.name.replace('VK ', '')}`, options: { fontFace: font, fontSize: brandSize } }], { ...base, x: width * 0.07, y: height * 0.08, w: width * 0.86, h: 0.53, fontSize: brandSize, align: focus ? 'center' : 'left', color: story ? 'FFFFFF' : primary, transparency: story ? 21 : 0 });
    const sizes = getSlideTypography(source, template, deck.layout);
    const x = width * (focus ? 0.09 : 0.07);
    const textWidth = width * (focus ? 0.82 : story ? 0.65 : 0.66);
    const top = height * (focus || (!story && source.kind === 'cover') ? 0.3 : story ? 0.25 : 0.26);
    const eyebrowHeight = cqwInches * 1.3 * 1.2;
    const titleSize = sizes.title * cqwPoints;
    const bodySize = sizes.body * cqwPoints;
    const titleHeight = textLineCount(source.title || 'Название слайда', textWidth, titleSize, font, true, -0.16 * cqwPoints) * titleSize / 72 * 1.16;
    const titleY = top + eyebrowHeight + (focus ? 2.4 : 3) * cqwInches;
    const bodyY = titleY + titleHeight + (focus ? 2 : 2.5) * cqwInches;
    const bodyHeight = source.body ? textLineCount(source.body, textWidth, bodySize, font) * bodySize / 72 * 1.55 : 0;
    if ((source.body ? bodyY + bodyHeight : titleY + titleHeight) > height * 0.885) throw new Error(`На слайде ${index + 1} слишком много текста для выбранного макета. Разделите его на несколько слайдов и повторите экспорт.`);
    const align = focus ? 'center' as const : 'left' as const;
    slide.addText(source.kind === 'cover' ? 'ИДЕИ, КОТОРЫЕ ОБЪЕДИНЯЮТ' : `ЧАСТЬ ${String(index).padStart(2, '0')}`, { ...base, x, y: top, w: textWidth, h: eyebrowHeight + 0.03, fontSize: 1.3 * cqwPoints, bold: true, charSpacing: 0.22 * cqwPoints, align, color: story ? 'FFFFFF' : primary, transparency: story ? 21 : 0 });
    slide.addText(source.title || 'Название слайда', { ...base, x, y: titleY, w: textWidth, h: titleHeight + 0.08, fontSize: titleSize, bold: true, color: story ? 'FFFFFF' : '243149', align, charSpacing: -0.16 * cqwPoints, lineSpacingMultiple: 1.16, paraSpaceAfter: 0 });
    if (source.body) slide.addText(source.body, { ...base, x, y: bodyY, w: textWidth, h: bodyHeight + 0.08, fontSize: bodySize, color: story ? 'FFFFFF' : '64718A', transparency: story ? 23 : 0, align, lineSpacingMultiple: 1.55, paraSpaceAfter: 0 });
    const footerColor = story ? 'FFFFFF' : focus ? '9DA9BA' : '91A0B5';
    const footerEnd = width * (deck.layout === 'classic' ? 0.77 : 0.93);
    slide.addText(`${template.name} · Презентация`, { ...base, x: width * 0.07, y: height * 0.94 - 0.2, w: 7.5, h: 0.24, fontSize: 1.25 * cqwPoints, charSpacing: 0.03 * cqwPoints, color: footerColor, transparency: story ? 43.5 : 0 });
    slide.addText(`${String(index + 1).padStart(2, '0')} / ${String(deck.slides.length).padStart(2, '0')}`, { ...base, x: footerEnd - 0.95, y: height * 0.94 - 0.2, w: 0.95, h: 0.24, fontSize: 1.25 * cqwPoints, charSpacing: 0.03 * cqwPoints, align: 'right', color: footerColor, transparency: story ? 43.5 : 0 });
  }
  await pptx.writeFile({ fileName: `${safeFilename(deck.title)}.pptx`, compression: true });
}
