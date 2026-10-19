async (page) => {
  page.setDefaultTimeout(120000);
  const data='../samples/business-acceptance';
  const out='../output/playwright';
  const errors=[], jobs=new Map(), report={synthetic:true,runs:[],exports:[]};
  const require=(value,message)=>{if(!value)throw new Error(message);};
  page.on('pageerror',error=>errors.push(error.message));
  page.on('response',async response=>{
    if(/\/jobs\/[^/?]+$/.test(new URL(response.url()).pathname)&&response.ok()){
      const job=await response.json().catch(()=>null);
      if(job?.status==='completed')jobs.set(job.id,job);
    }
  });
  const resumeBaseline=await page.evaluate(()=>{
    const id=localStorage.getItem('qwen-qa-resume');
    return id ? JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.find(deck=>deck.id===id) : null;
  });
  if(!resumeBaseline){
  await page.evaluate(()=>localStorage.removeItem('slide-studio:v1'));
  await page.reload();
  await page.setViewportSize({width:1440,height:900});
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('button')).some(button=>button.textContent.includes('Создать презентацию')&&!button.disabled));
  await page.getByLabel('Описание презентации',{exact:true}).fill('Подготовь для руководителя полный отчёт: чистая выручка, прибыль и маржа за отчётный период, сравнение с прошлым периодом и годом ранее, план-факт, продукты, регионы, каналы и возвраты. Объясни ограничения бюджета и команды по цитатам из контекста. Сформулируй доказанные выводы, отдельно обозначь гипотезы и риски, предложи ответственных, критерии и сроки действий. Числа и источники должны сохраняться при изменении оформления.');
  await page.getByRole('button',{name:'Настроить',exact:true}).click();
  await page.getByRole('spinbutton',{name:'Количество слайдов'}).fill('12');
  await page.getByRole('button',{name:'Готово',exact:true}).click();
  for(const name of ['sales.csv','plan.csv','products.csv','regions.csv','context.txt','content-pack.zip']){
    const folder=['products.csv','regions.csv','content-pack.zip'].includes(name)?'data-v1':'period-context-v1/baseline';
    await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(`${data}/${folder}/${name}`);
    await page.getByRole('textbox',{name:`Цель анализа ${name}`,exact:true}).waitFor({timeout:120000});
  }
  await page.getByRole('checkbox',{name:'Задать периоды и условия бизнес-анализа',exact:true}).check();
  await page.getByText('Загрузить периоды из файла',{exact:true}).click();
  await page.getByLabel('Файл периодов',{exact:true}).setInputFiles(`${data}/period-context-v1/settings.json`);
  await page.getByText('Условия и доказательства из контекста',{exact:true}).click();
  await page.getByLabel('Файл условий',{exact:true}).setInputFiles(`${data}/period-context-v1/baseline/conditions.json`);
  const context=await page.getByRole('combobox',{name:'Файл делового контекста'}).locator('option').allTextContents();
  require(context.includes('context.txt'),'Context source option missing');
  await page.getByRole('combobox',{name:'Файл делового контекста'}).selectOption({label:'context.txt'});
  require(await page.getByLabel('Отчётный период с',{exact:true}).inputValue()==='2026-04','Imported period missing');
  await page.getByRole('checkbox',{name:'Задать периоды и условия бизнес-анализа',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:`${out}/qwen-controls-1440.png`,fullPage:true});
  }else{
    await page.reload();
    await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
    await page.getByRole('button',{name:`Открыть ${resumeBaseline.title}`,exact:true}).first().click();
  }

  async function generate(label,width,height,existing){
    await page.setViewportSize({width,height});
    let secondsToEditor=null;
    if(!existing){
    const previousDeckId=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.id||null);
    await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
    await page.getByRole('region',{name:'Анализ данных',exact:true}).waitFor({timeout:120000});
    const started=Date.now();
    await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
    await page.getByRole('button',{name:'Скачать',exact:true}).waitFor({timeout:300000});
    secondsToEditor=(Date.now()-started)/1000;
    await page.waitForFunction(previous=>{const deck=JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0];return deck?.inference&&deck.id!==previous;},previousDeckId,{timeout:120000});
    }
    if(existing)await page.waitForFunction(id=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.id===id,existing.id);
    await page.getByRole('region',{name:'Участие текстовой модели'}).waitFor();
    await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.inference);
    const deck=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0]);
    require(deck.slides.length===12,'Business slide count');
    require(deck.inference.requested&&deck.inference.attempted&&deck.inference.attempts>0,'Browser did not actually request the model');
    const live=deck.inference.completed&&deck.inference.validation==='passed'&&!deck.inference.fallback_used;
    if(!live)require(deck.inference.fallback_used&&deck.inference.successful_calls===0,'Failure not declared as fallback');
    require(!await page.getByText('Ответ провайдера',{exact:true}).isVisible(),'Diagnostics should stay collapsed');
    await page.getByRole('region',{name:'Участие текстовой модели'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:`${out}/qwen-${label}-${width}.png`,fullPage:true});
    const title=`Q2 ${label}: проверенный отчёт`;
    const titleInput=page.getByRole('textbox',{name:'Название презентации'});
    if(await titleInput.inputValue()!==title)await titleInput.fill(title);
    const saveButton=page.getByRole('button',{name:'Сохранить изменения',exact:true});
    if(await saveButton.isVisible())await saveButton.click();
    await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.revision>=2,null,{timeout:120000});
    await page.getByRole('combobox',{name:'Оформление всей презентации'}).selectOption('story');
    await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.layout==='story'&&JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0].remote,null,{timeout:120000});
    await page.getByRole('button',{name:'Скачать',exact:true}).click();
    for(const format of ['PowerPoint','PDF']){
      const pending=page.waitForEvent('download',{timeout:180000});
      await page.getByRole('button',{name:new RegExp(`^${format}`)}).click();
      const download=await pending;
      const filename=`qwen-${label}.${format==='PDF'?'pdf':'pptx'}`;
      await download.saveAs(`${out}/${filename}`); report.exports.push(filename);
    }
    await page.getByRole('button',{name:'Закрыть',exact:true}).click();
    await page.reload();
    await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
    await page.getByRole('button',{name:`Открыть ${title}`,exact:true}).first().click();
    require(await page.getByRole('textbox',{name:'Название презентации'}).inputValue()===title,'Title lost after reopening');
    require(await page.getByRole('combobox',{name:'Оформление всей презентации'}).inputValue()==='story','Layout lost after reopening');
    await page.waitForFunction(id=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.id===id,deck.id);
    const reopened=await page.evaluate(id=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks.find(d=>d.id===id),deck.id);
    require(JSON.stringify(reopened.inference)===JSON.stringify(deck.inference),'Model evidence changed after saving/reopening');
    require(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),'Horizontal page overflow');
    report.runs.push({label,viewport:{width,height},deck_id:deck.id,slides:12,model_live:live,inference:deck.inference,seconds_to_editor:secondsToEditor,resumed_existing:!!existing,reopened:true});
    return deck;
  }

  const baseline=await generate('baseline',1440,900,resumeBaseline);
  await page.getByRole('button',{name:'Пересчитать из источников',exact:true}).click();
  require(await page.getByLabel('Отчётный период с',{exact:true}).inputValue()==='2026-04','Recalculation lost periods');
  await page.setViewportSize({width:1920,height:1080});
  for(const name of ['sales.csv','plan.csv','context.txt']){
    await page.getByRole('button',{name:`Удалить ${name}`,exact:true}).click();
    await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(`${data}/period-context-v1/version-b/${name}`);
    await page.getByRole('textbox',{name:`Цель анализа ${name}`,exact:true}).waitFor({timeout:120000});
  }
  const conditions=page.getByText('Условия и доказательства из контекста',{exact:true});
  if(!await page.getByLabel('Файл условий',{exact:true}).isVisible())await conditions.click();
  await page.getByLabel('Файл условий',{exact:true}).setInputFiles(`${data}/period-context-v1/version-b/conditions.json`);
  await page.getByRole('combobox',{name:'Файл делового контекста'}).selectOption({label:'context.txt'});
  const versionB=await generate('version-b',1920,1080);
  const kpi=deck=>deck.slides.find(slide=>slide.analysisId?.startsWith('business:kpi:'))?.visual?.series[0]?.values[0];
  require(kpi(baseline)===93563698&&kpi(versionB)===94823698,'Baseline/B independent KPI mismatch');
  require(baseline.id!==versionB.id,'Recalculation overwrote previous deck');
  require(errors.length===0,`Runtime errors: ${errors.join(';')}`);
  report.provider_jobs=Array.from(jobs.values()).map(job=>({id:job.id,inference:job.inference}));
  report.runtime_errors=errors;report.status='passed';
  await page.evaluate(value=>{localStorage.setItem('qwen-ui-report',JSON.stringify(value));localStorage.removeItem('qwen-qa-resume');},report);
  return report;
}
