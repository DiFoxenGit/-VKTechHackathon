async (page) => {
  await page.getByRole('button',{name:'Слайд — на главную',exact:true}).click();
  const input=page.getByLabel('Описание презентации',{exact:true});
  const text=await input.inputValue();
  await input.fill(text+' Создай ровно одну абстрактную иллюстрацию на слайде 11 справа: проверка рисков инфраструктуры. Без экранов, документов, букв, цифр и диаграмм внутри изображения.');
  await page.getByRole('combobox',{name:'Новые изображения',exact:true}).selectOption({label:'Добавить изображения'});
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).waitFor({state:'visible'});
  if ((await page.locator('.batch-generation').getAttribute('open'))===null) await page.locator('.batch-generation summary').click();
  await page.screenshot({path:'output/playwright/final-design-image-request.png',fullPage:true});
}
