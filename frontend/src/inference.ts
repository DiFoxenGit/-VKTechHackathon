/** Public evidence of a server call. Configuration alone never counts as success. */
export type ModelInference = {
  requested: boolean;
  attempted: boolean;
  completed: boolean;
  provider: string | null;
  model: string | null;
  attempts: number;
  successful_calls: number;
  duration_seconds: number;
  validation: 'not_run' | 'passed' | 'failed';
  fallback_used: boolean;
  status: string;
  error_code: string | null;
  response_id: string | null;
  content_reused_for_variants: number;
};

export function parseInference(value: unknown): ModelInference | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return;
  const v = value as Record<string, unknown>;
  if (typeof v.requested !== 'boolean' || typeof v.completed !== 'boolean') return;
  const count = (n: unknown) => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0 ? n : 0;
  const label = (s: unknown) => typeof s === 'string' ? s.slice(0, 200) : null;
  return {
    requested: v.requested, attempted: v.attempted === true, completed: v.completed,
    provider: label(v.provider), model: label(v.model), attempts: count(v.attempts),
    successful_calls: count(v.successful_calls),
    duration_seconds: typeof v.duration_seconds === 'number' && Number.isFinite(v.duration_seconds) && v.duration_seconds >= 0 ? v.duration_seconds : 0,
    validation: v.validation === 'passed' || v.validation === 'failed' ? v.validation : 'not_run',
    fallback_used: v.fallback_used === true, status: label(v.status) || 'unknown',
    error_code: label(v.error_code), response_id: label(v.response_id),
    content_reused_for_variants: count(v.content_reused_for_variants),
  };
}

export function hasValidatedModelText(value: ModelInference): boolean {
  return value.requested && value.attempted && value.completed && value.validation === 'passed'
    && value.attempts > 0 && value.successful_calls > 0 && !value.fallback_used;
}

export function inferenceCopy(value: ModelInference): { title: string; message: string; retry: boolean } {
  if (hasValidatedModelText(value)) return {
    title: 'Текст подготовлен моделью',
    message: 'Формулировки проверены по исходным фактам. Числа и графики взяты из расчётов.', retry: false,
  };
  if (!value.requested) return {
    title: 'Расчётная презентация', message: 'Содержание собрано из проверенных данных без обращения к текстовой модели.', retry: false,
  };
  const reason = /auth|unauthorized|forbidden/.test(value.error_code || '') ? 'Сервис модели отклонил доступ.'
    : /rate|quota/.test(value.error_code || '') ? 'Сервис модели ограничил число запросов.'
    : /timeout/.test(value.error_code || '') ? 'Сервис модели не ответил вовремя.'
    : /invalid|empty|truncat|validation/.test(value.error_code || '') ? 'Ответ модели не прошёл проверку.'
    : 'Текстовая модель сейчас недоступна.';
  return {
    title: 'Использован расчётный текст',
    message: `${reason} Презентация сохранена с проверенными расчётными формулировками. Можно повторить запрос и получить новую презентацию.`, retry: true,
  };
}
