async (page) => {
  const out='C:/Users/Степан/OneDrive/Документы/ChatGPT/hackaton/output/playwright';
  await page.locator('.filmstrip-slide').first().click();
  await page.getByLabel('Заголовок',{exact:true}).fill('Развитие продуктов: проверка сохранения');
  await page.locator('.preview-notice').waitFor();
  await page.screenshot({path:out+'/next-unsaved.png',fullPage:true});
  await page.getByRole('button',{name:'Сохранить изменения',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.preview-notice'));
  for(const [format,label] of [['pptx',/PowerPoint/],['pdf',/^PDF/]]){
    await page.getByRole('button',{name:'Скачать',exact:true}).click();
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:label}).click();
    await (await download).saveAs(`${out}/next-saved.${format}`);
    await page.getByRole('button',{name:'Закрыть',exact:true}).click();
  }
  await page.getByLabel('Оформление всей презентации',{exact:true}).selectOption('focus');
  await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.remote===true&&JSON.parse(localStorage.getItem('slide-studio:v1'))?.decks?.[0]?.layout==='focus');
  await page.reload();
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  await page.getByRole('button',{name:/Развитие продуктов/}).first().click();
  if(await page.getByLabel('Заголовок',{exact:true}).inputValue()!=='Развитие продуктов: проверка сохранения')throw new Error('Edit lost after reopen');
  await page.locator('.image-generation-status.unavailable').waitFor();
  await page.screenshot({path:out+'/next-saved-reopened.png',fullPage:true});
}
