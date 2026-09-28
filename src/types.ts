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

export type Slide = { id: string; title: string; body: string; kind: 'cover' | 'content' | 'closing' };
export type Layout = 'classic' | 'story' | 'focus';
export type Brief = { text: string; audience: string; goal: string; slideCount: number; templateId: string; materials: string; contentPackIds?: string[] };
export type Deck = {
  id: string;
  title: string;
  slides: Slide[];
  templateId: string;
  layout: Layout;
  updatedAt: string;
  brief?: Brief;
  remote?: boolean;
  revision?: number;
  exports?: Partial<Record<'pptx' | 'pdf' | 'html', string>>;
  serverIssues?: AuditIssue[];
};
export type AuditIssue = { id: string; slideId: string; severity: 'warning' | 'error'; title: string; description: string; fixable: boolean; rule: string };
