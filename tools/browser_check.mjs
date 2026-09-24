// Полный путь пользователя в нескольких браузерных движках: бриф → структура →
// три варианта → редактор → просмотр с замечаниями → проверка → скачанный PPTX.
//
// Запуск (нужен Playwright и его браузеры, ставятся отдельно от проекта):
//   npm i -D playwright && npx playwright install firefox webkit
//   node tools/browser_check.mjs http://localhost:5173 out/browsers chromium chrome firefox webkit
//
// chromium — движок Chrome и Яндекс Браузера, chrome — установленный Google Chrome,
// firefox — Gecko, webkit — движок Safari. На каждый шаг кладётся скриншот, в конце —
// report.json: сколько шагов прошло, сколько заняло, ошибки консоли и размер PPTX.
import { chromium, firefox, webkit } from 'playwright';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [, , base = 'http://localhost:5173', outDir = 'out/browsers', ...names] = process.argv;
const engines = {
  chromium: () => chromium.launch(),
  chrome: () => chromium.launch({ channel: 'chrome' }),
  firefox: () => firefox.launch(),
  webkit: () => webkit.launch(),
};
const BRIEF =
  'Инициатива: сервис автоматической вёрстки презентаций. Ручная сборка колоды занимает ' +
  '186 минут, сервис собирает её за 4 минуты. Пилот на двух командах за 6 недель: 68 колод, ' +
  'ошибок стиля 2 из 68. Просим решение о запуске на всю компанию.';

async function run(name) {
  const dir = join(outDir, name);
  mkdirSync(dir, { recursive: true });
  const browser = await engines[name]();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', error => consoleErrors.push(String(error)));
  const failed = [];
  page.on('response', response => {
    if (response.status() >= 400) failed.push(`${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`);
  });
  const steps = [];
  const started = Date.now();
  const step = async (title, action) => {
    const begun = Date.now();
    await action();
    await page.screenshot({ path: join(dir, `${String(steps.length + 1).padStart(2, '0')}-${title}.png`) });
    steps.push({ title, seconds: Math.round((Date.now() - begun) / 100) / 10 });
    console.log(`${name}: ${title} (${steps.at(-1).seconds} с)`);
  };
  const report = { browser: name, version: browser.version(), steps, consoleErrors, failed };
  try {
    await step('home', async () => {
      await page.goto(base);
      await page.getByText(/\d+ шаблона/).waitFor({ timeout: 30000 });
    });
    await step('brief', async () => {
      await page.locator('#brief').fill(BRIEF);
    });
    await step('outline', async () => {
      await page.getByRole('button', { name: /Создать презентацию/ }).click();
      await page.getByText('Сначала — главное').waitFor({ timeout: 180000 });
    });
    await step('variants', async () => {
      await page.getByRole('button', { name: /Сверстать/ }).click();
      await page.getByText('Одна история. Три взгляда.').waitFor({ timeout: 300000 });
      report.variants = await page.locator('.design-card:not([disabled])').count();
    });
    await step('editor', async () => {
      await page.getByRole('button', { name: /Открыть редактор/ }).click();
      await page.getByText('Содержание слайда').waitFor();
    });
    await step('edit-title', async () => {
      await page.getByRole('button', { name: /^Слайд 2:/ }).click();
      const title = page.getByLabel('Заголовок', { exact: true });
      await title.fill('Проверка правки в браузере');
      await page.getByLabel('Основной текст').click();
      await page.waitForTimeout(2500);
      report.editedTitle = await page.getByRole('button', { name: /^Слайд 2:/ }).getAttribute('aria-label');
    });
    await step('preview', async () => {
      await page.getByRole('button', { name: /Просмотр/ }).click();
      await page.locator('dialog[open]').waitFor();
      await page.locator('dialog[open] img, dialog[open] object, dialog[open] iframe').first().waitFor({ timeout: 60000 });
    });
    await step('preview-closed', async () => {
      await page.keyboard.press('Escape');
      await page.locator('dialog[open]').waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
      report.dialogClosedByEscape = (await page.locator('dialog[open]').count()) === 0;
    });
    await step('audit', async () => {
      await page.getByText('Настроить').first().click();
      await page.getByRole('button', { name: /Проверка слайдов/ }).click();
      await page.locator('.audit-panel').waitFor();
    });
    await step('export', async () => {
      await page.getByRole('button', { name: /^Скачать/ }).click();
      await page.locator('dialog[open]').waitFor();
      const [download] = await Promise.all([
        page.waitForEvent('download', { timeout: 120000 }),
        page.getByRole('button', { name: /PowerPoint/ }).click(),
      ]);
      const path = join(dir, 'deck.pptx');
      await download.saveAs(path);
      const bytes = readFileSync(path);
      report.pptx = { name: download.suggestedFilename(), bytes: bytes.length, zip: bytes.subarray(0, 2).toString() === 'PK' };
    });
    report.ok = true;
  } catch (error) {
    report.ok = false;
    report.error = String(error).split('\n')[0];
    await page.screenshot({ path: join(dir, 'failure.png') }).catch(() => {});
  }
  report.seconds = Math.round((Date.now() - started) / 1000);
  await browser.close();
  return report;
}

const reports = [];
for (const name of names.length ? names : Object.keys(engines)) reports.push(await run(name));
mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'report.json'), JSON.stringify(reports, null, 2));
for (const r of reports) {
  console.log(`${r.browser} ${r.version}: ${r.ok ? 'OK' : 'FAIL ' + r.error}, шагов ${r.steps.length}, ${r.seconds} с, ошибок консоли ${r.consoleErrors.length}`);
}
process.exit(reports.every(r => r.ok) ? 0 : 1);
