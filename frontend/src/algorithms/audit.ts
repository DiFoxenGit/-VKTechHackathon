import type { AuditIssue, Deck } from '../types';
import { cleanText, normalKey } from './text';

export function auditDeck(deck: Deck): AuditIssue[] {
  const issues: AuditIssue[] = [];
  const titles = new Map<string, number>();
  const bodies = new Map<string, number>();
  deck.slides.forEach((slide, index) => {
    const add = (rule: string, severity: AuditIssue['severity'], title: string, description: string, fixable = false) => issues.push({ id: `${slide.id}-${rule}`, slideId: slide.id, severity, title, description, fixable, rule });
    if (!slide.title.trim()) add('empty-title', 'error', 'Добавьте заголовок', 'Заголовок поможет читателю понять тему слайда.');
    else if (slide.title.trim().length > 100) add('long-title', 'warning', 'Длинный заголовок', `В заголовке ${slide.title.trim().length} символов. Сформулируйте основную мысль короче или перенесите детали в текст.`);
    if (slide.kind !== 'cover' && !slide.body.trim() && !slide.visual) add('empty-body', 'error', 'Слайду не хватает содержания', 'Исходного материала оказалось недостаточно. Добавьте текст или удалите этот слайд.');
    if (slide.body.trim().length > 400) add('long-body', 'warning', 'На слайде много текста', `${slide.body.trim().length} символов. Разделите материал между слайдами или сократите его вручную.`);
    const titleKey = normalKey(slide.title);
    if (titleKey && titles.has(titleKey)) add('duplicate-title', 'warning', 'Заголовок повторяется', `Такой заголовок уже есть на слайде ${titles.get(titleKey)}. Проверьте, нужен ли повтор.`);
    else if (titleKey) titles.set(titleKey, index + 1);
    const bodyKey = normalKey(slide.body);
    if (bodyKey && bodies.has(bodyKey)) add('duplicate-body', 'warning', 'Текст повторяется', `Такой текст уже есть на слайде ${bodies.get(bodyKey)}. Проверьте содержание обоих слайдов.`);
    else if (bodyKey) bodies.set(bodyKey, index + 1);
    if (slide.title !== cleanText(slide.title) || slide.body !== cleanText(slide.body)) add('whitespace', 'warning', 'Лишние пробелы', 'Можно убрать повторяющиеся пробелы и пустые строки, сохранив весь текст.', true);
  });
  return issues;
}

export function fixIssue(deck: Deck, issue: AuditIssue, updatedAt = deck.updatedAt): Deck {
  if (!issue.fixable || issue.rule !== 'whitespace' || !deck.slides.some(slide => slide.id === issue.slideId)) return deck;
  const slides = deck.slides.map(slide => slide.id === issue.slideId ? { ...slide, title: cleanText(slide.title), body: cleanText(slide.body) } : slide);
  return { ...deck, slides, title: slides[0]?.title || deck.title, updatedAt };
}

