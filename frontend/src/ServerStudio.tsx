/**
 * Полный серверный пайплайн в интерфейсе: шаблон → бриф → три варианта на
 * макетах шаблона → аудит с подсветкой → исправления → экспорт.
 *
 * Экран намеренно отдельный от демо-режима: здесь каждый пиксель приходит с
 * бэкенда, включая превью слайдов, поэтому видно настоящую вёрстку по шаблону.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, apiConfigured, waitForJob } from './services/api';
import type {
  ApiAuditIssue,
  ApiContentPack,
  ApiJob,
  ApiOutline,
  ApiSlideContent,
  ApiPresentation,
  ApiPurpose,
  ApiTemplateSummary,
} from './services/apiTypes';

const PURPOSES: { id: ApiPurpose; label: string }[] = [
  { id: 'project', label: 'Проект' },
  { id: 'feature', label: 'Фича' },
  { id: 'product', label: 'Продукт' },
  { id: 'initiative', label: 'Инициатива' },
];

const VARIANT_LABEL: Record<string, string> = {
  classic: 'Классический',
  split: 'Две колонки',
  focus: 'Фокус',
};

const EXAMPLE =
  'Пилот сервиса генерации презентаций: на старте 10 команд, после запуска 20 команд. ' +
  'Экономия времени дизайнера — 4 часа на колоду. Цель — масштабировать на всю компанию в следующем квартале.';

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function ServerStudio() {
  const [templates, setTemplates] = useState<ApiTemplateSummary[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [brief, setBrief] = useState(EXAMPLE);
  const [purpose, setPurpose] = useState<ApiPurpose>('project');
  const [slideCount, setSlideCount] = useState(10);
  const [contextual, setContextual] = useState(false);
  const [job, setJob] = useState<ApiJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [decks, setDecks] = useState<ApiPresentation[]>([]);
  const [active, setActive] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [outline, setOutline] = useState<ApiOutline | null>(null);
  const [packs, setPacks] = useState<ApiContentPack[]>([]);

  const loadTemplates = useCallback(async () => {
    try {
      const items = await api.listTemplates();
      setTemplates(items);
      setTemplateId(current => current || items[0]?.id || '');
    } catch (exc) {
      setError(message(exc));
    }
  }, []);

  useEffect(() => {
    if (apiConfigured) void loadTemplates();
  }, [loadTemplates]);

  const deck = decks[active];
  const issues = deck?.audit.issues ?? [];
  const fixable = useMemo(() => issues.filter(i => i.fixable), [issues]);

  /** Структура отдельно от вёрстки: ТЗ требует показать её и дать поправить. */
  async function buildOutline() {
    setBusy(true);
    setError('');
    setDecks([]);
    try {
      const result = await api.createOutline({
        brief,
        purpose,
        language: 'ru',
        slide_count: slideCount,
        content_pack_ids: packs.map(pack => pack.id),
      });
      setOutline(result);
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  function editSlide(index: number, patch: Partial<ApiSlideContent>) {
    setOutline(current =>
      current
        ? {
            ...current,
            slides: current.slides.map((slide, i) => (i === index ? { ...slide, ...patch } : slide)),
          }
        : current,
    );
  }

  function moveSlide(index: number, delta: number) {
    setOutline(current => {
      if (!current) return current;
      const target = index + delta;
      if (target < 0 || target >= current.slides.length) return current;
      const slides = [...current.slides];
      [slides[index], slides[target]] = [slides[target], slides[index]];
      return { ...current, slides };
    });
  }

  function removeSlide(index: number) {
    setOutline(current =>
      current && current.slides.length > 1
        ? { ...current, slides: current.slides.filter((_, i) => i !== index) }
        : current,
    );
  }

  async function uploadPack(file: File) {
    setUploading(true);
    setError('');
    try {
      const pack = await api.uploadContentPack(file, file.name);
      setPacks(current =>
        current.some(item => item.id === pack.id) ? current : [...current, pack],
      );
    } catch (exc) {
      setError(message(exc));
    } finally {
      setUploading(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError('');
    setDecks([]);
    setSelected(new Set());
    try {
      const started = await api.startGeneration({
        template_id: templateId,
        brief,
        purpose,
        language: 'ru',
        slide_count: outline ? outline.slides.length : slideCount,
        content_pack_ids: packs.map(pack => pack.id),
        outline: outline ?? undefined,
        contextual_audit: contextual,
      });
      const finished = await waitForJob(started.id, setJob);
      const results = await Promise.all(finished.presentation_ids.map(id => api.presentation(id)));
      setDecks(results);
      setActive(0);
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  async function uploadTemplate(file: File) {
    setUploading(true);
    setError('');
    try {
      const created = await api.uploadTemplate(file);
      await loadTemplates();
      setTemplateId(created.id);
    } catch (exc) {
      setError(message(exc));
    } finally {
      setUploading(false);
    }
  }

  async function runVisualAudit() {
    if (!deck) return;
    setBusy(true);
    setError('');
    try {
      const report = await api.runAudit(deck.id, { visual: true });
      setDecks(list =>
        list.map((item, index) => (index === active ? { ...item, audit: report } : item)),
      );
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  async function applySelected() {
    if (!deck || !selected.size) return;
    setBusy(true);
    setError('');
    try {
      const updated = await api.applyFixes(deck.id, deck.revision, [...selected]);
      setDecks(list => list.map((item, index) => (index === active ? updated : item)));
      setSelected(new Set());
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  async function download(format: 'pptx' | 'pdf' | 'html') {
    if (!deck) return;
    try {
      const blob = await api.download(api.exportPath(deck.id, format, deck.revision));
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${deck.title || 'presentation'}-${deck.variant}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (exc) {
      setError(message(exc));
    }
  }

  function toggle(issue: ApiAuditIssue) {
    setSelected(current => {
      const next = new Set(current);
      if (next.has(issue.id)) next.delete(issue.id);
      else next.add(issue.id);
      return next;
    });
  }

  if (!apiConfigured) {
    return (
      <div className="studio">
        <p className="studio-error">
          Адрес API не задан. Соберите фронтенд с переменной VITE_API_URL.
        </p>
      </div>
    );
  }

  return (
    <div className="studio">
      <header className="studio-head">
        <div>
          <h1>Студия на сервере</h1>
          <p>Слайды собираются внутри загруженного шаблона: макеты, фон и брендинг остаются его.</p>
        </div>
        <a className="studio-link" href="/">
          Демо-режим без сервера
        </a>
      </header>

      <section className="studio-form">
        <label className="studio-field studio-wide">
          <span>Бриф</span>
          <textarea rows={4} value={brief} onChange={e => setBrief(e.target.value)} />
        </label>

        <label className="studio-field">
          <span>Шаблон</span>
          <select value={templateId} onChange={e => setTemplateId(e.target.value)}>
            {templates.map(t => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>

        <label className="studio-field">
          <span>Назначение</span>
          <select value={purpose} onChange={e => setPurpose(e.target.value as ApiPurpose)}>
            {PURPOSES.map(p => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label className="studio-field">
          <span>Слайдов</span>
          <input
            type="number"
            min={1}
            max={30}
            value={slideCount}
            onChange={e => setSlideCount(Math.min(30, Math.max(1, Number(e.target.value) || 1)))}
          />
        </label>

        <label className="studio-field studio-check">
          <input type="checkbox" checked={contextual} onChange={e => setContextual(e.target.checked)} />
          <span>Контекстная проверка моделью</span>
        </label>

        <div className="studio-actions">
          <label className="studio-upload">
            {uploading ? 'Загрузка…' : 'Загрузить свой PPTX'}
            <input
              type="file"
              accept=".pptx"
              disabled={uploading}
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) void uploadTemplate(file);
                e.target.value = '';
              }}
            />
          </label>
          <label className="studio-upload">
            Добавить материалы
            <input
              type="file"
              accept=".txt,.md,.csv,.json,.pdf,.docx,.pptx"
              disabled={uploading}
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) void uploadPack(file);
                e.target.value = '';
              }}
            />
          </label>
          <button
            className="studio-secondary"
            disabled={busy || !brief.trim()}
            onClick={() => void buildOutline()}
          >
            {busy ? 'Работаем…' : 'Собрать структуру'}
          </button>
          <button className="studio-primary" disabled={busy || !templateId} onClick={() => void generate()}>
            {busy ? 'Генерация…' : outline ? 'Сверстать три варианта' : 'Сгенерировать три варианта'}
          </button>
        </div>
      </section>

      {packs.length > 0 && (
        <p className="studio-muted studio-packs">
          Материалы:{' '}
          {packs.map(pack => (
            <span key={pack.id} className="studio-chip">
              {pack.name} · {Math.round(pack.text.length / 1000)}k символов
              <button
                type="button"
                aria-label={`Убрать ${pack.name}`}
                onClick={() => setPacks(list => list.filter(item => item.id !== pack.id))}
              >
                ×
              </button>
            </span>
          ))}
        </p>
      )}

      {outline && (
        <section className="studio-outline">
          <header>
            <h2>Структура до вёрстки</h2>
            <p className="studio-muted">
              {outline.slides.length} слайдов. Правьте заголовки и тезисы, меняйте порядок —
              вёрстка соберётся по этой структуре.
            </p>
          </header>
          <ol>
            {outline.slides.map((slide, index) => (
              <li key={index}>
                <div className="studio-outline-head">
                  <input
                    value={slide.title}
                    onChange={e => editSlide(index, { title: e.target.value })}
                    aria-label={`Заголовок слайда ${index + 1}`}
                  />
                  <span className="studio-outline-kind">{slide.visual.kind}</span>
                  <button type="button" onClick={() => moveSlide(index, -1)} aria-label="Выше">
                    ↑
                  </button>
                  <button type="button" onClick={() => moveSlide(index, 1)} aria-label="Ниже">
                    ↓
                  </button>
                  <button type="button" onClick={() => removeSlide(index)} aria-label="Удалить">
                    ×
                  </button>
                </div>
                <textarea
                  rows={Math.max(2, slide.bullets.length)}
                  value={slide.bullets.join('\n')}
                  aria-label={`Тезисы слайда ${index + 1}`}
                  onChange={e =>
                    editSlide(index, {
                      bullets: e.target.value.split('\n').filter(line => line.trim()),
                    })
                  }
                />
              </li>
            ))}
          </ol>
        </section>
      )}

      {busy && job && (
        <div className="studio-progress">
          <div className="studio-bar" style={{ width: `${job.progress}%` }} />
          <span>
            {job.stage} · {job.progress}%
          </span>
        </div>
      )}

      {error && <p className="studio-error">{error}</p>}

      {decks.length > 0 && deck && (
        <>
          <nav className="studio-tabs">
            {decks.map((item, index) => (
              <button
                key={item.id}
                className={index === active ? 'active' : ''}
                onClick={() => {
                  setActive(index);
                  setSelected(new Set());
                }}
              >
                {VARIANT_LABEL[item.variant] ?? item.variant}
                <small>
                  {item.audit.counts.errors} ош · {item.audit.counts.warnings} пред
                </small>
              </button>
            ))}
          </nav>

          <div className="studio-meta">
            <span>Слайдов: {deck.deck.slides.length}</span>
            <span>Ревизия: {deck.revision}</span>
            <span>Редактируемых объектов: {deck.export_check?.native_objects ?? '—'}</span>
            <span>Слайдов-картинок: {deck.export_check?.raster_slides.length ?? 0}</span>
            <div className="studio-exports">
              {(['pptx', 'pdf', 'html'] as const).map(format => (
                <button key={format} onClick={() => void download(format)}>
                  {format.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="studio-body">
            <div className="studio-slides">
              {deck.deck.slides.map((slide, index) => (
                <figure key={index}>
                  <img
                    loading="lazy"
                    src={`${import.meta.env.VITE_API_URL}/presentations/${deck.id}/slides/${index}/preview?highlight=true&r=${deck.revision}`}
                    alt={`Слайд ${index + 1}: ${slide.content.title}`}
                  />
                  <figcaption>
                    {index + 1}. {slide.content.title}
                  </figcaption>
                </figure>
              ))}
            </div>

            <aside className="studio-audit">
              <h2>Аудит</h2>
              <p className="studio-muted">
                {issues.length === 0
                  ? 'Проблем не найдено.'
                  : `Найдено ${issues.length}, из них исправляются автоматически ${fixable.length}.`}
              </p>
              <ul>
                {issues.map(issue => (
                  <li key={issue.id} className={issue.severity}>
                    <label>
                      <input
                        type="checkbox"
                        disabled={!issue.fixable}
                        checked={selected.has(issue.id)}
                        onChange={() => toggle(issue)}
                      />
                      <span>
                        <b>
                          {issue.slide_index === null ? 'Колода' : `Слайд ${issue.slide_index + 1}`} ·{' '}
                          {issue.code}
                        </b>
                        <em className={issue.category}>
                          {issue.category === 'deterministic' ? 'правило' : 'модель'}
                        </em>
                        <span>{issue.message}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="studio-audit-actions">
                <button
                  className="studio-primary"
                  disabled={busy || selected.size === 0}
                  onClick={() => void applySelected()}
                >
                  Исправить выбранные ({selected.size})
                </button>
                <button
                  className="studio-secondary"
                  disabled={busy}
                  title="Каждый слайд уходит картинкой мультимодальной модели: заголовки-выводы, факты, мусор, читаемость"
                  onClick={() => void runVisualAudit()}
                >
                  Проверить по изображению
                </button>
              </div>
              {deck.audit.contextual?.status === 'completed' && (
                <p className="studio-muted">
                  Контекстная проверка выполнена, вход:{' '}
                  {deck.audit.contextual.input === 'slide_images'
                    ? 'изображения слайдов'
                    : 'текст слайдов'}
                  .
                </p>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
