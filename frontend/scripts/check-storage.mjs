import assert from 'node:assert/strict';
import {loadModule} from './load-module.mjs';
const { readSaved, STORAGE_KEY, DEFAULT_BRIEF } = await loadModule('src/storage.ts');
let stored = null;
globalThis.localStorage = { getItem(key) { assert.equal(key, STORAGE_KEY); return stored; } };
const load = value => { stored = JSON.stringify(value); return readSaved(); };
const slide = { id: 'cover', title: 'Идея', body: 'Содержание', kind: 'cover', notes: 'Полное исходное содержание' };
const brief = { ...DEFAULT_BRIEF, text: 'Описание презентации', materialName: 'notes.txt', materials: 'Текст', contentPackIds: ['pack'] };
const deck = {
  id: 'deck', title: 'Проект', slides: [slide], templateId: 'tech', layout: 'classic',
  updatedAt: '2026-10-16T12:00:00.000Z', brief, remote: true, revision: 2,
  exports: { pptx: '/api/v1/presentations/deck/export/pptx?revision=2' },
  serverIssues: [{ id: 'issue', slideId: 'cover', severity: 'warning', title: 'Проверка', description: 'Описание', fixable: false, rule: 'review' }],
};
const template = { id: 'custom', name: 'Мой шаблон', description: 'Фирменный стиль', color: '#0077FF', secondary: '#FF3885', font: 'Play', layoutCount: 4, slideCount: 10, tag: 'Шаблон', custom: true };
const valid = { brief, decks: [deck], customTemplates: [template] };
const imageGeneration = {status: 'partial', message: 'One of two created', count: 1, requested_count: 2,
  plan: {reason: 'Two requested scenes', images: [{slide: 2, prompt: 'An office in the forest', placement: 'left', style: 'photo'}]}};
assert.deepEqual(load({...valid, decks: [{...deck, imageGeneration: {...imageGeneration, api_key: 'must-not-persist'}}]}).decks[0].imageGeneration, imageGeneration);
assert.equal(load({...valid, brief: {...brief, generateImages: false}}).brief.generateImages, false);
assert.equal(load({...valid, brief: {...brief, generateImages: true}}).brief.generateImages, true);
assert.equal(load(valid).brief.generateImages, undefined);
assert.deepEqual(load(valid), valid, 'Valid saved projects must survive without losing metadata');
assert.equal(load({ brief: { text: null }, decks: [], customTemplates: [] }).brief.text, '');
assert.equal(load({ brief: { slideCount: Infinity, contentPackIds: [null, 'pack', 'pack'] } }).brief.slideCount, 10);
assert.deepEqual(load({ brief: { contentPackIds: [null, 'pack', 'pack'] } }).brief.contentPackIds, ['pack']);
assert.equal(load({ decks: [{ ...deck, slides: [{ title: null, body: 'Текст' }] }] }).decks.length, 0);
const repaired = load({ decks: [{ ...deck, layout: null, brief: { text: null }, slides: [slide, { ...slide, title: 'Другой' }, { title: 'Без id', body: '' }] }] }).decks[0];
assert.equal(new Set(repaired.slides.map(item => item.id)).size, 3, 'Restored slides must be independently editable');
assert.equal(repaired.layout, 'classic');
assert.equal(repaired.brief.text, '');
assert.equal(load({ decks: [deck, deck] }).decks.length, 1);
assert.equal(load({ decks: [{ ...deck, serverIssues: [{ ...deck.serverIssues[0], slideId: 'missing' }] }] }).decks[0].serverIssues.length, 0);
const restoredTemplate = load({ customTemplates: [{ ...template, font: null, color: 'bad' }] }).customTemplates[0];
assert.equal(restoredTemplate.font, 'Arial');
assert.equal(restoredTemplate.color, '#0077FF');
stored = '{broken';
assert.deepEqual(readSaved(), { brief: DEFAULT_BRIEF, decks: [], customTemplates: [] });
globalThis.localStorage.getItem = () => { throw new Error('Storage denied'); };
assert.equal(readSaved().decks.length, 0);
console.log('PASS: saved project round-trip, damaged data recovery, independent slide IDs, legacy defaults, denied storage');

globalThis.localStorage.getItem = () => stored;
const inference = {requested:true,attempted:true,completed:true,provider:'vk',model:'qwen38-27b-fp8',attempts:1,successful_calls:1,duration_seconds:1.2,validation:'passed',fallback_used:false,status:'completed',error_code:null,response_id:'provider-response',content_reused_for_variants:3};
assert.deepEqual(load({decks:[{...deck,inference}]}).decks[0].inference,inference,'Verified model evidence must survive reopening');
assert.equal(load({decks:[{...deck,inference:{...inference,authorization:'secret',calls:[{headers:'secret'}]}}]}).decks[0].inference.authorization,undefined,'Only public diagnostic fields are stored');
const {parseInference,hasValidatedModelText,inferenceCopy} = await loadModule('src/inference.ts');
assert.equal(hasValidatedModelText(parseInference(inference)),true);
for (const patch of [{attempted:false},{attempts:0},{successful_calls:0},{completed:false},{validation:'failed'},{fallback_used:true}]) {
  const evidence=parseInference({...inference,...patch});
  assert.equal(hasValidatedModelText(evidence),false,'Configuration or inconsistent evidence must never prove a model call');
  assert.equal(inferenceCopy(evidence).retry,true);
}
assert.match(inferenceCopy(parseInference({...inference,completed:false,fallback_used:true,error_code:'timeout'})).message,/не ответил вовремя/);
assert.equal(parseInference({model:'qwen',completed:true}),undefined);
console.log('PASS: model evidence persistence, secret-field exclusion, fail-closed success and actionable fallback');

const source = {...inference,content_source_job_id:'source-job',content_input_sha256:'a'.repeat(64),content_batch_id:'batch'};
const reused = {...source,attempted:false,attempts:0,successful_calls:0,shared_from_job_id:'source-job',
  content_revalidated:true,shared_inference:source};
assert.equal(hasValidatedModelText(parseInference(reused)),true);
assert.equal(hasValidatedModelText(load({decks:[{...deck,inference:reused}]}).decks[0].inference),true);
for(const patch of [{content_revalidated:false},{content_input_sha256:'b'.repeat(64)},
  {content_batch_id:'other-batch'},{shared_from_job_id:'missing'},{attempted:true}]) {
  assert.equal(hasValidatedModelText(parseInference({...reused,...patch})),false,'Shared content requires matching source and input evidence');
}
console.log('PASS: shared model content survives reopening without inventing additional calls');
