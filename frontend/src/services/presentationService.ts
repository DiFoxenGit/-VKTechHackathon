/** Единственное место, где интерфейс встречается с бэкендом.
 *
 * Прототип задумывался с этим швом: экраны работают со своими типами
 * (`Template`, `Deck`, `AuditIssue`), а здесь они собираются из ответов API.
 * Браузерного движка больше нет — колоду собирает сервис, поэтому то, что
 * видно на экране, совпадает с тем, что уедет в pptx.
 */
import { api, waitForJob } from './api';
import type {
  ApiAuditIssue,
  ApiOutline,
  ApiPresentation,
  ApiPurpose,
  ApiSlideContent,
  ApiTemplateSummary,
  ApiWorkflow,
} from './apiTypes';
import type { AuditIssue, Brief, Deck, Layout, Slide, Template } from '../types';

/** Варианты вёрстки сервиса в терминах экранов прототипа. */
export const LAYOUTS: Record<Layout, 'classic' | 'split' | 'focus'> = {
  classic: 'classic',
  story: 'split',
  focus: 'focus',
};

const VARIANTS: Record<string, Layout> = { classic: 'classic', split: 'story', focus: 'focus' };

export type Project = {
  id: string;
  revision: number;
  layout: Layout;
  deck: Deck;
  issues: AuditIssue[];
  exports: { pptx: string; pdf: string; html: string } | undefined;
  /** Проверка записанного файла: открывается ли и из чего собраны слайды. */
  file: { opens: boolean; slides: number; native_objects: number; raster_slides: number[] } | undefined;
};

function hex(value: string | undefined, fallback: string) {
  return value && /^[\da-f]{6}$/i.test(value) ? `#${value}` : fallback;
}

/** Паспорт дизайн-системы шаблона в карточку галереи. */
export function toTemplate(source: ApiTemplateSummary): Template {
  const tokens = source.tokens;
  const colors = (tokens?.colors ?? []).filter(c => /^[\da-f]{6}$/i.test(c));
  const accents = (tokens as { accents?: string[] } | undefined)?.accents ?? colors;
  const choice = (tokens as { font_choice?: { title?: { selected?: string } } } | undefined)?.font_choice;
  const fonts = tokens?.fonts ?? [];
  const sizes = tokens?.font_sizes ?? [];
  return {
    id: source.id,
    name: source.name.replace(/\.pptx$/i, ''),
    description: fonts.length
      ? `${fonts.slice(0, 2).join(', ')} · ${sizes.length} кеглей · ${colors.length} цветов`
      : 'Дизайн-система разобрана из файла',
    color: hex(accents[0] ?? colors[0], '#0674ff'),
    secondary: hex(accents[1] ?? colors[1], '#8a83d1'),
    font: choice?.title?.selected || fonts[0] || 'Manrope Variable',
    layoutCount: source.layouts?.length ?? 0,
    slideCount: (source as { slide_count?: number }).slide_count ?? 0,
    tag: `${Math.round(source.width / 914400)}:${Math.round(source.height / 914400)}`,
    custom: false,
  };
}

function kindOf(index: number, total: number): Slide['kind'] {
  if (index === 0) return 'cover';
  return index === total - 1 ? 'closing' : 'content';
}

/** Слайды сервиса в плоскую модель экранов: заголовок и текст одной строкой. */
export function toDeck(source: ApiPresentation): Deck {
  const slides = source.deck.slides.map((slide, index) => ({
    id: `${source.id}:${index}`,
    title: slide.content.title,
    body: slide.content.bullets.join('\n'),
    kind: kindOf(index, source.deck.slides.length),
  }));
  return {
    id: source.id,
    title: source.title,
    slides,
    templateId: source.template_id,
    layout: VARIANTS[source.variant] ?? 'classic',
    updatedAt: new Date().toISOString(),
  };
}

const SEVERITY: Record<string, AuditIssue['severity']> = { error: 'error', warning: 'warning' };

export function toIssues(source: ApiPresentation | { audit?: { issues?: ApiAuditIssue[] } }, deckId: string): AuditIssue[] {
  return (source.audit?.issues ?? []).map(issue => ({
    id: issue.id,
    slideId: `${deckId}:${issue.slide_index ?? 0}`,
    severity: SEVERITY[issue.severity] ?? 'warning',
    title: issue.message,
    description: issue.element_id
      ? `Блок «${issue.element_id}», слайд ${(issue.slide_index ?? 0) + 1}`
      : `Слайд ${(issue.slide_index ?? 0) + 1}`,
    fixable: issue.category !== 'contextual' && Boolean(issue.fixable),
    rule: issue.code,
    boxed: Boolean(issue.box),
    // Детерминированные правила, текстовый агент и агент по картинке помечают
    // свои находки по-разному — пользователю полезно знать, кто это нашёл.
    origin:
      issue.category !== 'contextual'
        ? 'rule'
        : issue.element_id === 'slide_image'
          ? 'image'
          : 'text',
  }));
}

function toProject(source: ApiPresentation): Project {
  return {
    id: source.id,
    revision: source.revision,
    layout: VARIANTS[source.variant] ?? 'classic',
    deck: toDeck(source),
    issues: toIssues(source, source.id),
    exports: source.exports,
    file: source.export_check,
  };
}

/** Текст слайда обратно в структуру сервиса: пустые строки не хранятся. */
function toContent(previous: ApiSlideContent, slide: Slide): ApiSlideContent {
  return {
    ...previous,
    title: slide.title,
    bullets: slide.body.split('\n').map(line => line.trim()).filter(Boolean),
  };
}

/** Правки экрана «Структура» обратно в план сервиса.
 *
 * Визуализации и ссылки на источники интерфейс не показывает, поэтому они
 * берутся из исходного плана по номеру слайда: пользователь правит текст, а
 * диаграммы и таблицы остаются на своих местах.
 */
export function toOutline(deck: Deck, source: ApiOutline | null): ApiOutline {
  return {
    title: source?.title || deck.title,
    slides: deck.slides.map(slide => {
      const index = Number(slide.id.split(':')[1]);
      const original = Number.isInteger(index) ? source?.slides[index] : undefined;
      return {
        title: slide.title,
        bullets: slide.body.split('\n').map(line => line.trim()).filter(Boolean),
        notes: original?.notes ?? '',
        source_refs: original?.source_refs?.length ? original.source_refs : ['brief'],
        visual: original?.visual ?? { kind: 'none' },
      };
    }),
  };
}

/** План сервиса в плоскую модель экранов: черновик, которого ещё нет на сервере. */
export function draftDeck(outline: ApiOutline, templateId: string): Deck {
  return {
    id: 'draft',
    title: outline.title,
    slides: outline.slides.map((slide, index) => ({
      id: `draft:${index}`,
      title: slide.title,
      body: slide.bullets.join('\n'),
      kind: kindOf(index, outline.slides.length),
    })),
    templateId,
    layout: 'classic',
    updatedAt: new Date().toISOString(),
  };
}

/** Версия сценария генерации — то, чем именно собрана колода. */
export type WorkflowInfo = {
  version: string;
  agents: { role: string; file: string; sha: string }[];
  latest: { version: string; why: string } | undefined;
};

/** Имена агентов на языке пользователя: в API они служебные. */
const AGENT_ROLES: Record<string, string> = {
  outline: 'Структура и текст',
  audit: 'Проверка текста',
  audit_image: 'Проверка по изображению',
  condense: 'Сокращение текста',
  assets: 'Подбор иллюстраций',
};

function toWorkflow(source: ApiWorkflow): WorkflowInfo {
  const sha = source.sha256 ?? {};
  return {
    version: source.version,
    agents: Object.entries(source.agents ?? {}).map(([key, file]) => ({
      role: AGENT_ROLES[key] ?? key,
      file,
      // Префикса хватает, чтобы сверить промпт с тем, что лежит в репозитории.
      sha: (sha[file] ?? '').slice(0, 8),
    })),
    latest: source.changelog?.[0],
  };
}

export const presentationService = {
  /** Чем собрана колода: версия сценария, промпты агентов и последнее изменение. */
  async workflow(): Promise<WorkflowInfo> {
    return toWorkflow(await api.workflow());
  },

  /** Только структура: быстрый шаг до вёрстки, его показывает экран «Структура». */
  async createOutline(brief: Brief, packIds: string[], purpose: ApiPurpose): Promise<ApiOutline> {
    return api.createOutline({
      brief: brief.text,
      purpose,
      language: 'ru',
      slide_count: brief.slideCount,
      content_pack_ids: packIds,
    });
  },

  async listTemplates(): Promise<Template[]> {
    const items = await api.listTemplates();
    return items.map(toTemplate);
  },

  async importTemplate(file: File): Promise<Template> {
    return toTemplate(await api.uploadTemplate(file));
  },

  async uploadMaterial(file: File) {
    const pack = await api.uploadContentPack(file, file.name);
    const counts = pack.asset_counts;
    const pictures = counts ? counts.icon + counts.illustration + counts.photo : 0;
    return { id: pack.id, name: pack.name, text: pack.text, pictures };
  },

  /** Бриф → три свёрстанных варианта. `onStage` показывает, что идёт сейчас. */
  async createDecks(
    brief: Brief,
    packIds: string[],
    purpose: ApiPurpose,
    onStage?: (stage: string, progress: number) => void,
    outline?: ApiOutline,
  ): Promise<{ projects: Project[]; warnings: string[] }> {
    const job = await api.startGeneration({
      template_id: brief.templateId,
      brief: brief.text,
      purpose,
      language: 'ru',
      slide_count: brief.slideCount,
      content_pack_ids: packIds,
      // Готовый план вёрстка берёт как есть: модель второй раз не вызывается.
      ...(outline ? { outline } : {}),
    });
    const finished = await waitForJob(job.id, state => onStage?.(state.stage, state.progress));
    const decks = await Promise.all(finished.presentation_ids.map(id => api.presentation(id)));
    return { projects: decks.map(toProject), warnings: finished.warnings ?? [] };
  },

  async open(id: string): Promise<Project> {
    return toProject(await api.presentation(id));
  },

  async recent(limit = 12): Promise<Project[]> {
    const { items } = await api.listPresentations(0, limit);
    // The list endpoint returns summaries without slide geometry or audit.
    const presentations = await Promise.all(items.map(item => api.presentation(item.id)));
    return presentations.map(toProject);
  },

  async saveSlide(project: Project, index: number, slide: Slide): Promise<Project> {
    const current = await api.presentation(project.id);
    const content = toContent(current.deck.slides[index].content, slide);
    return toProject(await api.editSlide(project.id, index, current.revision, content));
  },

  async applyFixes(project: Project, issueIds: string[]): Promise<Project> {
    return toProject(await api.applyFixes(project.id, project.revision, issueIds));
  },

  async recheck(project: Project, options?: { contextual?: boolean; visual?: boolean }): Promise<AuditIssue[]> {
    const report = await api.runAudit(project.id, options);
    return toIssues({ audit: report }, project.id);
  },

  /** Превью слайда приходит SVG с авторизацией, поэтому отдаём blob-ссылку. */
  async preview(project: Project, index: number, highlight = true): Promise<string> {
    const blob = await api.download(
      `/presentations/${project.id}/slides/${index}/preview?highlight=${highlight}`,
    );
    return URL.createObjectURL(blob);
  },

  async download(project: Project, format: 'pptx' | 'pdf' | 'html'): Promise<Blob> {
    return api.download(api.exportPath(project.id, format, project.revision));
  },
};
