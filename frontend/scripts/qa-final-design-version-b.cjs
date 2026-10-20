async (page) => {
  page.setDefaultTimeout(180000);let completed;
  const capture=async r=>{if(/\/jobs\/[^/?]+$/.test(new URL(r.url()).pathname)&&r.ok()){const job=await r.json();if(job.status==='completed')completed=job;}};
  page.on('response',capture);
  await page.getByRole('button',{name:'Слайд — на главную',exact:true}).click();
  const brandbook=page.locator('.brandbook-info');
  if(await brandbook.count())await brandbook.getByRole('button',{name:'Удалить',exact:true}).click();
  for(const name of ['sales.csv','plan.csv','context.txt']) {
    await page.getByRole('button',{name:`Удалить ${name}`,exact:true}).click();
    await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(`samples/business-acceptance/period-context-v1/version-b/${name}`);
    await page.getByRole('textbox',{name:`Цель анализа ${name}`,exact:true}).waitFor();
  }
  await page.getByLabel('Файл условий',{exact:true}).setInputFiles('samples/business-acceptance/period-context-v1/version-b/conditions.json');
  await page.getByRole('combobox',{name:'Файл делового контекста'}).selectOption({label:'context.txt'});
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).waitFor({state:'visible'});
  const prior=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].id);
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  await page.locator('.editor-toolbar').waitFor();
  await page.waitForFunction(prior=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].id!==prior,prior);
  const deck=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0]);
  await page.getByRole('button',{name:/^Слайд 2:/}).click();
  await page.waitForFunction(()=>{const image=document.querySelector('.canvas-holder img');return image?.complete&&image.naturalWidth>0;});
  await page.screenshot({path:'output/playwright/version-b-summary.png',fullPage:true});
  await page.evaluate(({id,job})=>localStorage.setItem('final-design-version-b',JSON.stringify({id,ids:job.presentation_ids,inference:job.inference,job_id:job.id})),{id:deck.id,job:completed});
  page.off('response',capture);
}
