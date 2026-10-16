async (page) => {
  const results = [];
  const check = (value, name) => { if (!value) throw new Error(name); results.push(name); };
  const brief = {text:'Описание тестового проекта для команды',audience:'Коллеги и команда',goal:'Представить идею',slideCount:3,templateId:'qa-tech',materials:'',contentPackIds:[]};
  const slides = [
    {id:'one',title:'Первый',body:'Главная мысль',kind:'cover'},
    {id:'two',title:'Второй',body:'Результат',kind:'content'},
    {id:'three',title:'Третий',body:'Следующий шаг',kind:'closing'},
  ];
  const saved = {brief,decks:[{id:'qa-deck',title:'Проект QA',slides,templateId:'qa-tech',layout:'classic',updatedAt:new Date().toISOString(),brief,remote:false}],customTemplates:[]};
  await page.addInitScript(({key,saved}) => {
    if(!sessionStorage.getItem(key)) { localStorage.setItem('slide-studio:v1',JSON.stringify(saved)); sessionStorage.setItem(key,'1'); }
  }, {key:'qa-editor-'+Date.now(),saved});
  await page.route('**/api/v1/templates',route=>route.fulfill({json:{items:[{id:'qa-tech',name:'VK Tech',layouts:[{index:0,name:'Титул'}]}]}}));
  await page.goto(page.url());
  await page.getByRole('button',{name:/Проект QA 3 слайда/}).click();
  await page.getByRole('textbox',{name:'Заголовок',exact:true}).fill('Изменённый заголовок');
  await page.getByRole('textbox',{name:'Основной текст',exact:true}).fill('Обновлённый текст');
  check(await page.locator('.canvas-holder').getByRole('heading',{name:'Изменённый заголовок'}).isVisible(),'Editing updates visible canvas');
  await page.getByRole('button',{name:'Дублировать слайд',exact:true}).click();
  check(await page.locator('.filmstrip-slide').count() === 4,'Duplicate adds one slide');
  await page.getByRole('button',{name:'Опустить текущий слайд',exact:true}).click();
  check(await page.locator('.filmstrip-slide').nth(2).getAttribute('aria-pressed') === 'true','Move keeps moved slide selected');
  await page.getByRole('button',{name:'Удалить текущий слайд',exact:true}).click();
  await page.getByRole('button',{name:'Вернуть слайд',exact:true}).click();
  check(await page.locator('.filmstrip-slide').count() === 4,'Undo restores duplicate');
  await page.getByRole('button',{name:'Слайд',exact:true}).click();
  check(await page.getByRole('textbox',{name:'Заголовок',exact:true}).inputValue() === 'Новый слайд','Add selects new slide');
  await page.locator('summary').click();
  await page.getByRole('button',{name:'Структура слайдов',exact:true}).click();
  await page.getByRole('textbox',{name:'Заголовок слайда 2',exact:true}).fill('Структура QA');
  await page.getByRole('button',{name:'Поднять слайд 2',exact:true}).click();
  check(await page.getByRole('textbox',{name:'Заголовок слайда 1',exact:true}).inputValue() === 'Структура QA','Outline reorders edited content');
  await page.getByRole('button',{name:'Выбрать дизайн',exact:true}).click();
  await page.getByRole('button',{name:/Выразительный/}).click();
  await page.getByRole('button',{name:'Открыть редактор',exact:true}).click();
  check(await page.locator('.canvas-holder .layout-story').count() === 1,'Design choice reaches editor');
  await page.getByRole('combobox',{name:'Оформление всей презентации'}).selectOption('focus');
  check(await page.locator('.canvas-holder .layout-focus').count() === 1,'Editor layout selector updates canvas');
  await page.getByRole('textbox',{name:'Заголовок',exact:true}).fill('');
  await page.locator('summary').click();
  await page.getByRole('button',{name:/Проверка слайдов/}).click();
  check(await page.getByRole('heading',{name:'Проверка слайдов',exact:true}).isVisible(),'Audit opens with current content');
  check(await page.locator('.audit-item').count() > 0,'Audit finds invalid content');
  await page.getByRole('button',{name:'Закрыть проверку',exact:true}).click();
  await page.getByRole('textbox',{name:'Заголовок',exact:true}).fill('Сохранённая структура');
  await page.getByRole('textbox',{name:'Название презентации',exact:true}).fill('Сохранённый проект');
  await page.waitForTimeout(750);
  await page.reload();
  await page.getByRole('button',{name:/Сохранённый проект 5 слайдов/}).click();
  check(await page.getByRole('textbox',{name:'Заголовок',exact:true}).inputValue() === 'Сохранённая структура','Reload preserves text and slide order');
  check(await page.locator('.canvas-holder .layout-focus').count() === 1,'Reload preserves layout');
  await page.getByRole('button',{name:'Просмотр',exact:true}).click();
  check(await page.evaluate(()=>Boolean(document.activeElement?.closest('dialog'))),'Preview focuses dialog');
  await page.keyboard.press('ArrowLeft');
  check(await page.getByRole('dialog',{name:'Слайд 1 из 5'}).isVisible(),'Preview prevents moving before first slide');
  await page.keyboard.press('Escape');
  for(const width of [320,390,600,768,1024,1440]) {
    await page.setViewportSize({width,height:900});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),`Editor fits ${width}px`);
  }
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  await page.getByPlaceholder('Найти презентацию').fill('нет такого');
  await page.getByRole('heading',{name:'Ничего не нашлось'}).waitFor();
  await page.getByRole('button',{name:'Очистить поиск',exact:true}).click();
  check(await page.getByRole('button',{name:'Открыть Сохранённый проект',exact:true}).isVisible(),'Search clears and restores results');
  await page.getByRole('button',{name:'Удалить презентацию Сохранённый проект',exact:true}).click();
  await page.getByRole('button',{name:'Оставить',exact:true}).click();
  check(await page.getByRole('button',{name:'Открыть Сохранённый проект',exact:true}).isVisible(),'Delete dialog can be cancelled');
  await page.getByRole('button',{name:'Удалить презентацию Сохранённый проект',exact:true}).click();
  await page.getByRole('button',{name:'Удалить',exact:true}).click();
  await page.getByRole('heading',{name:'Здесь будут ваши презентации'}).waitFor();
  await page.waitForTimeout(750);
  await page.reload();
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  check(await page.getByRole('heading',{name:'Здесь будут ваши презентации'}).isVisible(),'Deleted project stays deleted after reload');
  return {passed:results.length,results};
}
