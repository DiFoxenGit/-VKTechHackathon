/// <reference types="vite/client" />
import JSZip from 'jszip';
import playCyrillic400 from '@fontsource/play/files/play-cyrillic-400-normal.woff2?inline';
import playCyrillic700 from '@fontsource/play/files/play-cyrillic-700-normal.woff2?inline';
import playLatin400 from '@fontsource/play/files/play-latin-400-normal.woff2?inline';
import playLatin700 from '@fontsource/play/files/play-latin-700-normal.woff2?inline';
import type { AuditIssue, Brief, Deck, Layout, Slide, Template } from './types';

/** These counts, colours and fonts were read from the three supplied PPTX files. */
export const templates: Template[] = [
  { id: 'tech', name: 'VK Tech', description: 'Корпоративные презентации и продуктовые истории', color: '#0077FF', secondary: '#FF3885', font: 'Play', layoutCount: 39, slideCount: 54, tag: 'Корпоративный' },
  { id: 'workspace', name: 'VK WorkSpace', description: 'Командная работа, встречи и конференции', color: '#0077FF', secondary: '#00AEE8', font: 'Play', layoutCount: 15, slideCount: 29, tag: 'Для команд' },
  { id: 'education', name: 'VK Education', description: 'Образовательные проекты и выступления', color: '#0077FF', secondary: '#FF3885', font: 'Arial', layoutCount: 30, slideCount: 55, tag: 'Образование' },
];

export const EXAMPLE_BRIEF = `Рабочее пространство для команды

Команда использует несколько сервисов для переписки, встреч и совместной работы с документами. Информация теряется между чатами, а поиск нужного файла отвлекает от работы.

Мы предлагаем собрать повседневные инструменты в одном рабочем пространстве. Сотрудники смогут обсуждать задачи, проводить встречи и находить материалы проекта в привычном интерфейсе.

Начнём с одного понятного сценария: подготовка командной встречи. Участник открывает календарь, находит встречу и получает доступ к повестке и связанным документам.

При разработке уделим внимание понятной навигации. Основные действия должны быть видны сразу, а подсказки — помогать пользователю в нужный момент.

Для проверки идеи проведём тестирование прототипа с участниками команды. Попросим их найти документ, подготовить встречу и поделиться материалами с коллегой.

После тестирования соберём обратную связь и уточним сценарии. Следующий шаг — выбрать функции для первой версии продукта.`;

const cleanText = (text: string) => text.replace(/\r\n?/g, '\n').replace(/[ \t]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
const normalKey = (text: string) => cleanText(text).replace(/\s+/g, ' ').toLocaleLowerCase('ru-RU');
function hash(text: string): string {
  let value = 2166136261;
  for (let i = 0; i < text.length; i++) value = Math.imul(value ^ text.charCodeAt(i), 16777619);
  return (value >>> 0).toString(36);
}

function sourceUnits(text: string): string[] {
  // Paragraphs remain intact when possible; sentence boundaries make short briefs distributable.
  return cleanText(text).split(/\n+/).flatMap(paragraph => paragraph.split(/(?<=[.!?])\s+(?=[А-ЯЁA-Z«“])/)).filter(Boolean);
}

function heading(text: string, fallback: string): string {
  const first = text.split(/\n|(?<=[.!?])\s+/)[0]?.replace(/^[-–—•\d.)\s]+/, '').trim();
  if (!first) return fallback;
  const words = first.replace(/[.!?]$/, '').split(/\s+/);
  // A derived heading is a short excerpt. The complete source always remains in the body.
  return words.length > 10 ? `${words.slice(0, 10).join(' ')}…` : words.join(' ');
}

function distribute(units: string[], count: number): string[] {
  if (count <= 0) return [];
  const groups: string[][] = Array.from({ length: count }, () => []);
  let index = 0;
  let remainingLength = units.reduce((sum, unit) => sum + unit.length, 0);
  for (let group = 0; group < count && index < units.length; group++) {
    const remainingGroups = count - group;
    const target = remainingLength / remainingGroups;
    let length = 0;
    do {
      const unit = units[index++];
      groups[group].push(unit);
      length += unit.length;
      // Reserve one unit per remaining slide when there is enough source material.
    } while (index < units.length && length < target && units.length - index > remainingGroups - 1);
    remainingLength -= length;
  }
  // The last group holds all remaining text, including unusually long source paragraphs.
  if (index < units.length) groups[count - 1].push(...units.slice(index));
  return groups.map(group => group.join('\n\n'));
}

export function createDemoDeck(brief: Brief): Deck {
  const text = cleanText(brief.text);
  if (!text) throw new Error('Добавьте тему или текст презентации.');
  if (!Number.isInteger(brief.slideCount) || brief.slideCount < 1 || brief.slideCount > 30) throw new Error('Выберите от 1 до 30 слайдов.');
  const title = heading(text, 'Новая презентация');
  const id = `deck-${hash(JSON.stringify(brief))}`;
  const units = sourceUnits([text, brief.materials].filter(Boolean).join('\n\n'));
  // A complete standalone source title is already preserved on the cover.
  if (brief.slideCount > 1 && units[0]?.replace(/[.!?]$/, '') === title) units.shift();
  const context = [brief.audience ? `Для кого: ${cleanText(brief.audience)}` : '', brief.goal ? `Цель: ${cleanText(brief.goal)}` : ''].filter(Boolean).join('\n');
  const bodies = distribute(units, brief.slideCount === 1 ? 1 : brief.slideCount - 1);
  const slides: Slide[] = [{ id: `${id}-1`, title, body: brief.slideCount === 1 ? [context, bodies[0]].filter(Boolean).join('\n\n') : context, kind: 'cover' }];
  for (let i = 1; i < brief.slideCount; i++) {
    const body = bodies[i - 1] ?? '';
    slides.push({ id: `${id}-${i + 1}`, title: heading(body, `Раздел ${i}`), body, kind: i === brief.slideCount - 1 ? 'closing' : 'content' });
  }
  return { id, title, slides, templateId: brief.templateId, layout: 'classic', updatedAt: new Date().toISOString() };
}

export function auditDeck(deck: Deck): AuditIssue[] {
  const issues: AuditIssue[] = [];
  const titles = new Map<string, number>();
  const bodies = new Map<string, number>();
  deck.slides.forEach((slide, index) => {
    const add = (rule: string, severity: AuditIssue['severity'], title: string, description: string, fixable = false) => issues.push({ id: `${slide.id}-${rule}`, slideId: slide.id, severity, title, description, fixable, rule });
    if (!slide.title.trim()) add('empty-title', 'error', 'Добавьте заголовок', 'Заголовок поможет читателю понять тему слайда.');
    else if (slide.title.trim().length > 100) add('long-title', 'warning', 'Длинный заголовок', `В заголовке ${slide.title.trim().length} символов. Сформулируйте основную мысль короче или перенесите детали в текст.`);
    if (slide.kind !== 'cover' && !slide.body.trim()) add('empty-body', 'error', 'Слайду не хватает содержания', 'Исходного материала оказалось недостаточно. Добавьте текст или удалите этот слайд.');
    if (slide.body.trim().length > 400) add('long-body', 'warning', 'На слайде много текста', `${slide.body.trim().length} символов. Разделите материал между слайдами или сократите его вручную.`);
    const titleKey = normalKey(slide.title);
    if (titleKey && titles.has(titleKey)) add('duplicate-title', 'warning', 'Заголовок повторяется', `Такой заголовок уже есть на слайде ${titles.get(titleKey)}. Проверьте, нужен ли повтор.`);
    else if (titleKey) titles.set(titleKey, index + 1);
    const bodyKey = normalKey(slide.body);
    if (bodyKey && bodies.has(bodyKey)) add('duplicate-body', 'warning', 'Текст повторяется', `Такой текст уже есть на слайде ${bodies.get(bodyKey)}. Проверьте содержание обоих слайдов.`);
    else if (bodyKey) bodies.set(bodyKey, index + 1);
    if (slide.title !== cleanText(slide.title) || slide.body !== cleanText(slide.body)) add('whitespace', 'warning', 'Лишние пробелы', 'Можно убрать повторяющиеся пробелы и пустые строки, сохранив весь текст.', true);
  });
  return issues;
}

export function fixIssue(deck: Deck, issue: AuditIssue): Deck {
  if (!issue.fixable || issue.rule !== 'whitespace' || !deck.slides.some(slide => slide.id === issue.slideId)) return deck;
  const slides = deck.slides.map(slide => slide.id === issue.slideId ? { ...slide, title: cleanText(slide.title), body: cleanText(slide.body) } : slide);
  return { ...deck, slides, title: slides[0]?.title || deck.title, updatedAt: new Date().toISOString() };
}

function xmlDocument(text: string): Document {
  if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new Error('PPTX содержит неподдерживаемые XML-объявления. Сохраните файл заново в PowerPoint.');
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw new Error('Не удалось прочитать XML внутри PPTX. Проверьте, что файл не повреждён.');
  return doc;
}

/** Bound XML expansion before JSZip allocates decompressed buffers. No archive member is executed. */
function validateZipDirectory(buffer: ArrayBuffer): void {
  const view = new DataView(buffer);
  let end = -1;
  for (let i = view.byteLength - 22; i >= Math.max(0, view.byteLength - 65557); i--) {
    if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i + 20, true) === view.byteLength) { end = i; break; }
  }
  if (end < 0) throw new Error('Файл не похож на корректную презентацию PPTX.');
  const entries = view.getUint16(end + 10, true);
  let position = view.getUint32(end + 16, true);
  if (entries > 5000 || view.getUint16(end + 4, true) !== 0 || position >= end) throw new Error('Этот PPTX слишком сложный или использует неподдерживаемый формат архива.');
  let total = 0;
  let xmlTotal = 0;
  const decoder = new TextDecoder();
  for (let i = 0; i < entries; i++) {
    if (position + 46 > end || view.getUint32(position, true) !== 0x02014b50) throw new Error('Повреждена структура PPTX.');
    const length = view.getUint16(position + 28, true);
    const extra = view.getUint16(position + 30, true);
    const comment = view.getUint16(position + 32, true);
    if (position + 46 + length + extra + comment > end) throw new Error('Повреждена структура PPTX.');
    const name = decoder.decode(new Uint8Array(buffer, position + 46, length));
    const size = view.getUint32(position + 24, true);
    if (view.getUint16(position + 8, true) & 1) throw new Error('Снимите пароль с презентации перед импортом.');
    total += size;
    if (/^ppt\/(presentation\.xml|(?:slides|slideLayouts|theme)\/[^/]+\.xml)$/.test(name)) {
      xmlTotal += size;
      if (size > 4 * 1024 * 1024) throw new Error('В PPTX слишком большой XML-элемент. Упростите презентацию и попробуйте снова.');
    }
    if (total > 250 * 1024 * 1024 || xmlTotal > 24 * 1024 * 1024) throw new Error('Содержимое PPTX слишком велико для локального импорта.');
    position += 46 + length + extra + comment;
  }
}

export async function importTemplate(file: File): Promise<Template> {
  if (!/\.pptx$/i.test(file.name)) throw new Error('Загрузите шаблон в формате .pptx.');
  if (file.size > 50 * 1024 * 1024) throw new Error('Размер шаблона не должен превышать 50 МБ.');
  if (!file.size) throw new Error('Этот файл пустой. Выберите другой PPTX.');
  const buffer = await file.arrayBuffer();
  validateZipDirectory(buffer);
  const zip = await JSZip.loadAsync(buffer);
  const presentation = zip.file('ppt/presentation.xml');
  if (!presentation) throw new Error('В файле нет структуры презентации PowerPoint.');
  const root = xmlDocument(await presentation.async('string'));
  const size = root.getElementsByTagNameNS('*', 'sldSz')[0];
  const width = Number(size?.getAttribute('cx'));
  const height = Number(size?.getAttribute('cy'));
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || width > 1e9 || height > 1e9) throw new Error('Не удалось определить размер слайдов шаблона.');
  const files = Object.keys(zip.files).filter(name => !zip.files[name].dir);
  const slides = files.filter(name => /^ppt\/slides\/slide\d+\.xml$/.test(name));
  const layouts = files.filter(name => /^ppt\/slideLayouts\/slideLayout\d+\.xml$/.test(name));
  if (!slides.length) throw new Error('В шаблоне нет слайдов.');
  const themeFiles = files.filter(name => /^ppt\/theme\/theme\d+\.xml$/.test(name));
  const fonts = new Map<string, number>();
  const colors = new Map<string, number>();
  const accentCandidates: string[] = [];
  for (const name of [...slides, ...layouts, ...themeFiles]) {
    const fileEntry = zip.file(name);
    if (!fileEntry) continue;
    const doc = xmlDocument(await fileEntry.async('string'));
    for (const item of doc.getElementsByTagNameNS('*', 'latin')) {
      const font = item.getAttribute('typeface')?.trim();
      if (font && !font.startsWith('+') && font.length < 80 && !/symbol|wingdings|consolas/i.test(font)) fonts.set(font, (fonts.get(font) ?? 0) + 1);
    }
    for (const item of doc.getElementsByTagNameNS('*', 'srgbClr')) {
      const color = item.getAttribute('val')?.toUpperCase();
      if (color && /^[0-9A-F]{6}$/.test(color)) colors.set(color, (colors.get(color) ?? 0) + 1);
    }
    for (const tag of ['accent1', 'accent2', 'accent3']) {
      const accent = doc.getElementsByTagNameNS('*', tag)[0]?.getElementsByTagNameNS('*', 'srgbClr')[0]?.getAttribute('val')?.toUpperCase();
      if (accent && /^[0-9A-F]{6}$/.test(accent) && !accentCandidates.includes(accent)) accentCandidates.push(accent);
    }
  }
  const saturated = (hex: string) => {
    const values = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16));
    return Math.max(...values) - Math.min(...values) > 35;
  };
  const rankedColors = [...colors].sort((a, b) => b[1] - a[1]).map(([value]) => value).filter(saturated);
  const palette = [...new Set([...rankedColors, ...accentCandidates.filter(saturated)])];
  const font = [...fonts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'Arial';
  const ratio = Math.abs(width / height - 16 / 9) < 0.02 ? '16:9' : Math.abs(width / height - 4 / 3) < 0.02 ? '4:3' : `${(width / height).toFixed(2)}:1`;
  return { id: `custom-${hash(`${file.name}:${file.size}:${file.lastModified}`)}`, name: file.name.replace(/\.pptx$/i, ''), description: `Метаданные PPTX · исходный формат ${ratio}. Импортированы цвета и шрифт; графика и оригинальные макеты не переносятся. Экспорт — 16:9.`, color: `#${palette[0] ?? '0077FF'}`, secondary: `#${palette[1] ?? 'FF3885'}`, font, layoutCount: layouts.length, slideCount: slides.length, tag: 'Метаданные', custom: true };
}

const escapeHtml = (text: string) => text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
const safeColor = (color: string, fallback: string) => /^#[0-9a-f]{6}$/i.test(color) ? color : fallback;
const safeFont = (font: string) => /^[\p{L}\p{N} _-]{1,80}$/u.test(font) ? font : 'Arial';
const safeFilename = (title: string) => (title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim().slice(0, 100) || 'Презентация');

function approximateLines(text: string, width: number, size: number, font: string, title = false): number {
  const average = font === 'Play' ? 0.54 : 0.53;
  const characterWidth = Math.max(0.1, size * (title ? average + 0.025 : average) - (title ? 0.16 : 0));
  const capacity = Math.max(1, Math.floor(width / characterWidth));
  return text.split('\n').reduce((total, paragraph) => {
    let lines = 1;
    let length = 0;
    for (const word of paragraph.split(/\s+/)) {
      if (length && length + 1 + word.length > capacity) { lines++; length = 0; }
      length += (length ? 1 : 0) + word.length;
      if (length > capacity) { lines += Math.ceil(length / capacity) - 1; length %= capacity; }
    }
    return total + lines;
  }, 0);
}

/** Shared cqw font sizes for the canvas, standalone HTML and editable PPTX export. */
export function getSlideTypography(slide: Slide, template: Template, layout: Layout): { title: number; body: number } {
  const focus = layout === 'focus';
  const story = layout === 'story';
  const width = focus ? 82 : story ? 65 : 66;
  const top = focus || (!story && slide.kind === 'cover') ? 30 : story ? 25 : 26;
  const available = (86 - top) * 0.5625;
  const preferredTitle = focus ? 5.3 : story ? 5.5 : slide.kind === 'cover' ? 6.3 : 5;
  const preferredBody = focus ? 2.2 : 2.3;
  for (let percent = 100; percent >= 40; percent -= 2) {
    const title = Math.max(3.2, preferredTitle * percent / 100);
    const body = Math.max(1.8, preferredBody * percent / 100);
    const used = 1.56 + (focus ? 2.4 : 3) + approximateLines(slide.title, width, title, template.font, true) * title * 1.16
      + (slide.body ? (focus ? 2 : 2.5) + approximateLines(slide.body, width, body, template.font) * body * 1.55 : 0);
    if (used <= available) return { title: Number(title.toFixed(3)), body: Number(body.toFixed(3)) };
  }
  return { title: 3.2, body: 1.8 };
}

const embeddedPlayFonts = `@font-face{font-family:Play;font-style:normal;font-weight:400;src:url('${playCyrillic400}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}@font-face{font-family:Play;font-style:normal;font-weight:700;src:url('${playCyrillic700}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}@font-face{font-family:Play;font-style:normal;font-weight:400;src:url('${playLatin400}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}@font-face{font-family:Play;font-style:normal;font-weight:700;src:url('${playLatin700}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}`;

function htmlDocument(deck: Deck, template: Template): string {
  const primary = safeColor(template.color, '#0077FF');
  const secondary = safeColor(template.secondary, '#FF3885');
  const layout: Layout = ['classic', 'story', 'focus'].includes(deck.layout) ? deck.layout : 'classic';
  const slideHtml = deck.slides.map((slide, index) => {
    const sizes = getSlideTypography(slide, template, layout);
    const eyebrow = slide.kind === 'cover' ? 'ИДЕИ, КОТОРЫЕ ОБЪЕДИНЯЮТ' : `ЧАСТЬ ${String(index).padStart(2, '0')}`;
    return `<section class="slide-canvas layout-${layout} ${slide.kind === 'cover' ? 'is-cover' : ''}" aria-label="Слайд ${index + 1}" style="--body-size:${sizes.body}cqw;--title-size:${sizes.title}cqw"><div class="slide-brand"><span class="vk-mark">${template.custom ? 's' : 'vk'}</span><span>${escapeHtml(template.name.replace('VK ', ''))}</span></div><div class="slide-content"><div class="slide-eyebrow">${eyebrow}</div><h3>${escapeHtml(slide.title || 'Название слайда')}</h3>${slide.body ? `<p>${escapeHtml(slide.body)}</p>` : ''}</div><div class="slide-accent" aria-hidden="true"><div></div><div></div><div></div></div><div class="slide-bottom"><span>${escapeHtml(template.name)} · Презентация</span><span>${String(index + 1).padStart(2, '0')} / ${String(deck.slides.length).padStart(2, '0')}</span></div></section>`;
  }).join('\n');
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>${escapeHtml(deck.title)}</title><style>
${template.font === 'Play' ? embeddedPlayFonts : ''}
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

export function exportHtml(deck: Deck, template: Template): void {
  download(new Blob([htmlDocument(deck, template)], { type: 'text/html;charset=utf-8' }), `${safeFilename(deck.title)}.html`);
}

export function exportPrint(deck: Deck, template: Template): void {
  const popup = window.open('', '_blank');
  if (!popup) throw new Error('Браузер заблокировал окно печати. Разрешите всплывающие окна для этого сайта и повторите.');
  popup.opener = null;
  popup.document.open();
  popup.document.write(htmlDocument(deck, template));
  popup.document.close();
  const print = () => { popup.focus(); popup.print(); };
  if (popup.document.fonts) void popup.document.fonts.ready.then(() => popup.setTimeout(print, 200));
  else popup.setTimeout(print, 300);
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
  const { default: PptxGenJS } = await import('pptxgenjs');
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
    const slide = pptx.addSlide();
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
