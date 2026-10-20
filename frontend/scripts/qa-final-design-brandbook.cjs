async (page) => {
  page.setDefaultTimeout(180000);let completed;
  const capture=async r=>{if(/\/jobs\/[^/?]+$/.test(new URL(r.url()).pathname)&&r.ok()){const job=await r.json();if(job.status==='completed')completed=job;}};
  page.on('response',capture);
  await page.getByRole('button',{name:'Слайд — на главную',exact:true}).click();
  await page.getByLabel('Загрузить брендбук',{exact:true}).setInputFiles('samples/final-design/brandbook.json');
  await page.getByText('Демонстрационный брендбук · явный конфликт с шаблоном',{exact:true}).waitFor();
  const prior=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].id);
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  await page.locator('.editor-toolbar').waitFor();
  await page.waitForFunction(prior=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].id!==prior,prior);
  const deck=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0]);
  if(!deck.brief.brandbook)throw new Error('Brandbook did not survive generation');
  await page.waitForFunction(()=>{const image=document.querySelector('.canvas-holder img');return image?.complete&&image.naturalWidth>0;});
  await page.screenshot({path:'output/playwright/brandbook-cover.png',fullPage:true});
  await page.evaluate(({id,job})=>localStorage.setItem('final-design-brandbook',JSON.stringify({id,ids:job.presentation_ids,inference:job.inference,job_id:job.id})),{id:deck.id,job:completed});
  page.off('response',capture);
}
