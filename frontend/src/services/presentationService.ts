import { templates as localTemplates } from '../data/templates';
import { toBackendOutline } from '../algorithms/outline';
import type { Outline } from '../algorithms/outline';
import { runPresentationPipeline } from '../pipeline/presentationPipeline';
import type { PipelineDependencies, PipelineStage } from '../pipeline/presentationPipeline';
import type { AuditIssue, Brief, Deck, Slide, Template } from '../types';
import { parseVisual } from '../analytics';
import type { Material, Brandbook, AnalysisRequest, AnalysisResult } from '../analytics';

const API_BASE = (import.meta.env.DEV ? '/presentations/api/v1' : import.meta.env.VITE_PRESENTATIONS_API_BASE_URL || import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '');
const REQUEST_TIMEOUT = 30_000;
const TRANSFER_TIMEOUT = 120_000;
const GENERATION_TIMEOUT = 300_000;

/** Percentages describe measured transfer bytes or the server job, never elapsed time. */
export type ServiceProgress = {
  stage: 'preparing' | 'submitting' | 'queued' | 'generating' | 'fetching' | 'uploading' | 'processing' | 'downloading' | 'complete';
  progress?: number;
  loaded?: number;
  total?: number;
  jobId?: string;
  serverStage?: string;
  message?: string;
};

export type ServiceOptions = {
  /** Cancels browser requests and polling; an accepted server job may still finish. */
  signal?: AbortSignal;
  onProgress?: (event: ServiceProgress) => void;
};

type BackendTemplate = {
  id: string;
  name: string;
  tokens?: { fonts?: string[]; font_sizes?: number[]; colors?: string[]; theme?: Record<string, string> };
  layouts?: Array<{ index: number; name: string }>;
};

type ContentPack = Material & {sha256: string};

type Job = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress?: number;
  stage?: string;
  presentation_ids?: string[];
  error?: string;
  warnings?: string[];
};

type BackendPresentation = {
  image_generation?: import('../types').ImageGeneration;
  id: string;
  title: string;
  template_id: string;
  variant: 'classic' | 'split' | 'focus' | string;
  revision: number;
  created_at?: number;
  analysis?: AnalysisResult[];
  deck?: { slides?: Array<{ content?: { title?: string; bullets?: string[]; notes?: string; visual?: unknown; analysis_id?: string; source_refs?: string[] } }> };
  audit?: { issues?: Array<{ id: string; slide_index: number | null; code: string; message: string; fixable: boolean; severity: 'warning' | 'error' }> };
  exports?: Partial<Record<'pptx' | 'pdf' | 'html', string>>;
};

class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

function apiError(detail: unknown, status: number): Error {
  if (typeof detail === 'string' && /LibreOffice is required/i.test(detail)) {
    return new ApiError('Экспорт в этот формат временно недоступен. Скачайте PPTX или попробуйте позже.', status);
  }
  if (Array.isArray(detail)) {
    const messages = detail.map(item => typeof item === 'object' && item && 'msg' in item ? String(item.msg) : String(item)).filter(Boolean);
    if (messages.length) return new ApiError(messages.join('; '), status);
  }
  const fallback = status === 413 ? 'Файл слишком большой. Выберите файл до 50 МБ.'
    : status === 429 ? 'Сервер занят. Подождите немного и повторите попытку.'
    : status >= 500 ? 'Сервер временно недоступен. Попробуйте ещё раз через минуту.'
    : `Не удалось выполнить запрос (${status}). Попробуйте ещё раз.`;
  return new ApiError(typeof detail === 'string' && detail ? detail : fallback, status);
}

function abortError(): DOMException {
  return new DOMException('Операция отменена.', 'AbortError');
}

function checkAborted(signal?: AbortSignal | null): void {
  if (signal?.aborted) throw abortError();
}

function timeoutError(): Error {
  const error = new Error('Сервер долго не отвечает. Проверьте соединение и повторите попытку.');
  error.name = 'TimeoutError';
  return error;
}

async function withTimeout<T>(signal: AbortSignal | null | undefined, timeout: number, action: (signal: AbortSignal) => Promise<T>): Promise<T> {
  checkAborted(signal);
  const controller = new AbortController();
  const cancel = () => controller.abort(abortError());
  signal?.addEventListener('abort', cancel, { once: true });
  const timer = window.setTimeout(() => controller.abort(timeoutError()), timeout);
  try {
    const result = await action(controller.signal);
    checkAborted(signal);
    if (controller.signal.aborted) throw controller.signal.reason;
    return result;
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    if (error instanceof TypeError) throw new Error('Не удалось связаться с сервером. Проверьте подключение к интернету и повторите попытку.');
    throw error;
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}

async function checkResponse(response: Response): Promise<void> {
  if (response.ok) return;
  let detail: unknown = null;
  try { detail = (await response.json()).detail; } catch { /* The proxy may return an HTML error page. */ }
  throw apiError(detail, response.status);
}

async function request<T>(path: string, init: RequestInit = {}, timeout = REQUEST_TIMEOUT): Promise<T> {
  return withTimeout(init.signal, timeout, async signal => {
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal, headers });
    await checkResponse(response);
    try { return await response.json() as T; }
    catch (error) {
      if (signal.aborted) throw error;
      throw new Error('Сервер вернул некорректный ответ. Попробуйте ещё раз.');
    }
  });
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  checkAborted(signal);
  return new Promise((resolve, reject) => {
    const cancel = () => { window.clearTimeout(timer); reject(abortError()); };
    const timer = window.setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve(); }, ms);
    signal?.addEventListener('abort', cancel, { once: true });
  });
}

function upload<T>(path: string, file: File, options: ServiceOptions): Promise<T> {
  checkAborted(options.signal);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const cancel = () => xhr.abort();
    const finish = () => options.signal?.removeEventListener('abort', cancel);
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.timeout = TRANSFER_TIMEOUT;
    xhr.responseType = 'json';
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = event => options.onProgress?.({
      stage: 'uploading',
      progress: event.lengthComputable && event.total > 0 ? Math.round(event.loaded / event.total * 100) : undefined,
      loaded: event.loaded,
      total: event.lengthComputable ? event.total : undefined,
      message: 'Загружаем файл на сервер',
    });
    xhr.upload.onload = () => options.onProgress?.({ stage: 'processing', message: 'Файл загружен. Обрабатываем содержимое' });
    xhr.onload = () => {
      finish();
      if (xhr.status < 200 || xhr.status >= 300) { reject(apiError(xhr.response?.detail, xhr.status)); return; }
      if (!xhr.response) { reject(new Error('Сервер вернул некорректный ответ. Попробуйте загрузить файл ещё раз.')); return; }
      options.onProgress?.({ stage: 'complete', progress: 100 });
      resolve(xhr.response as T);
    };
    xhr.onerror = () => { finish(); reject(new Error('Не удалось загрузить файл. Проверьте соединение и повторите попытку.')); };
    xhr.ontimeout = () => { finish(); reject(timeoutError()); };
    xhr.onabort = () => { finish(); reject(abortError()); };
    options.signal?.addEventListener('abort', cancel, { once: true });
    const form = new FormData();
    form.append('file', file, file.name);
    options.onProgress?.({ stage: 'uploading', progress: 0, loaded: 0, message: 'Загружаем файл на сервер' });
    // A callback can cancel synchronously, before send() has activated the XHR.
    if (options.signal?.aborted) { finish(); reject(abortError()); return; }
    xhr.send(form);
  });
}

function jobProgress(job: Job): ServiceProgress {
  const messages: Record<string, string> = {
    outline: 'Собираем структуру презентации',
    balance: 'Распределяем содержание по слайдам',
    assets: 'Подбираем материалы шаблона',
    illustrations: 'Готовим иллюстрации',
    contextual_audit: 'Проверяем содержание',
    layout_and_audit: 'Верстаем слайды и проверяем оформление',
  };
  return {
    stage: job.status === 'queued' ? 'queued' : 'generating',
    progress: typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.max(0, Math.min(100, job.progress)) : undefined,
    jobId: job.id,
    serverStage: job.stage,
    message: job.status === 'queued' ? 'Ожидаем свободное место на сервере' : messages[job.stage || ''] || 'Собираем презентацию',
  };
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

function mapPresentation(record: BackendPresentation, brief: Brief): Deck {
  const sourceSlides = record.deck?.slides || [];
  if (!Array.isArray(sourceSlides) || !sourceSlides.length) throw new Error('Сервер вернул презентацию без слайдов. Попробуйте создать её ещё раз.');
  const slides: Slide[] = sourceSlides.map((slide, index) => {
    const content = slide.content || {};
    return {
      id: `${record.id}-${index}`,
      title: content.title || `Слайд ${index + 1}`,
      body: (content.bullets || []).join('\n'),
      ...(typeof content.notes === 'string' ? { notes: content.notes } : {}),
      visual: parseVisual(content.visual),
      rawVisual: content.visual as Record<string, unknown> | undefined,
      previewUrl: `${API_BASE}/presentations/${encodeURIComponent(record.id)}/slides/${index}/thumbnail?width=1280&revision=${record.revision}`,
      analysisId: content.analysis_id,
      sourceRefs: content.source_refs,
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
    analysis: record.analysis,
    imageGeneration: record.image_generation,
  };
}

/** Browser-side adapter for the production presentation API. */
export interface PresentationService {
  listTemplates(options?: ServiceOptions): Promise<Template[]>;
  uploadTemplate(file: File, options?: ServiceOptions): Promise<Template>;
  uploadContent(file: File, options?: ServiceOptions): Promise<ContentPack>;
  uploadBrandbook(file: File, options?: ServiceOptions): Promise<Brandbook>;
  analyseContent(packId: string, goal: string, options?: ServiceOptions, selections?: Record<string,AnalysisRequest>): Promise<{items: AnalysisResult[]}>;
  generate(brief: Brief, templateId: string, options?: ServiceOptions): Promise<Deck>;
  save(deck: Deck, options?: ServiceOptions): Promise<Deck>;
  retryIllustration(deck: Deck, options?: ServiceOptions): Promise<Deck>;
  download(deck: Deck, format: 'pptx' | 'pdf' | 'html', options?: ServiceOptions): Promise<void>;
}

async function renderPresentation(brief: Brief, templateId: string, outline: Outline, options: ServiceOptions, useServerAi: boolean): Promise<Deck> {
  checkAborted(options.signal);
  const startedAt = Date.now();
  options.onProgress?.({ stage: 'submitting', message: 'Отправляем задание на сервер' });
  const job = await request<Job>('/generations', {
    method: 'POST',
    signal: options.signal,
    body: JSON.stringify({
      brief: [brief.text, brief.audience ? `Для кого: ${brief.audience}` : '', brief.goal ? `Цель: ${brief.goal}` : '', !brief.contentPackIds?.length ? brief.materials : ''].filter(Boolean).join('\n\n'),
      purpose: 'project',
      language: 'ru',
      slide_count: brief.slideCount,
      content_pack_ids: brief.contentPackIds || [],
      contextual_audit: false,
      narrative: brief.narrative !== false,
      ...(brief.generateImages !== undefined ? {generate_images:brief.generateImages} : {}),
      analysis_goal: [brief.text,brief.goal].filter(Boolean).join('\n'),
      analysis_requests: Object.assign({},...(brief.materialFiles || []).map(f=>f.analysisRequests || {})),
      analysis_goals: Object.fromEntries((brief.materialFiles || []).filter(f=>f.goal?.trim()).map(f=>[f.id,f.goal!.trim()])),
      ...(brief.brandbook ? {brandbook_id: brief.brandbook.id} : {}),
      template_id: templateId,
      ...(useServerAi ? {} : { outline: toBackendOutline(outline, brief.contentPackIds) }),
    }),
  });

  let current = job;
  let polls = 0;
  while (current.status !== 'completed') {
    if (current.status === 'failed') throw new Error(current.error || 'Генерация презентации завершилась ошибкой.');
    options.onProgress?.(jobProgress(current));
    checkAborted(options.signal);
    const remaining = GENERATION_TIMEOUT - (Date.now() - startedAt);
    if (remaining <= 0) throw new Error('Генерация занимает больше 5 минут. Сервер может продолжать работу; попробуйте снова позже.');
    // Check the accepted job immediately. Back off only during longer generation.
    const interval = polls === 0 ? 0 : polls < 10 ? 800 : 1500;
    if (interval) await delay(Math.min(interval, remaining), options.signal);
    const requestBudget = GENERATION_TIMEOUT - (Date.now() - startedAt);
    if (requestBudget <= 0) throw new Error('Генерация занимает больше 5 минут. Сервер может продолжать работу; попробуйте снова позже.');
    current = await request<Job>(`/jobs/${encodeURIComponent(job.id)}`, { signal: options.signal }, Math.min(REQUEST_TIMEOUT, requestBudget));
    polls++;
  }
  const presentationId = current.presentation_ids?.[0];
  if (!presentationId) throw new Error('Сервер не вернул готовую презентацию.');
  options.onProgress?.({ stage: 'fetching', jobId: job.id, message: 'Презентация собрана. Открываем результат' });
  const deck = mapPresentation(await request<BackendPresentation>(`/presentations/${encodeURIComponent(presentationId)}`, { signal: options.signal }), brief);
  const previewIndex=Math.max(0,deck.slides.findIndex(s=>s.analysisId));
  deck.variantPreviews = Object.fromEntries((current.presentation_ids||[]).map((id,index)=>[
    ['classic','story','focus'][index], `${API_BASE}/presentations/${encodeURIComponent(id)}/slides/${previewIndex}/thumbnail?width=640&revision=1`
  ]));
  const warnings = Array.isArray(current.warnings) ? current.warnings.filter((warning): warning is string => typeof warning === 'string' && Boolean(warning.trim())) : [];
  deck.serverIssues = [...(deck.serverIssues || []), ...warnings.map((warning, index): AuditIssue => ({
    id: `${deck.id}-pipeline-warning-${index}`, slideId: deck.slides[0].id,
    severity: 'warning', title: 'Замечание при сборке', description: warning,
    fixable: false, rule: 'pipeline-warning',
  }))];
  return deck;
}

export function createPresentationService(aiDependencies: PipelineDependencies = {}): PresentationService {
  let serverAiConfigured = false;
  return {
    async listTemplates(options = {}) {
      options.onProgress?.({ stage: 'fetching', message: 'Загружаем шаблоны' });
      const response = await request<{ items: BackendTemplate[]; llm_configured?: boolean }>('/templates', { signal: options.signal });
      serverAiConfigured = response.llm_configured === true;
      options.onProgress?.({ stage: 'complete', progress: 100 });
      return response.items.map(mapTemplate);
    },

    async uploadTemplate(file, options = {}) {
      return mapTemplate(await upload<BackendTemplate>('/templates', file, options));
    },

    async uploadContent(file, options = {}) {
      return upload<ContentPack>('/content-packs', file, options);
    },
    async uploadBrandbook(file, options = {}) {
      return upload<Brandbook>('/brandbooks', file, options);
    },
    async analyseContent(packId, goal, options = {}, selections = {}) {
      return request<{items: AnalysisResult[]}>(`/content-packs/${encodeURIComponent(packId)}/analysis`, {method: 'POST',body:JSON.stringify({goal,requests:selections}),signal: options.signal});
    },

    async generate(brief, templateId, options = {}) {
      const messages: Partial<Record<PipelineStage, string>> = {
        prepare: 'Подготавливаем материалы', algorithms: 'Распределяем исходный текст по слайдам',
        ai: aiDependencies.ai ? 'Обрабатываем содержание с помощью ИИ' : 'Используем исходное содержание',
        validate: 'Проверяем структуру содержания', assemble: 'Собираем структуру презентации', audit: 'Проверяем слайды',
      };
      const { prepared, result } = await runPresentationPipeline({ ...brief, templateId }, {
        ...aiDependencies,
        render: prepared => renderPresentation(prepared.brief, templateId, prepared.outline, options, serverAiConfigured && !aiDependencies.ai),
      }, {
        signal: options.signal,
        onStage: stage => { if (messages[stage]) options.onProgress?.({ stage: 'preparing', message: messages[stage] }); },
      });
      if (prepared.aiStatus === 'fallback') {
        const warning = prepared.issues.find(issue => issue.rule === 'ai-fallback')!;
        result.serverIssues = [...(result.serverIssues || []), { ...warning, id: `${result.id}-ai-fallback`, slideId: result.slides[0].id }];
      }
      options.onProgress?.({ stage: 'complete', progress: 100 });
      return result;
    },

    async retryIllustration(deck, options = {}) {
      const record = await request<BackendPresentation>(`/presentations/${encodeURIComponent(deck.id)}/illustrations/retry`, {method:'POST',signal:options.signal,body:JSON.stringify({revision:deck.revision})}, GENERATION_TIMEOUT);
      return mapPresentation(record, deck.brief || {text:deck.title,audience:'',goal:'',slideCount:deck.slides.length,templateId:deck.templateId,materials:''});
    },

    async save(deck, options = {}) {
      options.onProgress?.({stage:'processing', message:'Сохраняем изменения и фирменное оформление'});
      const record = await request<BackendPresentation>(`/presentations/${encodeURIComponent(deck.id)}`, {
        method:'PATCH', signal:options.signal, body:JSON.stringify({
          revision:deck.revision, title:deck.title, variant:deck.layout==='story'?'split':deck.layout,
          slides:deck.slides.map(s=>({title:s.title, bullets:s.body ? s.body.split('\n') : [], notes:s.notes||'',
            source_refs:s.sourceRefs||[], analysis_id:s.analysisId||'', visual:s.visual||s.rawVisual||{kind:'none'}})),
        }),
      }, TRANSFER_TIMEOUT);
      return {...mapPresentation(record, deck.brief || {text:deck.title, audience:'', goal:'', slideCount:deck.slides.length, templateId:deck.templateId, materials:''}), variantPreviews:deck.variantPreviews};
    },

    async download(deck, format, options = {}) {
      checkAborted(options.signal);
      const exportPath = deck.exports?.[format] || `${API_BASE}/presentations/${encodeURIComponent(deck.id)}/export/${format}?revision=${deck.revision || 1}`;
      // The backend may omit the reverse proxy prefix in its root-relative export URLs.
      const routedPath = /^\/api\/v1(?:\/|$)/.test(exportPath) ? `${API_BASE}${exportPath.slice('/api/v1'.length)}` : exportPath;
      const url = new URL(routedPath, new URL(API_BASE, window.location.href)).href;
      options.onProgress?.({ stage: 'preparing', message: `Готовим файл ${format.toUpperCase()}` });
      const blob = await withTimeout(options.signal, TRANSFER_TIMEOUT, async signal => {
        const response = await fetch(url, { signal });
        await checkResponse(response);
        // Browsers decode compressed responses, so their Content-Length cannot measure decoded bytes.
        const encoded = response.headers.get('Content-Encoding');
        const length = encoded && encoded !== 'identity' ? 0 : Number(response.headers.get('Content-Length'));
        const total = Number.isFinite(length) && length > 0 ? length : undefined;
        options.onProgress?.({ stage: 'downloading', loaded: 0, total, message: 'Скачиваем файл' });
        if (!response.body) return response.blob();
        const reader = response.body.getReader();
        const chunks: ArrayBuffer[] = [];
        let loaded = 0;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value.slice().buffer);
            loaded += value.byteLength;
            options.onProgress?.({ stage: 'downloading', loaded, total, progress: total ? Math.min(100, Math.round(loaded / total * 100)) : undefined, message: 'Скачиваем файл' });
          }
        } finally { reader.releaseLock(); }
        return new Blob(chunks, { type: response.headers.get('Content-Type') || 'application/octet-stream' });
      });
      checkAborted(options.signal);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `${deck.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim() || 'Презентация'}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
      options.onProgress?.({ stage: 'complete', progress: 100, loaded: blob.size, total: blob.size });
    },
  };
}

export const presentationService = createPresentationService();
