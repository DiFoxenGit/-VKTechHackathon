import type { AnalysisResult } from './analytics';

const object = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const words: Record<string, string> = {
  sum: 'Сумма значений выбранного показателя', mean: 'Среднее арифметическое значений',
  median: 'Медиана: центральное значение упорядоченного ряда', count: 'Количество наблюдений',
};
export function analysisExplanation(result: AnalysisResult) {
  if (result.business_explanation) return result.business_explanation;
  const analysis = object(result.contract?.analysis), presentation = object(result.contract?.presentation);
  const columns = new Map(result.profile.columns.map(c => [c.id, c.name]));
  const metrics = Array.isArray(analysis.metrics) ? analysis.metrics.filter((m): m is string => typeof m === 'string').map(m => columns.get(m) || m) : [];
  const aggregation = typeof analysis.aggregation === 'string' ? analysis.aggregation : result.analysis_request?.aggregation;
  const period = Array.isArray(presentation.period) ? presentation.period.filter((p): p is string => typeof p === 'string') : [];
  const filters = result.analysis_request?.filters;
  const operations = [...new Set((result.facts || []).map(f => object(object(f).evidence).operation))];
  const derived = [operations.includes('growth_percent') ? 'Изменение: (последнее значение − первое) / первое × 100%. Сравниваются крайние сопоставимые периоды.' : '', operations.includes('percentage_points') ? 'Изменение доли: последнее значение минус первое, в процентных пунктах.' : '', operations.includes('share_percent') ? 'Доля: значение категории / сумма всех категорий × 100%.' : ''].filter(Boolean).join(' ');
  return {
    metric: metrics.join(', ') || result.visual?.series.map(s => s.name).join(', ') || 'Показатели исходной таблицы',
    formula: [(result.selected === 'table' && aggregation === 'identity') ? 'Исходные строки без пересчёта' : words[aggregation || ''] || 'Правило расчёта не передано источником', derived].filter(Boolean).join('. '),
    period: period.length ? [...new Set(period)].join(' — ') : 'Период не указан в расчёте',
    unit: typeof presentation.unit === 'string' && presentation.unit || result.visual?.unit || 'В источнике не указана',
    source: [result.source_file, result.sheet].filter(Boolean).join(' / '),
    exclusions: analysis.missing_policy === 'preserve_gaps_exclude_from_aggregate' ? 'Пропуски исключены из агрегатов и сохранены как разрывы на графике.' : 'Правило пропусков не передано источником.',
    filters: filters && Object.keys(filters).length ? Object.entries(filters).map(([id, values]) => `${columns.get(id) || id}: ${values.join(', ')}`).join('; ') : 'Без дополнительных фильтров',
  };
}
