import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

const original = await fs.readFile('src/storage.ts', 'utf8');
const compiled = ts.transpileModule(original, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const { readSaved, STORAGE_KEY, DEFAULT_BRIEF } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
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
