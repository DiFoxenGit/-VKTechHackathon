import { createDemoDeck, templates as localTemplates } from '../engine';
import type { AuditIssue, Brief, Deck, Slide, Template } from '../types';

const API_BASE = (import.meta.env.VITE_PRESENTATIONS_API_BASE_URL || '/presentations/api/v1').replace(/\/$/, '');

type BackendTemplate = {
  id: string;
  name: string;
  tokens?: { fonts?: string[]; font_sizes?: number[]; colors?: string[]; theme?: Record<string, string> };
  layouts?: Array<{ index: number; name: string }>;
};

type ContentPack = { id: string; name: string; text: string; sha256: string };

type Job = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress?: number;
  presentation_ids?: string[];
  error?: string;
};

type BackendPresentation = {
  id: string;
  title: string;
  template_id: string;
  variant: 'classic' | 'split' | 'focus' | string;
  revision: number;
  created_at?: number;
  deck?: { slides?: Array<{ content?: { title?: string; bullets?: string[] } }> };
  audit?: { issues?: Array<{ id: string; slide_index: number | null; code: string; message: string; fixable: boolean; severity: 'warning' | 'error' }> };
  exports?: Partial<Record<'pptx' | 'pdf' | 'html', string>>;
};

function apiError(detail: unknown, status: number): Error {
  if (Array.isArray(detail)) {
    const messages = detail.map(item => typeof item === 'object' && item && 'msg' in item ? String(item.msg) : String(item)).filter(Boolean);
    if (messages.length) return new Error(messages.join('; '));
  }
  return new Error(typeof detail === 'string' && detail ? detail : `Ошибка API (${status})`);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail: unknown = null;
    try { detail = (await response.json()).detail; } catch { /* The proxy may return an HTML error page. */ }
    throw apiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms));
}

function color(value: string | undefined, fallback: string): string {
  return value && /^[0-9a-f]{6}$/i.test(value.replace(/^#/, '')) ? `#${value.replace(/^#/, '')}` : fallback;
}

function templateLabel(name: string): { name: string; description: string; tag: string } {
  const lower = name.toLocaleLowerCase('ru-RU');
  if (lower.includes('education')) return { name: 'VK Education', description: 'Образовательные проекты и выступления', tag: 'Образование' };
  if (lower.includes('workspace') || lower.includes('work_space')) return { name: 'VK WorkSpace', description: 'Командная работа, встречи и конференции', tag: 'Для команд' };
  if (lower.includes('tech')) return { name: 'VK Tech', description: 'Корпоративные презентации и продуктовые истории', tag: 'Корпоративный' };
  return { name, description: 'Шаблон из библиотеки презентаций', tag: 'Загруженный шаблон' };
}

function mapTemplate(item: BackendTemplate): Template {
  const label = templateLabel(item.name);
  const tokens = item.tokens || {};
  const palette = (tokens.colors || []).filter(value => /^[0-9a-f]{6}$/i.test(value) && !/^(?:0{6}|f{6})$/i.test(value));
  const known = localTemplates.find(template => template.name === label.name);
  return {
    id: item.id,
    name: label.name,
    description: known?.description || label.description,
    color: color(tokens.theme?.accent1 || palette[0], known?.color || '#0077FF'),
    secondary: color(tokens.theme?.accent2 || palette[1], known?.secondary || '#FF3885'),
    font: tokens.fonts?.find(font => !/symbol|wingdings|consolas/i.test(font)) || known?.font || 'Arial',
    layoutCount: item.layouts?.length || known?.layoutCount || 0,
    slideCount: known?.slideCount || 0,
    tag: label.tag,
  };
}

function bulletsFromBody(body: string): string[] {
  return body.split(/\n+/).map(line => line.replace(/^\s*[•*-]\s*/, '').trim()).filter(Boolean).slice(0, 12);
}

function outlineFromBrief(brief: Brief) {
  const demo = createDemoDeck(brief);
  return {
    title: demo.title,
    slides: demo.slides.map(slide => ({
      title: slide.title || 'Без названия',
      bullets: bulletsFromBody(slide.body),
      notes: '',
      source_refs: ['brief'],
      visual: { kind: 'none' as const, categories: [], series: [], columns: [], rows: [], steps: [], unit: '' },
    })),
  };
}

function mapPresentation(record: BackendPresentation, brief: Brief): Deck {
  const sourceSlides = record.deck?.slides || [];
  const slides: Slide[] = sourceSlides.map((slide, index) => {
    const content = slide.content || {};
    return {
      id: `${record.id}-${index}`,
      title: content.title || `Слайд ${index + 1}`,
      body: (content.bullets || []).join('\n'),
      kind: index === 0 ? 'cover' : index === sourceSlides.length - 1 ? 'closing' : 'content',
    };
  });
  const serverIssues: AuditIssue[] = (record.audit?.issues || []).map(issue => {
    const index = issue.slide_index == null ? 0 : Math.max(0, Math.min(issue.slide_index, Math.max(0, sourceSlides.length - 1)));
    return {
      id: issue.id,
      slideId: `${record.id}-${index}`,
      severity: issue.severity,
      title: `Проверка: ${issue.code}`,
      description: issue.message,
      fixable: issue.fixable,
      rule: issue.code,
    };
  });
  return {
    id: record.id,
    title: record.title,
    slides,
    templateId: record.template_id,
    layout: record.variant === 'focus' ? 'focus' : record.variant === 'split' ? 'story' : 'classic',
    updatedAt: record.created_at ? new Date(record.created_at * 1000).toISOString() : new Date().toISOString(),
    brief: { ...brief },
    remote: true,
    revision: record.revision,
    exports: record.exports,
    serverIssues,
  };
}

/** Browser-side adapter for the production presentation API. */
export interface PresentationService {
  listTemplates(): Promise<Template[]>;
  uploadTemplate(file: File): Promise<Template>;
  uploadContent(file: File): Promise<ContentPack>;
  generate(brief: Brief, templateId: string): Promise<Deck>;
  download(deck: Deck, format: 'pptx' | 'pdf' | 'html'): Promise<void>;
}

export const presentationService: PresentationService = {
  async listTemplates() {
    const response = await request<{ items: BackendTemplate[] }>('/templates');
    return response.items.map(mapTemplate);
  },

  async uploadTemplate(file) {
    const form = new FormData();
    form.append('file', file, file.name);
    return mapTemplate(await request<BackendTemplate>('/templates', { method: 'POST', body: form }));
  },

  async uploadContent(file) {
    const form = new FormData();
    form.append('file', file, file.name);
    return request<ContentPack>('/content-packs', { method: 'POST', body: form });
  },

  async generate(brief, templateId) {
    const outline = outlineFromBrief(brief);
    const job = await request<Job>('/generations', {
      method: 'POST',
      body: JSON.stringify({
        brief: brief.text,
        purpose: 'project',
        language: 'ru',
        slide_count: brief.slideCount,
        content_pack_ids: brief.contentPackIds || [],
        contextual_audit: false,
        template_id: templateId,
        outline,
      }),
    });

    let current = job;
    for (let attempt = 0; attempt < 250; attempt++) {
      if (current.status === 'completed') break;
      if (current.status === 'failed') throw new Error(current.error || 'Генерация презентации завершилась ошибкой.');
      await delay(1200);
      current = await request<Job>(`/jobs/${job.id}`);
    }
    if (current.status !== 'completed') throw new Error('Сервер не завершил генерацию за 5 минут. Попробуйте ещё раз.');
    const presentationId = current.presentation_ids?.[0];
    if (!presentationId) throw new Error('Сервер не вернул готовую презентацию.');
    return mapPresentation(await request<BackendPresentation>(`/presentations/${presentationId}`), brief);
  },

  async download(deck, format) {
    const url = deck.exports?.[format] || `${API_BASE}/presentations/${deck.id}/export/${format}?revision=${deck.revision || 1}`;
    const response = await fetch(url);
    if (!response.ok) {
      let detail: unknown = null;
      try { detail = (await response.json()).detail; } catch { /* Preserve a useful generic message for binary errors. */ }
      throw apiError(detail, response.status);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = `${deck.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim() || 'Презентация'}.${format}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
  },
};
