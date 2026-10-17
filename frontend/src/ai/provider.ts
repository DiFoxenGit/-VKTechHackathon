import type { Brief } from '../types';
import type { Outline } from '../algorithms/outline';

export type AiInput = { brief: Brief; outline: Outline };
/** Model output contains text only. IDs, order, count, sources and layout belong to algorithms. */
export type AiDraft = { slides: Array<{ id: string; title: string; bullets: string[] }> };
export interface AiProvider {
  readonly id: string;
  enhance(input: AiInput, options: { signal: AbortSignal }): Promise<unknown>;
}

/** Wrap a server-side model call here; API keys must never be shipped to the browser. */
export function createAiProvider(id: string, call: AiProvider['enhance']): AiProvider {
  return { id, enhance: call };
}

export const disabledAiProvider: AiProvider = {
  id: 'disabled',
  async enhance() { return null; },
};
