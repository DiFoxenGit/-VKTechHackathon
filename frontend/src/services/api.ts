/** HTTP client for the presentation backend. One place that knows about the network. */

import type {
  ApiAuditReport,
  ApiBrief,
  ApiContentPack,
  ApiGenerateRequest,
  ApiJob,
  ApiOutline,
  ApiPresentation,
  ApiSlideContent,
  ApiTemplateSummary,
} from './apiTypes';

const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '');
/** /health lives outside the versioned prefix. */
const ROOT = BASE.replace(/\/api\/v1$/, '');
const TOKEN = import.meta.env.VITE_API_TOKEN ?? '';

/** The UI stays usable without a server: an empty base URL keeps the local demo engine. */
export const apiConfigured = Boolean(BASE);

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return TOKEN ? { ...extra, Authorization: `Bearer ${TOKEN}` } : extra;
}

async function failure(response: Response): Promise<ApiError> {
  const fallback = `Сервер ответил ${response.status}`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === 'string') return new ApiError(response.status, detail);
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0];
      return new ApiError(response.status, String(first?.msg ?? fallback));
    }
  } catch {
    // Body was empty or not JSON; the status code is all we know.
  }
  return new ApiError(response.status, fallback);
}

async function requestAt<T>(base: string, path: string, init: RequestInit = {}): Promise<T> {
  if (!BASE) throw new ApiError(0, 'Адрес API не настроен: задайте VITE_API_URL.');
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, headers: headers(init.headers as Record<string, string>) });
  } catch {
    throw new ApiError(0, 'Сервер недоступен. Проверьте, что бэкенд запущен.');
  }
  if (!response.ok) throw await failure(response);
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const request = <T>(path: string, init: RequestInit = {}) => requestAt<T>(BASE, path, init);

function json(body: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } };
}

function upload(file: File | Blob, name: string): RequestInit {
  const form = new FormData();
  form.append('file', file, name);
  return { method: 'POST', body: form };
}

export const api = {
  health: () => requestAt(ROOT, '/health'),

  listTemplates: () => request<{ items: ApiTemplateSummary[] }>('/templates').then(r => r.items ?? []),
  getTemplate: (id: string) => request<ApiTemplateSummary>(`/templates/${id}`),
  uploadTemplate: (file: File) => request<ApiTemplateSummary>('/templates', upload(file, file.name)),

  uploadContentPack: (file: File | Blob, name: string) =>
    request<ApiContentPack>('/content-packs', upload(file, name)),

  createOutline: (brief: ApiBrief) => request<ApiOutline>('/outlines', json(brief)),

  startGeneration: (request_: ApiGenerateRequest) => request<ApiJob>('/generations', json(request_)),
  job: (id: string) => request<ApiJob>(`/jobs/${id}`),

  presentation: (id: string) => request<ApiPresentation>(`/presentations/${id}`),
  listPresentations: (offset = 0, limit = 50) =>
    request<{ items: ApiPresentation[] }>(`/presentations?offset=${offset}&limit=${limit}`),

  audit: (id: string) => request<ApiAuditReport>(`/presentations/${id}/audit`),
  /** visual=true отправляет картинку каждого слайда мультимодальной модели. */
  runAudit: (id: string, { contextual = false, visual = false } = {}) =>
    request<ApiAuditReport>(
      `/presentations/${id}/audit?contextual=${contextual}&visual=${visual}`,
      { method: 'POST' },
    ),
  applyFixes: (id: string, revision: number, issueIds: string[]) =>
    request<ApiPresentation>(`/presentations/${id}/fixes`, json({ revision, issue_ids: issueIds })),
  editSlide: (id: string, index: number, revision: number, content: ApiSlideContent) =>
    request<ApiPresentation>(`/presentations/${id}/slides/${index}`, {
      ...json({ revision, content }),
      method: 'PATCH',
    }),

  /** Exports and previews need the auth header, so they are fetched as blobs, not linked. */
  async download(path: string): Promise<Blob> {
    const response = await fetch(path.startsWith('http') ? path : `${BASE}${path}`, { headers: headers() });
    if (!response.ok) throw await failure(response);
    return response.blob();
  },

  exportPath: (id: string, format: 'pptx' | 'pdf' | 'html', revision?: number) =>
    `/presentations/${id}/export/${format}${revision ? `?revision=${revision}` : ''}`,

  slidePreview: (id: string, index: number, highlight = true) =>
    request<unknown>(`/presentations/${id}/slides/${index}/preview?highlight=${highlight}`),
};

/** Poll a generation job until it finishes; reports progress so the UI can show stages. */
export async function waitForJob(
  id: string,
  onProgress?: (job: ApiJob) => void,
  { intervalMs = 1500, timeoutMs = 360000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<ApiJob> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const job = await api.job(id);
    onProgress?.(job);
    if (job.status === 'completed') return job;
    if (job.status === 'failed') throw new ApiError(500, job.error || 'Генерация не удалась.');
    if (Date.now() > deadline) throw new ApiError(408, 'Генерация не завершилась за отведённое время.');
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
}
