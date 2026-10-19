async (page) => {
  const root='C:/Users/Степан/OneDrive/Документы/ChatGPT/VKTechHackathon';
  const out='C:/Users/Степан/OneDrive/Документы/ChatGPT/hackaton/output/playwright';
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.waitForTimeout(1000);
  await page.evaluate(()=>localStorage.removeItem('slide-studio:v1'));
  await page.reload();
  await page.setViewportSize({width:1440,height:900});
  await page.getByLabel('Описание презентации',{exact:true}).fill('Развитие продуктов: выручка, динамика и прибыльность. Синтетический пробник визуальной проверки.');
  await page.getByLabel('Создать новую иллюстрацию в палитре шаблона',{exact:true}).check();
  await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(root+'/output/next-iteration/input/sales.csv');
  await page.locator('.material-card').filter({hasText:'sales.csv'}).waitFor();
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByRole('region',{name:'Анализ данных'}).waitFor();
  await page.locator('.analysis-status').first().waitFor();
  if(await page.locator('.analysis-panel pre').count())throw new Error('Raw JSON in ordinary UI');
  if(await page.locator('.analysis-controls').first().isVisible())throw new Error('Technical controls are not collapsed');
  await page.screenshot({path:out+'/next-raw-probe-1440.png',fullPage:true});
  await page.getByRole('button',{name:'Удалить sales.csv',exact:true}).click();
  for(const name of ['kpi-q3.csv','dynamics.csv','products-q3.csv','economics-q3.csv','context.txt']){
    await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(root+'/output/next-iteration/input/'+name);
    await page.locator('.material-card').filter({hasText:name}).waitFor();
    await page.getByRole('button',{name:'Материалы',exact:true}).waitFor({state:'visible'});
  }
  await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(root+'/samples/content-pack/visual-pack.zip');
  await page.locator('.material-card').filter({hasText:'visual-pack.zip'}).waitFor();
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.locator('.analysis-settings').filter({hasText:'economics-q3.csv'}).waitFor();
  for(const [name,task] of [['kpi-q3.csv','summary'],['dynamics.csv','dynamics'],['products-q3.csv','comparison'],['economics-q3.csv','reference']]){
    const control=page.locator('.analysis-settings').filter({hasText:name});
    await control.locator('summary').click();
    await control.getByLabel(/^Задача /).selectOption(task);
    if(task!=='reference')await control.getByLabel(/^Единица измерения /).fill('руб.');
    await control.locator('summary').click();
  }
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.analysis-status.refused').length===0);
  await page.getByText('Как посчитано',{exact:true}).first().click();
  await page.screenshot({path:out+'/next-analysis-1440.png',fullPage:true});
  await page.setViewportSize({width:1920,height:1080});
  await page.screenshot({path:out+'/next-analysis-1920.png',fullPage:true});
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  await page.getByRole('button',{name:'Скачать',exact:true}).waitFor({timeout:180000});
  await page.locator('.image-generation-status.unavailable').waitFor();
  await page.getByRole('button',{name:'Повторить генерацию картинки',exact:true}).click();
  await page.getByRole('button',{name:'Повторить генерацию картинки',exact:true}).waitFor({state:'visible'});
  await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.imageGeneration?.status==='unavailable');
  const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')));
  if(saved.decks[0].slides.length<10)throw new Error('Visual fixture lost its story pages');
  await page.locator('.filmstrip-slide').nth(saved.decks[0].slides.findIndex(s=>s.analysisId)).click();
  await page.locator('.canvas-holder img').waitFor();
  await page.waitForFunction(()=>{const im=document.querySelector('.canvas-holder img');return im?.complete&&im.naturalWidth>0;},null,{timeout:180000});
  await page.screenshot({path:out+'/next-editor-1920.png',fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.screenshot({path:out+'/next-editor-1440.png',fullPage:true});
  await page.reload();
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  await page.getByRole('button',{name:/Развитие продуктов/}).first().click();
  await page.locator('.image-generation-status.unavailable').waitFor();
  if(errors.length)throw new Error(errors.join('\n'));
  console.log(JSON.stringify({slides:saved.decks[0].slides.length,ordinaryUiWithoutJson:true,advancedCollapsed:true,imageUnavailable:true,reopened:true,viewports:[1440,1920]}));
}
