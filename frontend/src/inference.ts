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
  model_attempt?: number;
  model_max_attempts?: number;
  retry_reason?: string | null;
  shared_from_job_id?: string | null;
  content_source_job_id?: string | null;
  content_input_sha256?: string | null;
  content_batch_id?: string | null;
  content_revalidated?: boolean;
  shared_inference?: ModelInference;
};

export function parseInference(value: unknown, depth = 0): ModelInference | undefined {
  if (depth > 1) return;
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
    ...(typeof v.model_attempt === 'number' ? {model_attempt: count(v.model_attempt), model_max_attempts: count(v.model_max_attempts), retry_reason: label(v.retry_reason)} : {}),
    ...(typeof v.content_source_job_id === 'string' ? {
      content_source_job_id: label(v.content_source_job_id), content_input_sha256: label(v.content_input_sha256),
      content_batch_id: label(v.content_batch_id), content_revalidated: v.content_revalidated === true,
      shared_from_job_id: label(v.shared_from_job_id), shared_inference: parseInference(v.shared_inference, depth + 1),
    } : {}),
  };
}

export function hasValidatedModelText(value: ModelInference): boolean {
  if (value.shared_inference) {
    const source = value.shared_inference;
    return value.requested && value.completed && value.validation === 'passed' && !value.fallback_used
      && !value.attempted && value.attempts === 0 && value.successful_calls === 0 && value.content_revalidated === true
      && Boolean(value.content_batch_id && value.content_input_sha256 && value.shared_from_job_id)
      && value.shared_from_job_id === source.content_source_job_id && value.content_batch_id === source.content_batch_id
      && value.content_input_sha256 === source.content_input_sha256 && !source.shared_inference && hasValidatedModelText(source);
  }
  return value.requested && value.attempted && value.completed && value.validation === 'passed'
    && value.attempts > 0 && value.successful_calls > 0 && !value.fallback_used;
}

export function modelRetryReason(code: string | null | undefined): string | undefined {
  return ({invalid_response: 'Ответ не прошёл проверку фактов или формата. Модель исправляет текст.',
    timeout: 'Провайдер не ответил вовремя. Ожидаем повторный ответ.',
    rate_limit: 'Провайдер ограничил запросы. Повторяем после паузы.',
    connection: 'Соединение с моделью прервалось. Подключаемся снова.',
    provider_error: 'Сервис модели вернул ошибку. Повторяем запрос.'} as Record<string, string>)[code || ''];
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
