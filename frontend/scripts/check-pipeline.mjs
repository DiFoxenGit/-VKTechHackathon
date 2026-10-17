import assert from 'node:assert/strict';
import { loadModule } from './load-module.mjs';

const { buildOutline, distribute, sourceUnits, packBullets, toBackendOutline } = await loadModule('src/algorithms/outline.ts');
const { runPresentationPipeline } = await loadModule('src/pipeline/presentationPipeline.ts');
const { mergeAiDraft } = await loadModule('src/algorithms/mergeAiDraft.ts');
const brief = { text: '2026 год: запуск продукта\n\nКоманда проверила прототип. Участники нашли документ.', audience: 'Команда', goal: 'Обсудить запуск', materials: '', templateId: 'tech', slideCount: 3 };
const now = () => '2026-10-16T12:00:00.000Z';
const words = value => value.trim().split(/\s+/).join(' ');

for (let count = 1; count <= 30; count++) {
  const source = Array.from({ length: 93 }, (_, i) => `факт_${i}`).join(' ');
  const outline = buildOutline({ ...brief, text: source, slideCount: count });
  assert.equal(outline.slides.length, count);
  assert.equal(words(outline.slides.flatMap(slide => slide.bullets).join(' ').replace('Для кого: Команда Цель: Обсудить запуск ', '')), source);
  assert(outline.slides.every(slide => slide.bullets.length <= 12));
}
const units = Array.from({ length: 80 }, (_, i) => `Строка ${i}`);
assert.equal(words(packBullets(units).join(' ')), words(units.join(' ')), 'API bullet limits must not discard paragraphs');
assert.equal(packBullets(units).length, 12);
assert.deepEqual(distribute(['a', 'b', 'c', 'd'], 3, value => value.length).map(group => group.length), [1, 2, 1]);
assert.deepEqual(sourceUnits('x'.repeat(900)), ['x'.repeat(900)], 'Long tokens must not be truncated');
assert.throws(() => distribute([], 0, () => 1));
assert.throws(() => buildOutline({ ...brief, slideCount: NaN }));
assert.throws(() => buildOutline({ ...brief, text: '  ' }));
assert(buildOutline(brief).title.startsWith('2026'), 'Heading must retain leading years');

const original = structuredClone(brief);
const stages = [];
let rendered = 0;
const ai = { id: 'test', async enhance(input) {
  assert.deepEqual(input.outline, buildOutline(brief));
  input.brief.text = 'mutated by provider';
  return { slides: input.outline.slides.map(slide => ({ id: slide.id, title: `ИИ: ${slide.title}`, bullets: slide.bullets.length ? ['Согласованные тезисы'] : [] })).reverse() };
} };
const run = await runPresentationPipeline(brief, { ai, now, render: async prepared => {
  rendered++;
  assert(prepared.outline.title.startsWith('ИИ:'));
  assert.equal(toBackendOutline(prepared.outline).slides[1].bullets[0], 'Согласованные тезисы');
  return prepared.deck;
} }, { onStage: stage => stages.push(stage) });
assert.deepEqual(stages, ['prepare', 'algorithms', 'ai', 'validate', 'assemble', 'audit', 'render', 'complete']);
assert.deepEqual(brief, original, 'Provider and pipeline must not mutate caller input');
assert.equal(rendered, 1);
assert.equal(run.prepared.aiStatus, 'applied');
assert.deepEqual(run.prepared.outline.slides.map(s => s.id), ['slide-1', 'slide-2', 'slide-3']);
assert.deepEqual(run.prepared.outline.slides.map(s => s.sourceRefs), buildOutline(brief).slides.map(s => s.sourceRefs));
assert.deepEqual(await runPresentationPipeline(brief, { now }), await runPresentationPipeline(brief, { now }), 'Fixed clock makes the pipeline repeatable');

for (const value of [null, {}, { slides: [] }, { slides: [{ id: 'foreign', title: 'x', bullets: [] }] }]) {
  assert.throws(() => mergeAiDraft(buildOutline(brief), value));
}
const invalidAi = { id: 'invalid', async enhance() { return { slides: [] }; } };
await assert.rejects(runPresentationPipeline(brief, { ai: invalidAi, render: async () => { throw new Error('Renderer must not run'); } }), /некорректную структуру/);
const fallback = await runPresentationPipeline(brief, { ai: invalidAi, aiFailure: 'fallback', now });
assert.equal(fallback.prepared.aiStatus, 'fallback');
assert.deepEqual(fallback.prepared.outline, buildOutline(brief));
assert(fallback.prepared.issues.some(issue => issue.rule === 'ai-fallback'));
const hanging = { id: 'hanging', enhance: () => new Promise(() => {}) };
await assert.rejects(runPresentationPipeline(brief, { ai: hanging, aiTimeoutMs: 5 }), { name: 'TimeoutError' });
for (const cancelAt of stages) {
  const controller = new AbortController();
  await assert.rejects(runPresentationPipeline(brief, { now }, { signal: controller.signal, onStage(stage) { if (stage === cancelAt) controller.abort(); } }), { name: 'AbortError' });
}
const controller = new AbortController();
const pending = runPresentationPipeline(brief, { ai: { id: 'cancel', async enhance() { controller.abort(); return new Promise(() => {}); } }, aiFailure: 'fallback' }, { signal: controller.signal });
await assert.rejects(pending, { name: 'AbortError' });
const sparse = await runPresentationPipeline({ ...brief, text: 'Тема', materials: '', slideCount: 10 }, { now });
assert(sparse.prepared.issues.some(issue => issue.rule === 'empty-body'), 'Insufficient material must be reported rather than invented');
console.log('PASS: source preservation, 1–30 slides, bullet packing, deterministic pipeline, AI merge/validation, timeout, fallback and cancellation');
