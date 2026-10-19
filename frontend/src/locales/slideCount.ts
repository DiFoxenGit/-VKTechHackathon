export type CountLocale = 'ru' | 'en';
export const slideCountText = {
  ru: {
    label: 'Количество слайдов',
    sync: 'Число слайдов взято из текста запроса.',
    range: 'Выберите целое количество слайдов от 1 до 30.',
    ambiguous: 'В запросе указано разное количество слайдов. Оставьте одно число.',
    conflict: (text: number, selected: number) => `В тексте указано ${text}, в настройках — ${selected}. Измените текст или используйте число из запроса.`,
    useText: 'Использовать число из запроса',
  },
  en: {
    label: 'Number of slides',
    sync: 'The slide count was taken from your brief.',
    range: 'Choose a whole number of slides from 1 to 30.',
    ambiguous: 'The brief specifies conflicting slide counts. Keep one number.',
    conflict: (text: number, selected: number) => `The brief requests ${text} slides, but settings specify ${selected}. Edit the brief or use its count.`,
    useText: 'Use the count from the brief',
  },
};
