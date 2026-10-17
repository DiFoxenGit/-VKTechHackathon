async page => {
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).waitFor();
  await page.getByLabel('Описание презентации',{exact:true}).fill('Синтетический отчёт для проверки подключения VK. В январе продажи продукта составили 100 руб., в феврале 200 руб. Покажите оба значения и сравните результаты. Данные используются только для демонстрации.');
  await page.getByRole('button',{name:'Настроить',exact:true}).click();
  await page.getByRole('spinbutton',{name:'Количество слайдов'}).fill('1');
  await page.getByRole('button',{name:'Готово',exact:true}).click();
  const submitted=page.waitForResponse(r=>r.url().endsWith('/generations')&&r.request().method()==='POST');
  const completed=page.waitForResponse(r=>/\/api\/v1\/presentations\/[^/?]+$/.test(new URL(r.url()).pathname),{timeout:240000});
  const started=Date.now();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  const response=await submitted;
  if(response.request().postDataJSON().outline)throw new Error('The server model must receive the brief without a client-generated outline');
  const record=await (await completed).json();
  if(record.generation?.provider!=='vk'||record.generation?.mode!=='llm')throw new Error('Real VK pipeline was not used');
  await page.getByRole('button',{name:'Скачать',exact:true}).waitFor();
  await page.getByRole('button',{name:'Скачать',exact:true}).click();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:/PowerPoint/}).click();
  const download=await downloadPromise;
  await download.saveAs('C:/Users/Степан/OneDrive/Документы/ChatGPT/hackaton/output/final/real-vk.pptx');
  const report={provider:record.generation.provider,model:record.generation.model,mode:record.generation.mode,slides:record.deck.slides.length,elapsed_seconds:(Date.now()-started)/1000,audit:record.audit.counts};
  await page.evaluate(r=>localStorage.setItem('final-model-report',JSON.stringify(r)),report);
  return report;
}
