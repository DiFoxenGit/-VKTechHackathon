import type { Template } from '../types';
import { hash } from '../algorithms/text';

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
  const { default: JSZip } = await import('jszip').catch(error => {
    throw new Error('Не удалось загрузить модуль чтения PPTX. Проверьте подключение и повторите импорт.', { cause: error });
  });
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

