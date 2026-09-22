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
export type Brief = { text: string; audience: string; goal: string; slideCount: number; templateId: string; materials: string };
export type Deck = { id: string; title: string; slides: Slide[]; templateId: string; layout: Layout; updatedAt: string; brief?: Brief };
export type AuditIssue = { id: string; slideId: string; severity: 'warning' | 'error'; title: string; description: string; fixable: boolean; rule: string; /** У находки есть рамка: её можно обвести на превью. */ boxed: boolean; /** Кто нашёл: правило, модель по тексту или модель по картинке слайда. */ origin: 'rule' | 'text' | 'image' };
