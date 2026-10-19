import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {loadModule} from './load-module.mjs';
const {explicitSlideCount, slideCountIssue, countFromText}=await loadModule('src/algorithms/slideCount.ts');
const {normalizeBrief}=await loadModule('src/algorithms/outline.ts');
const cases=JSON.parse(await fs.readFile('../backend/tests/fixtures/slide_count_cases.json','utf8'));
for (const item of cases) {
  if (item.error) assert.throws(()=>explicitSlideCount(item.text),item.text);
  else assert.equal(explicitSlideCount(item.text)??null,item.count,item.text);
}
const original={text:'Создай презентацию из пяти слайдов.',slideCount:10};
assert.equal(countFromText(original).slideCount,5);
assert.equal(original.slideCount,10,'Do not mutate saved source data');
assert.throws(()=>normalizeBrief(original),/5.*10/);
assert.equal(normalizeBrief(countFromText(original)).slideCount,5);
assert(slideCountIssue(original.text,10));
assert.equal(slideCountIssue(original.text,5),'');
assert.equal(slideCountIssue('Тема про 5 продуктов и 10 регионов.',10),'');
assert.match(slideCountIssue(original.text,10,'en'),/brief requests 5/);
console.log('Slide count: shared RU/EN cases, saved defaults, conflicts and normalization passed');
