import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

const engine = 'data:text/javascript;base64,' + Buffer.from(`export const templates = []; export const createDemoDeck = brief => ({title: brief.text, slides: [{title: brief.text,body: 'Тезис'}]});`).toString('base64');
const original = await fs.readFile('src/services/presentationService.ts', 'utf8');
const transpiled = ts.transpileModule(original, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replace("from '../engine'", `from '${engine}'`)
  .replace('import.meta.env.VITE_PRESENTATIONS_API_BASE_URL', "'http://api.example/api/v1'");
const compiled = transpiled.replace('import.meta.env.DEV','false');
globalThis.window = { setTimeout: (fn, ms) => { const timer = setTimeout(fn, ms); if (ms === 30000) timer.unref(); return timer; }, clearTimeout, location: { href: 'http://frontend.example/' } };
const { presentationService: service } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const brief = {text:'Тестовая презентация', slideCount:1, templateId:'template'};
const record = {id:'deck', title:'Тест', template_id:'template', variant:'classic', revision:1, deck:{slides:[{content:{title:'Тест',bullets:['Тезис']}}]}};
const response = body => new Response(JSON.stringify(body), {headers:{'Content-Type':'application/json'}});
let calls = [];
let progress = [];
globalThis.fetch = async (url, init) => { calls.push({url,init}); return response(calls.length === 1 ? {id:'job',status:'completed',presentation_ids:['deck']} : record); };
const deck = await service.generate(brief,'template',{onProgress: event => progress.push(event)});
assert.equal(deck.id,'deck');
assert.equal(calls.length,2, 'already complete generation must not poll');
assert.deepEqual(progress.map(event=>event.stage),['preparing','submitting','fetching','complete']);
assert.equal(JSON.parse(calls[0].init.body).contextual_audit,false);

let emptyDeckCall = 0;
globalThis.fetch = async () => response(++emptyDeckCall === 1 ? {id:'job',status:'completed',presentation_ids:['deck']} : {...record,deck:{slides:[]}});
await assert.rejects(service.generate(brief,'template'),/без слайдов/);

calls = []; progress = [];
const jobs = [{id:'job',status:'queued',progress:0}, {id:'job',status:'running',stage:'layout_and_audit',progress:45}, {id:'job',status:'completed',progress:100,presentation_ids:['deck']}, record];
globalThis.fetch = async url => { calls.push(url); return response(jobs.shift()); };
await service.generate(brief,'template',{onProgress: event=>progress.push(event)});
assert.equal(calls.length,4);
assert.equal(progress.find(event=>event.stage==='generating').progress,45);
assert.equal(progress.find(event=>event.stage==='generating').message,'Верстаем слайды и проверяем оформление');

calls = []; const controller = new AbortController();
globalThis.fetch = async url => { calls.push(url); return response({id:'job',status:'running',stage:'outline',progress:5}); };
await assert.rejects(service.generate(brief,'template',{signal:controller.signal,onProgress:event=>{if(event.stage==='generating') controller.abort();}}),{name:'AbortError'});
assert.equal(calls.length,1,'cancellation in a status callback must prevent all further requests');
await assert.rejects(service.listTemplates({signal:AbortSignal.abort()}),{name:'AbortError'});

globalThis.fetch = async (_url, {signal}) => new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
const inFlightController = new AbortController();
const inFlight = service.listTemplates({signal:inFlightController.signal});
inFlightController.abort();
await assert.rejects(inFlight,{name:'AbortError'});
const normalTimeout = window.setTimeout;
window.setTimeout = (fn,ms) => normalTimeout(fn,ms === 30000 ? 5 : ms);
await assert.rejects(service.listTemplates(),{name:'TimeoutError'});
window.setTimeout = normalTimeout;

globalThis.fetch = async () => new Response('bad gateway',{status:502});
await assert.rejects(service.listTemplates(),/Сервер временно недоступен/);

globalThis.fetch = async () => new Response(JSON.stringify({detail:'LibreOffice is required for PDF and faithful HTML export; use the backend Docker image'}),{status:503,headers:{'Content-Type':'application/json'}});
await assert.rejects(service.download(deck,'pdf'),/Экспорт в этот формат временно недоступен\. Скачайте PPTX/);
globalThis.fetch = async () => new Response('<html/>',{status:200});
await assert.rejects(service.listTemplates(),/некорректный ответ/);

let lastXHR;
globalThis.XMLHttpRequest = class {
  upload = {}; status = 200; response = {id:'pack',text:'Материал'};
  constructor(){ lastXHR=this; }
  open(method,url){ this.method=method; this.url=url; }
  setRequestHeader(){}
  send(body){ this.body=body; queueMicrotask(()=>{this.upload.onprogress({lengthComputable:true,loaded:50,total:100});this.upload.onload();this.onload();}); }
  abort(){this.onabort?.();}
};
progress = [];
const pack = await service.uploadContent(new File(['Материал'],'material.txt'),{onProgress:event=>progress.push(event)});
assert.equal(pack.id,'pack');
assert.equal(lastXHR.url,'http://api.example/api/v1/content-packs');
assert.equal(lastXHR.body.get('file').name,'material.txt');
assert.deepEqual(progress.map(event=>event.stage),['uploading','uploading','processing','complete']);
assert.equal(progress[1].progress,50);
const uploadController = new AbortController();
await assert.rejects(service.uploadContent(new File(['x'],'test.txt'),{signal:uploadController.signal,onProgress:()=>uploadController.abort()}),{name:'AbortError'});
assert.equal(lastXHR.body,undefined,'cancelled uploads must not be sent');

let clicked = false;
globalThis.document = {createElement:()=>({click(){clicked=true},remove(){}}), body:{appendChild(){}}};
let downloadUrl;
globalThis.fetch = async url => {downloadUrl=url; return new Response(new Uint8Array([1,2,3,4]),{headers:{'Content-Type':'application/octet-stream','Content-Length':'4'}});};
progress = [];
await service.download({...deck,exports:{pptx:'/api/v1/presentations/deck/export/pptx'}},'pptx',{onProgress:event=>progress.push(event)});
assert.equal(downloadUrl,'http://api.example/api/v1/presentations/deck/export/pptx');
assert.equal(clicked,true);
assert.equal(progress.find(event=>event.loaded===4).progress,100);
assert.equal(progress.at(-1).stage,'complete');

const devCompiled = transpiled.replace('import.meta.env.DEV','true');
const {presentationService:devService} = await import('data:text/javascript;base64,'+Buffer.from(devCompiled).toString('base64'));
await devService.download({...deck,exports:{pptx:'/api/v1/presentations/deck/export/pptx?revision=2'}},'pptx');
assert.equal(downloadUrl,'http://frontend.example/presentations/api/v1/presentations/deck/export/pptx?revision=2');
await devService.download({...deck,exports:{pptx:'/presentations/api/v1/presentations/deck/export/pptx?revision=2'}},'pptx');
assert.equal(downloadUrl,'http://frontend.example/presentations/api/v1/presentations/deck/export/pptx?revision=2');
let templatesUrl;
globalThis.fetch = async url => {templatesUrl=url;return response({items:[]})};
await devService.listTemplates();
assert.equal(templatesUrl,'/presentations/api/v1/templates');
console.log('PASS: generation stages, exact server progress, immediate completion, cancellation, network/JSON errors, upload bytes, processing state, export origin, streamed download');
