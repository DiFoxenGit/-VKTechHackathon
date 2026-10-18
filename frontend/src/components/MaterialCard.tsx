import type { Material, AnalysisResult } from '../analytics';
import { materialSourceUrl } from '../services/presentationService';

export function MaterialCard({file, results, disabled, onRemove, onGoal}: {
  file: Material; results: AnalysisResult[]; disabled: boolean; onRemove: () => void; onGoal: (goal: string) => void;
}) {
  const rejected = file.file_report?.filter(r => r.status !== 'accepted') || [];
  const type = file.name.split('.').pop()?.toUpperCase() || 'Файл';
  const issue = rejected[0]?.reason || results.find(r => r.status === 'refused')?.reason || results.flatMap(r => r.warnings)[0];
  const visual = results.find(r=>r.status!=='refused')?.visual;
  const number = (v: number | null) => v===null ? '—' : v.toLocaleString('ru-RU',{maximumFractionDigits:8});
  const preview = visual?.kind==='table' ? {columns:visual.columns,rows:visual.rows.slice(0,3)} : visual?.kind==='kpi' ? {columns:['Показатель','Значение'],rows:visual.series.slice(0,3).map(s=>[s.name,number(s.values[0])])} : visual ? {columns:[visual.x_label||'Категория',...visual.series.map(s=>s.name)],rows:visual.categories.slice(0,3).map((c,i)=>[c,...visual.series.map(s=>number(s.values[i]))])} : undefined;
  return <article className="material-card">
    <div className="analysis-card-heading"><div><span className="material-type">{type}</span><strong>{file.name}</strong></div><button className="text-button" disabled={disabled} aria-label={`Удалить ${file.name}`} onClick={onRemove}>Удалить</button></div>
    <p className="material-meta">{file.tableCount || results.length ? `${(file.rowCount ?? results.reduce((n,r)=>n+r.profile.row_count,0)).toLocaleString('ru-RU')} строк · ${file.tableCount ?? results.length} таблиц` : ['CSV','XLSX','JSON'].includes(type) ? 'Табличные данные · готовы к проверке' : type === 'ZIP' ? 'Пакет материалов · загружен' : 'Текст и контекст · загружен'}</p>
    {issue && <p className="analysis-warning" role="status">{issue}{rejected.length>1 ? ` Ещё файлов с замечаниями: ${rejected.length-1}.` : ''}</p>}
    <label className="material-analysis-goal">Для чего использовать<input aria-label={`Цель анализа ${file.name}`} placeholder="Например: динамика выручки или ограничения команды" value={file.goal||''} maxLength={1000} disabled={disabled} onChange={e=>onGoal(e.target.value)}/></label>
    <a className="text-button" href={materialSourceUrl(file.id)} download={file.name}>Скачать исходник</a>
    <details><summary>Посмотреть содержимое</summary>{preview ? <div className="material-table-preview"><table><thead><tr>{preview.columns.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{preview.rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>)}</tbody></table><small>Первые 3 строки выбранного представления. Расчёт учитывает все строки с учётом заданных фильтров.</small></div> : <p className="material-text-preview">{file.text.slice(0,1600) || 'Содержимое доступно после проверки данных.'}{file.text.length>1600 && '…'}</p>}</details>
  </article>;
}
