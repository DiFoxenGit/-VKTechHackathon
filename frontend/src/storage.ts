import { normalizeImageGeneration } from './imagePlan';
import type { AuditIssue, Brief, Deck, Layout, Slide, Template } from './types';
import { parseVisual } from './analytics';
import { restoreBusinessRequest } from './business';
import { parseInference } from './inference';
import type { AnalysisRequest, AnalysisResult } from './analytics';

export type Saved = { brief: Brief; decks: Deck[]; customTemplates: Template[] };
export const STORAGE_KEY = 'slide-studio:v1';
export const DEFAULT_BRIEF: Brief = { narrative:true, text: '', audience: 'Коллеги и команда', goal: 'Представить идею', slideCount: 10, templateId: 'tech', materials: '', contentPackIds: [] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const text = (value: unknown, fallback = ''): string => typeof value === 'string' ? value : fallback;
const identifier = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const integer = (value: unknown, min: number, max = Number.MAX_SAFE_INTEGER): value is number => typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;

function normalizeBrief(value: unknown, fallback: Brief = DEFAULT_BRIEF): Brief {
  const source = isRecord(value) ? value : {};
  return {
    ...(typeof source.generateImages === 'boolean' ? {generateImages:source.generateImages} : {}),
    ...(restoreBusinessRequest(source.business) ? {business:restoreBusinessRequest(source.business)} : {}),
    narrative: typeof source.narrative === "boolean" ? source.narrative : true,
    text: text(source.text, fallback.text),
    audience: text(source.audience, fallback.audience),
    goal: text(source.goal, fallback.goal),
    slideCount: integer(source.slideCount, 1, 30) ? source.slideCount : fallback.slideCount,
    templateId: identifier(source.templateId) ? source.templateId : fallback.templateId,
    materials: text(source.materials, fallback.materials),
    ...(typeof source.materialName === 'string' ? { materialName: source.materialName } : {}),
    contentPackIds: Array.isArray(source.contentPackIds) ? [...new Set(source.contentPackIds.filter(identifier))] : [...(fallback.contentPackIds || [])],
    ...(Array.isArray(source.materialFiles) ? {materialFiles: source.materialFiles.filter(isRecord).filter(m => identifier(m.id) && typeof m.name === 'string' && typeof m.text === 'string').map(m => ({id:String(m.id),name:String(m.name),text:String(m.text),...(integer(m.sizeBytes,0)?{sizeBytes:m.sizeBytes}:{}),...(integer(m.rowCount,0)?{rowCount:m.rowCount}:{}),...(integer(m.tableCount,0)?{tableCount:m.tableCount}:{}),...(typeof m.sourceHash==='string'?{sourceHash:m.sourceHash}:{}),...(typeof m.goal==='string'?{goal:m.goal}:{}),...(isRecord(m.analysisRequests)?{analysisRequests:m.analysisRequests as Record<string,AnalysisRequest>}:{}),file_report:Array.isArray(m.file_report) ? m.file_report.filter(isRecord).map(f => ({name:text(f.name),status:text(f.status),reason:text(f.reason)})) : undefined})) } : {}),
    ...(isRecord(source.brandbook) && identifier(source.brandbook.id) && isRecord(source.brandbook.tokens) ? {brandbook:{id:source.brandbook.id,name:text(source.brandbook.name),tokens:{colors:Array.isArray(source.brandbook.tokens.colors)?source.brandbook.tokens.colors.filter((v):v is string=>typeof v==='string'&&/^#?[0-9a-f]{6}$/i.test(v)):[],font:text(source.brandbook.tokens.font)},warnings:Array.isArray(source.brandbook.warnings)?source.brandbook.warnings.filter((v):v is string=>typeof v==='string'):[]}} : {}),
  };
}

function normalizeIssues(value: unknown, slides: Slide[]): AuditIssue[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const slideIds = new Set(slides.map(slide => slide.id));
  const ids = new Set<string>();
  return value.flatMap((item, index) => {
    if (!isRecord(item) || !identifier(item.slideId) || !slideIds.has(item.slideId) || typeof item.title !== 'string' || typeof item.description !== 'string') return [];
    let id = identifier(item.id) ? item.id : `saved-issue-${index + 1}`;
    while (ids.has(id)) id += '-duplicate';
    ids.add(id);
    return [{
      id,
      slideId: item.slideId,
      severity: item.severity === 'error' ? 'error' as const : 'warning' as const,
      title: item.title,
      description: item.description,
      fixable: item.fixable === true,
      rule: text(item.rule, 'review'),
    }];
  });
}

function normalizeExports(value: unknown): Deck['exports'] {
  if (!isRecord(value)) return undefined;
  const exports: NonNullable<Deck['exports']> = {};
  for (const format of ['pptx', 'pdf', 'html'] as const) {
    const url = value[format];
    if (!identifier(url)) continue;
    try {
      // Relative API paths and signed HTTP URLs are both valid export locations.
      if (['http:', 'https:'].includes(new URL(url, 'https://saved-presentation.invalid/').protocol)) exports[format] = url;
    } catch { /* A malformed export can be requested again using the presentation id. */ }
  }
  return Object.keys(exports).length ? exports : undefined;
}

function normalizeDeck(value: unknown): Deck | null {
  if (!isRecord(value) || !identifier(value.id) || typeof value.title !== 'string' || !Array.isArray(value.slides) || !value.slides.length) return null;
  const sourceSlides = value.slides;
  // Do not silently discard slide content from a damaged saved project.
  if (!sourceSlides.every(item => isRecord(item) && typeof item.title === 'string' && typeof item.body === 'string')) return null;
  const reservedIds = new Set(sourceSlides.flatMap(item => identifier(item.id) ? [item.id] : []));
  const usedIds = new Set<string>();
  const slides: Slide[] = sourceSlides.map((item, index) => {
    let id: string;
    if (identifier(item.id) && !usedIds.has(item.id)) id = item.id;
    else {
      id = `${value.id}-slide-${index + 1}`;
      while (usedIds.has(id) || reservedIds.has(id)) id += '-restored';
    }
    usedIds.add(id);
    const kind: Slide['kind'] = item.kind === 'cover' || item.kind === 'content' || item.kind === 'closing'
      ? item.kind : index === 0 ? 'cover' : index === sourceSlides.length - 1 ? 'closing' : 'content';
    return { id, title: item.title, body: item.body, kind, ...(typeof item.previewUrl === "string" && item.previewUrl.startsWith("/") ? {previewUrl:item.previewUrl}:{}), ...(isRecord(item.rawVisual)?{rawVisual:item.rawVisual}:{}), ...(typeof item.notes === 'string' ? { notes: item.notes } : {}), ...(parseVisual(item.visual)?{visual:parseVisual(item.visual)}:{}),...(identifier(item.analysisId)?{analysisId:item.analysisId}:{}),...(Array.isArray(item.sourceRefs)?{sourceRefs:item.sourceRefs.filter(identifier)}:{}) };
  });
  const templateId = identifier(value.templateId) ? value.templateId : DEFAULT_BRIEF.templateId;
  const layout: Layout = value.layout === 'story' || value.layout === 'focus' ? value.layout : 'classic';
  const updatedAt = typeof value.updatedAt === 'string' && Number.isFinite(Date.parse(value.updatedAt)) ? value.updatedAt : new Date(0).toISOString();
  const brief = isRecord(value.brief) ? normalizeBrief(value.brief, { ...DEFAULT_BRIEF, templateId, slideCount: Math.min(30, slides.length) }) : undefined;
  const serverIssues = normalizeIssues(value.serverIssues, slides);
  const exports = normalizeExports(value.exports);
  const inference = parseInference(value.inference);
  return {
    id: value.id,
    title: value.title,
    slides,
    templateId,
    layout,
    updatedAt,
    ...(brief ? { brief } : {}),
    ...(typeof value.remote === 'boolean' ? { remote: value.remote } : {}),
    ...(isRecord(value.variantPreviews)?{variantPreviews:Object.fromEntries(Object.entries(value.variantPreviews).filter(([k,v])=>["classic","story","focus"].includes(k)&&typeof v==="string"&&v.startsWith("/")))}:{}),
    ...(integer(value.revision, 1) ? { revision: value.revision } : {}),
    ...(exports ? { exports } : {}),
    ...(inference ? { inference } : {}),
    ...(serverIssues ? { serverIssues } : {}),
    ...(normalizeImageGeneration(value.imageGeneration) ? {imageGeneration: normalizeImageGeneration(value.imageGeneration)} : {}),
    ...(Array.isArray(value.analysis)?{analysis:value.analysis.filter(isRecord).filter(a=>identifier(a.analysis_id)&&isRecord(a.profile)&&Array.isArray(a.profile.columns)&&Array.isArray(a.candidates)&&Array.isArray(a.warnings)) as unknown as AnalysisResult[]} : {}),
  };
}

function normalizeTemplate(value: unknown): Template | null {
  if (!isRecord(value) || !identifier(value.id) || typeof value.name !== 'string') return null;
  const color = (item: unknown, fallback: string) => typeof item === 'string' && /^#[\da-f]{6}$/i.test(item) ? item : fallback;
  return {
    id: value.id,
    name: value.name,
    description: text(value.description),
    color: color(value.color, '#0077FF'),
    secondary: color(value.secondary, '#FF3885'),
    font: typeof value.font === 'string' && /^[\p{L}\p{N} _-]{1,80}$/u.test(value.font) ? value.font : 'Arial',
    layoutCount: integer(value.layoutCount, 0) ? value.layoutCount : 0,
    slideCount: integer(value.slideCount, 0) ? value.slideCount : 0,
    tag: text(value.tag, 'Загруженный шаблон'),
    ...(typeof value.custom === 'boolean' ? { custom: value.custom } : {}),
  };
}

function uniqueById<T extends { id: string }>(items: T[]): T[] {
  const ids = new Set<string>();
  return items.filter(item => {
    if (ids.has(item.id)) return false;
    ids.add(item.id);
    return true;
  });
}

export function readSaved(): Saved {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (isRecord(data)) return {
      brief: normalizeBrief(data.brief),
      decks: uniqueById(Array.isArray(data.decks) ? data.decks.map(normalizeDeck).filter((deck): deck is Deck => deck !== null) : []),
      customTemplates: uniqueById(Array.isArray(data.customTemplates) ? data.customTemplates.map(normalizeTemplate).filter((template): template is Template => template !== null) : []),
    };
  } catch { /* Storage can be unavailable, contain invalid JSON, or use an older format. */ }
  return { brief: normalizeBrief(undefined), decks: [], customTemplates: [] };
}
