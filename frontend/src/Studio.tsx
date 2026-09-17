/**
 * Единый интерфейс сервиса: шаблон → бриф и материалы → структура → варианты,
 * аудит и экспорт. Всё, что видно на экране, приходит с бэкенда: превью слайдов
 * — это рендер собранного PPTX, а не наша перерисовка.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Download,
  FileText,
  Image as ImageIcon,
  Layers,
  ListTree,
  Moon,
  Plus,
  RefreshCw,
  ScanEye,
  Sun,
  Trash2,
  Upload,
  Wand2,
} from 'lucide-react';
import { Wordmark } from './brand/Logo';
import { applyTheme, readTheme, type Theme } from './brand/theme';
import { api, apiConfigured, waitForJob } from './services/api';
import type {
  ApiAuditIssue,
  ApiContentPack,
  ApiJob,
  ApiOutline,
  ApiPresentation,
  ApiPurpose,
  ApiSlideContent,
  ApiTemplateSummary,
} from './services/apiTypes';

const PURPOSES: { id: ApiPurpose; label: string; hint: string }[] = [
  { id: 'project', label: 'Проект', hint: 'Статус, результаты, сроки' },
  { id: 'feature', label: 'Фича', hint: 'Боль, решение, эффект' },
  { id: 'product', label: 'Продукт', hint: 'Рынок, ценность, модель' },
  { id: 'initiative', label: 'Инициатива', hint: 'Возможность, план, запрос' },
];

const VARIANTS: Record<string, { label: string; hint: string }> = {
  classic: { label: 'Классический', hint: 'Текст сверху, визуализация снизу' },
  split: { label: 'Две колонки', hint: 'Текст слева, визуализация справа' },
  focus: { label: 'Фокус', hint: 'Одна мысль, крупный кегль' },
};

const EXAMPLE =
  'Внедряем сервис автоматической вёрстки презентаций. Этапы: анализ шаблонов, ' +
  'пилот на 10 командах, запуск на 20 команд, масштабирование на компанию. ' +
  'Экономия 4 часа дизайнера на колоду, 200 презентаций в квартал.';

const STAGES: Record<string, string> = {
  queued: 'В очереди',
  outline: 'Планируем структуру',
  balance: 'Подгоняем тексты под шаблон',
  contextual_audit: 'Проверяем содержание',
  layout_and_audit: 'Верстаем и проверяем',
  completed: 'Готово',
  failed: 'Ошибка',
};

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => applyTheme(theme), [theme]);
  const next: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };
  const label = { system: 'Как в системе', light: 'Светлая тема', dark: 'Тёмная тема' }[theme];
  return (
    <button className="ghost" onClick={() => setTheme(next[theme])} title={label} aria-label={label}>
      {theme === 'dark' ? <Moon size={17} /> : theme === 'light' ? <Sun size={17} /> : <Layers size={17} />}
      <span className="only-wide">{label}</span>
    </button>
  );
}

function TemplateCard({
  template,
  active,
  onPick,
}: {
  template: ApiTemplateSummary;
  active: boolean;
  onPick: () => void;
}) {
  const colors = (template.tokens?.colors ?? []).slice(0, 5);
  const font = template.tokens?.fonts?.[0];
  const sizes = template.tokens?.font_sizes ?? [];
  return (
    <button className={`template ${active ? 'active' : ''}`} onClick={onPick} aria-pressed={active}>
      <span className="template-head">
        <span className="template-name">{template.name}</span>
        {active && <Check size={16} />}
      </span>
      <span className="swatches">
        {colors.map(color => (
          <span key={color} style={{ background: `#${color}` }} />
        ))}
      </span>
      <span className="template-meta">
        {font ?? 'шрифт не указан'}
        {sizes.length > 0 && ` · ${sizes.length} ступеней кегля`}
        {template.layouts && ` · ${template.layouts.length} макетов`}
      </span>
    </button>
  );
}

export default function Studio() {
  const [templates, setTemplates] = useState<ApiTemplateSummary[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [brief, setBrief] = useState(EXAMPLE);
  const [purpose, setPurpose] = useState<ApiPurpose>('project');
  const [slideCount, setSlideCount] = useState(10);
  const [contextual, setContextual] = useState(false);
  const [packs, setPacks] = useState<ApiContentPack[]>([]);
  const [outline, setOutline] = useState<ApiOutline | null>(null);
  const [decks, setDecks] = useState<ApiPresentation[]>([]);
  const [active, setActive] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [job, setJob] = useState<ApiJob | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

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
  const template = templates.find(t => t.id === templateId);

  async function run<T>(label: string, action: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    setError('');
    try {
      return await action();
    } catch (exc) {
      setError(message(exc));
      return undefined;
    } finally {
      setBusy('');
    }
  }

  const uploadTemplate = (file: File) =>
    run('Разбираем шаблон', async () => {
      const created = await api.uploadTemplate(file);
      await loadTemplates();
      setTemplateId(created.id);
    });

  const uploadPack = (file: File) =>
    run('Читаем материалы', async () => {
      const pack = await api.uploadContentPack(file, file.name);
      setPacks(current => (current.some(p => p.id === pack.id) ? current : [...current, pack]));
    });

  const buildOutline = () =>
    run('Планируем структуру', async () => {
      const result = await api.createOutline({
        brief,
        purpose,
        language: 'ru',
        slide_count: slideCount,
        content_pack_ids: packs.map(p => p.id),
      });
      setOutline(result);
      setDecks([]);
    });

  const generate = () =>
    run('Собираем три варианта', async () => {
      setDecks([]);
      const started = await api.startGeneration({
        template_id: templateId,
        brief,
        purpose,
        language: 'ru',
        slide_count: outline ? outline.slides.length : slideCount,
        content_pack_ids: packs.map(p => p.id),
        outline: outline ?? undefined,
        contextual_audit: contextual,
      });
      const finished = await waitForJob(started.id, setJob);
      const results = await Promise.all(finished.presentation_ids.map(id => api.presentation(id)));
      setDecks(results);
      setActive(0);
      setSelected(new Set());
    });

  const runVisualAudit = () =>
    deck &&
    run('Смотрим слайды глазами модели', async () => {
      const report = await api.runAudit(deck.id, { visual: true });
      setDecks(list => list.map((item, i) => (i === active ? { ...item, audit: report } : item)));
    });

  const applySelected = () =>
    deck &&
    selected.size > 0 &&
    run('Исправляем', async () => {
      const updated = await api.applyFixes(deck.id, deck.revision, [...selected]);
      setDecks(list => list.map((item, i) => (i === active ? updated : item)));
      setSelected(new Set());
    });

  const download = (format: 'pptx' | 'pdf' | 'html') =>
    deck &&
    run('Готовим файл', async () => {
      const blob = await api.download(api.exportPath(deck.id, format, deck.revision));
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${deck.title || 'presentation'}-${deck.variant}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    });

  function editSlide(index: number, patch: Partial<ApiSlideContent>) {
    setOutline(current =>
      current
        ? { ...current, slides: current.slides.map((s, i) => (i === index ? { ...s, ...patch } : s)) }
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

  function toggleIssue(issue: ApiAuditIssue) {
    setSelected(current => {
      const next = new Set(current);
      if (next.has(issue.id)) next.delete(issue.id);
      else next.add(issue.id);
      return next;
    });
  }

  const step = decks.length ? 3 : outline ? 2 : 1;

  return (
    <div className="app">
      <header className="topbar">
        <Wordmark />
        <nav className="topbar-actions">
          <ThemeSwitch />
        </nav>
      </header>

      {!apiConfigured && (
        <p className="banner error">
          Не задан адрес API: соберите фронтенд с переменной VITE_API_URL.
        </p>
      )}

      <main className="layout">
        <section className="hero">
          <h1>
            Презентация <span>в стиле вашего шаблона</span>
          </h1>
          <p>
            Загрузите шаблон и бриф. Сервис разберёт дизайн-систему, соберёт структуру,
            сверстает три варианта на макетах шаблона и проверит результат аудитом.
          </p>
          <ol className="steps">
            {['Шаблон и бриф', 'Структура', 'Варианты и аудит'].map((label, index) => (
              <li key={label} className={step > index ? 'done' : step === index + 1 ? 'now' : ''}>
                <span>{index + 1}</span>
                {label}
              </li>
            ))}
          </ol>
        </section>

        <section className="card">
          <header className="card-head">
            <h2>
              <Layers size={18} /> Шаблон
            </h2>
            <label className="ghost file">
              <Upload size={16} />
              Загрузить PPTX
              <input
                type="file"
                accept=".pptx"
                onChange={e => {
                  const file = e.target.files?.[0];
                  if (file) void uploadTemplate(file);
                  e.target.value = '';
                }}
              />
            </label>
          </header>
          <div className="templates">
            {templates.map(item => (
              <TemplateCard
                key={item.id}
                template={item}
                active={item.id === templateId}
                onPick={() => setTemplateId(item.id)}
              />
            ))}
            {templates.length === 0 && <p className="muted">Шаблонов пока нет — загрузите PPTX.</p>}
          </div>
        </section>

        <section className="card">
          <header className="card-head">
            <h2>
              <Wand2 size={18} /> Бриф
            </h2>
            <label className="ghost file">
              <Plus size={16} />
              Материалы
              <input
                type="file"
                accept=".txt,.md,.csv,.json,.pdf,.docx,.pptx"
                onChange={e => {
                  const file = e.target.files?.[0];
                  if (file) void uploadPack(file);
                  e.target.value = '';
                }}
              />
            </label>
          </header>

          <textarea
            rows={4}
            value={brief}
            onChange={e => setBrief(e.target.value)}
            aria-label="Бриф"
            placeholder="О чём презентация, для кого и с какими цифрами"
          />

          {packs.length > 0 && (
            <ul className="chips">
              {packs.map(pack => (
                <li key={pack.id}>
                  <FileText size={14} />
                  {pack.name}
                  <em>{Math.max(1, Math.round(pack.text.length / 1000))}k символов</em>
                  <button
                    aria-label={`Убрать ${pack.name}`}
                    onClick={() => setPacks(list => list.filter(p => p.id !== pack.id))}
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="purposes">
            {PURPOSES.map(item => (
              <button
                key={item.id}
                className={`purpose ${purpose === item.id ? 'active' : ''}`}
                onClick={() => setPurpose(item.id)}
                aria-pressed={purpose === item.id}
              >
                <b>{item.label}</b>
                <span>{item.hint}</span>
              </button>
            ))}
          </div>

          <div className="row">
            <label className="field">
              <span>Слайдов</span>
              <input
                type="number"
                min={1}
                max={30}
                value={slideCount}
                onChange={e => setSlideCount(Math.min(30, Math.max(1, Number(e.target.value) || 1)))}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={contextual}
                onChange={e => setContextual(e.target.checked)}
              />
              <span>Проверка содержания моделью</span>
            </label>
            <div className="row-actions">
              <button className="secondary" disabled={!!busy || !brief.trim()} onClick={() => void buildOutline()}>
                <ListTree size={16} />
                Собрать структуру
              </button>
              <button className="primary" disabled={!!busy || !templateId} onClick={() => void generate()}>
                {outline ? 'Сверстать три варианта' : 'Сгенерировать'}
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </section>

        {busy && (
          <div className="progress" role="status">
            <div className="bar" style={{ width: `${job?.progress ?? 8}%` }} />
            <span>
              <RefreshCw size={15} className="spin" />
              {busy}
              {job?.stage && job.progress ? ` · ${STAGES[job.stage] ?? job.stage} ${job.progress}%` : ''}
            </span>
          </div>
        )}

        {error && (
          <p className="banner error">
            <AlertTriangle size={16} /> {error}
          </p>
        )}

        {outline && (
          <section className="card">
            <header className="card-head">
              <h2>
                <ListTree size={18} /> Структура
              </h2>
              <span className="muted">
                {outline.slides.length} слайдов · правьте до вёрстки
              </span>
            </header>
            <ol className="outline">
              {outline.slides.map((slide, index) => (
                <li key={index}>
                  <div className="outline-head">
                    <input
                      value={slide.title}
                      onChange={e => editSlide(index, { title: e.target.value })}
                      aria-label={`Заголовок слайда ${index + 1}`}
                    />
                    {slide.visual.kind !== 'none' && <em className="kind">{slide.visual.kind}</em>}
                    <button onClick={() => moveSlide(index, -1)} aria-label="Выше">↑</button>
                    <button onClick={() => moveSlide(index, 1)} aria-label="Ниже">↓</button>
                    <button
                      onClick={() =>
                        setOutline(current =>
                          current && current.slides.length > 1
                            ? { ...current, slides: current.slides.filter((_, i) => i !== index) }
                            : current,
                        )
                      }
                      aria-label="Удалить слайд"
                    >
                      <Trash2 size={14} />
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

        {deck && (
          <section className="card result">
            <header className="card-head">
              <h2>
                <ImageIcon size={18} /> Три варианта
              </h2>
              <span className="muted">{template?.name}</span>
            </header>

            <div className="variants">
              {decks.map((item, index) => (
                <button
                  key={item.id}
                  className={`variant ${index === active ? 'active' : ''}`}
                  onClick={() => {
                    setActive(index);
                    setSelected(new Set());
                  }}
                >
                  <b>{VARIANTS[item.variant]?.label ?? item.variant}</b>
                  <span>{VARIANTS[item.variant]?.hint}</span>
                  <em>
                    {item.audit.counts.errors > 0 && (
                      <span className="dot error" title="Ошибки" />
                    )}
                    {item.audit.counts.errors} ош · {item.audit.counts.warnings} пред
                  </em>
                </button>
              ))}
            </div>

            <div className="meta">
              <span>Слайдов: {deck.deck.slides.length}</span>
              <span>Ревизия: {deck.revision}</span>
              <span>Редактируемых объектов: {deck.export_check?.native_objects ?? '—'}</span>
              <span>Слайдов-картинок: {deck.export_check?.raster_slides.length ?? 0}</span>
              <div className="exports">
                {(['pptx', 'pdf', 'html'] as const).map(format => (
                  <button key={format} className="ghost" onClick={() => void download(format)}>
                    <Download size={15} />
                    {format.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div className="result-body">
              <div className="slides">
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

              <aside className="audit">
                <h3>Аудит</h3>
                <p className="muted">
                  {issues.length === 0
                    ? 'Проблем не найдено.'
                    : `Найдено ${issues.length}, исправляются автоматически ${fixable.length}.`}
                </p>
                <ul>
                  {issues.map(issue => (
                    <li key={issue.id} className={issue.severity}>
                      <label>
                        <input
                          type="checkbox"
                          disabled={!issue.fixable}
                          checked={selected.has(issue.id)}
                          onChange={() => toggleIssue(issue)}
                        />
                        <span>
                          <b>
                            {issue.slide_index === null ? 'Колода' : `Слайд ${issue.slide_index + 1}`}
                            <em className={issue.category}>
                              {issue.category === 'deterministic' ? 'правило' : 'модель'}
                            </em>
                          </b>
                          <span>{issue.message}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
                <div className="audit-actions">
                  <button
                    className="primary"
                    disabled={!!busy || selected.size === 0}
                    onClick={() => void applySelected()}
                  >
                    <Check size={16} />
                    Исправить выбранные ({selected.size})
                  </button>
                  <button className="secondary" disabled={!!busy} onClick={() => void runVisualAudit()}>
                    <ScanEye size={16} />
                    Проверить по изображению
                  </button>
                </div>
                {deck.audit.contextual?.status === 'completed' && (
                  <p className="muted small">
                    Контекстная проверка выполнена по{' '}
                    {deck.audit.contextual.input === 'slide_images' ? 'изображениям слайдов' : 'тексту слайдов'}.
                  </p>
                )}
              </aside>
            </div>
          </section>
        )}
      </main>

      <footer className="foot">
        Слайдер · кейс VK Tech «Цифровой дизайнер презентаций» · ЛЦТ 2026
      </footer>
    </div>
  );
}
