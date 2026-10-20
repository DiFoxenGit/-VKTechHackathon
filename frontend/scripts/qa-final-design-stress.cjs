async (page) => {
  page.setDefaultTimeout(180000);
  let completed;
  const capture=async response=>{if(/\/jobs\/[^/?]+$/.test(new URL(response.url()).pathname)&&response.ok()) {const job=await response.json();if(job.status==='completed')completed=job;}};
  page.on('response',capture);
  await page.getByRole('button',{name:'Слайд — на главную',exact:true}).click();
  const input=page.getByLabel('Описание презентации',{exact:true});
  await input.fill((await input.inputValue()).split(' Создай ровно одну абстрактную иллюстрацию')[0]);
  await page.getByRole('combobox',{name:'Новые изображения',exact:true}).selectOption({label:'Не создавать изображения'});
  await page.getByLabel('Загрузить шаблон PPTX',{exact:true}).setInputFiles('output/final-design/synthetic-dark.pptx');
  await page.getByText('Шаблон добавлен:',{exact:false}).first().waitFor();
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).waitFor({state:'visible'});
  const prior=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].id);
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  await page.locator('.editor-toolbar').waitFor();
  await page.waitForFunction(prior=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].id!==prior,prior);
  const first=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0]);
  if(first.slides.length!==12||first.slides[0].role!=='cover')throw new Error('Stress cover/count mismatch');
  await page.getByRole('combobox',{name:'Оформление всей презентации'}).selectOption('focus');
  await page.waitForFunction(()=>{const image=document.querySelector('.canvas-holder img');return image?.src.includes('revision=2')&&image.complete&&image.naturalWidth>0;});
  await page.getByRole('button',{name:'Просмотр',exact:true}).click();
  await page.waitForFunction(()=>{const image=document.querySelector('dialog img');return image?.src.includes('revision=2')&&image.complete&&image.naturalWidth>0;});
  await page.screenshot({path:'output/playwright/stress-modal-r2.png',fullPage:true});
  await page.getByRole('button',{name:'Закрыть',exact:true}).click();
  await page.getByRole('combobox',{name:'Оформление всей презентации'}).selectOption('classic');
  await page.waitForFunction(()=>{const image=document.querySelector('.canvas-holder img');return image?.src.includes('revision=3')&&image.complete&&image.naturalWidth>0;});
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  await page.getByRole('button',{name:`Открыть ${first.title}`,exact:true}).first().click();
  await page.waitForFunction(()=>{const image=document.querySelector('.canvas-holder img');return image?.src.includes('revision=3')&&image.complete&&image.naturalWidth>0;});
  await page.getByRole('button',{name:'Скачать',exact:true}).click();
  for(const format of ['PPTX','PDF']) {
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:new RegExp(`^${format==='PPTX'?'PowerPoint':format}`)}).click();
    const download=await pending;await download.saveAs(`output/playwright/stress-r3.${format.toLowerCase()}`);
  }
  await page.getByRole('button',{name:'Закрыть',exact:true}).click();
  await page.evaluate(({job,id})=>localStorage.setItem('final-design-stress',JSON.stringify({id,ids:job.presentation_ids,inference:job.inference,job_id:job.id,synthetic:true,sha256:'2f5f3a179c94fa937658e4973f2579e391d83e43224a881c0447def6ec0f14dd',saved_revision:3})),{job:completed,id:first.id});
  page.off('response',capture);
}
