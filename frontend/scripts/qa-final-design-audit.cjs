async (page) => {
  page.setDefaultTimeout(180000);
  await page.setViewportSize({width:1440,height:1000});
  const seed = await page.evaluate(async () => {
    const {presentationService}=await import('/src/services/presentationService.ts');
    const brief={text:'ТЕСТОВАЯ КОПИЯ · выбор исправления аудита',audience:'QA',goal:'Проверить',slideCount:2,templateId:'',materials:''};
    const deck=await presentationService.open('4f02d69fbc4649008872a44ff73d6ee5',brief);
    return {brief:deck.brief,decks:[deck],customTemplates:[]};
  });
  await page.addInitScript(seed=>{
    if(!sessionStorage.getItem('final-audit-seed')) {
      localStorage.setItem('slide-studio:v1',JSON.stringify(seed));sessionStorage.setItem('final-audit-seed','1');
    }
  },seed);
  await page.reload();
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  await page.getByRole('button',{name:'Открыть ТЕСТОВАЯ КОПИЯ · выбор исправления аудита',exact:true}).click();
  await page.getByRole('button',{name:'Скачать',exact:true}).waitFor({state:'visible'});
  await page.locator('.editor-more summary').click();
  await page.getByRole('button',{name:/^Проверка слайдов/}).click();
  await page.getByRole('button',{name:'Проверить смысл моделью',exact:true}).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.audit-check-status')].some(el=>el.textContent.includes('Контекстный аудит: выполнен')));
  const before=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0]);
  await page.getByRole('checkbox',{name:'Исправить оформление: out_of_bounds',exact:true}).first().check();
  await page.screenshot({path:'output/playwright/audit-before-selected.png',fullPage:true});
  await page.getByRole('button',{name:'Применить выбранные (1)',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.audit-result')?.textContent.includes('Ревизия 2.'));
  await page.getByRole('button',{name:'Проверить смысл моделью',exact:true}).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.audit-check-status')].some(el=>el.textContent.includes('Контекстный аудит: выполнен')));
  await page.waitForFunction(()=>{const deck=JSON.parse(localStorage.getItem('slide-studio:v1')||'{}').decks?.[0];return deck?.revision===2&&deck.auditChecks?.contextual?.status==='completed';});
  const after=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks[0]);
  if(before.slides.map(s=>s.body).join('|')!==after.slides.map(s=>s.body).join('|'))throw new Error('Protected facts changed');
  if(!after.serverIssues.some(i=>i.category==='contextual'))throw new Error('Unselected semantic issue disappeared');
  await page.screenshot({path:'output/playwright/audit-after-rechecked.png',fullPage:true});
  await page.getByRole('button',{name:'Скачать',exact:true}).click();
  for(const format of ['PPTX','PDF']) {
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:new RegExp(`^${format==='PPTX'?'PowerPoint':format}`)}).click();
    const file=await download;await file.saveAs(`output/playwright/audit-after-r2.${format.toLowerCase()}`);
  }
  await page.getByRole('button',{name:'Закрыть',exact:true}).click();
  await page.getByRole('button',{name:'Вернуть версию до исправлений',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.audit-result')?.textContent.includes('ревизия 3.'));
  await page.evaluate(({before,after})=>localStorage.setItem('final-design-audit',JSON.stringify({before,after,undo_revision:3,deliberately_injected:true})),{before,after});
}
