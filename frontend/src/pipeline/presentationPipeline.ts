import type { AuditIssue, Brief, Deck } from '../types';
import type { AiProvider } from '../ai/provider';
import { disabledAiProvider } from '../ai/provider';
import { assembleDeck, buildOutline, normalizeBrief } from '../algorithms/outline';
import type { Outline } from '../algorithms/outline';
import { mergeAiDraft } from '../algorithms/mergeAiDraft';
import { auditDeck } from '../algorithms/audit';

export type PipelineStage = 'prepare' | 'algorithms' | 'ai' | 'validate' | 'assemble' | 'audit' | 'render' | 'complete';
export type PreparedPresentation = { brief: Brief; outline: Outline; deck: Deck; issues: AuditIssue[]; aiStatus: 'disabled' | 'applied' | 'fallback' };
export type PipelineOptions = {
  signal?: AbortSignal;
  onStage?: (stage: PipelineStage) => void;
};
export type PipelineDependencies = {
  ai?: AiProvider;
  aiFailure?: 'fail' | 'fallback';
  aiTimeoutMs?: number;
  now?: () => string;
};

function checkAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Операция отменена.', 'AbortError');
}

async function enhance(ai: AiProvider, input: { brief: Brief; outline: Outline }, options: PipelineOptions, timeout: number): Promise<unknown> {
  checkAborted(options.signal);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel = () => {};
  const interrupted = new Promise<never>((_resolve, reject) => {
    cancel = () => { const error = new DOMException('Операция отменена.', 'AbortError'); controller.abort(error); reject(error); };
    options.signal?.addEventListener('abort', cancel, { once: true });
    timer = setTimeout(() => {
      const error = new Error('ИИ не ответил за отведённое время.');
      error.name = 'TimeoutError';
      controller.abort(error);
      reject(error);
    }, timeout);
  });
  try {
    // Isolate the original plan from a provider that mutates its input.
    return await Promise.race([Promise.resolve().then(() => {
      checkAborted(options.signal);
      return ai.enhance(structuredClone(input), { signal: controller.signal });
    }), interrupted]);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', cancel);
  }
}

/** The sole orchestrator: algorithms → optional AI → validation → assembly → audit → renderer. */
export async function runPresentationPipeline(
  source: Brief,
  dependencies: PipelineDependencies & { render?: (prepared: PreparedPresentation, options: PipelineOptions) => Promise<Deck> } = {},
  options: PipelineOptions = {},
): Promise<{ prepared: PreparedPresentation; result: Deck }> {
  const stage = (value: PipelineStage) => { checkAborted(options.signal); options.onStage?.(value); checkAborted(options.signal); };
  stage('prepare');
  const brief = normalizeBrief(source);
  stage('algorithms');
  let outline = buildOutline(brief);
  const ai = dependencies.ai ?? disabledAiProvider;
  const timeout = dependencies.aiTimeoutMs ?? 30_000;
  if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('Таймаут ИИ должен быть положительным.');
  let aiStatus: PreparedPresentation['aiStatus'] = 'disabled';
  stage('ai');
  try {
    const draft = await enhance(ai, { brief, outline }, options, timeout);
    stage('validate');
    if (draft === null && ai === disabledAiProvider) aiStatus = 'disabled';
    else { outline = mergeAiDraft(outline, draft); aiStatus = 'applied'; }
  } catch (error) {
    checkAborted(options.signal);
    if (error instanceof Error && error.name === 'AbortError') throw error;
    if (dependencies.aiFailure !== 'fallback') throw error;
    aiStatus = 'fallback';
  }
  stage('assemble');
  const deck = assembleDeck(outline, brief, (dependencies.now ?? (() => new Date().toISOString()))());
  stage('audit');
  const issues = auditDeck(deck);
  if (aiStatus === 'fallback') issues.push({ id: `${deck.slides[0].id}-ai-fallback`, slideId: deck.slides[0].id, severity: 'warning', title: 'Презентация собрана без ИИ', description: 'ИИ не вернул корректный результат. Использован исходный текст и алгоритмическая структура.', fixable: false, rule: 'ai-fallback' });
  const prepared = { brief, outline, deck, issues, aiStatus };
  stage('render');
  const result = dependencies.render ? await dependencies.render(prepared, options) : deck;
  stage('complete');
  return { prepared, result };
}
