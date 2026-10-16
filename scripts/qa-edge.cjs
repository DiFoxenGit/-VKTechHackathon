async (page) => {
  const passed = [];
  const check = (value, name) => {if (!value) throw new Error(name); passed.push(name);};
  let completed = false;
  const template = {id:'test-tech',name:'VK Tech',layouts:[{index:0,name:'Титул'}]};
  await page.route('**/api/v1/**',async route => {
    const path = new URL(route.request().url()).pathname;
    if(path.endsWith('/templates')) {
      if(route.request().method() === 'POST') {await new Promise(resolve=>setTimeout(resolve,1000));return route.fulfill({json:{...template,id:'custom-1',name:'Мой шаблон'}});}
      return route.fulfill({json:{items:[template]}});
    }
    if(path.endsWith('/generations')) return route.fulfill({json:{id:'long-job',status:'queued'}});
    if(path.endsWith('/jobs/long-job')) return route.fulfill({json:completed?{id:'long-job',status:'completed',presentation_ids:['deck']}:{id:'long-job',status:'running',stage:'outline',progress:17}});
    if(path.endsWith('/presentations/deck')) return route.fulfill({json:{id:'deck',title:'Долгий запрос',template_id:'test-tech',variant:'classic',revision:1,deck:{slides:[{content:{title:'Первый',bullets:['Описание']}}]}}});
    if(path.includes('/export/')) return route.fulfill({contentType:'application/octet-stream',body:'export content'});
    return route.abort();
  });
  await page.goto(page.url());
  await page.getByRole('button',{name:'Питч продукта',exact:true}).click();
  await page.clock.install();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  await page.getByRole('heading',{name:'Собираем структуру',exact:true}).waitFor();
  await page.clock.fastForward(46000);
  await page.getByText(/Генерация занимает больше времени/).waitFor();
  check(await page.getByRole('progressbar').getAttribute('aria-valuenow') === '17','Long wait keeps measured progress');
  await page.screenshot({path:'output/playwright/ux-long-wait.png'});
  completed = true;
  await page.clock.runFor(2000);
  await page.getByRole('button',{name:'Скачать',exact:true}).waitFor();
  await page.getByRole('button',{name:'Скачать',exact:true}).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button',{name:/PowerPoint/}).click();
  check((await download).suggestedFilename() === 'Долгий запрос.pptx','Remote export downloads expected file');
  await page.getByRole('button',{name:'Закрыть',exact:true}).click();
  await page.getByRole('button',{name:'Слайд — на главную'}).click();
  await page.getByRole('button',{name:'Настроить',exact:true}).click();
  await page.getByLabel('Загрузить шаблон PPTX',{exact:true}).setInputFiles({name:'brand.pptx',mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation',buffer:Buffer.from('fixture')});
  await page.getByRole('dialog').getByRole('heading',{name:/Загружаем шаблон|Разбираем оформление/}).waitFor();
  await page.getByRole('button',{name:/Мой шаблон/}).waitFor();
  check(await page.getByRole('button',{name:/Мой шаблон/}).getAttribute('aria-pressed') === 'true','Uploaded template becomes selected');
  await page.getByRole('button',{name:'Готово',exact:true}).click();
  for(const width of [320,768,1024]) {
    await page.setViewportSize({width,height:900});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),`Home fits ${width}px`);
  }
  return {passed:passed.length,results:passed};
}
