import type { Outline } from './outline';
import { packBullets } from './outline';
import { cleanText } from './text';

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const invalid = () => new Error('ИИ вернул некорректную структуру презентации.');

/** Validate untrusted model output before it can reach rendering or the API. */
export function mergeAiDraft(outline: Outline, value: unknown): Outline {
  if (!record(value) || !Array.isArray(value.slides) || value.slides.length !== outline.slides.length) throw invalid();
  const allowed = new Set(outline.slides.map(slide => slide.id));
  const drafts = new Map<string, { title: string; bullets: string[] }>();
  for (const slide of value.slides) {
    if (!record(slide) || typeof slide.id !== 'string' || !allowed.has(slide.id) || drafts.has(slide.id) ||
        typeof slide.title !== 'string' || !slide.title.trim() || slide.title.length > 240 ||
        !Array.isArray(slide.bullets) || slide.bullets.length > 200 ||
        slide.bullets.some(item => typeof item !== 'string' || !item.trim() || item.length > 20000)) throw invalid();
    drafts.set(slide.id, { title: cleanText(slide.title), bullets: packBullets(slide.bullets) });
  }
  const slides = outline.slides.map(slide => {
    const draft = drafts.get(slide.id)!;
    // A model may summarize, but cannot silently erase an existing slide's content.
    if (slide.bullets.length && !draft.bullets.length) throw invalid();
    return { ...slide, ...draft, sourceRefs: [...slide.sourceRefs] };
  });
  return { title: slides[0].title, slides };
}
