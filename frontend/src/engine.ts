/** Presentation helpers that stay in the browser.
 *
 * Генерация, аудит и экспорт переехали на сервер: здесь остаётся только то, что
 * нужно самому экрану — пример брифа и расчёт кегля для превью слайда.
 */
import type { Layout, Slide, Template } from './types';

export const EXAMPLE_BRIEF = `Рабочее пространство для команды

Команда использует несколько сервисов для переписки, встреч и совместной работы с документами. Информация теряется между чатами, а поиск нужного файла отвлекает от работы.

Мы предлагаем собрать повседневные инструменты в одном рабочем пространстве. Сотрудники смогут обсуждать задачи, проводить встречи и находить материалы проекта в привычном интерфейсе.

Начнём с одного понятного сценария: подготовка командной встречи. Участник открывает календарь, находит встречу и получает доступ к повестке и связанным документам.

При разработке уделим внимание понятной навигации. Основные действия должны быть видны сразу, а подсказки — помогать пользователю в нужный момент.

Для проверки идеи проведём тестирование прототипа с участниками команды. Попросим их найти документ, подготовить встречу и поделиться материалами с коллегой.

После тестирования соберём обратную связь и уточним сценарии. Следующий шаг — выбрать функции для первой версии продукта.`;

function approximateLines(text: string, width: number, size: number, font: string, title = false): number {
  const average = font === 'Play' ? 0.54 : 0.53;
  const characterWidth = Math.max(0.1, size * (title ? average + 0.025 : average) - (title ? 0.16 : 0));
  const capacity = Math.max(1, Math.floor(width / characterWidth));
  return text.split('\n').reduce((total, paragraph) => {
    let lines = 1;
    let length = 0;
    for (const word of paragraph.split(/\s+/)) {
      if (length && length + 1 + word.length > capacity) { lines++; length = 0; }
      length += (length ? 1 : 0) + word.length;
      if (length > capacity) { lines += Math.ceil(length / capacity) - 1; length %= capacity; }
    }
    return total + lines;
  }, 0);
}

/** Shared cqw font sizes for the canvas, standalone HTML and editable PPTX export. */

export function getSlideTypography(slide: Slide, template: Template, layout: Layout): { title: number; body: number } {
  const focus = layout === 'focus';
  const story = layout === 'story';
  const width = focus ? 82 : story ? 65 : 66;
  const top = focus || (!story && slide.kind === 'cover') ? 30 : story ? 25 : 26;
  const available = (86 - top) * 0.5625;
  const preferredTitle = focus ? 5.3 : story ? 5.5 : slide.kind === 'cover' ? 6.3 : 5;
  const preferredBody = focus ? 2.2 : 2.3;
  for (let percent = 100; percent >= 40; percent -= 2) {
    const title = Math.max(3.2, preferredTitle * percent / 100);
    const body = Math.max(1.8, preferredBody * percent / 100);
    const used = 1.56 + (focus ? 2.4 : 3) + approximateLines(slide.title, width, title, template.font, true) * title * 1.16
      + (slide.body ? (focus ? 2 : 2.5) + approximateLines(slide.body, width, body, template.font) * body * 1.55 : 0);
    if (used <= available) return { title: Number(title.toFixed(3)), body: Number(body.toFixed(3)) };
  }
  return { title: 3.2, body: 1.8 };
}
