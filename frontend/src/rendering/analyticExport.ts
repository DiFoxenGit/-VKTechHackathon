import type PptxGenJS from 'pptxgenjs';
import type { Slide, Template } from '../types';

/** Editable Office objects; no raster fallback for data. */
export function addAnalyticSlide(pptx: PptxGenJS, source: Slide, template: Template, index: number, total: number) {
  const v=source.visual!;
  const slide=pptx.addSlide(), primary=template.color.replace('#',''), font=template.font;
  slide.background={color:'FFFFFF'};
  slide.addText(template.name,{x:.55,y:.2,w:11,h:.3,fontFace:font,fontSize:14,color:primary});
  slide.addText(source.title,{x:.55,y:.7,w:12.1,h:.75,fontFace:font,fontSize:26,bold:true,color:'243149',breakLine:false});
  const box={x:.6,y:1.65,w:12,h:4.65};
  const colors=[primary,'E66A42','24A880','9B67DA','D4A40E','47B4CE','CF5B99','536981'];
  if(v.kind==='table')slide.addTable([v.columns,...v.rows].map((row,r)=>row.map(text=>({text,options:{bold:r===0,fill:{color:r===0?'EEF3FA':'FFFFFF'},align:/^[+\-]?\d[\d\s,.]*$/.test(text)?'right' as const:'left' as const}}))),{...box,fontFace:font,fontSize:14,border:{type:'solid',color:'DBE3EE',pt:.5},color:'243149',margin:4,autoPage:false,rowH:.36,fill:{color:'FFFFFF'}});
  else if(v.kind==='kpi'){
    slide.addText(`${v.series[0].values[0]?.toLocaleString('ru-RU')??'—'} ${v.unit}`,{...box,fontFace:font,fontSize:48,bold:true,align:'center',color:primary});
    slide.addText(v.series[0].name,{x:.6,y:4.6,w:12,h:.5,fontFace:font,fontSize:20,align:'center'});
  } else {
    const types={line:'line' as const,pie:'pie' as const,scatter:'scatter' as const};
    const kind=types[v.kind as keyof typeof types]||'bar';
    // PptxGenJS scatter uses the first series as the shared X coordinates.
    const data=v.kind==='scatter' ? [{name:v.x_label,labels:v.categories,values:v.x_values},...v.series.map(s=>({name:s.name,labels:v.categories,values:s.values}))] : v.series.map(s=>({name:s.name,labels:v.categories,values:s.values}));
    slide.addChart(kind,data,{...box,chartColors:colors,showLegend:v.kind==='pie'||v.series.length>1,legendPos:'b',showValue:v.kind!=='scatter'&&v.kind!=='pie',showPercent:v.kind==='pie',showTitle:false,catAxisTitle:v.x_label,valAxisTitle:v.y_label||v.unit,showCatAxisTitle:!!v.x_label,showValAxisTitle:!!(v.y_label||v.unit),catAxisLabelFontSize:11,valAxisLabelFontSize:11,lineSize:v.kind==='scatter'?0:2,lineDataSymbol:'circle',lineDataSymbolSize:5,barGrouping:v.kind==='stacked_bar'?'stacked':'clustered',barGapWidthPct:v.kind==='histogram'?0:60,barOverlapPct:v.kind==='stacked_bar'?100:0,displayBlanksAs:'gap',dataLabelPosition:v.kind==='pie'?'bestFit':v.kind==='stacked_bar'?'ctr':v.kind==='line'?'t':'outEnd'});
  }
  slide.addText(`Источник: ${v.source}`,{x:.6,y:6.45,w:12,h:.25,fontFace:font,fontSize:10,color:'59677B'});
  if(source.body)slide.addText(source.body,{x:.6,y:6.8,w:11,h:.35,fontFace:font,fontSize:10,color:'59677B'});
  slide.addText(`${index+1} / ${total}`,{x:11.7,y:7.1,w:1,h:.2,fontSize:10,align:'right'});
  slide.addNotes([source.notes||'',`analysis_id: ${source.analysisId||''}`,`sources: ${source.sourceRefs?.join(', ')||''}`].join('\n'));
}
