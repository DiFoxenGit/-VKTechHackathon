import type { Brief, Deck, Slide } from '../types';
import { cleanText, hash } from './text';

export type OutlineSlide = { id: string; title: string; bullets: string[]; kind: Slide['kind']; sourceRefs: string[] };
export type Outline = { title: string; slides: OutlineSlide[] };
type SourceUnit = { text: string; source: string };

export function normalizeBrief(brief: Brief): Brief {
  if (!Number.isInteger(brief.slideCount) || brief.slideCount < 1 || brief.slideCount > 30) throw new Error('Выберите от 1 до 30 слайдов.');
  const text = cleanText(brief.text);
  if (!text) throw new Error('Добавьте тему или текст презентации.');
  return { ...brief, text, materials: cleanText(brief.materials || ''), audience: cleanText(brief.audience || ''), goal: cleanText(brief.goal || ''), contentPackIds: [...new Set(brief.contentPackIds || [])] };
}

export function heading(text: string, fallback: string): string {
  const first = text.split(/\n|(?<=[.!?])\s+/)[0]?.replace(/^\s*(?:[-–—•]\s+|\d+[.)]\s+)/, '').trim();
  if (!first) return fallback;
  const words = first.replace(/[.!?]$/, '').split(/\s+/);
  const title = words.length > 10 ? `${words.slice(0, 10).join(' ')}…` : words.join(' ');
  return title.length > 240 ? `${title.slice(0, 239)}…` : title;
}

/** Split at word boundaries, retaining every word and never cutting a long token. */
export function sourceUnits(text: string, limit = 400): string[] {
  if (!Number.isFinite(limit) || limit < 1) throw new Error('Размер текстового блока должен быть положительным.');
  return cleanText(text).split(/\n+/).flatMap(paragraph => paragraph.split(/(?<=[.!?])\s+(?=[А-ЯЁA-Z«“])/)).filter(Boolean).flatMap(sentence => {
    const chunks: string[] = [];
    let chunk = '';
    for (const word of sentence.split(/\s+/)) {
      if (chunk && chunk.length + word.length + 1 > limit) { chunks.push(chunk); chunk = ''; }
      chunk += (chunk ? ' ' : '') + word;
    }
    if (chunk) chunks.push(chunk);
    return chunks;
  });
}

/** Contiguous, weight-balanced groups; reserve one unit per remaining group. */
export function distribute<T>(units: readonly T[], count: number, weight: (unit: T) => number): T[][] {
  if (!Number.isInteger(count) || count < 1) throw new Error('Количество групп должно быть положительным целым числом.');
  const weights = units.map(weight);
  if (weights.some(value => !Number.isFinite(value) || value < 0)) throw new Error('Вес блока должен быть конечным неотрицательным числом.');
  const groups: T[][] = Array.from({ length: count }, () => []);
  let index = 0;
  let remaining = weights.reduce((sum, value) => sum + value, 0);
  for (let group = 0; group < count && index < units.length; group++) {
    const slots = count - group;
    const target = remaining / Math.min(slots, units.length - index);
    let length = 0;
    do {
      length += weights[index];
      groups[group].push(units[index++]);
    } while (index < units.length && (slots === 1 || (
      units.length - index > slots - 1 &&
      Math.abs(length + weights[index] - target) <= Math.abs(length - target)
    )));
    remaining -= length;
  }
  return groups;
}

/** API allows twelve bullets. Merge excess paragraphs instead of dropping them. */
export function packBullets(parts: readonly string[]): string[] {
  const nonempty = parts.map(cleanText).filter(Boolean);
  return nonempty.length <= 12 ? nonempty : distribute(nonempty, 12, text => text.length).map(group => group.join('\n'));
}

export function buildOutline(brief: Brief): Outline {
  const normalized = normalizeBrief(brief);
  const title = heading(normalized.text, 'Новая презентация');
  const count = normalized.slideCount;
  const bodyCount = count === 1 ? 1 : count - 1;
  const limit = Math.max(1, Math.min(400, Math.ceil((normalized.text.length + normalized.materials.length) / bodyCount)));
  const units: SourceUnit[] = [
    ...sourceUnits(normalized.text, limit).map(text => ({ text, source: 'brief' })),
    ...sourceUnits(normalized.materials, limit).map(text => ({ text, source: 'materials' })),
  ];
  // Only remove a standalone title whose full text is already on the cover.
  if (count > 1 && units[0]?.text === title) units.shift();
  const groups = distribute(units, bodyCount, unit => unit.text.length);
  const context = [normalized.audience ? `Для кого: ${normalized.audience}` : '', normalized.goal ? `Цель: ${normalized.goal}` : ''].filter(Boolean);
  const slides: OutlineSlide[] = [{ id: 'slide-1', title, bullets: packBullets([...context, ...(count === 1 ? groups[0].map(unit => unit.text) : [])]), kind: 'cover', sourceRefs: [...new Set(['brief', ...(count === 1 ? groups[0].map(unit => unit.source) : [])])] }];
  for (let index = 1; index < count; index++) {
    const group = groups[index - 1];
    slides.push({ id: `slide-${index + 1}`, title: heading(group[0]?.text || '', `Раздел ${index}`), bullets: packBullets(group.map(unit => unit.text)), kind: index === count - 1 ? 'closing' : 'content', sourceRefs: [...new Set(group.map(unit => unit.source))] });
  }
  return { title, slides };
}

export function assembleDeck(outline: Outline, brief: Brief, updatedAt: string): Deck {
  const id = `deck-${hash(JSON.stringify({ brief, outline }))}`;
  return { id, title: outline.title, templateId: brief.templateId, layout: 'classic', updatedAt, brief: { ...brief, contentPackIds: [...(brief.contentPackIds || [])] }, slides: outline.slides.map(slide => ({ id: `${id}-${slide.id}`, title: slide.title, body: slide.bullets.join('\n'), kind: slide.kind })) };
}

export function toBackendOutline(outline: Outline, contentPackIds: string[] = []) {
  return { title: outline.title, slides: outline.slides.map(slide => ({ title: slide.title, bullets: packBullets(slide.bullets), notes: '', source_refs: [...new Set(slide.sourceRefs.flatMap(ref => ref === 'materials' ? contentPackIds.length ? contentPackIds : ['brief'] : [ref]))], visual: { kind: 'none' as const, categories: [], series: [], columns: [], rows: [], steps: [], unit: '' } })) };
}
