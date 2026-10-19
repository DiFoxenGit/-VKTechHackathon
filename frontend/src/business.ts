export const PERIOD_NAMES = {current:'Отчётный период', previous:'Сравнительный период', year_ago:'Год назад', history:'История', plan:'План'} as const;
export type BusinessSettings = Record<keyof typeof PERIOD_NAMES, [string,string]>;
export const DEFAULT_BUSINESS_SETTINGS: BusinessSettings = {current:['2026-07','2026-09'],previous:['2026-04','2026-06'],year_ago:['2025-07','2025-09'],history:['2025-01','2026-09'],plan:['2026-01','2026-12']};
export const CONDITION_NAMES = {
  budget:{total:'Общий бюджет',partners:'Партнёрская экономика',implementation:'Готовность внедрения',regions:'Региональные гипотезы',reserve:'Резерв'},
  capacity:{engineers:'Инженеры внедрения',analysts:'Аналитики',max_parallel_implementations:'Параллельные внедрения'},
  owners:{partners:'Владелец партнёрского направления',implementation:'Владелец внедрения',regions:'Владелец регионального анализа'},
} as const;
type Bound<T> = {value:T;quote:string};
export type BusinessConditions = {
  sections:Record<string,string>;
  budget:Record<keyof typeof CONDITION_NAMES.budget,Bound<number>>;
  capacity:Record<keyof typeof CONDITION_NAMES.capacity,Bound<number>>;
  owners:Record<keyof typeof CONDITION_NAMES.owners,Bound<string>>;
  reporting_period:Bound<[string,string]>;
  channel_event:string|null;
};
export type BusinessRequest = {settings:BusinessSettings;conditions:BusinessConditions|null;context_source_id:string|null};
const record = (v:unknown):v is Record<string,unknown> => !!v && typeof v==='object' && !Array.isArray(v);
const range = (v:unknown,draft=false):v is [string,string] => Array.isArray(v)&&v.length===2&&v.every(x=>typeof x==='string'&&(draft||/^[1-9]\d{3}-(0[1-9]|1[0-2])$/.test(x)));

export function parseBusinessSettings(value:unknown,draft=false):BusinessSettings {
  if(!record(value)||Object.keys(value).length!==5||!Object.keys(PERIOD_NAMES).every(k=>range(value[k],draft)))throw new Error('В файле периодов нужны пять диапазонов месяцев: отчёт, сравнение, год назад, история и план.');
  return structuredClone(value) as BusinessSettings;
}
export function parseBusinessConditions(value:unknown,draft=false):BusinessConditions {
  if(!record(value)||!record(value.sections)||Object.keys(value.sections).length!==8||!['1','2','3','4','5','6','7','8'].every(k=>typeof (value.sections as Record<string,unknown>)[k]==='string')||
    !record(value.reporting_period)||!range(value.reporting_period.value,draft)||typeof value.reporting_period.quote!=='string'||!(value.channel_event===null||typeof value.channel_event==='string'))throw new Error('Файл условий должен содержать восемь разделов, отчётный период с цитатой и событие канала.');
  for(const group of ['budget','capacity','owners'] as const){
    const fields=value[group];
    if(!record(fields)||Object.keys(fields).length!==Object.keys(CONDITION_NAMES[group]).length)throw new Error('В файле условий не хватает бюджета, ресурсов или владельцев.');
    for(const key of Object.keys(CONDITION_NAMES[group])){
      const field=fields[key];
      if(!record(field)||typeof field.quote!=='string'||(group==='owners'?typeof field.value!=='string':typeof field.value!=='number'||!Number.isSafeInteger(field.value)||field.value<0||field.value>1e12))throw new Error('Для каждого условия нужны значение и точная цитата из контекста.');
    }
  }
  return structuredClone(value) as BusinessConditions;
}
export function restoreBusinessRequest(value:unknown):BusinessRequest|undefined {
  if(!record(value))return undefined;
  // Incomplete month edits are still drafts: preserve them on reload so the
  // server can explain the error instead of silently selecting default dates.
  try{return {settings:parseBusinessSettings(value.settings,true),conditions:value.conditions===null?null:parseBusinessConditions(value.conditions,true),context_source_id:typeof value.context_source_id==='string'?value.context_source_id:null};}
  catch{return undefined;}
}
export function emptyBusinessConditions(settings:BusinessSettings):BusinessConditions {
  const fields=(group:keyof typeof CONDITION_NAMES,numeric:boolean)=>Object.fromEntries(Object.keys(CONDITION_NAMES[group]).map(k=>[k,{value:numeric?0:'',quote:''}]));
  return {sections:Object.fromEntries(Array.from({length:8},(_,i)=>[String(i+1),''])),budget:fields('budget',true),capacity:fields('capacity',true),owners:fields('owners',false),reporting_period:{value:[...settings.current],quote:''},channel_event:null} as BusinessConditions;
}
export function businessApiFields(value?:BusinessRequest){
  return value?{business_settings:value.settings,business_conditions:value.conditions,business_context_id:value.context_source_id}:{};
}

export function analysisForSlide(items:import('./analytics').AnalysisResult[],id?:string){
  if(!id)return items;
  if(!id.startsWith('business:'))return items.filter(item=>item.analysis_id===id);
  const views:Record<string,string>={decision:'quarter_kpi',kpi:'quarter_kpi',trend:'monthly_trend',plan:'plan_actual',products:'product_contribution',regions:'region_plan_gap',channels:'channel_profitability',concentration:'product_structure',returns:'refunds',priorities:'decision_table',risks:'region_plan_gap',actions:'decision_table'};
  return items.filter(item=>item.business_view===views[id.split(':')[1]]);
}
