async (page) => {
  const issues=[];page.on('pageerror',error=>issues.push(error.message));
  const template={id:'qa-model-template',name:'VK Tech',layouts:[]};
  let generation=0;
  const trace=live=>({requested:true,attempted:true,completed:live,provider:'vk',model:'qwen38-27b-fp8',attempts:live?1:2,successful_calls:live?1:0,duration_seconds:1.5,validation:live?'passed':'failed',fallback_used:!live,status:live?'completed':'fallback',error_code:live?null:'provider_error',response_id:live?'controlled-response':null,content_reused_for_variants:live?3:0});
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/templates'))return route.fulfill({json:{items:[template],llm_configured:true}});
    if(path.endsWith('/generations')){generation++;return route.fulfill({json:generation===2?{id:'retry-failed',status:'failed',error:'Провайдер временно недоступен'}:{id:'job-'+generation,status:'completed',presentation_ids:['qa-model-'+generation]}});}
    if(/\/presentations\/qa-model-\d+$/.test(path)){
      const id=path.split('/').pop(),live=id==='qa-model-3';
      return route.fulfill({json:{id,title:live?'Проверенный ответ модели':'Сохранённый расчётный результат',template_id:template.id,variant:'classic',revision:1,generation:{inference:trace(live)},deck:{slides:[{content:{title:'Заголовок из данных',bullets:['Проверенные исходные факты']}}]}}});
    }
    return route.fulfill({status:404,body:''});
  });
  await page.evaluate(()=>localStorage.removeItem('slide-studio:v1'));
  await page.reload();
  await page.getByRole('button',{name:'Питч продукта',exact:true}).click();
  await page.getByRole('button',{name:'Создать презентацию',exact:true}).click();
  await page.getByText('Использован расчётный текст',{exact:true}).waitFor();
  const retry=page.getByRole('button',{name:'Повторить с моделью',exact:true});
  await retry.click();
  await page.getByRole('alert').filter({hasText:'Предыдущая презентация сохранена.'}).waitFor();
  if(await page.getByRole('textbox',{name:'Название презентации'}).inputValue()!=='Сохранённый расчётный результат')throw new Error('Failed retry overwrote the presentation');
  await retry.click();
  await page.getByText('Текст подготовлен моделью',{exact:true}).waitFor();
  await page.waitForFunction(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks.length===2);
  const decks=await page.evaluate(()=>JSON.parse(localStorage.getItem('slide-studio:v1')).decks);
  if(!decks.some(deck=>deck.id==='qa-model-1'&&deck.inference.fallback_used))throw new Error('Previous revision disappeared');
  if(!decks.some(deck=>deck.id==='qa-model-3'&&deck.inference.completed))throw new Error('Validated response missing');
  await page.reload();
  await page.getByRole('button',{name:'Мои презентации',exact:true}).click();
  await page.getByRole('button',{name:'Открыть Сохранённый расчётный результат',exact:true}).click();
  await page.getByText('Использован расчётный текст',{exact:true}).waitFor();
  if(issues.length)throw new Error(issues.join(';'));
  return {status:'passed',scope:'controlled responses, not live Qwen',checks:['visible fallback','failed retry preserves previous deck','validated retry creates new deck','both versions survive reload'],model_requests:generation};
}
