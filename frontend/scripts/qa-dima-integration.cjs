async (page) => {
  await page.setViewportSize({width:1440,height:1100});
  await page.getByRole('button',{name:'Настроить',exact:true}).click();
  await page.getByLabel('Загрузить шаблон PPTX',{exact:true}).setInputFiles('C:/Users/Степан/Downloads/Датасет/VK Tech шаблон.pptx');
  await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Загрузить свой')?.disabled,null,{timeout:120000});
  await page.getByRole('button',{name:'Готово',exact:true}).click();
  await page.getByLabel('Описание презентации',{exact:true}).fill('Распределение заказов. Синтетические данные для проверки интеграции.');
  await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles('C:/Users/Степан/OneDrive/Документы/ChatGPT/VKTechHackathon/samples/analytics/datasets/04-orders.csv');
  await page.getByRole('textbox',{name:'Цель анализа 04-orders.csv',exact:true}).fill('Распределение');
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByRole('region',{name:'Анализ данных'}).waitFor();
  await page.getByRole('region',{name:'Анализ данных'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:'C:/Users/Степан/OneDrive/Документы/ChatGPT/hackaton/output/playwright/dima-before-selection.png',fullPage:true});

  await page.getByRole('checkbox',{name:'amount',exact:true}).check();
  await page.getByRole('textbox',{name:/^Единица измерения /}).fill('RUB');
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByText('60 строк · 3 колонок · Гистограмма',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();

  await page.getByRole('button',{name:'Скачать',exact:true}).waitFor({timeout:120000});
  await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.analysis?.[0]?.contract?.schema_version==='1.0');
  const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')));
  const result=saved.decks[0].analysis[0];
  if(result.contract.analysis.metrics.join(',')!=='c2')throw new Error('Explicit metric was lost');
  if(result.contract.presentation.unit!=='RUB')throw new Error('Explicit unit was lost');
  const median=result.contract.facts.find(f=>f.evidence.operation==='median');
  if(median.value!==533.5)throw new Error('Wrong median');
  await page.screenshot({path:'C:/Users/Степан/OneDrive/Документы/ChatGPT/hackaton/output/playwright/dima-editor.png',fullPage:true});
  await page.getByRole('combobox',{name:'Оформление всей презентации'}).selectOption('focus');
  await page.getByRole('button',{name:'Скачать',exact:true}).click();
  const promise=page.waitForEvent('download');
  await page.getByRole('button',{name:/PowerPoint/}).click();
  const download=await promise;
  await download.saveAs('C:/Users/Степан/OneDrive/Документы/ChatGPT/hackaton/output/playwright/dima-edited.pptx');
  await page.evaluate(report=>localStorage.setItem('dima-ui-report',JSON.stringify(report)),{contract:'1.0',refusalResolvedByUserMetric:true,metric:'c2',unit:'RUB',median:median.value,download:'dima-edited.pptx'});
}
