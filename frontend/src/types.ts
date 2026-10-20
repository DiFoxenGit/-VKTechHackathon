export type Template = {
  id: string;
  name: string;
  description: string;
  color: string;
  secondary: string;
  font: string;
  layoutCount: number;
  slideCount: number;
  tag: string;
  custom?: boolean;
};

export type Slide = { blockRoles?: string[]; role?: 'auto' | 'cover' | 'content' | 'closing'; previewUrl?: string; rawVisual?: Record<string, unknown>; id: string; title: string; body: string; kind: 'cover' | 'content' | 'closing'; notes?: string; visual?: import('./analytics').Visual; analysisId?: string; sourceRefs?: string[] };
export type Layout = 'classic' | 'story' | 'focus';
export type ImageGeneration = {status: 'not_requested' | 'ready' | 'partial' | 'unavailable' | 'failed'; message: string; count?: number; requested_count?: number; plan?: {reason: string; images: {slide: number; prompt: string; placement: 'left' | 'right'; style: 'photo' | 'illustration'}[]}};
export type Brief = { business?: import('./business').BusinessRequest; generateImages?: boolean; narrative?: boolean; text: string; audience: string; goal: string; slideCount: number; templateId: string; materials: string; materialName?: string; contentPackIds?: string[]; materialFiles?: import('./analytics').Material[]; brandbook?: import('./analytics').Brandbook };
export type Deck = {
  inference?: import('./inference').ModelInference;
  imageGeneration?: ImageGeneration;
  id: string;
  title: string;
  slides: Slide[];
  templateId: string;
  layout: Layout;
  updatedAt: string;
  brief?: Brief;
  remote?: boolean;
  revision?: number;
  variantPreviews?: Partial<Record<Layout,string>>;
  exports?: Partial<Record<'pptx' | 'pdf' | 'html', string>>;
  serverIssues?: AuditIssue[];
  auditChecks?: Partial<Record<'contextual' | 'visual', {status: string; provider?: string; model?: string; input?: string}>>;
  slideSize?: {width: number; height: number};
  undoRevision?: number;
  analysis?: import('./analytics').AnalysisResult[];
};
export type AuditIssue = { id: string; slideId: string; severity: 'warning' | 'error'; title: string; description: string; fixable: boolean; rule: string; source?: 'local' | 'server'; category?: string; box?: number[] | null };
