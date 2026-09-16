/**
 * Integration seam between the UI and the pipeline.
 *
 * With VITE_API_URL set every step runs on the backend: the outline comes from the
 * model, layout and audit run against the real template, and exports are produced
 * from the template file itself. Without it the local demo engine keeps the UI
 * usable offline, but no template rules are applied.
 */

import { createDemoDeck, templates as localTemplates } from '../engine';
import type { Brief, Deck, Slide } from '../types';
import { api, apiConfigured, waitForJob } from './api';
import type {
  ApiAuditReport,
  ApiJob,
  ApiOutline,
  ApiPresentation,
  ApiPurpose,
  ApiSlideContent,
  ApiTemplateSummary,
} from './apiTypes';

export interface PresentationService {
  createOutline(brief: Brief): Promise<Deck>;
}

export type GenerationResult = {
  presentations: ApiPresentation[];
  job: ApiJob;
};

const MAX_BRIEF = 30000;

/** Bullets travel as one text block in the UI; keep the round trip lossless. */
const bulletsToBody = (bullets: string[]) => bullets.join('\n');
const bodyToBullets = (body: string) =>
  body
    .split('\n')
    .map(line => line.replace(/^[•\-–—*]\s*/, '').trim())
    .filter(Boolean);

function slideKind(index: number, total: number): Slide['kind'] {
  if (index === 0) return 'cover';
  return index === total - 1 ? 'closing' : 'content';
}

export function outlineToDeck(outline: ApiOutline, brief: Brief, id = `deck-${Date.now().toString(36)}`): Deck {
  return {
    id,
    title: outline.title,
    templateId: brief.templateId,
    layout: 'classic',
    updatedAt: new Date().toISOString(),
    brief,
    slides: outline.slides.map((slide, index) => ({
      id: `${id}-${index + 1}`,
      title: slide.title,
      body: bulletsToBody(slide.bullets),
      kind: slideKind(index, outline.slides.length),
    })),
  };
}

/** Send the structure the user actually sees, so edits in the outline screen survive. */
export function deckToOutline(deck: Deck): ApiOutline {
  return {
    title: deck.title,
    slides: deck.slides.map<ApiSlideContent>(slide => ({
      title: slide.title,
      bullets: bodyToBullets(slide.body),
      notes: '',
      source_refs: ['brief'],
      visual: { kind: 'none' },
    })),
  };
}

function purposeOf(brief: Brief): ApiPurpose {
  const goal = `${brief.goal} ${brief.text}`.toLowerCase();
  if (/фич|feature|функци/.test(goal)) return 'feature';
  if (/продукт|product/.test(goal)) return 'product';
  if (/инициатив|предлож|initiative/.test(goal)) return 'initiative';
  return 'project';
}

function briefText(brief: Brief): string {
  const parts = [
    brief.text.trim(),
    brief.audience.trim() ? `Аудитория: ${brief.audience.trim()}` : '',
    brief.goal.trim() ? `Цель: ${brief.goal.trim()}` : '',
  ].filter(Boolean);
  return parts.join('\n\n').slice(0, MAX_BRIEF);
}

/** Long source material belongs in a content pack, not in the brief field. */
async function packIds(brief: Brief): Promise<string[]> {
  const materials = brief.materials?.trim();
  if (!materials) return [];
  const blob = new Blob([materials], { type: 'text/plain' });
  const pack = await api.uploadContentPack(blob, 'materials.txt');
  return [pack.id];
}

/**
 * The UI keeps its own template list; the backend keys templates by opaque id.
 * Match on name so a template imported on the server is picked automatically.
 */
export async function resolveTemplateId(localId: string): Promise<string> {
  const remote = await api.listTemplates();
  if (!remote.length) throw new Error('На сервере нет импортированных шаблонов. Загрузите PPTX.');
  const local = localTemplates.find(t => t.id === localId);
  const wanted = (local?.name ?? localId).toLowerCase();
  const byName = remote.find((t: ApiTemplateSummary) => t.name.toLowerCase().includes(wanted) || wanted.includes(t.name.toLowerCase()));
  return (byName ?? remote[0]).id;
}

export const presentationService: PresentationService & {
  readonly usesBackend: boolean;
  generate(brief: Brief, deck?: Deck, onProgress?: (job: ApiJob) => void): Promise<GenerationResult>;
  audit(presentationId: string, contextual?: boolean): Promise<ApiAuditReport>;
  fix(presentationId: string, revision: number, issueIds: string[]): Promise<ApiPresentation>;
  download(presentationId: string, format: 'pptx' | 'pdf' | 'html', revision?: number): Promise<Blob>;
} = {
  usesBackend: apiConfigured,

  /** Structure first: the user reviews and edits it before anything is laid out. */
  async createOutline(brief) {
    if (!apiConfigured) return createDemoDeck(brief);
    const outline = await api.createOutline({
      brief: briefText(brief),
      purpose: purposeOf(brief),
      language: 'ru',
      slide_count: brief.slideCount,
      content_pack_ids: await packIds(brief),
    });
    return outlineToDeck(outline, brief);
  },

  /** Full pipeline: three variants laid out on the real template, audited and exported. */
  async generate(brief, deck, onProgress) {
    if (!apiConfigured) throw new Error('Генерация на сервере недоступна: не задан VITE_API_URL.');
    const templateId = await resolveTemplateId(brief.templateId);
    const outline = deck ? deckToOutline(deck) : undefined;
    const job = await api.startGeneration({
      template_id: templateId,
      brief: briefText(brief),
      purpose: purposeOf(brief),
      language: 'ru',
      slide_count: outline?.slides.length ?? brief.slideCount,
      content_pack_ids: outline ? [] : await packIds(brief),
      outline,
    });
    const finished = await waitForJob(job.id, onProgress);
    const presentations = await Promise.all(finished.presentation_ids.map(id => api.presentation(id)));
    return { presentations, job: finished };
  },

  audit: (presentationId, contextual = false) =>
    contextual ? api.runAudit(presentationId, { contextual: true }) : api.audit(presentationId),

  fix: (presentationId, revision, issueIds) => api.applyFixes(presentationId, revision, issueIds),

  download: (presentationId, format, revision) =>
    api.download(api.exportPath(presentationId, format, revision)),
};
