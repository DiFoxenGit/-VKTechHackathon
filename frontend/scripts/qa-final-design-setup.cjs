async (page) => {
  page.setDefaultTimeout(120000);
  await page.setViewportSize({width:1440,height:1000});
  await page.reload();
  await page.getByRole('button',{name:'Настроить',exact:true}).click();
  await page.getByRole('spinbutton',{name:'Количество слайдов'}).fill('12');
  await page.getByRole('button',{name:'Готово',exact:true}).click();
  await page.getByLabel('Описание презентации',{exact:true}).fill('Подготовьте управленческий отчёт для коммерческого директора и руководителя продукта. Покажите чистую выручку, валовую прибыль, маржу, план-факт, вклад продуктов и регионов, экономику каналов и возвраты. Разделите подтверждённые выводы и гипотезы. Сохраните бюджет, владельцев и ограничения из делового контекста.');
  const templates='C:/Users/Степан/.codex/worktrees/stepa-final-qwen/hackaton/templates';
  await page.getByLabel('Загрузить шаблон PPTX',{exact:true}).setInputFiles(`${templates}/VK Tech шаблон.pptx`);
  await page.getByText('Шаблон добавлен:',{exact:false}).first().waitFor();
  for(const name of ['sales.csv','plan.csv','products.csv','regions.csv','context.txt','content-pack.zip']) {
    const folder=['products.csv','regions.csv','content-pack.zip'].includes(name)?'data-v1':'period-context-v1/baseline';
    await page.getByLabel('Загрузить материалы',{exact:true}).setInputFiles(`samples/business-acceptance/${folder}/${name}`);
    await page.getByRole('textbox',{name:`Цель анализа ${name}`,exact:true}).waitFor();
  }
  await page.getByRole('checkbox',{name:'Задать периоды и условия бизнес-анализа',exact:true}).check();
  await page.getByText('Загрузить периоды из файла',{exact:true}).click();
  await page.getByLabel('Файл периодов',{exact:true}).setInputFiles('samples/business-acceptance/period-context-v1/settings.json');
  await page.getByText('Условия и доказательства из контекста',{exact:true}).click();
  await page.getByLabel('Файл условий',{exact:true}).setInputFiles('samples/business-acceptance/period-context-v1/baseline/conditions.json');
  await page.getByRole('combobox',{name:'Файл делового контекста'}).selectOption({label:'context.txt'});
  await page.getByRole('combobox',{name:'Новые изображения',exact:true}).selectOption({label:'Не создавать изображения'});
  await page.getByRole('button',{name:'Проверить данные',exact:true}).click();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).waitFor({state:'visible'});
  await page.screenshot({path:'output/playwright/final-design-inputs.png',fullPage:true});
  console.log('Real template and full synthetic business inputs uploaded through UI; analysis prepared; images disabled for first design pass.');
}
