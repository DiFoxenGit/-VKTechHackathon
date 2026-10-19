import { useEffect, useId, useState } from 'react';
import { Check, CheckCircle2, Clock3, Download, FileUp, Presentation } from 'lucide-react';
import type { ServiceProgress } from '../services/presentationService';

export type OperationKind = 'save' | 'generation' | 'material' | 'template' | 'pptx' | 'pdf' | 'html';

type OperationProgressProps = {
  kind: OperationKind;
  progress: ServiceProgress;
  startedAt: number;
  onCancel?: () => void;
  compact?: boolean;
};

const generationStages: Record<ServiceProgress['stage'], { title: string; detail: string; step: number }> = {
  preparing: { title: 'Готовим запрос', detail: 'Собираем ваш бриф, материалы и выбранный стиль.', step: 0 },
  submitting: { title: 'Отправляем задание', detail: 'Передаём бриф сервису генерации. Дождитесь подтверждения.', step: 0 },
  queued: { title: 'Задание в очереди', detail: 'Сервис принял запрос. Генерация начнётся, когда освободятся ресурсы.', step: 1 },
  generating: { title: 'Создаём презентацию', detail: 'Сервис собирает содержание и оформляет слайды. Результат откроется автоматически.', step: 2 },
  fetching: { title: 'Открываем результат', detail: 'Получаем готовые слайды и подготавливаем редактор.', step: 3 },
  uploading: { title: 'Передаём материалы', detail: 'Отправляем файлы, необходимые для презентации.', step: 0 },
  processing: { title: 'Обрабатываем презентацию', detail: 'Сервис подготавливает слайды. Результат откроется автоматически.', step: 2 },
  downloading: { title: 'Получаем презентацию', detail: 'Загружаем готовые слайды в редактор.', step: 3 },
  complete: { title: 'Презентация готова', detail: 'Можно перейти к просмотру и редактированию слайдов.', step: 3 },
};

const generationTitles: Record<string, string> = {
  analytics: 'Проверяем данные и периоды',
  model_content: 'Модель готовит выводы',
  outline: 'Собираем структуру',
  balance: 'Распределяем содержание',
  assets: 'Подбираем материалы',
  illustrations: 'Создаём иллюстрации',
  contextual_audit: 'Проверяем содержание',
  layout_and_audit: 'Оформляем и проверяем слайды',
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.round(bytes)} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} МБ`;
}

function operationCopy(kind: OperationKind, stage: ServiceProgress['stage']) {
  if (kind === 'save') return {title:'Сохраняем оформление', detail:'Обновляем файл и предпросмотр с учётом правок.'};
  if (kind === 'generation') return generationStages[stage];
  const upload = kind === 'material' || kind === 'template';
  const format = kind.toUpperCase();
  if (stage === 'complete') return {
    title: upload ? 'Файл обработан' : 'Файл готов к скачиванию',
    detail: upload ? 'Результат обработки получен.' : 'Браузер сохранит файл в папку загрузок.',
  };
  if (stage === 'uploading') return {
    title: kind === 'template' ? 'Загружаем шаблон' : 'Загружаем материалы',
    detail: 'Передаём файл. После загрузки сервис обработает его содержимое.',
  };
  if (stage === 'downloading') return {
    title: `Скачиваем ${format}`,
    detail: 'Получаем файл. Браузер предложит сохранить его после загрузки.',
  };
  if (stage === 'preparing') return {
    title: upload ? 'Подготавливаем файл' : `Подготавливаем ${format}`,
    detail: upload ? 'Проверяем файл перед загрузкой.' : 'Подготавливаем презентацию к экспорту.',
  };
  if (stage === 'queued') return {
    title: 'Ожидаем обработки',
    detail: 'Сервис принял запрос. Продолжим автоматически, когда результат будет готов.',
  };
  if (kind === 'material') return { title: 'Читаем материалы', detail: 'Сервис извлекает текст из файла, чтобы использовать его в презентации.' };
  if (kind === 'template') return { title: 'Разбираем оформление', detail: 'Сервис извлекает цвета, шрифты и макеты из вашего PPTX.' };
  return { title: `Создаём файл ${format}`, detail: 'Сервис подготавливает экспорт. Скачивание начнётся автоматически.' };
}

/** Shows only measured progress; stage changes and elapsed time never invent a percentage. */
export function OperationProgress({ kind, progress, startedAt, onCancel, compact = false }: OperationProgressProps) {
  const titleId = useId();
  const [now, setNow] = useState(Date.now);
  const complete = progress.stage === 'complete';
  useEffect(() => {
    setNow(Date.now());
    if (complete) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [startedAt, complete]);

  const elapsed = Math.max(0, Math.floor((now - startedAt) / 1000));
  const time = `${Math.floor(elapsed / 60).toString().padStart(2, '0')}:${(elapsed % 60).toString().padStart(2, '0')}`;
  const upload = kind === 'material' || kind === 'template';
  const copy = operationCopy(kind, progress.stage);
  const title = kind === 'generation' && progress.stage === 'generating'
    ? generationTitles[progress.serverStage ?? ''] ?? copy.title
    : copy.title;
  const detail = progress.message?.trim() || copy.detail;
  const measuredStage = kind === 'generation'
    ? progress.stage === 'generating'
    : progress.stage === 'uploading' || progress.stage === 'downloading';
  const transferSize = measuredStage && Number.isFinite(progress.loaded) && Number.isFinite(progress.total) && (progress.total ?? 0) > 0;
  const measured = transferSize ? ((progress.loaded ?? 0) / (progress.total ?? 1)) * 100 : progress.progress;
  const percentage = measuredStage && typeof measured === 'number' && Number.isFinite(measured)
    ? Math.max(0, Math.min(100, Math.round(measured)))
    : undefined;
  const currentStep = generationStages[progress.stage].step;
  const Icon = complete ? CheckCircle2 : kind === 'generation' ? Presentation : upload ? FileUp : Download;
  const label = kind === 'generation' ? 'Создание презентации' : kind === 'material' ? 'Материалы для презентации' : kind === 'template' ? 'Ваш шаблон' : `Экспорт ${kind.toUpperCase()}`;

  return <section className={`operation-panel${compact ? ' operation-panel--compact' : ''}${complete ? ' operation-panel--complete' : ''}`} aria-labelledby={titleId}>
    <div className="operation-header">
      <div className="operation-icon" aria-hidden="true"><Icon size={22} /></div>
      <div className="operation-heading">
        <span className="operation-eyebrow">{label}</span>
        <h2 id={titleId} aria-live="polite" aria-atomic="true">{title}</h2>
        <p>{detail}</p>
      </div>
      <div className="operation-timer" aria-label={`Прошло ${Math.floor(elapsed / 60)} мин. ${elapsed % 60} сек.`}>
        <Clock3 size={14} aria-hidden="true" /><span aria-hidden="true">{time}</span>
      </div>
    </div>

    <div className="operation-progress-label" aria-hidden="true">
      <span>{complete ? 'Готово' : transferSize ? `${formatBytes(progress.loaded ?? 0)} из ${formatBytes(progress.total ?? 0)}` : percentage !== undefined ? 'Прогресс генерации от сервиса' : 'Выполняется'}</span>
      {percentage !== undefined && <strong>{percentage}%</strong>}
    </div>
    <div
      className={`operation-track${percentage === undefined && !complete ? ' operation-track--indeterminate' : ''}`}
      role="progressbar"
      aria-label={title}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={complete ? 100 : percentage}
      aria-valuetext={complete ? 'Завершено' : percentage !== undefined ? `${percentage}%` : 'Выполняется, точный прогресс пока недоступен'}
    >
      <span style={percentage !== undefined || complete ? { width: `${complete ? 100 : percentage}%` } : undefined} />
    </div>

    {kind === 'generation' && !compact && <ol className="operation-steps" aria-label="Этапы создания">
      {['Подготовка', 'Очередь', 'Создание', 'Открытие'].map((step, index) => {
        const done = complete || index < currentStep;
        const active = !complete && index === currentStep;
        return <li key={step} className={done ? 'is-complete' : active ? 'is-current' : ''} aria-current={active ? 'step' : undefined}>
          <span className="operation-step-number" aria-hidden="true">{done ? <Check size={13} /> : index + 1}</span>
          <span>{step}<span className="sr-only">{done ? ': завершено' : active ? ': выполняется' : ': ожидается'}</span></span>
        </li>;
      })}
    </ol>}

    {!complete && elapsed >= 45 && <p className="operation-wait-note">
      {kind === 'generation'
        ? 'Генерация занимает больше времени. Продолжаем проверять результат — повторно отправлять запрос не нужно.'
        : upload
          ? 'Обработка занимает больше времени. Продолжаем ждать ответ сервиса; повторно загружать файл не нужно.'
          : 'Экспорт ещё выполняется. Продолжаем ждать файл — повторно нажимать «Скачать» не нужно.'}
    </p>}
    {onCancel && !complete && <div className="operation-actions">
      <button type="button" onClick={onCancel}>{upload ? 'Отменить загрузку' : kind === 'generation' ? 'Прекратить ожидание' : 'Отменить скачивание'}</button>
      {kind === 'generation' && <span>Задание на сервере может продолжиться.</span>}
    </div>}
  </section>;
}
