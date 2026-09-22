import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, ChevronLeft, ChevronRight, CircleHelp, Clock3, Copy, Download, FileText, FolderOpen, GripVertical, LayoutTemplate, LoaderCircle, Maximize2, Monitor, PanelLeftClose, Paperclip, Plus, Presentation, Search, ShieldCheck, Sparkles, Trash2, Upload, X, AlertCircle, CheckCircle2, ArrowUpRight, Lightbulb, FileUp, SlidersHorizontal, Eye } from 'lucide-react';
import type { Brief, Deck, Layout, Slide, Template } from './types';
import { EXAMPLE_BRIEF, getSlideTypography } from './engine';
import { draftDeck, presentationService, toOutline } from './services/presentationService';
import type { Project, WorkflowInfo } from './services/presentationService';
import type { ApiOutline } from './services/apiTypes';

type Screen = 'create' | 'outline' | 'design' | 'editor' | 'projects' | 'templates';
type Saved = { brief: Brief; decks: Deck[] };
const STORAGE_KEY = 'slide-studio:v1';
/** Цель из брифа в назначение колоды: от него зависит состав слайдов. */
const PURPOSES: Record<string, 'project' | 'product' | 'feature' | 'initiative'> = {
  'Представить идею': 'initiative',
  'Показать результаты': 'project',
  'Запустить продукт': 'product',
  'Объяснить решение': 'feature',
};
/** Пока список шаблонов едет с сервера, экранам нужен кто-то с такими же полями:
 *  иначе первый рендер падает на обращении к имени шаблона. */
const LOADING_TEMPLATE: Template = {
  id: '', name: 'Загружаем шаблоны…', description: 'Дизайн-система придёт с сервера',
  color: '#0674ff', secondary: '#8a83d1', font: 'Manrope Variable',
  layoutCount: 0, slideCount: 0, tag: '16:9',
};
const STAGES: Record<string, string> = {
  queued: 'В очереди', outline: 'Собираем структуру', balance: 'Подгоняем текст под шаблон',
  assets: 'Подписываем картинки шаблона', contextual_audit: 'Проверяем содержание', compose: 'Верстаем варианты', audit: 'Аудит', export: 'Готовим файлы',
};
const DEFAULT_BRIEF: Brief = { text: '', audience: 'Коллеги и команда', goal: 'Представить идею', slideCount: 10, templateId: 'tech', materials: '' };

function readSaved(): Saved {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (data && Array.isArray(data.decks)) return {
      brief: { ...DEFAULT_BRIEF, ...data.brief },
      decks: data.decks.filter((d: Deck) => d && typeof d.id === 'string' && typeof d.title === 'string' && Array.isArray(d.slides) && d.slides.length > 0 && d.slides.every(s => s && typeof s.title === 'string' && typeof s.body === 'string')),
    };
  } catch { /* Storage may be unavailable or contain an old format. */ }
  return { brief: DEFAULT_BRIEF, decks: [] };
}

/** «1 замечание», «2 замечания», «5 замечаний»: без этого счётчик выглядит небрежно. */
function issueWord(count: number): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return 'замечаний';
  const ones = count % 10;
  if (ones === 1) return 'замечание';
  if (ones >= 2 && ones <= 4) return 'замечания';
  return 'замечаний';
}

function IconButton({ children, label, ...props }: { children: ReactNode; label: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className="icon-button" title={label} aria-label={label} {...props}>{children}</button>;
}

function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const el = ref.current; el?.showModal(); return () => { el?.close(); }; }, []);
  return <dialog ref={ref} className={`modal ${wide ? 'wide' : ''}`} onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="modal-heading"><h2>{title}</h2><IconButton label="Закрыть" onClick={onClose}><X size={20} /></IconButton></div>
    {children}
  </dialog>;
}

function TemplateArt({ template, compact = false }: { template: Template; compact?: boolean }) {
  return <div className={`template-art ${compact ? 'compact' : ''} art-${template.id}`} style={{ '--template-color': template.color, '--template-secondary': template.secondary } as CSSProperties} aria-hidden="true">
    <div className="mini-brand"><span className="vk-mark">vk</span>{template.name.replace('VK ', '')}</div>
    <div className="mini-title">{template.id === 'education' ? <>Знания.<br />Возможности.<br />Будущее.</> : template.id === 'workspace' ? <>Работаем<br />лучше.<br />Вместе.</> : <>Технологии,<br />которые<br />двигают вперёд.</>}</div>
    <div className="template-geometry"><span /><span /><span /></div>
    <div className="mini-footer">{template.custom ? 'ВАШ ФИРМЕННЫЙ СТИЛЬ' : 'ИДЕИ ПРИОБРЕТАЮТ ФОРМУ'}<span>01</span></div>
  </div>;
}

function SlideCanvas({ slide, template, layout, index = 0, total = 10, miniature = false }: { slide: Slide; template: Template; layout: Layout; index?: number; total?: number; miniature?: boolean }) {
  const typography = getSlideTypography(slide, template, layout);
  return <div className={`slide-canvas layout-${layout} ${slide.kind === 'cover' ? 'is-cover' : ''} ${miniature ? 'miniature' : ''}`} style={{ '--slide-color': template.color, '--slide-secondary': template.secondary, '--title-size': `${typography.title}cqw`, '--body-size': `${typography.body}cqw`, fontFamily: `${template.font}, Arial, sans-serif` } as CSSProperties}>
    <div className="slide-brand"><span className="vk-mark">{template.custom ? 's' : 'vk'}</span><span>{template.name.replace('VK ', '')}</span></div>
    <div className="slide-content"><div className="slide-eyebrow">{slide.kind === 'cover' ? 'ИДЕИ, КОТОРЫЕ ОБЪЕДИНЯЮТ' : `ЧАСТЬ ${String(index).padStart(2, '0')}`}</div><h3>{slide.title || 'Название слайда'}</h3>{slide.body && <p>{slide.body}</p>}</div>
    <div className="slide-accent" aria-hidden="true"><div /><div /><div /></div>
    <div className="slide-bottom"><span>{template.name} · Презентация</span><span>{String(index + 1).padStart(2, '0')} / {String(total).padStart(2, '0')}</span></div>
  </div>;
}

const layoutOptions: { id: Layout; name: string; description: string; detail: string }[] = [
  { id: 'classic', name: 'Классический', description: 'Чёткая структура и спокойный ритм', detail: 'Для отчётов и деловых встреч' },
  { id: 'story', name: 'Выразительный', description: 'Контрастные акценты и крупный текст', detail: 'Для выступлений и новых идей' },
  { id: 'focus', name: 'Минималистичный', description: 'Больше воздуха, фокус на главном', detail: 'Для питчей и коротких историй' },
];

export default function App() {
  const [initial] = useState(readSaved);
  const [brief, setBrief] = useState<Brief>(initial.brief);
  const [decks, setDecks] = useState<Deck[]>(initial.decks);
  // Шаблоны, материалы и колоды живут на сервере: интерфейс только показывает их.
  const [templates, setTemplates] = useState<Template[]>([]);
  const [packs, setPacks] = useState<{ id: string; name: string }[]>([]);
  const [variants, setVariants] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [stage, setStage] = useState('');
  // План колоды до вёрстки: его правит экран «Структура».
  const [plan, setPlan] = useState<ApiOutline | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [screen, setScreen] = useState<Screen>('create');
  const [deck, setDeck] = useState<Deck | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [storageError, setStorageError] = useState(false);
  const [toast, setToast] = useState('');
  const [dialog, setDialog] = useState<'help' | 'export' | 'preview' | 'settings' | null>(null);
  // Превью слайда рисует сервер: это тот же PDF, что уедет пользователю.
  const [previewUrl, setPreviewUrl] = useState('');
  // Сервер умеет обводить найденные проблемы прямо на слайде.
  const [previewHighlight, setPreviewHighlight] = useState(true);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  // Чем собрана колода: версия сценария и промпты агентов.
  const [workflow, setWorkflow] = useState<WorkflowInfo | null>(null);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [materialName, setMaterialName] = useState(initial.brief.materials ? 'Сохранённые текстовые материалы' : '');
  const [dragging, setDragging] = useState(false);
  const [projectSearch, setProjectSearch] = useState('');
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const materialInput = useRef<HTMLInputElement>(null);
  const templateInput = useRef<HTMLInputElement>(null);
  const workflowCard = useRef<HTMLDivElement>(null);
  const briefInput = useRef<HTMLTextAreaElement>(null);
  const allTemplates = templates;
  const currentTemplate = allTemplates.find(t => t.id === (deck && ['outline', 'design', 'editor'].includes(screen) ? deck.templateId : brief.templateId)) || allTemplates[0] || LOADING_TEMPLATE;
  const issues = project?.issues ?? [];
  const slide = deck?.slides[Math.min(activeSlide, deck.slides.length - 1)];

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ brief, decks })); setStorageError(false); }
    catch { setStorageError(true); }
  }, [brief, decks]);
  // Список шаблонов — с сервера: их разбирает бэкенд, а не браузер.
  useEffect(() => {
    presentationService.listTemplates()
      .then(items => {
        setTemplates(items);
        setBrief(prev => (items.some(t => t.id === prev.templateId) ? prev : { ...prev, templateId: items[0]?.id ?? '' }));
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Сервис недоступен: не удалось получить шаблоны.'));
  }, []);
  // Версия сценария — справочная: её отсутствие не повод пугать пользователя ошибкой.
  useEffect(() => {
    presentationService.workflow().then(setWorkflow).catch(() => setWorkflow(null));
  }, []);
  // Карточка версии закрывается кликом мимо и по Escape — как обычное меню.
  useEffect(() => {
    if (!workflowOpen) return;
    const away = (event: MouseEvent) => {
      if (!workflowCard.current?.contains(event.target as Node)) setWorkflowOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setWorkflowOpen(false); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', escape);
    };
  }, [workflowOpen]);
  useEffect(() => {
    if (!deck) return;
    setDecks(prev => [deck, ...prev.filter(d => d.id !== deck.id)]);
  }, [deck]);
  useEffect(() => {
    if (dialog !== 'preview' || !project) { setPreviewUrl(''); return; }
    let live = true;
    let url = '';
    // Прошлая картинка отдаётся по blob-ссылке, которую мы сейчас отзовём:
    // показывать её дальше нельзя, поэтому уходим на локальный рендер.
    setPreviewUrl('');
    setPreviewBusy(true);
    presentationService.preview(project, activeSlide, previewHighlight)
      .then(value => { if (live) { url = value; setPreviewUrl(value); } else URL.revokeObjectURL(value); })
      .catch(() => setPreviewUrl(''))
      .finally(() => { if (live) setPreviewBusy(false); });
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [dialog, project, activeSlide, previewHighlight]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 4500); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => { setError(''); window.scrollTo({ top: 0 }); }, [screen]);

  function navigate(next: Screen) {
    setScreen(next); setAuditOpen(false);
    // Список презентаций живёт на сервере: показываем его, а не кэш браузера.
    if (next === 'projects') {
      presentationService.recent()
        .then(items => setDecks(items.map(item => item.deck)))
        .catch(() => undefined);
    }
  }
  async function openDeck(saved: Deck) {
    setBusy('open');
    try {
      const opened = await presentationService.open(saved.id);
      setProject(opened); setVariants([opened]); setDeck(opened.deck); setActiveSlide(0);
      const source = saved.brief || { ...DEFAULT_BRIEF, text: opened.deck.slides.map(s => `${s.title}\n${s.body}`).join('\n\n'), slideCount: opened.deck.slides.length, templateId: opened.deck.templateId };
      setBrief(source); setMaterialName(source.materials ? 'Сохранённые текстовые материалы' : '');
      navigate('editor');
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось открыть презентацию.'); }
    finally { setBusy(null); }
  }
  function updateBrief<K extends keyof Brief>(key: K, value: Brief[K]) { setBrief(prev => ({ ...prev, [key]: value })); if (key === 'text') setError(''); }
  function updateDeck(updater: (prev: Deck) => Deck) { setDeck(prev => prev ? { ...updater(prev), updatedAt: new Date().toISOString() } : prev); }
  function editSlide(id: string, field: 'title' | 'body', value: string) { updateDeck(d => ({ ...d, slides: d.slides.map(s => s.id === id ? { ...s, [field]: value } : s) })); }
  function moveSlide(index: number, direction: number) {
    updateDeck(d => { const slides = [...d.slides]; const other = index + direction; if (other < 0 || other >= slides.length) return d; [slides[index], slides[other]] = [slides[other], slides[index]]; return { ...d, slides }; });
    setActiveSlide(Math.max(0, index + direction));
  }
  function addSlide() {
    if (!deck || deck.slides.length >= 30) return;
    updateDeck(d => ({ ...d, slides: [...d.slides, { id: crypto.randomUUID(), title: 'Новый слайд', body: '', kind: 'content' }] }));
    setActiveSlide(deck.slides.length);
  }
  function removeSlide(id: string) {
    if (!deck || deck.slides.length <= 1) return;
    updateDeck(d => ({ ...d, slides: d.slides.filter(s => s.id !== id) }));
    setActiveSlide(prev => Math.max(0, Math.min(prev, deck.slides.length - 2)));
  }
  async function startDeck() {
    if (brief.text.trim().length < 20) { setError('Добавьте хотя бы 20 символов: тему и несколько тезисов.'); briefInput.current?.focus(); return; }
    if (!currentTemplate?.id) { setError('Сначала выберите шаблон: сервис верстает по его дизайн-системе.'); return; }
    setBusy('outline'); setStage('Собираем структуру'); setWarnings([]);
    try {
      // Сначала только план: по ТЗ структуру видно и можно править до вёрстки.
      const outline = await presentationService.createOutline(
        { ...brief, templateId: currentTemplate.id },
        packs.map(pack => pack.id),
        PURPOSES[brief.goal] ?? 'project',
      );
      setPlan(outline);
      setDeck({ ...draftDeck(outline, currentTemplate.id), brief: { ...brief } });
      setProject(null); setVariants([]); setActiveSlide(0); navigate('outline');
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось собрать структуру. Ваш текст сохранён.'); }
    finally { setBusy(null); setStage(''); }
  }

  /** Со структуры — в вёрстку: правки уходят готовым планом, модель не вызывается снова. */
  async function layoutDeck() {
    if (!deck || !currentTemplate.id) return;
    setBusy('layout'); setStage('Верстаем варианты'); setWarnings([]);
    try {
      const { projects, warnings: notes } = await presentationService.createDecks(
        { ...brief, templateId: currentTemplate.id },
        packs.map(pack => pack.id),
        PURPOSES[brief.goal] ?? 'project',
        (name, progress) => setStage(`${STAGES[name] ?? name} · ${progress}%`),
        toOutline(deck, plan),
      );
      if (!projects.length) throw new Error('Сервис не вернул ни одного варианта.');
      setVariants(projects); setWarnings(notes);
      const first = projects.find(item => item.layout === 'classic') ?? projects[0];
      setProject(first); setDeck({ ...first.deck, brief: { ...brief } }); setActiveSlide(0); navigate('design');
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сверстать варианты.'); }
    finally { setBusy(null); setStage(''); }
  }

  /** Переключение варианта вёрстки: содержание одно, раскладка разная. */
  function chooseLayout(layout: Layout) {
    const next = variants.find(item => item.layout === layout);
    if (!next) return;
    setProject(next); setDeck({ ...next.deck, brief: { ...brief } }); setActiveSlide(0);
  }

  /** Правка слайда уходит на сервер: там пересчитываются вёрстка и аудит. */
  async function saveSlide(index: number) {
    if (!project || !deck) return;
    setBusy('save');
    try {
      const updated = await presentationService.saveSlide(project, index, deck.slides[index]);
      setProject(updated);
      setVariants(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      setDeck(prev => (prev ? { ...prev, slides: updated.deck.slides } : prev));
      setToast('Слайд пересобран по шаблону');
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить слайд.'); }
    finally { setBusy(null); }
  }

  /** Исправления аудита применяет сервис: каждое создаёт новую ревизию. */
  async function fixIssues(ids: string[]) {
    if (!project || !ids.length) return;
    setBusy('fix');
    try {
      const updated = await presentationService.applyFixes(project, ids);
      setProject(updated);
      setVariants(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      setDeck(prev => (prev ? { ...prev, slides: updated.deck.slides } : prev));
      setToast(updated.issues.length ? `Осталось замечаний: ${updated.issues.length}` : 'Аудит чист');
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось применить исправления.'); }
    finally { setBusy(null); }
  }
  /** Проверки моделью идут поверх детерминированных: сервер пересобирает отчёт
   *  целиком, поэтому находки не дублируются при повторном запуске. */
  async function runAudit(kind: 'contextual' | 'visual') {
    if (!project) return;
    setBusy(kind);
    try {
      const found = await presentationService.recheck(project, { [kind]: true });
      setProject(prev => (prev ? { ...prev, issues: found } : prev));
      setVariants(prev => prev.map(item => (item.id === project.id ? { ...item, issues: found } : item)));
      setToast(found.length ? `Замечаний после проверки: ${found.length}` : 'Замечаний нет');
    } catch (e) { setError(e instanceof Error ? e.message : 'Проверка не удалась.'); }
    finally { setBusy(null); }
  }
  async function readMaterial(file?: File) {
    if (!file) return;
    if (!/\.(txt|md|csv|json|pdf|docx|pptx|zip|svg|png|jpe?g)$/i.test(file.name)) { setError('Материалы: TXT, MD, CSV, JSON, PDF с текстовым слоем, DOCX, PPTX, картинки SVG, PNG, JPEG или ZIP с ними.'); return; }
    if (file.size > 50 * 1024 * 1024) { setError('Выберите файл до 50 МБ.'); return; }
    setBusy('material');
    try {
      // Текст из PDF, DOCX и PPTX достаёт сервис: в браузере это делать нечем.
      const pack = await presentationService.uploadMaterial(file);
      setPacks(prev => [...prev.filter(item => item.id !== pack.id), { id: pack.id, name: pack.name }]);
      if (pack.text) updateBrief('materials', pack.text.slice(0, 50000));
      setMaterialName(file.name); setError('');
      // Картинки пакета сервис сам ставит на слайды: иконки и иллюстрации по смыслу тезисов.
      setToast(`Материал добавлен: ${[pack.text.length ? `${pack.text.length} символов` : '', pack.pictures ? `${pack.pictures} картинок` : ''].filter(Boolean).join(', ')}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось прочитать файл. Попробуйте ещё раз.'); }
    finally { setBusy(null); }
  }
  async function uploadTemplate(file?: File) {
    if (!file) return;
    setBusy('template');
    try {
      const t = await presentationService.importTemplate(file);
      setTemplates(prev => [...prev.filter(existing => existing.id !== t.id), t]); updateBrief('templateId', t.id); setToast('Шаблон добавлен: извлечены цвета, шрифт и число макетов'); setError('');
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось открыть шаблон. Проверьте PPTX-файл.'); }
    finally { setBusy(null); if (templateInput.current) templateInput.current.value = ''; }
  }
  async function download(format: 'pptx' | 'html' | 'pdf') {
    if (!project || !deck) return;
    setBusy(format);
    try {
      // Файлы собирает сервис: браузер их только сохраняет.
      const blob = await presentationService.download(project, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${deck.title.replace(/[^\wа-яё\s.-]/gi, ' ').trim() || 'Презентация'}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
      setToast('Файл готов — проверьте загрузки браузера');
    } catch (e) { setToast(e instanceof Error ? e.message : 'Не удалось создать файл. Попробуйте ещё раз.'); }
    finally { setBusy(null); }
  }

  function templateCards(library = false) {
    return <div className={library ? 'template-library' : 'template-grid'}>{allTemplates.map(t => <button key={t.id} type="button" className={`template-card ${brief.templateId === t.id ? 'selected' : ''}`} onClick={() => { updateBrief('templateId', t.id); if (library) setToast(`Выбран шаблон ${t.name}`); }} aria-pressed={brief.templateId === t.id}>
      <div className="template-picture"><TemplateArt template={t} compact /><span className="template-radio">{brief.templateId === t.id && <Check size={13} strokeWidth={3} />}</span></div>
      <div className="template-caption"><strong>{t.name}</strong>{!library && <span>{t.tag}</span>}{library && <><p>{t.description}</p><div className="template-meta"><span>{t.layoutCount} макетов</span><span>{t.font}</span></div><div className="palette"><i style={{ background: t.color }} /><i style={{ background: t.secondary }} /><i style={{ background: '#202020' }} /><i style={{ background: '#e8eef7' }} /><span>{t.custom ? 'Загруженный шаблон' : 'Из материалов кейса'}</span></div></>}</div>
    </button>)}</div>;
  }

  return <div className={`app-shell simplified ${screen === 'create' ? 'home-shell' : ''} ${screen === 'editor' ? 'editor-shell' : ''}`}>
    <div className="app-main">
      <header className="simple-header">
        <button className="brand" onClick={() => navigate('create')} aria-label="Слайд — на главную"><span className="brand-icon"><Presentation size={23} strokeWidth={1.8} /></span><span>слайд<span className="brand-dot">.</span></span></button>
        <nav aria-label="Основная навигация"><button className={screen === 'projects' ? 'selected' : ''} onClick={() => navigate('projects')}><FolderOpen size={16} />Мои презентации</button><button className={screen === 'templates' ? 'selected' : ''} onClick={() => navigate('templates')}><LayoutTemplate size={16} />Шаблоны</button></nav>
        <div className="simple-header-right"><span className="demo-badge">{templates.length ? `${templates.length} шаблона` : 'Подключаемся'}</span>{workflow && <div className="workflow-badge" ref={workflowCard}><button type="button" aria-expanded={workflowOpen} aria-haspopup="dialog" onClick={() => setWorkflowOpen(!workflowOpen)}>Сценарий {workflow.version}</button>{workflowOpen && <div className="workflow-card" role="dialog" aria-label={`Сценарий генерации ${workflow.version}`}><strong>Сценарий генерации {workflow.version}</strong><p>Текст, иллюстрации и проверки готовят разные агенты. Рядом — файл промпта и начало его sha256: по ним видно, какой в точности версией собрана колода.</p><ul>{workflow.agents.map(agent => <li key={agent.file}><span>{agent.role}</span><code>{agent.file}</code>{agent.sha && <em title="Начало sha256 промпта">{agent.sha}</em>}</li>)}</ul>{workflow.latest && <div className="workflow-change"><span>Что изменилось в {workflow.latest.version}</span><p>{workflow.latest.why}</p></div>}</div>}</div>}<IconButton label="Как это работает" onClick={() => setDialog('help')}><CircleHelp size={19} /></IconButton></div>
      </header>

      <main className={`main-content ${screen === 'editor' ? 'editor-main' : ''}`}>
        {storageError && <div className="error-banner" role="alert"><AlertCircle size={18} /><span>Не удалось сохранить изменения в браузере. Скачайте презентацию перед закрытием страницы.</span></div>}
        {screen !== 'editor' && screen !== 'create' && <div className="page-heading"><div><div className="eyebrow">{screen === 'templates' ? 'ВАШ ФИРМЕННЫЙ СТИЛЬ' : screen === 'projects' ? 'РАБОЧЕЕ ПРОСТРАНСТВО' : 'ВАША ПРЕЗЕНТАЦИЯ'}</div><h1>{screen === 'outline' ? 'Сначала — главное' : screen === 'design' ? 'Одна история. Три взгляда.' : screen === 'templates' ? 'Узнаваемый стиль каждого слайда' : 'Мои презентации'}</h1><p>{screen === 'outline' ? 'Проверьте историю, измените текст и расставьте слайды в нужном порядке.' : screen === 'design' ? 'Выберите подачу, которая подходит вашей истории. Содержание останется прежним.' : screen === 'templates' ? 'Три фирменных шаблона из материалов кейса. Или добавьте свой.' : 'Все ваши идеи и последние изменения хранятся в этом браузере.'}</p></div>{screen === 'projects' && <button className="primary-button" onClick={() => navigate('create')}><Plus size={18} />Новая презентация</button>}</div>}

        {(busy === 'outline' || busy === 'layout') && <div className="error-banner progress-banner" role="status"><LoaderCircle size={18} className="spin" /><span>{stage || 'Собираем презентацию'}</span></div>}
        {warnings.map(note => <div className="error-banner warning-banner" role="status" key={note}><AlertCircle size={18} /><span>{note}</span></div>)}
        {error && <div className="error-banner" role="alert"><AlertCircle size={18} /><span>{error}</span><IconButton label="Закрыть сообщение" onClick={() => setError('')}><X size={16} /></IconButton></div>}

        {screen === 'create' && <section className="creation-home">
          <div className="home-title"><div className="home-kicker"><span />Меньше рутины. Больше ваших идей.</div><h1>О чём <span>расскажем?</span></h1><p>Добавьте идею — получите презентацию в фирменном стиле.</p></div>
          <div className={`prompt-composer ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); void readMaterial(e.dataTransfer.files[0]); }}>
            <label className="sr-only" htmlFor="brief">Описание презентации</label>
            <textarea id="brief" ref={briefInput} value={brief.text} maxLength={6000} onChange={e => updateBrief('text', e.target.value)} onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !busy) { e.preventDefault(); void startDeck(); } }} placeholder="Например, питч нового продукта для команды. Какую проблему решаем, в чём идея и что делаем дальше…" aria-invalid={Boolean(error)} />
            {materialName && <div className="attached-material"><FileText size={15} /><span>{materialName}</span><IconButton label="Удалить материалы" onClick={() => { updateBrief('materials', ''); setMaterialName(''); }}><X size={14} /></IconButton></div>}
            <div className="composer-toolbar"><div className="composer-tools"><button className="composer-tool" title="Материалы: TXT, MD, CSV, JSON, PDF, DOCX, PPTX, картинки или ZIP" onClick={() => materialInput.current?.click()}><Paperclip size={18} /><span>Материалы</span></button><button className="composer-tool" onClick={() => setDialog('settings')}><SlidersHorizontal size={17} /><span>Настроить</span></button></div><button className="primary-button create-deck-button" disabled={Boolean(busy)} onClick={() => void startDeck()}>{busy === 'outline' ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={17} />}<span>{busy === 'outline' ? 'Создаём…' : 'Создать презентацию'}</span><ArrowUpRight size={18} /></button></div>
          </div>
          <div className="composer-meta"><span>{brief.slideCount} слайдов <i /> {currentTemplate.name}</span><span>Ctrl + Enter</span></div>
          <div className="starter-prompts"><span>Нужна идея?</span><button onClick={() => updateBrief('text', EXAMPLE_BRIEF)}>Питч продукта<ArrowUpRight size={14} /></button><button onClick={() => updateBrief('text', 'Итоги работы над проектом для команды. Мы подготовили прототип сервиса, обсудили сценарии с пользователями и собрали обратную связь. Расскажите о проделанной работе, найденных сложностях и следующих шагах. Следующий этап — проверить основные сценарии и определить приоритеты разработки.')}>Итоги проекта<ArrowUpRight size={14} /></button><button onClick={() => updateBrief('text', 'Предлагаем запустить внутреннюю базу знаний. Сейчас полезные материалы распределены по разным чатам. Соберём инструкции и ответы на частые вопросы в одном месте. Начнём с пилота в одной команде, получим обратную связь и улучшим поиск. Цель — согласовать пилот и ответственных.')}>Предложить идею<ArrowUpRight size={14} /></button></div>
          <div className="home-fineprint">Вёрстка идёт по дизайн-системе вашего шаблона. Результат можно отредактировать и скачать в PPTX, PDF или HTML.</div>
          {decks.length > 0 && <section className="home-recent"><div><h2>Продолжить работу</h2><button onClick={() => navigate('projects')}>Все презентации<ArrowRight size={14} /></button></div><div className="home-recent-list">{decks.slice(0, 2).map(d => <button key={d.id} onClick={() => void openDeck(d)}><span className="recent-deck-icon"><Presentation size={19} /></span><span><strong>{d.title || 'Без названия'}</strong><small>{d.slides.length} слайдов · {new Date(d.updatedAt).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</small></span><ArrowUpRight size={17} /></button>)}</div></section>}
        </section>}

        {screen === 'outline' && deck && <div className="outline-layout"><section><div className="outline-toolbar"><span><Presentation size={16} />{deck.slides.length} слайдов</span><span>Текст можно редактировать</span></div><div className="outline-list">{deck.slides.map((s, i) => <article className="outline-row" key={s.id}><div className="outline-index"><GripVertical size={16} /><span>{String(i + 1).padStart(2, '0')}</span></div><div className="outline-fields"><label className="sr-only" htmlFor={`title-${s.id}`}>Заголовок слайда {i + 1}</label><input id={`title-${s.id}`} value={s.title} onChange={e => editSlide(s.id, 'title', e.target.value)} placeholder="Заголовок слайда" maxLength={250} /><label className="sr-only" htmlFor={`body-${s.id}`}>Текст слайда {i + 1}</label><textarea id={`body-${s.id}`} value={s.body} onChange={e => editSlide(s.id, 'body', e.target.value)} placeholder="Добавьте ключевые тезисы. Они появятся на слайде." rows={2} maxLength={6000} /></div><div className="outline-actions"><IconButton label={`Поднять слайд ${i + 1}`} disabled={i === 0} onClick={() => moveSlide(i, -1)}><ArrowUp size={15} /></IconButton><IconButton label={`Опустить слайд ${i + 1}`} disabled={i === deck.slides.length - 1} onClick={() => moveSlide(i, 1)}><ArrowDown size={15} /></IconButton><IconButton label={`Удалить слайд ${i + 1}`} disabled={deck.slides.length === 1} onClick={() => removeSlide(s.id)}><Trash2 size={15} /></IconButton></div></article>)}</div><button className="add-slide" disabled={deck.slides.length >= 30} onClick={addSlide}><Plus size={17} />Добавить слайд</button><div className="flow-actions"><button className="secondary-button" onClick={() => navigate('create')}><ArrowLeft size={16} />К брифу</button><button className="primary-button" disabled={Boolean(busy)} onClick={() => void layoutDeck()}>{variants.length ? 'Сверстать заново' : 'Сверстать варианты'}<ArrowRight size={17} /></button></div></section><aside className="outline-aside panel"><div className="section-icon"><Lightbulb size={20} /></div><h3>Один слайд — одна мысль</h3><p>Оставьте в заголовке главное, а в тексте — то, что помогает это объяснить.</p><hr /><span className="eyebrow">ВЫБРАННЫЙ СТИЛЬ</span><TemplateArt template={currentTemplate} compact /><strong>{currentTemplate.name}</strong><div className="inline-note"><AlertCircle size={16} />Структуру собрала модель по брифу и материалам. Проверьте её: дальше по ней идёт вёрстка, и слайды соберутся ровно из этого текста.</div></aside></div>}

        {screen === 'design' && deck && <><div className="design-info"><span><CheckCircle2 size={17} />{deck.slides.length} слайдов с одинаковым содержанием</span><span>Шаблон: {currentTemplate.name}</span></div><div className="design-grid">{layoutOptions.map(option => <button key={option.id} className={`design-card ${deck.layout === option.id ? 'selected' : ''}`} aria-pressed={deck.layout === option.id} disabled={!variants.some(item => item.layout === option.id)} onClick={() => chooseLayout(option.id)}><div className="design-preview"><SlideCanvas slide={deck.slides[0]} template={currentTemplate} layout={option.id} miniature total={deck.slides.length} /></div><div className="design-copy"><div><h2>{option.name}</h2><span className="choice-circle">{deck.layout === option.id && <Check size={15} />}</span></div><p>{option.description}</p><span>{option.detail}</span></div></button>)}</div><div className="design-tip"><Sparkles size={19} /><div><strong>Три варианта уже свёрстаны сервисом</strong><p>Содержание одно, отличается раскладка. Переключайтесь — редактор откроет выбранный.</p></div></div><div className="flow-actions"><button className="secondary-button" onClick={() => navigate('outline')}><ArrowLeft size={16} />К структуре</button><button className="primary-button" onClick={() => { setActiveSlide(0); navigate('editor'); }}>Открыть редактор<ArrowRight size={17} /></button></div></>}

        {screen === 'editor' && deck && slide && <><div className="editor-toolbar"><div className="editor-title"><IconButton label="К моим презентациям" onClick={() => navigate('projects')}><ArrowLeft size={19} /></IconButton><label><span className="sr-only">Название презентации</span><input value={deck.title} onChange={e => updateDeck(d => ({ ...d, title: e.target.value }))} maxLength={120} /></label><span>{deck.slides.length} слайдов</span></div><div className="editor-toolbar-actions"><details className="editor-more"><summary><SlidersHorizontal size={16} />Настроить</summary><div className="editor-more-menu"><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); navigate('outline'); }}><FileText size={16} />Структура слайдов</button><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); navigate('design'); }}><LayoutTemplate size={16} />Варианты оформления</button><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); setAuditOpen(!auditOpen); }}><ShieldCheck size={16} />Проверка слайдов{issues.length > 0 && <span className="issue-count">{issues.length}</span>}</button></div></details><button className="primary-button" onClick={() => setDialog('export')}><Download size={16} />Скачать</button></div></div><div className={`editor-workspace ${auditOpen ? 'with-audit' : ''}`}><aside className="filmstrip"><div className="filmstrip-title"><span>СЛАЙДЫ</span><IconButton label="Добавить слайд" disabled={deck.slides.length >= 30} onClick={addSlide}><Plus size={16} /></IconButton></div>{deck.slides.map((s, i) => <button key={s.id} className={`filmstrip-slide ${i === activeSlide ? 'active' : ''}`} onClick={() => setActiveSlide(i)} aria-label={`Слайд ${i + 1}: ${s.title}`} aria-pressed={i === activeSlide}><span className="filmstrip-number">{i + 1}</span><SlideCanvas slide={s} template={currentTemplate} layout={deck.layout} index={i} total={deck.slides.length} miniature />{issues.some(issue => issue.slideId === s.id) && <span className="slide-warning"><AlertCircle size={12} /></span>}</button>)}<button className="filmstrip-add" onClick={addSlide} disabled={deck.slides.length >= 30}><Plus size={17} />Слайд</button></aside><div className="canvas-workspace"><div className="canvas-topline"><span>{layoutOptions.find(l => l.id === deck.layout)?.name}</span><button className="text-button" onClick={() => setDialog('preview')}><Maximize2 size={15} />Просмотр</button></div><div className="canvas-holder"><SlideCanvas slide={slide} template={currentTemplate} layout={deck.layout} index={activeSlide} total={deck.slides.length} /></div><div className="canvas-pagination"><IconButton label="Предыдущий слайд" disabled={activeSlide === 0} onClick={() => setActiveSlide(activeSlide - 1)}><ChevronLeft size={17} /></IconButton><span>{activeSlide + 1} из {deck.slides.length}</span><IconButton label="Следующий слайд" disabled={activeSlide === deck.slides.length - 1} onClick={() => setActiveSlide(activeSlide + 1)}><ChevronRight size={17} /></IconButton></div><section className="slide-edit-panel"><div className="slide-edit-header"><h2>Содержание слайда</h2><div><IconButton label="Поднять текущий слайд" disabled={activeSlide === 0} onClick={() => moveSlide(activeSlide, -1)}><ArrowUp size={15} /></IconButton><IconButton label="Опустить текущий слайд" disabled={activeSlide === deck.slides.length - 1} onClick={() => moveSlide(activeSlide, 1)}><ArrowDown size={15} /></IconButton><IconButton label="Дублировать слайд" disabled={deck.slides.length >= 30} onClick={() => { updateDeck(d => { const slides = [...d.slides]; slides.splice(activeSlide + 1, 0, { ...slide, id: crypto.randomUUID() }); return { ...d, slides }; }); setActiveSlide(activeSlide + 1); }}><Copy size={15} /></IconButton><IconButton label="Удалить текущий слайд" disabled={deck.slides.length <= 1} onClick={() => removeSlide(slide.id)}><Trash2 size={15} /></IconButton></div></div><label>Заголовок<input value={slide.title} onChange={e => editSlide(slide.id, 'title', e.target.value)} onBlur={() => void saveSlide(activeSlide)} maxLength={250} /></label><label>Основной текст<textarea value={slide.body} onChange={e => editSlide(slide.id, 'body', e.target.value)} onBlur={() => void saveSlide(activeSlide)} placeholder="Тезисы, по одному в строке" rows={4} maxLength={6000} /></label><div className="editor-layout-select"><label htmlFor="editor-layout">Оформление всей презентации</label><select id="editor-layout" value={deck.layout} onChange={e => updateDeck(d => ({ ...d, layout: e.target.value as Layout }))}>{layoutOptions.map(l => <option value={l.id} key={l.id}>{l.name}</option>)}</select></div></section></div>{auditOpen && <aside className="audit-panel"><div className="audit-heading"><ShieldCheck size={20} /><h2>Проверка слайдов</h2><IconButton label="Закрыть проверку" onClick={() => setAuditOpen(false)}><PanelLeftClose size={17} /></IconButton></div>{project?.file && <p className="audit-file-note">{project.file.opens ? `Файл открывается: ${project.file.slides} слайдов, ${project.file.native_objects} редактируемых объектов${project.file.raster_slides.length ? `, из них картинками: ${project.file.raster_slides.length}` : ''}` : 'Файл не открывается — причина в замечаниях ниже'}</p>}<p className="audit-description">Правила проверяют геометрию, длину текста и повторы сразу. Модель можно позвать отдельно: по тексту или по картинке слайда.</p><div className="audit-actions"><button className="secondary-button" disabled={Boolean(busy)} onClick={() => void runAudit('contextual')}>{busy === 'contextual' ? <LoaderCircle className="spin" size={15} /> : <FileText size={15} />}Проверить содержание</button><button className="secondary-button" disabled={Boolean(busy)} onClick={() => void runAudit('visual')}>{busy === 'visual' ? <LoaderCircle className="spin" size={15} /> : <Eye size={15} />}Проверить по изображению</button></div><div className={`audit-summary ${issues.length ? 'has-issues' : ''}`}>{issues.length ? <AlertCircle size={22} /> : <CheckCircle2 size={24} />}<div><strong>{issues.length ? `${issues.length} замечаний` : 'Всё в порядке'}</strong><span>{issues.length ? 'Проверьте перед экспортом' : 'По доступным проверкам'}</span></div></div>{issues.map(issue => <button className={`audit-item ${slide.id === issue.slideId ? 'active' : ''}`} key={issue.id} onClick={() => setActiveSlide(deck.slides.findIndex(s => s.id === issue.slideId))}><span className="audit-slide-label">Слайд {deck.slides.findIndex(s => s.id === issue.slideId) + 1}<ArrowUpRight size={14} /></span><strong>{issue.title}</strong><p>{issue.description}</p>{issue.origin !== 'rule' && <span className="audit-origin">{issue.origin === 'image' ? 'Модель, по изображению' : 'Модель, по тексту'}</span>}{issue.fixable && <span className="audit-fix" role="button" tabIndex={0} onClick={event => { event.stopPropagation(); void fixIssues([issue.id]); }} onKeyDown={event => { if (event.key === 'Enter') { event.stopPropagation(); void fixIssues([issue.id]); } }}>Исправить</span>}<span className={`audit-severity ${issue.severity}`}>{issue.severity === 'error' ? 'Нужно исправить' : 'Рекомендуем проверить'}</span></button>)}<div className="audit-note"><CircleHelp size={16} /><p>Проверка фактов, контраста и пересечений объектов потребует серверного аудита.</p></div></aside>}</div></>}

        {screen === 'templates' && <><div className="library-toolbar"><span>{allTemplates.length} шаблона · формат 16:9</span><button className="primary-button" disabled={Boolean(busy)} onClick={() => templateInput.current?.click()}>{busy === 'template' ? <LoaderCircle size={17} className="spin" /> : <Upload size={17} />}Загрузить PPTX</button></div>{templateCards(true)}<div className="library-disclosure"><FileUp size={22} /><div><h3>Есть свой фирменный шаблон?</h3><p>Добавьте PPTX до 50 МБ. Демоверсия извлечёт палитру, шрифт и количество макетов. Полный перенос композиции и графики требует бэкенда.</p></div><button className="secondary-button" onClick={() => navigate('create')}>Создать презентацию<ArrowRight size={16} /></button></div></>}

        {screen === 'projects' && <><div className="projects-toolbar"><label className="search-field"><Search size={17} /><input placeholder="Найти презентацию" value={projectSearch} onChange={e => setProjectSearch(e.target.value)} /></label><span><Clock3 size={15} />Сначала последние</span></div>{decks.filter(d => d.title.toLowerCase().includes(projectSearch.toLowerCase())).length === 0 ? <div className="empty-state"><span><Presentation size={34} /></span><h2>{projectSearch ? 'Ничего не нашлось' : 'Здесь будут ваши презентации'}</h2><p>{projectSearch ? 'Попробуйте другое название или очистите поиск.' : 'Начните с идеи. Мы сохраним результат в этом браузере.'}</p><button className="primary-button" onClick={() => projectSearch ? setProjectSearch('') : navigate('create')}>{projectSearch ? 'Очистить поиск' : 'Создать первую презентацию'}<ArrowRight size={16} /></button></div> : <div className="projects-grid">{decks.filter(d => d.title.toLowerCase().includes(projectSearch.toLowerCase())).map(d => <article className="project-card" key={d.id}><button className="project-open" onClick={() => void openDeck(d)} aria-label={`Открыть ${d.title}`}><SlideCanvas slide={d.slides[0]} template={allTemplates.find(t => t.id === d.templateId) || templates[0]} layout={d.layout} miniature total={d.slides.length} /></button><div className="project-info"><h2>{d.title || 'Без названия'}</h2><div><span>{d.slides.length} слайдов · {new Date(d.updatedAt).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</span><IconButton label={`Удалить презентацию ${d.title}`} onClick={() => setDeleteId(d.id)}><Trash2 size={16} /></IconButton></div></div></article>)}</div>}</>}
      </main>
      {screen !== 'editor' && <footer className="page-footer"><span>Создано для идей, которые стоит показать</span><span>Слайд · ЛЦТ 2026</span></footer>}
    </div>

    <input ref={materialInput} className="sr-only" type="file" accept=".txt,.md,.csv,.json,.pdf,.docx,.pptx,.zip,.svg,.png,.jpg,.jpeg" onChange={e => { void readMaterial(e.target.files?.[0]); e.target.value = ''; }} aria-label="Загрузить текстовые материалы" />
    <input type="file" ref={templateInput} className="sr-only" accept=".pptx" onChange={e => void uploadTemplate(e.target.files?.[0])} aria-label="Загрузить шаблон PPTX" />
    {toast && <div className="toast" role="status"><CheckCircle2 size={18} /><span>{toast}</span><IconButton label="Скрыть уведомление" onClick={() => setToast('')}><X size={15} /></IconButton></div>}
    {dialog === 'settings' && <Modal title="Пара настроек — и готово" onClose={() => setDialog(null)} wide>
      <div className="settings-content"><section><div className="settings-label"><h3>Фирменный стиль</h3><button className="text-button" disabled={Boolean(busy)} onClick={() => templateInput.current?.click()}>{busy === 'template' ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}Загрузить свой</button></div>{templateCards()}<p className="settings-hint">PPTX до 50 МБ. В демо импортируются цвета и шрифт.</p></section>
      <div className="settings-row"><label htmlFor="slide-count">Количество слайдов</label><div className="amount-control"><IconButton label="Уменьшить число слайдов" disabled={brief.slideCount <= 3} onClick={() => updateBrief('slideCount', brief.slideCount - 1)}>−</IconButton><input id="slide-count" type="number" min={3} max={20} value={brief.slideCount} onChange={e => updateBrief('slideCount', Math.max(3, Math.min(20, Number(e.target.value) || 3)))} /><IconButton label="Увеличить число слайдов" disabled={brief.slideCount >= 20} onClick={() => updateBrief('slideCount', brief.slideCount + 1)}><Plus size={16} /></IconButton></div></div>
      <div className="brief-selects"><label>Для кого<select value={brief.audience} onChange={e => updateBrief('audience', e.target.value)}><option>Коллеги и команда</option><option>Руководство</option><option>Клиенты и партнёры</option><option>Эксперты и жюри</option><option>Студенты</option></select></label><label>Задача презентации<select value={brief.goal} onChange={e => updateBrief('goal', e.target.value)}><option>Представить идею</option><option>Показать результаты</option><option>Убедить и получить поддержку</option><option>Объяснить и обучить</option></select></label></div>
      {error && <div className="error-banner" role="alert"><AlertCircle size={16} />{error}</div>}
      <button className="primary-button full-width" onClick={() => setDialog(null)}>Готово<Check size={17} /></button></div>
    </Modal>}
    {dialog === 'help' && <Modal title="От идеи до готовой презентации" onClose={() => setDialog(null)}><div className="help-steps">{[{ title: 'Опишите идею', body: 'Добавьте основные тезисы, выберите аудиторию и фирменный шаблон. Для быстрого старта воспользуйтесь примером.' }, { title: 'Нажмите «Создать презентацию»', body: 'Откроется готовая презентация. Стиль и количество слайдов подберёт стандартный сценарий; их можно изменить заранее в настройках.' }, { title: 'Скачайте или доработайте', body: 'Редактируйте текст прямо в редакторе. Структура, три варианта оформления и проверка доступны через «Настроить». Скачать можно PPTX, PDF или веб-презентацию одним файлом.' }].map((item, i) => <div key={item.title}><span>{i + 1}</span><section><h3>{item.title}</h3><p>{item.body}</p></section></div>)}</div><div className="modal-note"><Sparkles size={19} /><p><strong>Колоду собирает сервис, а не браузер.</strong> Структуру и текст пишет модель по брифу и материалам, вёрстка идёт по дизайн-системе вашего шаблона, а перед выдачей слайды проходят проверку. Поэтому на экране ровно то, что уедет в PPTX.</p></div><button className="primary-button full-width" onClick={() => setDialog(null)}>Всё понятно<Check size={17} /></button></Modal>}
    {dialog === 'export' && deck && <Modal title="Презентация готова к выходу" onClose={() => setDialog(null)}><p className="modal-subtitle">{deck.slides.length} слайдов · {currentTemplate.name}</p>{issues.length > 0 && <div className="export-warning"><AlertCircle size={18} /><span>В презентации есть замечания: {issues.length}.</span><button onClick={() => { setDialog(null); setAuditOpen(true); }}>Посмотреть</button></div>}<div className="export-options"><button onClick={() => void download('pptx')} disabled={Boolean(busy)}><span className="export-file pptx"><Presentation size={24} /></span><span><strong>PowerPoint <small>.pptx</small></strong><p>Редактируемые заголовки, текст и фигуры</p></span>{busy === 'pptx' ? <LoaderCircle className="spin" size={19} /> : <Download size={19} />}</button><button onClick={() => void download('pdf')} disabled={Boolean(busy)}><span className="export-file pdf"><FileText size={24} /></span><span><strong>PDF <small>.pdf</small></strong><p>Та же вёрстка, готовая к рассылке</p></span>{busy === 'pdf' ? <LoaderCircle className="spin" size={19} /> : <Download size={19} />}</button><button onClick={() => void download('html')} disabled={Boolean(busy)}><span className="export-file html"><Monitor size={24} /></span><span><strong>Веб-презентация <small>.html</small></strong><p>Один файл, открывается в любом браузере</p></span><Download size={19} /></button></div><p className="export-disclosure">Файлы собирает сервис из исходного шаблона: заголовки, текст, таблицы и диаграммы остаются редактируемыми объектами, слайдов-картинок нет.</p></Modal>}
    {dialog === 'preview' && deck && slide && <Modal title={`Слайд ${activeSlide + 1} из ${deck.slides.length}`} onClose={() => setDialog(null)} wide>{(() => { const found = issues.filter(i => i.slideId === slide.id); const boxed = found.filter(i => i.boxed).length; return <div className="preview-toolbar"><label className="preview-toggle"><input type="checkbox" checked={previewHighlight} onChange={e => setPreviewHighlight(e.target.checked)} />Показать замечания</label><span className={`preview-count ${found.length ? 'has-issues' : ''}`}>{previewBusy ? <><LoaderCircle className="spin" size={14} />Рисуем слайд…</> : found.length ? <><AlertCircle size={14} />{found.length} {issueWord(found.length)} на слайде{previewHighlight && !boxed ? ' — без привязки к месту, текст в панели проверки' : ''}</> : <><CheckCircle2 size={14} />Замечаний на слайде нет</>}</span></div>; })()}{previewUrl ? <img className="preview-frame" src={previewUrl} alt={`Слайд ${activeSlide + 1}`} /> : <SlideCanvas slide={slide} template={currentTemplate} layout={deck.layout} index={activeSlide} total={deck.slides.length} />}<div className="preview-navigation"><button className="secondary-button" disabled={activeSlide === 0} onClick={() => setActiveSlide(activeSlide - 1)}><ChevronLeft size={17} />Назад</button><button className="secondary-button" disabled={activeSlide === deck.slides.length - 1} onClick={() => setActiveSlide(activeSlide + 1)}>Далее<ChevronRight size={17} /></button></div></Modal>}
    {deleteId && <Modal title="Удалить презентацию?" onClose={() => setDeleteId(null)}><p className="modal-subtitle">Она исчезнет из этого браузера. Скачанные файлы сохранятся.</p><div className="flow-actions"><button className="secondary-button" onClick={() => setDeleteId(null)}>Оставить</button><button className="danger-button" onClick={() => { setDecks(prev => prev.filter(d => d.id !== deleteId)); if (deck?.id === deleteId) setDeck(null); setDeleteId(null); setToast('Презентация удалена'); }}>Удалить</button></div></Modal>}
  </div>;
}
