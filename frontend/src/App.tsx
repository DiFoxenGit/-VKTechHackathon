import { ImageGenerationStatus } from './components/ImageGenerationStatus';
import { ImageOptions } from './components/ImageOptions';
import { BusinessControls } from './components/BusinessControls';
import { analysisForSlide } from './business';
import { memo, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, ChevronLeft, ChevronRight, CircleHelp, Clock3, Copy, Download, FileText, FolderOpen, GripVertical, LayoutTemplate, LoaderCircle, Maximize2, Monitor, PanelLeftClose, Paperclip, Plus, Presentation, Search, ShieldCheck, Sparkles, Trash2, Upload, X, AlertCircle, CheckCircle2, ArrowUpRight, Lightbulb, FileUp, SlidersHorizontal } from 'lucide-react';
import type { Brief, Deck, Layout, Slide, Template } from './types';
import { templates, EXAMPLE_BRIEF } from './data/templates';
import { auditDeck } from './algorithms/audit';
import { getSlideTypography } from './algorithms/typography';
import { exportHtml, exportPptx, exportPrint } from './rendering/export';
import { presentationService } from './services/presentationService';
import type { ServiceProgress } from './services/presentationService';
import { OperationProgress } from './components/OperationProgress';
import { readSaved, STORAGE_KEY, DEFAULT_BRIEF } from './storage';
import type { Saved } from './storage';
import { visualMarkup, visualStyles } from './analytics';
import type { AnalysisResult } from './analytics';
import { AnalysisPanel } from './components/AnalysisPanel';
import { AnalysisControls } from './components/AnalysisControls';
import { countFromText, explicitSlideCount, slideCountIssue } from './algorithms/slideCount';
import { slideCountText } from './locales/slideCount';
import { MaterialCard } from './components/MaterialCard';
import { ServerSlidePreview } from './components/ServerSlidePreview';
import { ModelGenerationStatus } from './components/ModelGenerationStatus';

type Screen = 'create' | 'outline' | 'design' | 'editor' | 'projects' | 'templates';
type Operation = 'save' | 'generation' | 'material' | 'template' | 'pptx' | 'pdf' | 'html';

function slideCountLabel(count: number) {
  const lastTwo = count % 100;
  const last = count % 10;
  const word = lastTwo >= 11 && lastTwo <= 14 ? 'слайдов' : last === 1 ? 'слайд' : last >= 2 && last <= 4 ? 'слайда' : 'слайдов';
  return `${count} ${word}`;
}

function SlideCountHint({text, count, onUseText}: {text: string; count: number; onUseText: () => void}) {
  const issue = slideCountIssue(text, count);
  let specified: number | undefined;
  try { specified = explicitSlideCount(text); } catch { /* The issue is rendered below. */ }
  return <div id="slide-count-hint" className={`slide-count-hint ${issue ? 'is-error' : ''}`} aria-live="polite">
    {issue || (specified !== undefined ? slideCountText.ru.sync : '')}
    {issue && specified !== undefined && <button type="button" className="text-button" onClick={onUseText}>{slideCountText.ru.useText}</button>}
  </div>;
}

function IconButton({ children, label, ...props }: { children: ReactNode; label: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className="icon-button" title={label} aria-label={label} {...props}>{children}</button>;
}

function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => { const el = ref.current; el?.showModal(); return () => { el?.close(); }; }, []);
  return <dialog ref={ref} aria-labelledby={titleId} className={`modal ${wide ? 'wide' : ''}`} onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="modal-heading"><h2 id={titleId}>{title}</h2><IconButton label="Закрыть" onClick={onClose}><X size={20} /></IconButton></div>
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

const SlideCanvas = memo(function SlideCanvas({ slide, template, layout, index = 0, total = 10, miniature = false }: { slide: Slide; template: Template; layout: Layout; index?: number; total?: number; miniature?: boolean }) {
  const typography = getSlideTypography(slide, template, layout);
  if (slide.previewUrl) return <ServerSlidePreview url={slide.previewUrl} title={slide.title} miniature={miniature}/>;
  if (slide.visual) return <div className={`slide-canvas analytic-canvas ${miniature ? 'miniature' : ''}`} style={{'--slide-color':template.color,fontFamily:`${template.font}, Arial, sans-serif`} as CSSProperties}><header>{template.name}</header><h3>{slide.title}</h3><div className="data-visual" dangerouslySetInnerHTML={{__html:visualMarkup(slide.visual,template.color)}} /><p className="data-source">Источник: {slide.visual.source || slide.sourceRefs?.join(', ') || 'Материалы пользователя'}</p><footer>{slide.body} <span>{index+1} / {total}</span></footer></div>;
  return <div className={`slide-canvas layout-${layout} ${slide.kind === 'cover' ? 'is-cover' : ''} ${miniature ? 'miniature' : ''}`} style={{ '--slide-color': template.color, '--slide-secondary': template.secondary, '--title-size': `${typography.title}cqw`, '--body-size': `${typography.body}cqw`, fontFamily: `${template.font}, Arial, sans-serif` } as CSSProperties}>
    <div className="slide-brand"><span className="vk-mark">{template.custom ? 's' : 'vk'}</span><span>{template.name.replace('VK ', '')}</span></div>
    <div className="slide-content"><div className="slide-eyebrow">{slide.kind === 'cover' ? 'ИДЕИ, КОТОРЫЕ ОБЪЕДИНЯЮТ' : `ЧАСТЬ ${String(index).padStart(2, '0')}`}</div><h3>{slide.title || 'Название слайда'}</h3>{slide.body && <p>{slide.body}</p>}</div>
    <div className="slide-accent" aria-hidden="true"><div /><div /><div /></div>
    <div className="slide-bottom"><span>{template.name} · Презентация</span><span>{String(index + 1).padStart(2, '0')} / {String(total).padStart(2, '0')}</span></div>
  </div>;
});

const layoutOptions: { id: Layout; name: string; description: string; detail: string }[] = [
  { id: 'classic', name: 'Классический', description: 'Чёткая структура и спокойный ритм', detail: 'Для отчётов и деловых встреч' },
  { id: 'story', name: 'Выразительный', description: 'Контрастные акценты и крупный текст', detail: 'Для выступлений и новых идей' },
  { id: 'focus', name: 'Минималистичный', description: 'Больше воздуха, фокус на главном', detail: 'Для питчей и коротких историй' },
];

export default function App() {
  const [initial] = useState(readSaved);
  const [brief, setBrief] = useState<Brief>(() => countFromText(initial.brief));
  const [decks, setDecks] = useState<Deck[]>(initial.decks);
  const [customTemplates, setCustomTemplates] = useState<Template[]>(initial.customTemplates);
  const [remoteTemplates, setRemoteTemplates] = useState<Template[]>([]);
  const [screen, setScreen] = useState<Screen>('create');
  const [deck, setDeck] = useState<Deck | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);
  const [busy, setBusy] = useState<Operation | null>(null);
  const [progress, setProgress] = useState<ServiceProgress>({ stage: 'preparing' });
  const [startedAt, setStartedAt] = useState(0);
  const operationRef = useRef<AbortController | null>(null);
  const briefContextRef = useRef(0);
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const [readyDeck, setReadyDeck] = useState<Deck | null>(null);
  const [connection, setConnection] = useState<'loading' | 'ready' | 'error'>('loading');
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [generationRetry, setGenerationRetry] = useState<'create' | 'model' | null>(null);
  const [briefError, setBriefError] = useState('');
  const [exportError, setExportError] = useState('');
  const [storageError, setStorageError] = useState(false);
  const [toast, setToast] = useState('');
  const [dialog, setDialog] = useState<'help' | 'export' | 'preview' | 'settings' | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [materialName, setMaterialName] = useState(initial.brief.materialName || (initial.brief.materials || initial.brief.contentPackIds?.length ? 'Сохранённые материалы' : ''));
  const [removedSlide, setRemovedSlide] = useState<{ deckId: string; slide: Slide; index: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [projectSearch, setProjectSearch] = useState('');
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const materialInput = useRef<HTMLInputElement>(null);
  const templateInput = useRef<HTMLInputElement>(null);
  const brandbookInput = useRef<HTMLInputElement>(null);
  const [analysisPreview, setAnalysisPreview] = useState<AnalysisResult[]>([]);
  const briefInput = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { setAnalysisPreview([]); }, [brief.text, brief.business, brief.materialFiles, brief.contentPackIds]);
  const allTemplates = useMemo(() => {
    const merged = remoteTemplates.length ? [...remoteTemplates, ...customTemplates] : [...customTemplates, ...templates];
    return merged.filter((template, index) => merged.findIndex(item => item.id === template.id) === index);
  }, [customTemplates, remoteTemplates]);
  const currentTemplateBase = allTemplates.find(t => t.id === (deck && ['outline', 'design', 'editor'].includes(screen) ? deck.templateId : brief.templateId)) || templates[0];
  const activeBrandbook = deck && ['outline','design','editor'].includes(screen) ? deck.brief?.brandbook : brief.brandbook;
  const currentTemplate = activeBrandbook ? {...currentTemplateBase,color:activeBrandbook.tokens.colors?.[0] ? '#'+activeBrandbook.tokens.colors[0].replace(/^#/,'') : currentTemplateBase.color,font:activeBrandbook.tokens.font || currentTemplateBase.font} : currentTemplateBase;
  const issues = useMemo(() => deck ? [...auditDeck(deck), ...(deck.remote ? deck.serverIssues || [] : [])] : [], [deck]);
  const slide = deck?.slides[Math.min(activeSlide, deck.slides.length - 1)];

  const savedRef = useRef<Saved>({ brief, decks, customTemplates });
  savedRef.current = { brief, decks, customTemplates };
  useEffect(() => {
    setSaving(true);
    const timer = window.setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRef.current)); setStorageError(false); }
      catch { setStorageError(true); }
      setSaving(false);
    }, 600);
    return () => clearTimeout(timer);
  }, [brief, decks, customTemplates]);
  useEffect(() => {
    const flush = () => {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRef.current)); }
      catch { setStorageError(true); }
    };
    const onVisibility = () => { if (document.visibilityState === 'hidden') flush(); };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', onVisibility);
      operationRef.current?.abort();
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setConnection('loading');
    void presentationService.listTemplates({ signal: controller.signal }).then(items => {
      if (controller.signal.aborted) return;
      if (!items.length) { setConnection('error'); return; }
      setRemoteTemplates(items);
      setConnection('ready');
      setBrief(prev => {
        if (items.some(item => item.id === prev.templateId) || savedRef.current.customTemplates.some(item => item.id === prev.templateId)) return prev;
        const legacy = templates.find(item => item.id === prev.templateId);
        const matching = items.find(item => item.name === legacy?.name) || items[0];
        return matching ? { ...prev, templateId: matching.id } : prev;
      });
    }).catch(() => {
      if (!controller.signal.aborted) setConnection('error');
    });
    return () => controller.abort();
  }, [connectionAttempt]);
  useEffect(() => {
    if (!deck) return;
    setDecks(prev => [deck, ...prev.filter(d => d.id !== deck.id)]);
  }, [deck]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 4500); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => { setError(''); window.scrollTo({ top: 0 }); }, [screen]);
  useEffect(() => {
    if (dialog !== 'preview' || !deck) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault();
        setActiveSlide(index => Math.max(0, Math.min(deck.slides.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1))));
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dialog, deck?.slides.length]);

  function navigate(next: Screen) { setScreen(next); setAuditOpen(false); }
  function newPresentation() {
    briefContextRef.current++;
    if (busy === 'material' || busy === 'template') cancelOperation();
    setBrief(prev => ({ ...DEFAULT_BRIEF, templateId: prev.templateId, slideCount: prev.slideCount }));
    setMaterialName(''); setBriefError(''); navigate('create');
    window.requestAnimationFrame(() => briefInput.current?.focus());
  }
  function openDeck(saved: Deck) {
    briefContextRef.current++;
    if (busy === 'material' || busy === 'template') cancelOperation();
    setDeck(saved); setActiveSlide(0); setRemovedSlide(null); setReadyDeck(null);
    const source = saved.brief || { ...DEFAULT_BRIEF, text: saved.slides.map(s => `${s.title}\n${s.body}`).join('\n\n'), slideCount: saved.slides.length, templateId: saved.templateId };
    setBrief(countFromText(source)); setMaterialName(source.materialName || (source.materials || source.contentPackIds?.length ? 'Сохранённые материалы' : ''));
    navigate('editor');
  }
  function updateBrief<K extends keyof Brief>(key: K, value: Brief[K]) {
    setBrief(prev => key === 'text' ? countFromText({ ...prev, [key]: value }) : { ...prev, [key]: value });
    if (key === 'text' || key === 'slideCount') { setError(''); setBriefError(''); }
  }
  function updateDeck(updater: (prev: Deck) => Deck) { setDeck(prev => {
    if (!prev) return prev;
    const next = updater(prev);
    return {...next, variantPreviews:undefined, slides:next.slides.map(s=>({...s,previewUrl:undefined})), updatedAt:new Date().toISOString(), remote:false};
  }); }
  async function saveDeck(next = deck) {
    if (!next?.revision) return;
    const controller=beginOperation('save'); if(!controller)return;
    try {const saved=await presentationService.save(next,operationOptions(controller)); if(!controller.signal.aborted){setDeck(saved);setToast('Сохранено. Предпросмотр соответствует файлу экспорта');}}
    catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'Не удалось сохранить');}
    finally{finishOperation(controller);}
  }
  async function retryIllustration() {
    if (!deck?.revision || !deck.remote) return;
    const controller = beginOperation('save'); if (!controller) return;
    try {
      const saved = await presentationService.retryIllustration(deck, operationOptions(controller));
      if (!controller.signal.aborted) {setDeck(saved);if(saved.imageGeneration?.status==='ready')setToast(saved.imageGeneration.message);}
    } catch(e) {if(!controller.signal.aborted)setError(e instanceof Error ? e.message : 'Не удалось создать иллюстрацию');}
    finally {finishOperation(controller);}
  }
  async function changeLayout(layout: Layout) {
    if(!deck || busy)return;
    const next={...deck,layout,remote:false,slides:deck.slides.map(s=>({...s,previewUrl:undefined}))};
    setDeck(next);
    if(next.revision)await saveDeck(next);
  }
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
    const index = deck.slides.findIndex(s => s.id === id);
    if (index < 0) return;
    setRemovedSlide({ deckId: deck.id, slide: deck.slides[index], index });
    updateDeck(d => ({ ...d, slides: d.slides.filter(s => s.id !== id) }));
    setActiveSlide(prev => Math.max(0, Math.min(prev > index ? prev - 1 : prev, deck.slides.length - 2)));
  }
  function restoreSlide() {
    if (!removedSlide || removedSlide.deckId !== deck?.id || deck.slides.length >= 30) return;
    updateDeck(d => { const slides = [...d.slides]; slides.splice(removedSlide.index, 0, removedSlide.slide); return { ...d, slides }; });
    setActiveSlide(removedSlide.index); setRemovedSlide(null);
  }
  function beginOperation(kind: Operation) {
    if (operationRef.current) return null;
    const controller = new AbortController();
    operationRef.current = controller;
    setBusy(kind); setProgress({ stage: kind === 'generation' ? 'preparing' : kind === 'material' || kind === 'template' ? 'uploading' : 'preparing' });
    setStartedAt(Date.now()); setError(''); setGenerationRetry(null);
    return controller;
  }
  function operationOptions(controller: AbortController) {
    return { signal: controller.signal, onProgress: (event: ServiceProgress) => { if (operationRef.current === controller) setProgress(event); } };
  }
  function finishOperation(controller: AbortController) {
    if (operationRef.current !== controller) return;
    operationRef.current = null; setBusy(null);
  }
  function cancelOperation() {
    const controller = operationRef.current;
    if (!controller) return;
    controller.abort(); finishOperation(controller);
    setToast(busy === 'generation' ? 'Ожидание прекращено. Ваш бриф сохранён; задание на сервере может продолжиться.' : 'Загрузка отменена. Можно попробовать ещё раз.');
  }
  async function startDeck() {
    const countIssue = slideCountIssue(brief.text, brief.slideCount);
    if (countIssue) { setBriefError(countIssue); briefInput.current?.focus(); return; }
    if (brief.text.trim().length < 20) { setBriefError('Добавьте хотя бы 20 символов: тему и несколько тезисов.'); briefInput.current?.focus(); return; }
    if (connection !== 'ready') return;
    const controller = beginOperation('generation');
    if (!controller) return;
    const briefContext = briefContextRef.current;
    setBriefError(''); setReadyDeck(null);
    try {
      const result = await presentationService.generate({ ...brief, templateId: currentTemplate.id }, currentTemplate.id, operationOptions(controller));
      if (controller.signal.aborted) return;
      setDecks(prev => [result, ...prev.filter(d => d.id !== result.id)]);
      if (screenRef.current === 'create' && briefContextRef.current === briefContext) { setDeck(result); setActiveSlide(0); navigate('editor'); setToast('Презентация готова. Можно редактировать и скачивать.'); }
      else setReadyDeck(result);
    } catch (e) { if (!controller.signal.aborted) { setError(`${e instanceof Error ? e.message : 'Не удалось создать презентацию.'} Ваш бриф сохранён — попробуйте ещё раз.`); setGenerationRetry('create'); } }
    finally { finishOperation(controller); }
  }
  async function retryModel() {
    if (!deck?.brief || operationRef.current) return;
    const previous = deck;
    const controller = beginOperation('generation');
    if (!controller) return;
    const briefContext = briefContextRef.current;
    try {
      const result = await presentationService.generate(previous.brief!, previous.templateId, operationOptions(controller));
      if (controller.signal.aborted) return;
      setDecks(prev => [result, ...prev.filter(d => d.id !== result.id)]);
      if (screenRef.current === 'editor' && briefContextRef.current === briefContext) {
        setDeck(result); setActiveSlide(0);
        setToast('Создана новая презентация. Предыдущая версия сохранена в проектах.');
      } else setReadyDeck(result);
    } catch (e) {
      if (!controller.signal.aborted) { setError(`${e instanceof Error ? e.message : 'Не удалось повторить запрос модели.'} Предыдущая презентация сохранена.`); setGenerationRetry('model'); }
    } finally { finishOperation(controller); }
  }
  async function readMaterial(file?: File) {
    if (!file) return;
    if (operationRef.current) return;
    if (!/\.(txt|md|csv|xlsx|json|docx|pptx|pdf|zip)$/i.test(file.name)) { setError('Поддерживаются TXT, MD, CSV, XLSX, JSON, DOCX, PPTX, PDF и ZIP.'); return; }
    if (!file.size) { setError('Файл пуст. Выберите файл с материалами.'); return; }
    if (file.size > 50 * 1024 * 1024) { setError('Выберите файл до 50 МБ.'); return; }
    const controller = beginOperation('material');
    if (!controller) return;
    try {
      const pack = await presentationService.uploadContent(file, operationOptions(controller));
      if (controller.signal.aborted) return;
      const material={id:pack.id,name:pack.name,text:pack.text,sizeBytes:file.size,file_report:pack.file_report,sourceHash:pack.sha256,rowCount:pack.datasets?.reduce((n,t)=>n+t.rows.length,0),tableCount:pack.datasets?.length};
      setBrief(prev => (prev.contentPackIds?.includes(pack.id) || prev.materialFiles?.some(f=>f.sourceHash && f.sourceHash===pack.sha256)) ? prev : ({ ...prev, materials: [prev.materials,pack.text].filter(Boolean).join('\n\n'), materialName: pack.name, contentPackIds: [...(prev.contentPackIds || []),pack.id],materialFiles:[...(prev.materialFiles || []),material] }));
      setAnalysisPreview([]);
      setMaterialName(pack.name); setError(''); setToast('Материалы загружены на сервер');
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Не удалось прочитать файл. Попробуйте ещё раз.'); }
    finally { finishOperation(controller); }
  }
  async function readMaterials(files: File[]) {
    if ((brief.contentPackIds?.length || 0) + files.length > 10) {setError('Можно добавить до 10 материалов. Удалите лишние файлы или объедините их в ZIP.');return;}
    for (const file of files) await readMaterial(file);
  }
  async function readBrandbook(file?: File) {
    if (!file) return;
    if (!file.size || file.size>50*1024*1024) {setError('Выберите непустой брендбук до 50 МБ.');return;}
    const controller=beginOperation('material');if(!controller)return;
    try {const brandbook=await presentationService.uploadBrandbook(file,operationOptions(controller));if(!controller.signal.aborted){setBrief(prev=>({...prev,brandbook}));setToast('Брендбук загружен');}}
    catch(error){if(!controller.signal.aborted)setError(error instanceof Error?error.message:'Не удалось загрузить брендбук');}
    finally{finishOperation(controller);}
  }
  async function previewAnalysis() {
    const controller=beginOperation('material');if(!controller)return;
    setAnalysisPreview([]);
    try {const {items}=await presentationService.analyseMaterials(brief,operationOptions(controller));if(!controller.signal.aborted){setAnalysisPreview(items);if(!items.length)setToast('В материалах не найдены структурированные таблицы');}}
    catch(error){if(!controller.signal.aborted)setError(error instanceof Error?error.message:'Не удалось проанализировать данные');}
    finally{finishOperation(controller);}
  }
  async function uploadTemplate(file?: File) {
    if (!file) return;
    if (operationRef.current) return;
    if (!/\.pptx$/i.test(file.name) || !file.size || file.size > 50 * 1024 * 1024) { setError('Выберите непустой PPTX-файл до 50 МБ.'); if (templateInput.current) templateInput.current.value = ''; return; }
    const controller = beginOperation('template');
    if (!controller) return;
    try {
      const t = await presentationService.uploadTemplate(file, operationOptions(controller));
      if (controller.signal.aborted) return;
      setCustomTemplates(prev => [...prev.filter(existing => existing.id !== t.id), { ...t, custom: true }]); updateBrief('templateId', t.id); setToast('Шаблон добавлен: извлечены цвета, шрифт и число макетов'); setError('');
      setConnection('ready');
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Не удалось открыть шаблон. Проверьте PPTX-файл.'); }
    finally { finishOperation(controller); if (templateInput.current) templateInput.current.value = ''; }
  }
  async function download(format: 'pptx' | 'html' | 'pdf') {
    if (!deck) return;
    const controller = beginOperation(format);
    if (!controller) return;
    setExportError('');
    try {
      if (deck.revision) {
        const saved=deck.remote ? deck : await presentationService.save(deck,operationOptions(controller));
        if(!controller.signal.aborted)setDeck(saved);
        await presentationService.download(saved,format,operationOptions(controller));
      } else if (deck.remote) await presentationService.download(deck, format, operationOptions(controller));
      else if (format === 'pptx') await exportPptx(deck, currentTemplate);
      else if (format === 'html') await exportHtml(deck, currentTemplate);
      else await exportPrint(deck, currentTemplate);
      if (!controller.signal.aborted) setToast(format === 'pdf' && !deck.remote && !deck.revision ? 'В окне печати выберите «Сохранить как PDF»' : 'Файл готов — проверьте загрузки браузера');
    } catch (e) { if (!controller.signal.aborted) setExportError(e instanceof Error ? e.message : 'Не удалось создать файл. Попробуйте ещё раз.'); }
    finally { finishOperation(controller); }
  }

  function templateCards(library = false) {
    return <div className={library ? 'template-library' : 'template-grid'}>{allTemplates.map(t => <button key={t.id} type="button" className={`template-card ${brief.templateId === t.id ? 'selected' : ''}`} onClick={() => { updateBrief('templateId', t.id); if (library) setToast(`Выбран шаблон ${t.name}`); }} aria-pressed={brief.templateId === t.id}>
      <div className="template-picture"><TemplateArt template={t} compact /><span className="template-radio">{brief.templateId === t.id && <Check size={13} strokeWidth={3} />}</span></div>
      <div className="template-caption"><strong>{t.name}</strong>{!library && <span>{t.tag}</span>}{library && <><p>{t.description}</p><div className="template-meta"><span>{t.layoutCount} макетов</span><span>{t.font}</span></div><div className="palette"><i style={{ background: t.color }} /><i style={{ background: t.secondary }} /><i style={{ background: '#202020' }} /><i style={{ background: '#e8eef7' }} /><span>{t.custom ? 'Загруженный шаблон' : 'Из материалов кейса'}</span></div></>}</div>
    </button>)}</div>;
  }

  const progressPanel = busy && <OperationProgress kind={busy} progress={progress} startedAt={startedAt} onCancel={busy === 'generation' || busy === 'material' || busy === 'template' || deck?.remote ? cancelOperation : undefined} compact={busy !== 'generation' || screen !== 'create'} />;

  return <div className={`app-shell simplified ${screen === 'create' ? 'home-shell' : ''} ${screen === 'editor' ? 'editor-shell' : ''}`}>
    <div className="app-main">
      <header className="simple-header">
        <button className="brand" onClick={() => navigate('create')} aria-label="Слайд — на главную"><span className="brand-icon"><Presentation size={23} strokeWidth={1.8} /></span><span>слайд<span className="brand-dot">.</span></span></button>
        <nav aria-label="Основная навигация"><button className={screen === 'projects' ? 'selected' : ''} onClick={() => navigate('projects')}><FolderOpen size={16} />Мои презентации</button><button className={screen === 'templates' ? 'selected' : ''} onClick={() => navigate('templates')}><LayoutTemplate size={16} />Шаблоны</button></nav>
        <div className="simple-header-right"><span className={`save-indicator ${storageError ? 'is-error' : ''}`}>{storageError ? 'Не сохранено' : saving ? 'Сохраняем…' : 'Сохранено в браузере'}</span><IconButton label="Как это работает" onClick={() => setDialog('help')}><CircleHelp size={19} /></IconButton></div>
      </header>

      <main className={`main-content ${screen === 'editor' ? 'editor-main' : ''}`}>
        {storageError && <div className="error-banner" role="alert"><AlertCircle size={18} /><span>Не удалось сохранить изменения в браузере. Скачайте презентацию перед закрытием страницы.</span></div>}
        {screen !== 'editor' && screen !== 'create' && <div className="page-heading"><div><div className="eyebrow">{screen === 'templates' ? 'ВАШ ФИРМЕННЫЙ СТИЛЬ' : screen === 'projects' ? 'РАБОЧЕЕ ПРОСТРАНСТВО' : 'ВАША ПРЕЗЕНТАЦИЯ'}</div><h1>{screen === 'outline' ? 'Сначала — главное' : screen === 'design' ? 'Одна история. Три взгляда.' : screen === 'templates' ? 'Узнаваемый стиль каждого слайда' : 'Мои презентации'}</h1><p>{screen === 'outline' ? 'Проверьте историю, измените текст и расставьте слайды в нужном порядке.' : screen === 'design' ? 'Выберите подачу, которая подходит вашей истории. Содержание останется прежним.' : screen === 'templates' ? 'Три фирменных шаблона из материалов кейса. Или добавьте свой.' : 'Все ваши идеи и последние изменения хранятся в этом браузере.'}</p></div>{screen === 'projects' && <button className="primary-button" onClick={newPresentation}><Plus size={18} />Новая презентация</button>}</div>}

        {connection !== 'ready' && <div className={`service-notice ${connection === 'error' ? 'is-error' : ''}`} role="status"><AlertCircle size={18} /><span>{connection === 'loading' ? 'Подключаемся к сервису презентаций…' : 'Сервис пока недоступен. Ваши сохранённые презентации можно открыть и редактировать.'}</span>{connection === 'error' && <button className="secondary-button" onClick={() => setConnectionAttempt(value => value + 1)}>Подключиться снова</button>}</div>}
        {readyDeck && <div className="generation-result" role="status"><CheckCircle2 size={20} /><span>Готова презентация «{readyDeck.title}»</span><button className="primary-button" onClick={() => openDeck(readyDeck)}>Открыть</button></div>}
        {removedSlide && removedSlide.deckId === deck?.id && ['editor', 'outline'].includes(screen) && <div className="generation-result" role="status"><span>Слайд удалён</span><button className="secondary-button" disabled={deck.slides.length >= 30} onClick={restoreSlide}>Вернуть слайд</button><IconButton label="Скрыть сообщение об удалении" onClick={() => setRemovedSlide(null)}><X size={16} /></IconButton></div>}
        {busy && (busy !== 'generation' || screen !== 'create') && dialog !== 'export' && !(dialog === 'settings' && busy === 'template') && progressPanel}
        {exportError && dialog !== 'export' && <div className="error-banner" role="alert"><AlertCircle size={18} /><span>{exportError}</span><button className="secondary-button" onClick={() => setDialog('export')}>Повторить скачивание</button></div>}
        {error && <div className="error-banner" role="alert"><AlertCircle size={18} /><span>{error}</span>{generationRetry && <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void (generationRetry === 'model' ? retryModel() : startDeck())}>Повторить</button>}<IconButton label="Закрыть сообщение" onClick={() => { setError(''); setGenerationRetry(null); }}><X size={16} /></IconButton></div>}

        {screen === 'create' && <section className="creation-home">
          <div className="home-title"><div className="home-kicker"><span />Меньше рутины. Больше ваших идей.</div><h1>{busy === 'generation' ? <>Создаём <span>вашу историю</span></> : <>О чём <span>расскажем?</span></>}</h1><p>{busy === 'generation' ? 'Следите за этапами — готовая презентация откроется автоматически.' : 'Добавьте идею — получите презентацию в фирменном стиле.'}</p></div>
          {busy === 'generation' ? progressPanel : <>
          <div className={`prompt-composer ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }} onDrop={e => { e.preventDefault(); setDragging(false); void readMaterials(Array.from(e.dataTransfer.files)); }}>
            <label className="sr-only" htmlFor="brief">Описание презентации</label>
            <textarea id="brief" ref={briefInput} value={brief.text} maxLength={6000} onChange={e => updateBrief('text', e.target.value)} onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !busy) { e.preventDefault(); void startDeck(); } }} placeholder="Например, питч нового продукта для команды. Какую проблему решаем, в чём идея и что делаем дальше…" aria-invalid={Boolean(briefError)} aria-describedby="brief-hint" />
            {materialName && !brief.materialFiles?.length && <div className="attached-material"><FileText size={15} /><span>{materialName}</span><IconButton label="Удалить материалы" disabled={Boolean(busy)} onClick={() => { setBrief(prev => ({ ...prev, materials: '', materialName: '', contentPackIds: [] })); setMaterialName(''); }}><X size={14} /></IconButton></div>}
            <div className="composer-toolbar"><div className="composer-tools"><button className="composer-tool" disabled={Boolean(busy)} title="TXT, MD, CSV, XLSX, JSON, DOCX, PPTX, PDF или ZIP до 50 МБ" onClick={() => materialInput.current?.click()}><Paperclip size={18} /><span>Материалы</span></button><button className="composer-tool" disabled={Boolean(busy)} onClick={() => setDialog('settings')}><SlidersHorizontal size={17} /><span>Настроить</span></button></div><button className="primary-button create-deck-button" disabled={Boolean(busy) || connection !== 'ready'} onClick={() => void startDeck()}><Sparkles size={17} /><span>Создать презентацию</span><ArrowUpRight size={18} /></button></div>
          </div>
          <div className={`brief-hint ${briefError ? 'is-error' : ''}`} id="brief-hint" role={briefError ? 'alert' : undefined}><span>{briefError || 'Опишите тему, основные мысли и желаемый результат.'}</span><span>{brief.text.length.toLocaleString('ru-RU')} / 6 000</span></div>
          <div className="composer-meta"><label className="slide-count-control">{slideCountText.ru.label}<select aria-describedby="slide-count-hint" disabled={Boolean(busy)} value={brief.slideCount} onChange={e => updateBrief('slideCount', Number(e.target.value))}>{Array.from({length:30}, (_, i) => i + 1).map(count => <option key={count} value={count}>{slideCountLabel(count)}</option>)}</select><span>{currentTemplate.name}</span></label><span>Ctrl / ⌘ + Enter</span></div>
          <SlideCountHint text={brief.text} count={brief.slideCount} onUseText={() => {setBrief(prev => countFromText(prev)); setBriefError('');}} />
          <div className="starter-prompts"><span>Нужна идея?</span><button onClick={() => updateBrief('text', EXAMPLE_BRIEF)}>Питч продукта<ArrowUpRight size={14} /></button><button onClick={() => updateBrief('text', 'Итоги работы над проектом для команды. Мы подготовили прототип сервиса, обсудили сценарии с пользователями и собрали обратную связь. Расскажите о проделанной работе, найденных сложностях и следующих шагах. Следующий этап — проверить основные сценарии и определить приоритеты разработки.')}>Итоги проекта<ArrowUpRight size={14} /></button><button onClick={() => updateBrief('text', 'Предлагаем запустить внутреннюю базу знаний. Сейчас полезные материалы распределены по разным чатам. Соберём инструкции и ответы на частые вопросы в одном месте. Начнём с пилота в одной команде, получим обратную связь и улучшим поиск. Цель — согласовать пилот и ответственных.')}>Предложить идею<ArrowUpRight size={14} /></button></div>
          <div className="material-files">{brief.materialFiles?.map(file=><MaterialCard key={file.id} file={file} context={brief.business?.context_source_id === file.id} results={analysisPreview.filter(r=>r.packId===file.id)} disabled={Boolean(busy)} onRemove={()=>{setBrief(prev=>{const files=(prev.materialFiles||[]).filter(f=>f.id!==file.id);return {...prev,materialFiles:files,contentPackIds:(prev.contentPackIds||[]).filter(id=>id!==file.id),materials:files.map(f=>f.text).join('\n\n')};});setAnalysisPreview([]);}} onGoal={goal=>{setBrief(prev=>({...prev,materialFiles:prev.materialFiles?.map(f=>f.id===file.id?{...f,goal}:f)}));setAnalysisPreview([]);}}/>)}</div>
          <label className="story-toggle"><input type="checkbox" checked={brief.narrative !== false} onChange={e=>updateBrief('narrative',e.target.checked)}/>Связная история: задача, контекст, данные и выводы</label><ImageOptions value={brief.generateImages} disabled={Boolean(busy)} onChange={value=>updateBrief('generateImages',value)}/><div className="data-actions"><button className="secondary-button" disabled={Boolean(busy)} onClick={()=>brandbookInput.current?.click()}><Upload size={16}/>Загрузить брендбук</button>{Boolean(brief.contentPackIds?.length)&&<button className="secondary-button" disabled={Boolean(busy)} onClick={()=>void previewAnalysis()}>Проверить данные</button>}</div>
          {brief.brandbook&&<div className="brandbook-info"><strong>{brief.brandbook.name}</strong><button className="text-button" disabled={Boolean(busy)} onClick={()=>setBrief(prev=>({...prev,brandbook:undefined}))}>Удалить</button><p>Брендбук имеет приоритет над шаблоном. Поддержка: JSON-токены, явные палитра/шрифт в текстовом PDF, brandbook.json в ZIP. Файлы .fig и сканы не поддерживаются.</p>{brief.brandbook.warnings.map((w,i)=><p key={i}>{w}</p>)}</div>}
          {Boolean(brief.contentPackIds?.length)&&<BusinessControls value={brief.business} materials={brief.materialFiles||[]} disabled={Boolean(busy)} onChange={business=>{setBrief(prev=>({...prev,business}));setError('');}}/>}
          {analysisPreview.length>0&&<><AnalysisPanel items={analysisPreview}/>{analysisPreview.filter(result=>!result.business_view).map(result=><AnalysisControls key={result.analysis_id} result={result} value={brief.materialFiles?.find(f=>f.id===result.packId)?.analysisRequests?.[result.dataset_id]||result.analysis_request||{}} onChange={selection=>{setBrief(prev=>({...prev,materialFiles:prev.materialFiles?.map(f=>f.id===result.packId?{...f,analysisRequests:{...f.analysisRequests,[result.dataset_id]:selection}}:f)}));setToast('Параметры изменены. Нажмите «Проверить данные» для пересчёта');}}/>)}</>}
          <div className="home-fineprint">Бриф сохраняется автоматически. Создание может занять несколько минут.</div></>}
          {decks.length > 0 && <section className="home-recent"><div><h2>Продолжить работу</h2><button onClick={() => navigate('projects')}>Все презентации<ArrowRight size={14} /></button></div><div className="home-recent-list">{decks.slice(0, 2).map(d => <button key={d.id} onClick={() => openDeck(d)}><span className="recent-deck-icon"><Presentation size={19} /></span><span><strong>{d.title || 'Без названия'}</strong><small>{slideCountLabel(d.slides.length)} · {new Date(d.updatedAt).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</small></span><ArrowUpRight size={17} /></button>)}</div></section>}
        </section>}

        {screen === 'outline' && deck && <div className="outline-layout"><section><div className="outline-toolbar"><span><Presentation size={16} />{slideCountLabel(deck.slides.length)}</span><span>Текст можно редактировать</span></div><div className="outline-list">{deck.slides.map((s, i) => <article className="outline-row" key={s.id}><div className="outline-index"><GripVertical size={16} /><span>{String(i + 1).padStart(2, '0')}</span></div><div className="outline-fields"><label className="sr-only" htmlFor={`title-${s.id}`}>Заголовок слайда {i + 1}</label><input readOnly={Boolean(s.analysisId)} id={`title-${s.id}`} value={s.title} onChange={e => editSlide(s.id, 'title', e.target.value)} placeholder="Заголовок слайда" maxLength={250} /><label className="sr-only" htmlFor={`body-${s.id}`}>Текст слайда {i + 1}</label><textarea readOnly={Boolean(s.analysisId)} id={`body-${s.id}`} value={s.body} onChange={e => editSlide(s.id, 'body', e.target.value)} placeholder="Добавьте ключевые тезисы. Они появятся на слайде." rows={2} maxLength={6000} /></div><div className="outline-actions"><IconButton label={`Поднять слайд ${i + 1}`} disabled={i === 0} onClick={() => moveSlide(i, -1)}><ArrowUp size={15} /></IconButton><IconButton label={`Опустить слайд ${i + 1}`} disabled={i === deck.slides.length - 1} onClick={() => moveSlide(i, 1)}><ArrowDown size={15} /></IconButton><IconButton label={`Удалить слайд ${i + 1}`} disabled={deck.slides.length === 1 || Boolean(s.analysisId)} onClick={() => removeSlide(s.id)}><Trash2 size={15} /></IconButton></div></article>)}</div><button className="add-slide" disabled={deck.slides.length >= 30} onClick={addSlide}><Plus size={17} />Добавить слайд</button><div className="flow-actions"><button className="secondary-button" onClick={() => navigate('create')}><ArrowLeft size={16} />К брифу</button><button className="primary-button" onClick={() => navigate('design')}>Выбрать дизайн<ArrowRight size={17} /></button></div></section><aside className="outline-aside panel"><div className="section-icon"><Lightbulb size={20} /></div><h3>Один слайд — одна мысль</h3><p>Оставьте в заголовке главное, а в тексте — то, что помогает это объяснить.</p><hr /><span className="eyebrow">ВЫБРАННЫЙ СТИЛЬ</span><TemplateArt template={currentTemplate} compact /><strong>{currentTemplate.name}</strong><div className="inline-note"><AlertCircle size={16} />Демоструктура собрана из вашего текста по простым правилам. Проверьте её перед оформлением.</div></aside></div>}

        {screen === 'design' && deck && <><div className="design-info"><span><CheckCircle2 size={17} />{slideCountLabel(deck.slides.length)} с одинаковым содержанием</span><span>Шаблон: {currentTemplate.name}</span></div><div className="design-grid">{layoutOptions.map(option => <button key={option.id} className={`design-card ${deck.layout === option.id ? 'selected' : ''}`} aria-pressed={deck.layout === option.id} disabled={Boolean(busy)} onClick={() => void changeLayout(option.id)}><div className="design-preview"><SlideCanvas slide={{...deck.slides[0],previewUrl:deck.variantPreviews?.[option.id]}} template={currentTemplate} layout={option.id} miniature total={deck.slides.length} /></div><div className="design-copy"><div><h2>{option.name}</h2><span className="choice-circle">{deck.layout === option.id && <Check size={15} />}</span></div><p>{option.description}</p><span>{option.detail}</span></div></button>)}</div><div className="design-tip"><Sparkles size={19} /><div><strong>Стиль можно сменить в редакторе</strong><p>Ваш текст и порядок слайдов сохранятся.</p></div></div><div className="flow-actions"><button className="secondary-button" onClick={() => navigate('outline')}><ArrowLeft size={16} />К структуре</button><button className="primary-button" onClick={() => { setActiveSlide(0); navigate('editor'); }}>Открыть редактор<ArrowRight size={17} /></button></div></>}

        {screen === 'editor' && deck && slide && <><div className="editor-toolbar"><div className="editor-title"><IconButton label="К моим презентациям" onClick={() => navigate('projects')}><ArrowLeft size={19} /></IconButton><label><span className="sr-only">Название презентации</span><input disabled={Boolean(busy)} value={deck.title} onChange={e => updateDeck(d => ({ ...d, title: e.target.value }))} maxLength={120} /></label><span>{slideCountLabel(deck.slides.length)}</span></div><div className="editor-toolbar-actions">{deck.revision && !deck.remote ? <button className="secondary-button" disabled={Boolean(busy)} onClick={()=>void saveDeck()}>Сохранить изменения</button> : null}<details className="editor-more"><summary><SlidersHorizontal size={16} />Настроить</summary><div className="editor-more-menu"><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); navigate('outline'); }}><FileText size={16} />Структура слайдов</button><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); navigate('design'); }}><LayoutTemplate size={16} />Варианты оформления</button><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); setAuditOpen(!auditOpen); }}><ShieldCheck size={16} />Проверка слайдов{issues.length > 0 && <span className="issue-count">{issues.length}</span>}</button></div></details><button className="primary-button" disabled={Boolean(busy)} onClick={() => { setExportError(''); setDialog('export'); }}><Download size={16} />Скачать</button></div></div><div inert={Boolean(busy)} className={`editor-workspace ${auditOpen ? 'with-audit' : ''}`}><aside className="filmstrip"><div className="filmstrip-title"><span>СЛАЙДЫ</span><IconButton label="Добавить слайд" disabled={deck.slides.length >= 30} onClick={addSlide}><Plus size={16} /></IconButton></div>{deck.slides.map((s, i) => <button key={s.id} className={`filmstrip-slide ${i === activeSlide ? 'active' : ''}`} onClick={() => setActiveSlide(i)} aria-label={`Слайд ${i + 1}: ${s.title}`} aria-pressed={i === activeSlide}><span className="filmstrip-number">{i + 1}</span><SlideCanvas slide={s} template={currentTemplate} layout={deck.layout} index={i} total={deck.slides.length} miniature />{issues.some(issue => issue.slideId === s.id) && <span className="slide-warning"><AlertCircle size={12} /></span>}</button>)}<button className="filmstrip-add" onClick={addSlide} disabled={deck.slides.length >= 30}><Plus size={17} />Слайд</button></aside><div className="canvas-workspace"><div className="canvas-topline"><span>{layoutOptions.find(l => l.id === deck.layout)?.name}</span><button className="text-button" onClick={() => setDialog('preview')}><Maximize2 size={15} />Просмотр</button></div><div className="canvas-holder">{deck.revision && !deck.remote && <p className="preview-notice" role="status">Есть несохранённые правки. Сохраните изменения, чтобы обновить фирменный предпросмотр.</p>}<SlideCanvas slide={slide} template={currentTemplate} layout={deck.layout} index={activeSlide} total={deck.slides.length} /></div><div className="canvas-pagination"><IconButton label="Предыдущий слайд" disabled={activeSlide === 0} onClick={() => setActiveSlide(activeSlide - 1)}><ChevronLeft size={17} /></IconButton><span>{activeSlide + 1} из {deck.slides.length}</span><IconButton label="Следующий слайд" disabled={activeSlide === deck.slides.length - 1} onClick={() => setActiveSlide(activeSlide + 1)}><ChevronRight size={17} /></IconButton></div><section className="slide-edit-panel">{deck.inference && <ModelGenerationStatus inference={deck.inference} disabled={Boolean(busy)} onRetry={deck.brief ? () => void retryModel() : undefined}/>}{deck.imageGeneration && <ImageGenerationStatus value={deck.imageGeneration} disabled={Boolean(busy)||!deck.remote} onRetry={()=>void retryIllustration()}/>}<div className="slide-edit-header"><h2>Содержание слайда</h2>{slide.analysisId?.startsWith('business:')&&<button className="text-button" disabled={Boolean(busy)} onClick={()=>{if(deck.brief){setBrief(deck.brief);setMaterialName(deck.brief.materialName||'Сохранённые материалы');}setAnalysisPreview([]);navigate('create');setToast('Измените периоды, условия или исходники, проверьте данные и создайте новую презентацию');}}>Пересчитать из источников</button>}<div><IconButton label="Поднять текущий слайд" disabled={activeSlide === 0} onClick={() => moveSlide(activeSlide, -1)}><ArrowUp size={15} /></IconButton><IconButton label="Опустить текущий слайд" disabled={activeSlide === deck.slides.length - 1} onClick={() => moveSlide(activeSlide, 1)}><ArrowDown size={15} /></IconButton><IconButton label="Дублировать слайд" disabled={deck.slides.length >= 30 || Boolean(slide.analysisId)} onClick={() => { updateDeck(d => { const slides = [...d.slides]; slides.splice(activeSlide + 1, 0, { ...slide, id: crypto.randomUUID() }); return { ...d, slides }; }); setActiveSlide(activeSlide + 1); }}><Copy size={15} /></IconButton><IconButton label="Удалить текущий слайд" disabled={deck.slides.length <= 1 || Boolean(slide.analysisId)} onClick={() => removeSlide(slide.id)}><Trash2 size={15} /></IconButton></div></div><label>Заголовок<input readOnly={Boolean(slide.analysisId)} title={slide.analysisId ? 'Проверенный вывод: измените исходные данные для пересчёта' : undefined} value={slide.title} onChange={e => editSlide(slide.id, 'title', e.target.value)} maxLength={250} /></label><label>Основной текст<textarea readOnly={Boolean(slide.analysisId)} value={slide.body} onChange={e => editSlide(slide.id, 'body', e.target.value)} placeholder="Добавьте тезисы для этого слайда" rows={4} maxLength={6000} /></label>{deck.analysis?.length ? <AnalysisPanel items={analysisForSlide(deck.analysis,slide.analysisId)}/> : null}<div className="editor-layout-select"><label htmlFor="editor-layout">Оформление всей презентации</label><select id="editor-layout" value={deck.layout} onChange={e => void changeLayout(e.target.value as Layout)} disabled={Boolean(busy)}>{layoutOptions.map(l => <option value={l.id} key={l.id}>{l.name}</option>)}</select></div></section></div>{auditOpen && <aside className="audit-panel"><div className="audit-heading"><ShieldCheck size={20} /><h2>Проверка слайдов</h2><IconButton label="Закрыть проверку" onClick={() => setAuditOpen(false)}><PanelLeftClose size={17} /></IconButton></div><p className="audit-description">Проверяем длину текста, заполнение и повторы. Замечания обновляются при редактировании.</p><div className={`audit-summary ${issues.length ? 'has-issues' : ''}`}>{issues.length ? <AlertCircle size={22} /> : <CheckCircle2 size={24} />}<div><strong>{issues.length ? `${issues.length} замечаний` : 'Всё в порядке'}</strong><span>{issues.length ? 'Проверьте перед экспортом' : 'По доступным проверкам'}</span></div></div>{issues.map(issue => <button className={`audit-item ${slide.id === issue.slideId ? 'active' : ''}`} key={issue.id} onClick={() => setActiveSlide(deck.slides.findIndex(s => s.id === issue.slideId))}><span className="audit-slide-label">Слайд {deck.slides.findIndex(s => s.id === issue.slideId) + 1}<ArrowUpRight size={14} /></span><strong>{issue.title}</strong><p>{issue.description}</p><span className={`audit-severity ${issue.severity}`}>{issue.severity === 'error' ? 'Нужно исправить' : 'Рекомендуем проверить'}</span></button>)}<div className="audit-note"><CircleHelp size={16} /><p>Проверка фактов, контраста и пересечений объектов потребует серверного аудита.</p></div></aside>}</div></>}

        {screen === 'templates' && <><div className="library-toolbar"><span>{allTemplates.length} шаблона · формат 16:9</span><button className="primary-button" disabled={Boolean(busy)} onClick={() => templateInput.current?.click()}>{busy === 'template' ? <LoaderCircle size={17} className="spin" /> : <Upload size={17} />}Загрузить PPTX</button></div>{templateCards(true)}<div className="library-disclosure"><FileUp size={22} /><div><h3>Есть свой фирменный стиль?</h3><p>Добавьте PPTX до 50 МБ — сервер извлечёт палитру, шрифты и макеты и использует исходный файл при экспорте.</p></div><button className="secondary-button" onClick={() => navigate('create')}>Создать презентацию<ArrowRight size={16} /></button></div></>}

        {screen === 'projects' && <><div className="projects-toolbar"><label className="search-field"><Search size={17} /><input placeholder="Найти презентацию" value={projectSearch} onChange={e => setProjectSearch(e.target.value)} /></label><span><Clock3 size={15} />Сначала последние</span></div>{decks.filter(d => d.title.toLowerCase().includes(projectSearch.toLowerCase())).length === 0 ? <div className="empty-state"><span><Presentation size={34} /></span><h2>{projectSearch ? 'Ничего не нашлось' : 'Здесь будут ваши презентации'}</h2><p>{projectSearch ? 'Попробуйте другое название или очистите поиск.' : 'Начните с идеи. Мы сохраним результат в этом браузере.'}</p><button className="primary-button" onClick={() => projectSearch ? setProjectSearch('') : newPresentation()}>{projectSearch ? 'Очистить поиск' : 'Создать первую презентацию'}<ArrowRight size={16} /></button></div> : <div className="projects-grid">{decks.filter(d => d.title.toLowerCase().includes(projectSearch.toLowerCase())).map(d => <article className="project-card" key={d.id}><button className="project-open" onClick={() => openDeck(d)} aria-label={`Открыть ${d.title}`}><SlideCanvas slide={d.slides[0]} template={allTemplates.find(t => t.id === d.templateId) || templates[0]} layout={d.layout} miniature total={d.slides.length} /></button><div className="project-info"><h2>{d.title || 'Без названия'}</h2><div><span>{slideCountLabel(d.slides.length)} · {new Date(d.updatedAt).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</span><IconButton label={`Удалить презентацию ${d.title}`} onClick={() => setDeleteId(d.id)}><Trash2 size={16} /></IconButton></div></div></article>)}</div>}</>}
      </main>
      {screen !== 'editor' && <footer className="page-footer"><span>Создано для идей, которые стоит показать</span><span>Слайд · ЛЦТ 2026</span></footer>}
    </div>

    <input ref={materialInput} className="sr-only" type="file" multiple accept=".txt,.md,.csv,.xlsx,.json,.docx,.pptx,.pdf,.zip" onChange={e => { void readMaterials(Array.from(e.target.files || [])); e.target.value = ''; }} aria-label="Загрузить материалы" />
    <style>{visualStyles}</style><input type="file" className="sr-only" ref={brandbookInput} accept=".json,.pdf,.zip" aria-label="Загрузить брендбук" onChange={e=>{void readBrandbook(e.target.files?.[0]);e.target.value='';}}/>
    <input type="file" ref={templateInput} className="sr-only" accept=".pptx" onChange={e => void uploadTemplate(e.target.files?.[0])} aria-label="Загрузить шаблон PPTX" />
    {toast && <div className="toast" role="status"><CheckCircle2 size={18} /><span>{toast}</span><IconButton label="Скрыть уведомление" onClick={() => setToast('')}><X size={15} /></IconButton></div>}
    {dialog === 'settings' && <Modal title="Пара настроек — и готово" onClose={() => setDialog(null)} wide>
      <div className="settings-content">{busy === 'template' && progressPanel}<section><div className="settings-label"><h3>Фирменный стиль</h3><button className="text-button" disabled={Boolean(busy)} onClick={() => templateInput.current?.click()}>{busy === 'template' ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}Загрузить свой</button></div>{templateCards()}<p className="settings-hint">PPTX до 50 МБ. Сервер сохранит шаблон и применит его при генерации.</p></section>
      <div className="settings-row"><label htmlFor="slide-count">Количество слайдов</label><div className="amount-control"><IconButton label="Уменьшить число слайдов" disabled={brief.slideCount <= 1} onClick={() => updateBrief('slideCount', brief.slideCount - 1)}>−</IconButton><input id="slide-count" type="number" min={1} max={30} value={brief.slideCount} onChange={e => updateBrief('slideCount', Math.max(1, Math.min(30, Number(e.target.value) || 1)))} /><IconButton label="Увеличить число слайдов" disabled={brief.slideCount >= 30} onClick={() => updateBrief('slideCount', brief.slideCount + 1)}><Plus size={16} /></IconButton></div></div>
      <div className="brief-selects"><label>Для кого<select value={brief.audience} onChange={e => updateBrief('audience', e.target.value)}><option>Коллеги и команда</option><option>Руководство</option><option>Клиенты и партнёры</option><option>Эксперты и жюри</option><option>Студенты</option></select></label><label>Задача презентации<select value={brief.goal} onChange={e => updateBrief('goal', e.target.value)}><option>Представить идею</option><option>Показать результаты</option><option>Убедить и получить поддержку</option><option>Объяснить и обучить</option></select></label></div>
      {error && <div className="error-banner" role="alert"><AlertCircle size={16} />{error}</div>}
      <button className="primary-button full-width" onClick={() => setDialog(null)}>Готово<Check size={17} /></button></div>
    </Modal>}
    {dialog === 'help' && <Modal title="От идеи до готовой презентации" onClose={() => setDialog(null)}><div className="help-steps">{[{ title: 'Опишите идею', body: 'Добавьте основные тезисы, выберите аудиторию и фирменный шаблон. Для быстрого старта воспользуйтесь примером.' }, { title: 'Нажмите «Создать презентацию»', body: 'Мы покажем этапы и прогресс создания. Генерация может занять несколько минут. Бриф сохранится, даже если вы прекратите ожидание.' }, { title: 'Скачайте или доработайте', body: 'Редактируйте текст прямо в редакторе. Скачать результат можно в форматах PPTX, HTML или PDF.' }].map((item, i) => <div key={item.title}><span>{i + 1}</span><section><h3>{item.title}</h3><p>{item.body}</p></section></div>)}</div><div className="modal-note"><Sparkles size={19} /><p><strong>Ваши изменения сохраняются автоматически.</strong> Презентации доступны в разделе «Мои презентации» в этом браузере. Во время создания можно перейти в библиотеку — мы сообщим, когда результат будет готов.</p></div><button className="primary-button full-width" onClick={() => setDialog(null)}>Всё понятно<Check size={17} /></button></Modal>}
    {dialog === 'export' && deck && <Modal title="Скачать презентацию" onClose={() => setDialog(null)}><p className="modal-subtitle">{slideCountLabel(deck.slides.length)} · {currentTemplate.name}</p>{busy && ['pptx', 'pdf', 'html'].includes(busy) && progressPanel}{exportError && <div className="error-banner" role="alert"><AlertCircle size={18} /><span>{exportError}</span></div>}{issues.length > 0 && <div className="export-warning"><AlertCircle size={18} /><span>В презентации есть замечания: {issues.length}.</span><button onClick={() => { setDialog(null); setAuditOpen(true); }}>Посмотреть</button></div>}<div className="export-options"><button onClick={() => void download('pptx')} disabled={Boolean(busy)}><span className="export-file pptx"><Presentation size={24} /></span><span><strong>PowerPoint <small>.pptx</small></strong><p>Редактируемые заголовки, текст и фигуры</p></span>{busy === 'pptx' ? <LoaderCircle className="spin" size={19} /> : <Download size={19} />}</button><button onClick={() => void download('pdf')} disabled={Boolean(busy)}><span className="export-file pdf"><FileText size={24} /></span><span><strong>PDF <small>.pdf</small></strong><p>{deck.remote ? 'Файл для отправки и печати' : 'Через «Сохранить как PDF» в окне печати'}</p></span>{busy === 'pdf' ? <LoaderCircle className="spin" size={19} /> : <Download size={19} />}</button><button onClick={() => void download('html')} disabled={Boolean(busy)}><span className="export-file html"><Monitor size={24} /></span><span><strong>Веб-презентация <small>.html</small></strong><p>Один файл, открывается в любом браузере</p></span>{busy === 'html' ? <LoaderCircle className="spin" size={19} /> : <Download size={19} />}</button></div><p className="export-disclosure">{deck.remote ? 'Скачиваем готовую версию в выбранном фирменном шаблоне. Подготовка PDF и HTML может занять немного времени.' : 'Файл включает ваши последние правки и оформление из редактора. PDF сохраните через диалог печати браузера.'}</p></Modal>}
    {dialog === 'preview' && deck && slide && <Modal title={`Слайд ${activeSlide + 1} из ${deck.slides.length}`} onClose={() => setDialog(null)} wide><SlideCanvas slide={slide} template={currentTemplate} layout={deck.layout} index={activeSlide} total={deck.slides.length} /><div className="preview-navigation"><button className="secondary-button" disabled={activeSlide === 0} onClick={() => setActiveSlide(activeSlide - 1)}><ChevronLeft size={17} />Назад</button><button className="secondary-button" disabled={activeSlide === deck.slides.length - 1} onClick={() => setActiveSlide(activeSlide + 1)}>Далее<ChevronRight size={17} /></button></div></Modal>}
    {deleteId && <Modal title="Удалить презентацию?" onClose={() => setDeleteId(null)}><p className="modal-subtitle">Она исчезнет из этого браузера. Скачанные файлы сохранятся.</p><div className="flow-actions"><button className="secondary-button" onClick={() => setDeleteId(null)}>Оставить</button><button className="danger-button" onClick={() => { setDecks(prev => prev.filter(d => d.id !== deleteId)); if (deck?.id === deleteId) setDeck(null); setDeleteId(null); setToast('Презентация удалена'); }}>Удалить</button></div></Modal>}
  </div>;
}
