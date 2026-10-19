import {useState} from 'react';
import type {Material} from '../analytics';
import {CONDITION_NAMES, DEFAULT_BUSINESS_SETTINGS, PERIOD_NAMES, emptyBusinessConditions, parseBusinessConditions, parseBusinessSettings} from '../business';
import type {BusinessConditions, BusinessRequest, BusinessSettings} from '../business';

export function BusinessControls({value,materials,disabled,onChange}:{value?:BusinessRequest;materials:Material[];disabled:boolean;onChange:(value:BusinessRequest|undefined)=>void}){
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const update=(patch:Partial<BusinessRequest>)=>{if(value)onChange({...value,...patch});};
  const conditions=value?.conditions;
  function changeConditions(patch:Partial<BusinessConditions>){if(conditions)update({conditions:{...conditions,...patch}});}
  async function importFile(file:File|undefined,kind:'settings'|'conditions'){
    if(!file)return;
    setLoading(true);
    try{
      if(!file.size||file.size>128*1024)throw new Error('Выберите непустой файл параметров до 128 КБ.');
      const parsed:unknown=JSON.parse(await file.text());
      if(kind==='settings')update({settings:parseBusinessSettings(parsed)});
      else update({conditions:parseBusinessConditions(parsed)});
      setError('');
    }catch(e){setError(`Файл не применён. ${e instanceof SyntaxError?'Не удалось прочитать JSON.':e instanceof Error?e.message:'Проверьте формат файла.'}`);}
    finally{setLoading(false);}
  }
  return <section className="business-controls" aria-label="Бизнес-анализ"><fieldset disabled={disabled||loading}>
    <label className="story-toggle"><input type="checkbox" checked={!!value} onChange={e=>onChange(e.target.checked?{settings:structuredClone(DEFAULT_BUSINESS_SETTINGS),conditions:null,context_source_id:null}:undefined)}/>Задать периоды и условия бизнес-анализа</label>
    {value&&<>
      <p>Продажи, план и справочники рассчитываются вместе. Периоды задаются закрытыми месяцами. Начальные значения относятся к исходному сценарию III квартала 2026.</p>
      <div className="business-periods">{Object.entries(PERIOD_NAMES).map(([key,label])=><fieldset key={key}><legend>{label}</legend>{[0,1].map(index=><label key={index}>{index===0?'С':'По'}<input type="month" aria-label={`${label} ${index===0?'с':'по'}`} value={value.settings[key as keyof BusinessSettings][index]} onChange={e=>{const bounds:[string,string]=[...value.settings[key as keyof BusinessSettings]];bounds[index]=e.target.value;update({settings:{...value.settings,[key]:bounds}});}}/></label>)}</fieldset>)}</div>
      <small>Сравнения имеют одинаковую длину. История заканчивается последним отчётным месяцем и покрывает сравнения. Будущие строки остаются в исходнике, но не входят в выбранный расчёт.</small>
      <details><summary>Загрузить периоды из файла</summary><label>Файл периодов<input type="file" accept=".json,application/json" onChange={e=>{void importFile(e.target.files?.[0],'settings');e.target.value='';}}/></label></details>
      <details className="business-conditions"><summary>Условия и доказательства из контекста</summary>
        <p>Для другого периода нужны согласованные условия: значения и точные цитаты текущего контекста. Можно загрузить подготовленный файл условий или заполнить форму. Проверка подтвердит цитаты и диапазон отчёта.</p>
        <label>Файл условий<input type="file" accept=".json,application/json" onChange={e=>{void importFile(e.target.files?.[0],'conditions');e.target.value='';}}/></label>
        {!conditions&&<button type="button" className="secondary-button" onClick={()=>update({conditions:emptyBusinessConditions(value.settings)})}>Заполнить условия вручную</button>}
        {conditions&&<>
          <label>Файл делового контекста<select aria-label="Файл делового контекста" value={value.context_source_id||''} onChange={e=>update({context_source_id:e.target.value||null})}><option value="">Выберите загруженный материал</option>{materials.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          <fieldset><legend>Подтверждение отчётного периода</legend>{[0,1].map(i=><label key={i}>{i===0?'С':'По'}<input type="month" aria-label={`Период в контексте ${i===0?'с':'по'}`} value={conditions.reporting_period.value[i]} onChange={e=>{const bounds:[string,string]=[...conditions.reporting_period.value];bounds[i]=e.target.value;changeConditions({reporting_period:{...conditions.reporting_period,value:bounds}});}}/></label>)}
            <label>Цитата с отчётными месяцами<textarea rows={2} value={conditions.reporting_period.quote} onChange={e=>changeConditions({reporting_period:{...conditions.reporting_period,quote:e.target.value}})}/></label>
          </fieldset>
          {(['budget','capacity','owners'] as const).map(group=><details key={group}><summary>{group==='budget'?'Бюджет, ₽':group==='capacity'?'Ресурсы и ограничения':'Ответственные'}</summary>{Object.entries(CONDITION_NAMES[group]).map(([key,label])=>{
            const field=(conditions[group] as Record<string,{value:string|number;quote:string}>)[key];
            const change=(patch:{value?:string|number;quote?:string})=>changeConditions({[group]:{...conditions[group],[key]:{...field,...patch}}});
            return <fieldset key={key}><legend>{label}</legend><label>Значение<input aria-label={label} type={group==='owners'?'text':'number'} min={0} max={1e12} step={1} value={field.value} onChange={e=>change({value:group==='owners'?e.target.value:Number(e.target.value)})}/></label><label>Точная цитата<textarea aria-label={`Цитата: ${label}`} rows={2} maxLength={3000} value={field.quote} onChange={e=>change({quote:e.target.value})}/></label></fieldset>;
          })}</details>)}
          <label>Событие канала — точная цитата, если подтверждено<textarea rows={2} value={conditions.channel_event||''} onChange={e=>changeConditions({channel_event:e.target.value||null})}/></label>
          <details><summary>Восемь смысловых разделов контекста</summary><p>Вставьте точный текст соответствующих разделов текущего источника.</p>{Object.entries({1:'Компания и продукты',2:'Управленческое решение',3:'История и события',4:'Бюджет и ресурсы',5:'Клиенты и границы данных',6:'Определения метрик',7:'Риски и ответственность',8:'Вопросы руководителя'}).map(([key,label])=><label key={key}>{label}<textarea rows={4} value={conditions.sections[key]||''} onChange={e=>changeConditions({sections:{...conditions.sections,[key]:e.target.value}})}/></label>)}</details>
          <button type="button" className="text-button" onClick={()=>update({conditions:null,context_source_id:null})}>Убрать явные условия</button>
        </>}
      </details>
      <p role="status">После изменения проверьте данные и создайте презентацию заново: анализ, история и сроки обновятся вместе. Предыдущая презентация останется в проектах.</p>
    </>}
    {error&&<p className="analysis-warning" role="alert">{error}</p>}
  </fieldset></section>;
}
