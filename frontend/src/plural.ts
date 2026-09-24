/** Русское склонение после числа: plural(1, …) → «слайд», plural(3, …) → «слайда»,
 *  plural(5, …) → «слайдов». Для 11–14 всегда множественная форма. */
export function plural(count: number, one: string, few: string, many: string): string {
  const tens = Math.abs(count) % 100;
  if (tens >= 11 && tens <= 14) return many;
  const ones = tens % 10;
  if (ones === 1) return one;
  if (ones >= 2 && ones <= 4) return few;
  return many;
}

/** Число вместе со словом: «3 слайда», «12 слайдов». */
export function count(value: number, one: string, few: string, many: string): string {
  return `${value} ${plural(value, one, few, many)}`;
}
