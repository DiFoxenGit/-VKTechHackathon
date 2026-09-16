/** Contracts of the backend pipeline (see docs/API.md). Names mirror the server. */

export type ApiVisual = {
  kind: 'none' | 'table' | 'bar' | 'line' | 'process' | 'icon';
  categories?: string[];
  series?: { name: string; values: number[] }[];
  columns?: string[];
  rows?: string[][];
  steps?: string[];
  unit?: string;
};

export type ApiSlideContent = {
  title: string;
  bullets: string[];
  notes: string;
  source_refs: string[];
  visual: ApiVisual;
};

export type ApiOutline = { title: string; slides: ApiSlideContent[] };

export type ApiPurpose = 'feature' | 'product' | 'project' | 'initiative';

export type ApiBrief = {
  brief: string;
  purpose: ApiPurpose;
  language: string;
  slide_count: number;
  content_pack_ids: string[];
};

export type ApiGenerateRequest = ApiBrief & {
  template_id: string;
  outline?: ApiOutline;
  contextual_audit?: boolean;
};

export type ApiTemplateSummary = {
  id: string;
  name: string;
  width: number;
  height: number;
  tokens?: { fonts: string[]; font_sizes: number[]; colors: string[]; theme: Record<string, string> };
  layouts?: { index: number; name: string }[];
};

export type ApiContentPack = { id: string; name: string; text: string; sha256: string };

export type ApiJob = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: string;
  progress: number;
  presentation_ids: string[];
  error?: string;
  elapsed_seconds?: number;
  status_url?: string;
};

export type ApiAuditIssue = {
  id: string;
  slide_index: number | null;
  element_id: string | null;
  code: string;
  message: string;
  box: [number, number, number, number] | null;
  fixable: boolean;
  category: 'deterministic' | 'contextual';
  severity: 'error' | 'warning';
};

export type ApiAuditReport = {
  issues: ApiAuditIssue[];
  counts: { errors: number; warnings: number };
  contextual: { status: string; input?: string };
  geometry_units?: string;
  limitations?: string[];
};

export type ApiDeckElement = {
  id: string;
  kind: string;
  role?: string;
  text?: string;
  box: [number, number, number, number];
  font_size?: number;
  font?: string;
  color?: string;
  accent?: string;
  data?: ApiVisual;
};

export type ApiDeckSlide = {
  index: number;
  background: string;
  pattern_index: number;
  layout_index: number;
  content: ApiSlideContent;
  elements: ApiDeckElement[];
};

export type ApiPresentation = {
  id: string;
  template_id: string;
  title: string;
  variant: 'classic' | 'split' | 'focus';
  revision: number;
  deck: { width: number; height: number; variant: string; slides: ApiDeckSlide[] };
  audit: ApiAuditReport;
  exports?: Record<'pptx' | 'pdf' | 'html', string>;
  export_check?: { opens: boolean; slides: number; native_objects: number; raster_slides: number[] };
  generation?: { mode: string; model?: string; purpose?: string; language?: string };
};

export type ApiHealth = { status?: string; llm?: unknown; pdf?: unknown };
