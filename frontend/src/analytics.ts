export type Visual = {
  kind: string; categories: string[]; series: {name: string; values: (number | null)[]}[];
  columns: string[]; rows: string[][]; unit: string; source: string;
  x_label: string; y_label: string; x_values: number[];
};
export type AnalysisRequest = {
  goal?: string; task?: 'dynamics'|'comparison'|'shares'|'distribution'|'relationship'|'reference'|'summary';
  dimension?: string | null; series_dimension?: string | null; metrics?: string[];
  aggregation?: 'sum'|'mean'|'median'|'count'; unit?: string;
  number_locale?: 'decimal_comma'|'decimal_point'|null;
  filters?: Record<string,(string|number|boolean|null)[]>;
};
export type AnalysisResult = {
  analysis_id: string; dataset_id: string; selected: string; title: string;
  status: string; reason?: string; source_file: string; sheet: string; source_hash: string;
  candidates: {kind: string; reason: string}[]; warnings: string[];
  profile: {row_count: number; columns: {id: string; name: string; kind: string; role: string; missing: number}[]};
  analysis_request?: AnalysisRequest; packId?: string;
  contract?: {schema_version: '1.0'; dataset_ref: unknown; analysis: unknown; visualization: unknown; data: unknown; facts: unknown[]; presentation: unknown; status: string};
  facts: unknown[]; provenance: unknown[]; visual: Visual;
};
export type Material = { id: string; name: string; text: string; goal?: string; analysisRequests?: Record<string,AnalysisRequest>; file_report?: {name: string; status: string; reason?: string}[] };
export type Brandbook = {id: string; name: string; tokens: {colors?: string[]; font?: string; background?: string}; warnings: string[]};
export const visualNames: Record<string, string> = {table:'Таблица',bar:'Столбцы',line:'Линия',pie:'Круговая',scatter:'Точечная',histogram:'Гистограмма',grouped_bar:'Группированные столбцы',stacked_bar:'Накопительные столбцы',kpi:'Ключевой показатель'};
export function parseVisual(input: unknown): Visual | undefined {
  if (!input || typeof input !== 'object') return;
  const v = input as Partial<Visual>;
  if (!v.kind || !visualNames[v.kind]) return;
  const strings = (value: unknown): string[] => Array.isArray(value) && value.every(v => typeof v === 'string') ? value : [];
  const series = Array.isArray(v.series) ? v.series.filter(s => s && typeof s.name === 'string' && Array.isArray(s.values) && s.values.every(n => n === null || typeof n === 'number' && Number.isFinite(n))) : [];
  const categories = strings(v.categories);
  if (v.kind !== 'table' && (!series.length || !categories.length || series.some(s => s.values.length !== categories.length))) return;
  const columns = strings(v.columns), rows = Array.isArray(v.rows) ? v.rows.filter(r => Array.isArray(r) && r.every(c => typeof c === 'string')) : [];
  if (v.kind === 'table' && (!columns.length || !rows.length || rows.some(r => r.length !== columns.length))) return;
  const x_values = Array.isArray(v.x_values) && v.x_values.every(n => typeof n === 'number' && Number.isFinite(n)) ? v.x_values : [];
  if (v.kind === 'scatter' && x_values.length !== categories.length) return;
  return {kind:v.kind, categories, series, columns, rows, x_values, unit:typeof v.unit === 'string' ? v.unit : '',source:typeof v.source === 'string' ? v.source : '',x_label:typeof v.x_label === 'string' ? v.x_label : '',y_label:typeof v.y_label === 'string' ? v.y_label : ''};
}
export const escapeMarkup = (text: string) => text.replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]!);
const fmt = (n: number | null) => n === null ? '—' : n.toLocaleString('ru-RU',{maximumSignificantDigits:15});
const palette = ['#0077FF','#E66A42','#24A880','#9B67DA','#D4A40E','#47B4CE','#CF5B99','#536981'];
export function visualMarkup(v: Visual, primary = '#0077FF'): string {
  const e = escapeMarkup, colors = [/^#[0-9a-f]{6}$/i.test(primary) ? primary : palette[0], ...palette.slice(1)];
  if (v.kind === 'table') return `<div class="data-table-wrap"><table class="data-table"><thead><tr>${v.columns.map(c=>`<th>${e(c)}</th>`).join('')}</tr></thead><tbody>${v.rows.map(row=>`<tr>${row.map(c=>`<td style="text-align:${/^[+\-]?\d[\d\s,.]*$/.test(c)?'right':'left'}">${e(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  if (v.kind === 'kpi') return `<div class="data-kpi"><strong>${e(fmt(v.series[0].values[0]))} ${e(v.unit)}</strong><span>${e(v.series[0].name)}</span></div>`;
  let body = '';
  const text = (x:number,y:number,label:string,anchor='middle',size=13) => `<text x="${x}" y="${y}" text-anchor="${anchor}" font-size="${size}" fill="currentColor">${e(label)}</text>`;
  const legend = (v.kind==='pie' ? v.categories : v.series.map(s=>s.name)).map((label,i)=>`<span><i style="background:${colors[i%colors.length]}"></i>${e(label)}</span>`).join('');
  if (v.kind === 'pie') {
    const values = v.series[0].values.map(n=>n??0), total = values.reduce((a,b)=>a+b,0);
    let angle = -Math.PI/2;
    for (let i=0;i<values.length;i++) {
      const sweep = values[i]/total*Math.PI*2, end=angle+sweep;
      if (sweep >= Math.PI*2 - 1e-8) body += `<circle cx="350" cy="155" r="125" fill="${colors[i%colors.length]}"/>`;
      else if (sweep>0) body += `<path d="M350,155 L${350+125*Math.cos(angle)},${155+125*Math.sin(angle)} A125,125 0 ${sweep>Math.PI?1:0},1 ${350+125*Math.cos(end)},${155+125*Math.sin(end)} Z" fill="${colors[i%colors.length]}"><title>${e(v.categories[i])}: ${fmt(values[i])}</title></path>`;
      if(values[i]/total>=.04) body += text(350+83*Math.cos(angle+sweep/2),160+83*Math.sin(angle+sweep/2),`${fmt(values[i]/total*100)}%`);
      angle=end;
    }
  } else {
    const all=v.series.flatMap(s=>s.values.filter((n):n is number=>n!==null));
    const stack=v.categories.map((_,i)=>v.series.reduce((sum,s)=>sum+Math.max(0,s.values[i]??0),0));
    const negativeStack=v.categories.map((_,i)=>v.series.reduce((sum,s)=>sum+Math.min(0,s.values[i]??0),0));
    const min=Math.min(0,...(v.kind==='stacked_bar'?negativeStack:all)), max=Math.max(1,...(v.kind==='stacked_bar'?stack:all));
    const py=(n:number)=>255-(n-min)/(max-min)*220, step=590/v.categories.length;
    for(let i=0;i<=4;i++){const n=min+(max-min)*i/4,y=py(n);body+=`<line x1="80" y1="${y}" x2="680" y2="${y}" stroke="#9caabd" stroke-opacity=".3"/>`+text(73,y+4,fmt(n),'end',12);}
    if(v.kind==='scatter') {
      const lo=Math.min(...v.x_values),hi=Math.max(lo+1,...v.x_values);
      for(const s of v.series) s.values.forEach((n,i)=>{if(n!==null)body+=`<circle cx="${80+(v.x_values[i]-lo)/(hi-lo)*590}" cy="${py(n)}" r="4" fill="${colors[0]}"><title>${fmt(v.x_values[i])}, ${fmt(n)}</title></circle>`;});
      for(let i=0;i<=4;i++)body+=text(80+i/4*590,277,fmt(lo+(hi-lo)*i/4));
    } else {
      const positive=new Array(v.categories.length).fill(0), negative=new Array(v.categories.length).fill(0);
      v.series.forEach((s,si)=>{
        let segment:string[]=[];
        const flush=()=>{if(segment.length)body+=`<polyline points="${segment.join(' ')}" fill="none" stroke="${colors[si%colors.length]}" stroke-width="3"/>`;segment=[];};
        s.values.forEach((n,i)=>{
          if(n===null){flush();return;}
          const x=85+(i+.5)*step,y=py(n),color=colors[si%colors.length];
          if(v.kind==='line'){segment.push(`${x},${y}`);body+=`<circle cx="${x}" cy="${y}" r="3" fill="${color}"/>`;}
          else {
            const stacked=v.kind==='stacked_bar', width=step*.75/(stacked?1:v.series.length), left=85+i*step+step*.12+(stacked?0:si*width);
            const before=stacked?(n>=0?positive[i]:negative[i]):0,after=before+n;
            if(stacked){if(n>=0)positive[i]=after;else negative[i]=after;}
            body+=`<rect x="${left}" y="${Math.min(py(before),py(after))}" width="${Math.max(1,width-2)}" height="${Math.max(1,Math.abs(py(before)-py(after)))}" fill="${color}"><title>${e(v.categories[i])}, ${e(s.name)}: ${fmt(n)}</title></rect>`;
          }
          if(v.categories.length<=12&&v.series.length===1)body+=text(x,y-7,fmt(n),'middle',12);
        });flush();
      });
      v.categories.forEach((label,i)=>{const short=label.length>23?label.slice(0,21)+'…':label;body+=text(85+(i+.5)*step,278,short,'middle',v.categories.length>10?9:12);});
    }
    body+=text(380,310,v.x_label||'','middle',12)+text(80,17,v.y_label||v.unit,'start',12);
  }
  return `<svg viewBox="0 0 720 325" role="img" aria-label="${e(visualNames[v.kind]||v.kind)}">${body}</svg><div class="data-legend">${legend}</div>`;
}
export const visualStyles = `.data-visual{width:100%;color:#243149}.data-visual svg{display:block;width:100%;max-height:100%}.data-legend{display:flex;justify-content:center;gap:8px 16px;flex-wrap:wrap;font-size:12px}.data-legend span{display:inline-flex;gap:5px;align-items:center}.data-legend i{width:9px;height:9px;border-radius:2px}.data-table-wrap{overflow:auto}.data-table{width:100%;border-collapse:collapse;font-size:14px;table-layout:fixed}.data-table td,.data-table th{padding:7px 9px;border-bottom:1px solid #dbe3ee;overflow-wrap:anywhere}.data-table th{background:#eef3fa;text-align:left}.data-kpi{padding:40px;text-align:center;display:grid;gap:12px}.data-kpi strong{font-size:50px}.data-source{font-size:11px;color:#59677b;margin-top:8px;overflow-wrap:anywhere}`;
