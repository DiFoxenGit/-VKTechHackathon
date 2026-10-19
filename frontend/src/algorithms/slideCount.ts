import { slideCountText } from '../locales/slideCount';
import type { CountLocale } from '../locales/slideCount';

const words: Record<string, number> = {
  один:1, одного:1, одну:1, one:1, два:2, двух:2, two:2, три:3, трех:3, three:3,
  четыре:4, четырех:4, four:4, пять:5, пяти:5, five:5, шесть:6, шести:6, six:6,
  семь:7, семи:7, seven:7, восемь:8, восьми:8, eight:8, девять:9, девяти:9, nine:9,
  десять:10, десяти:10, ten:10, одиннадцать:11, одиннадцати:11, eleven:11,
  двенадцать:12, двенадцати:12, twelve:12, тринадцать:13, тринадцати:13, thirteen:13,
  четырнадцать:14, четырнадцати:14, fourteen:14, пятнадцать:15, пятнадцати:15, fifteen:15,
  шестнадцать:16, шестнадцати:16, sixteen:16, семнадцать:17, семнадцати:17, seventeen:17,
  восемнадцать:18, восемнадцати:18, eighteen:18, девятнадцать:19, девятнадцати:19, nineteen:19,
  двадцать:20, двадцати:20, twenty:20, тридцать:30, тридцати:30, thirty:30,
};
const token = '(?:[0-9]+(?:[.,][0-9]+)?|[a-zа-я]+(?:[ -]+[a-zа-я]+)?)';
const slide = '(?:слайд(?:ов|ами|ах|а|ы)?|slides?)';
const patterns = [
  new RegExp('(?<![\\p{L}\\p{N}_])(?:из|на|в|of|with|создай|сделай|подготовь|нужно|нужны|ровно|create|make|generate)\\s+('+token+')\\s+'+slide+'(?![\\p{L}\\p{N}_])','gu'),
  new RegExp('(?<![\\p{L}\\p{N}_])('+token+')-slide\\s+(?:presentation|deck)(?![\\p{L}\\p{N}_])','gu'),
];

export function explicitSlideCount(text: string, locale: CountLocale = 'ru'): number | undefined {
  const values = new Set<number>();
  const normalized = text.toLowerCase().replaceAll('ё','е');
  for (const pattern of patterns) for (const match of normalized.matchAll(pattern)) {
    const valueText = match[1];
    let value: number | undefined;
    if (/^[0-9]+$/.test(valueText)) value = Number(valueText);
    else if (/^[0-9]+[.,][0-9]+$/.test(valueText)) throw new Error(slideCountText[locale].range);
    else {
      const parts = valueText.split(/[ -]+/);
      value = words[valueText];
      if (value === undefined && parts.length === 2 && words[parts[0]] === 20 && words[parts[1]] > 0 && words[parts[1]] < 10) value = 20 + words[parts[1]];
      if (value === undefined) continue;
    }
    if (!Number.isInteger(value) || value < 1 || value > 30) throw new Error(slideCountText[locale].range);
    values.add(value);
  }
  if (values.size > 1) throw new Error(slideCountText[locale].ambiguous);
  return values.values().next().value;
}

export function slideCountIssue(text: string, count: number, locale: CountLocale = 'ru'): string {
  try {
    const specified = explicitSlideCount(text, locale);
    return specified !== undefined && specified !== count ? slideCountText[locale].conflict(specified,count) : '';
  } catch (error) { return error instanceof Error ? error.message : slideCountText[locale].ambiguous; }
}

export function countFromText<T extends {text: string; slideCount: number}>(brief: T): T {
  try { return {...brief, slideCount: explicitSlideCount(brief.text) ?? brief.slideCount}; }
  catch { return brief; } // The form and submission validation show the issue.
}
