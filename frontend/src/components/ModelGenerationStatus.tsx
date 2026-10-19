import type { ModelInference } from '../inference';
import { hasValidatedModelText, inferenceCopy } from '../inference';

export function ModelGenerationStatus({ inference, disabled, onRetry }: {
  inference: ModelInference; disabled: boolean; onRetry?: () => void;
}) {
  const copy = inferenceCopy(inference);
  return <section className={`model-generation-status ${copy.retry ? 'is-fallback' : ''}`} aria-label="Участие текстовой модели">
    <div role="status"><strong>{copy.title}</strong><p>{copy.message}</p></div>
    {copy.retry && onRetry && <button type="button" className="secondary-button" disabled={disabled} onClick={onRetry}>Повторить с моделью</button>}
    <details className="model-diagnostics"><summary>Диагностика генерации</summary><dl>
      <div><dt>Провайдер / модель</dt><dd>{inference.provider || 'Не задан'} / {inference.model || 'Не задана'}</dd></div>
      <div><dt>Обращение к модели</dt><dd>{inference.attempted ? 'Выполнено' : 'Не выполнено'}</dd></div>
      <div><dt>Попытки / проверенные ответы</dt><dd>{inference.attempts} / {hasValidatedModelText(inference) ? inference.successful_calls : 0}</dd></div>
      <div><dt>Время модели</dt><dd>{inference.duration_seconds.toLocaleString('ru-RU', {maximumFractionDigits: 2})} с</dd></div>
      <div><dt>Проверка ответа</dt><dd>{inference.validation === 'passed' ? 'Пройдена' : inference.validation === 'failed' ? 'Не пройдена' : 'Не выполнялась'}</dd></div>
      <div><dt>Резервный текст</dt><dd>{inference.fallback_used ? 'Использован' : 'Не использован'}</dd></div>
      <div><dt>Оформления с общим текстом</dt><dd>{inference.content_reused_for_variants}</dd></div>
      {inference.response_id && <div><dt>Ответ провайдера</dt><dd>{inference.response_id}</dd></div>}
      {inference.error_code && <div><dt>Код ошибки</dt><dd>{inference.error_code}</dd></div>}
    </dl></details>
  </section>;
}
