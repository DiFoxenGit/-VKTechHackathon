import assert from 'node:assert/strict';
import {loadModule} from './load-module.mjs';
const defines={'import.meta.env.DEV':'false','import.meta.env.VITE_PRESENTATIONS_API_BASE_URL':"'http://api.example/api/v1'"};
globalThis.window={setTimeout,clearTimeout,location:{href:'http://frontend.example/'}};
const {createPresentationService}=await loadModule('src/services/presentationService.ts',defines);
const service=createPresentationService();
const brief={text:'Test',audience:'Команда',goal:'Показать',slideCount:2,templateId:'t',materials:''};
const record={id:'deck',title:'Results',template_id:'t',variant:'split',revision:2,deck:{width:960,height:540,slides:[
  {content:{role:'content',title:'Evidence',bullets:['Fact'],block_roles:['evidence']}},
  {content:{role:'cover',title:'Cover',bullets:['Period\nAudience'],block_roles:['subtitle']}},
]},audit:{model_checks:{contextual:{status:'completed',model:'qwen38-27b-fp8',provider:'vk'}},issues:[
  {id:'geometry',slide_index:0,code:'out_of_bounds',message:'Outside',box:[-10,20,60,40],fixable:true,severity:'warning'},
  {id:'meaning',slide_index:1,code:'title_mismatch',message:'Meaning',category:'contextual',fixable:false,severity:'warning'},
]}};
let sent=[];
globalThis.fetch=async(url,init={})=>{sent.push({url,method:init.method,body:init.body?JSON.parse(init.body):undefined});return new Response(JSON.stringify(record),{headers:{'Content-Type':'application/json'}});};
const deck={...record,templateId:'t',brief,layout:'classic',remote:true,updatedAt:'',slides:record.deck.slides.map((s,i)=>({id:String(i),title:s.content.title,body:s.content.bullets.join('\n'),role:s.content.role,kind:s.content.role,blockRoles:s.content.block_roles})),variantPreviews:{classic:'/old'}};
const saved=await service.save(deck);
assert.equal(saved.slides[0].kind,'content','First evidence must retain its explicit role');
assert.equal(saved.slides[1].kind,'cover','Moved cover retains its role');
assert.deepEqual(sent[0].body.slides[1].bullets,['Period\nAudience']);
assert.deepEqual(sent[0].body.slides[1].block_roles,['subtitle']);
assert.equal(saved.variantPreviews,undefined,'Old thumbnails must expire after save');
assert(saved.slides.every(s=>s.previewUrl.includes('revision=2')));
assert.deepEqual(saved.serverIssues[0].box,[-10,20,60,40]);
assert.equal(saved.auditChecks.contextual.model,'qwen38-27b-fp8');
await service.audit(saved,'contextual');
assert(sent.at(-2).url.endsWith('/audit?contextual=true'));
const fixed=await service.fix(saved,['geometry']);
assert.deepEqual(sent.at(-1).body,{revision:2,issue_ids:['geometry']});
assert.equal(fixed.undoRevision,2);
await service.restore(fixed,2);
assert(sent.at(-1).url.endsWith('/revisions/2/restore'));
const {readSaved}=await loadModule('src/storage.ts');
globalThis.localStorage={getItem:()=>JSON.stringify({brief,decks:[fixed]})};
const reopened=readSaved().decks[0];
assert.equal(reopened.slides[1].role,'cover');
assert.deepEqual(reopened.slides[1].blockRoles,['subtitle']);
assert.equal(reopened.undoRevision,2);
assert.deepEqual(reopened.serverIssues[0].box,[-10,20,60,40]);
assert.equal(reopened.auditChecks.contextual.provider,'vk');
console.log('PASS: cover/block role round-trip, revision previews, audit selection and undo persistence');
