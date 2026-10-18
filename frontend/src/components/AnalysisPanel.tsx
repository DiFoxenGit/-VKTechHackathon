import type { AnalysisResult } from '../analytics';
import { visualNames } from '../analytics';
import { analysisExplanation } from '../analysisExplanation';
export function AnalysisPanel({items}: {items: AnalysisResult[]}) {
  return <section className="analysis-panel" aria-label="Анализ данных"><h3>Что показали материалы</h3>{items.map(result => {
    const explanation = analysisExplanation(result);
    return <article key={result.analysis_id}>
      <div className="analysis-card-heading"><strong>{result.source_file}</strong><span className={`analysis-status ${result.status}`}>{result.status === 'refused' ? 'Нужно уточнение' : result.warnings.length ? 'Есть замечания' : 'Готово к анализу'}</span></div>
      <p>{result.profile.row_count.toLocaleString('ru-RU')} строк · {result.profile.columns.length} колонок{result.status !== 'refused' && ` · ${visualNames[result.selected] || 'Представление данных'}`}</p>
      {result.status === 'refused' ? <p className="analysis-warning" role="status">{result.reason}</p> : <>
        <p className="analysis-conclusion">{result.title}</p>
        {result.candidates[0] && <p>{result.candidates[0].reason}</p>}
        <details><summary>Как посчитано</summary><dl className="calculation-details">{Object.entries({Показатель:explanation.metric,Расчёт:explanation.formula,Период:explanation.period,Единицы:explanation.unit,Источник:explanation.source,Фильтры:explanation.filters,Пропуски:explanation.exclusions}).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></details>
        {result.candidates.length > 1 && <details><summary>Другие способы показать данные</summary><ul>{result.candidates.slice(1).map((candidate,index)=><li key={index}><b>{visualNames[candidate.kind] || 'Представление'}</b>: {candidate.reason}</li>)}</ul></details>}
      </>}
      {[...new Set(result.warnings)].map((warning,index)=><p className="analysis-warning" key={index}>{warning}</p>)}
    </article>;
  })}</section>;
}
