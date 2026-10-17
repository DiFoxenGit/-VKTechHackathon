import type { AnalysisRequest, AnalysisResult } from '../analytics';

export function AnalysisControls({result, value, onChange}: {
  result: AnalysisResult; value: AnalysisRequest; onChange: (value: AnalysisRequest) => void;
}) {
  const columns = result.profile.columns;
  const update = (patch: Partial<AnalysisRequest>) => onChange({...value,...patch});
  return <fieldset className="analysis-controls"><legend>{result.source_file} · {result.sheet}: параметры анализа</legend>
    <label>Задача<select aria-label={`Задача ${result.dataset_id}`} value={value.task||''} onChange={e=>update({task:(e.target.value||undefined) as AnalysisRequest['task']})}>
      <option value="">По цели анализа</option>{Object.entries({dynamics:'Динамика',comparison:'Сравнение',shares:'Доли',distribution:'Распределение',relationship:'Взаимосвязь',reference:'Справочная таблица',summary:'Итоговый показатель'}).map(([key,name])=><option key={key} value={key}>{name}</option>)}
    </select></label>
    <label>Измерение<select aria-label={`Измерение ${result.dataset_id}`} value={value.dimension||''} onChange={e=>update({dimension:e.target.value||null})}><option value="">Автоматически</option>{columns.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
    <label>Разделить на серии<select aria-label={`Серии ${result.dataset_id}`} value={value.series_dimension||''} onChange={e=>update({series_dimension:e.target.value||null})}><option value="">Без разделения</option>{columns.filter(c=>c.role==='dimension'||c.role==='time').map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
    <label>Расчёт<select aria-label={`Расчёт ${result.dataset_id}`} value={value.aggregation||'sum'} onChange={e=>update({aggregation:e.target.value as AnalysisRequest['aggregation']})}>{Object.entries({sum:'Сумма',mean:'Среднее',median:'Медиана',count:'Количество'}).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></label>
    <label>Единица измерения<input aria-label={`Единица измерения ${result.dataset_id}`} value={value.unit||''} maxLength={80} placeholder="Если известна из источника" onChange={e=>update({unit:e.target.value})}/></label>
    <div>Метрики {columns.filter(c=>c.role==='metric').map(c=><label key={c.id}><input type="checkbox" checked={Boolean(value.metrics?.includes(c.id))} onChange={e=>update({metrics:e.target.checked?[...(value.metrics||[]),c.id]:(value.metrics||[]).filter(id=>id!==c.id)})}/>{c.name}</label>)}</div>
    <small>После изменения нажмите «Проверить данные». Пустой выбор метрик использует правила автоматического анализа.</small>
  </fieldset>;
}
