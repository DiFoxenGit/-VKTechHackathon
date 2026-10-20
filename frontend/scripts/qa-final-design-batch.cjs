async (page) => {
  page.setDefaultTimeout(300000);
  const prior = await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')||'{}').decks?.[0]?.id || '');
  const label = await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).brief.generateImages ? 'with-images' : 'baseline-no-images');
  const jobs=new Map();
  const capture=async response=>{
    if (/\/jobs\/[^/?]+$/.test(new URL(response.url()).pathname) && response.ok()) {
      const job=await response.json();if(['completed','failed'].includes(job.status))jobs.set(job.id,job);
    }
  };
  page.on('response',capture);
  const started=Date.now();
  if ((await page.locator('.batch-generation').getAttribute('open')) === null) await page.locator('.batch-generation summary').click();
  await page.getByRole('button',{name:'Создать 9 вариантов',exact:true}).click();
  await page.locator('.editor-toolbar').waitFor();
  await page.waitForFunction(prior=>{const state=JSON.parse(localStorage.getItem('slide-studio:v1')||'{}');return state.decks?.length>=9&&state.decks[0].id!==prior;},prior);
  const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')));
  const report={label,elapsed_ui_seconds:(Date.now()-started)/1000,
    summary:await page.locator('.batch-summary').innerText(),jobs:[...jobs.values()].map(({id,status,inference,presentation_ids})=>({id,status,inference,presentation_ids})),
    ids:saved.decks.slice(0,9).map(d=>d.id),counts:saved.decks.slice(0,9).map(d=>d.slides.length)};
  if(!report.counts.every(count=>count===12))throw new Error('Final page budget mismatch');
  if(!saved.decks.slice(0,9).every(deck=>deck.slides[0].role==='cover'))throw new Error('Missing semantic cover');
  await page.evaluate(report=>localStorage.setItem('final-design-'+report.label,JSON.stringify(report)),report);
  await page.locator('.canvas-holder .server-canvas img').waitFor();
  await page.waitForFunction(()=>{const image=document.querySelector('.canvas-holder .server-canvas img');return image?.complete&&image.naturalWidth>0;});
  await page.screenshot({path:`output/playwright/final-design-${label}-cover.png`,fullPage:true});
  page.off('response',capture);
  console.log(JSON.stringify({summary:report.summary,jobs:report.jobs.map(j=>({id:j.id,status:j.status,provider:j.inference?.provider,model:j.inference?.model,successful_calls:j.inference?.successful_calls,validation:j.inference?.validation})),ids:report.ids}));
}
