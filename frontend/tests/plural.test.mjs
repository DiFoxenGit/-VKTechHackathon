// Склонения после числа: ошибка тут видна на каждом экране («3 макетов», «22 цветов»).
import assert from 'node:assert/strict';
import test from 'node:test';
import { count, plural } from '../src/plural.ts';

const forms = ['слайд', 'слайда', 'слайдов'];

test('одна, несколько и много — по последней цифре', () => {
  assert.equal(plural(1, ...forms), 'слайд');
  assert.equal(plural(3, ...forms), 'слайда');
  assert.equal(plural(5, ...forms), 'слайдов');
  assert.equal(plural(0, ...forms), 'слайдов');
});

test('11–14 всегда во множественном, 21 и 22 — по последней цифре', () => {
  for (const n of [11, 12, 13, 14, 111, 112]) assert.equal(plural(n, ...forms), 'слайдов', String(n));
  assert.equal(plural(21, ...forms), 'слайд');
  assert.equal(plural(22, ...forms), 'слайда');
  assert.equal(plural(101, ...forms), 'слайд');
});

test('count ставит число перед словом', () => {
  assert.equal(count(3, 'макет', 'макета', 'макетов'), '3 макета');
  assert.equal(count(22, 'цвет', 'цвета', 'цветов'), '22 цвета');
});
