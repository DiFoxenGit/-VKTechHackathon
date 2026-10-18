"""Build Dima's draft integration artifacts, never a slide deck or live service run."""
import csv
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from designer.analytics.business import build_business_analysis, explain_business
from business_reference import calculate


def load(directory,name):
    with (directory/(name+'.csv')).open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def build(directory):
    rows=[load(directory,n) for n in ('sales','plan','products','regions')]
    result=build_business_analysis(*rows)
    expected=calculate(directory)
    comparisons=[]
    for answer in expected['answers']:
        actual=result['facts'][answer['id']]['exact']
        assert actual==answer['exact'],(answer['id'],actual,answer['exact'])
        comparisons.append({'id':answer['id'],'exact_match':True})
    output=directory.parent/'review-v1';output.mkdir(exist_ok=True)
    write(output/'business-analysis.json',result)
    write(output/'reference-comparison.json',comparisons)
    definitions=[
        ('decision','Как распределить усилия в IV квартале?',['qoq_net_growth','qoq_margin_change'],'quarter_kpi','Разделить расширение продаж и проверку экономики; причинность не установлена.'),
        ('kpi','Каковы результаты III квартала?',['q3_net','q3_profit','q3_margin'],'quarter_kpi','Маржа — отношение сумм, а не среднее строковых процентов.'),
        ('trend','Сохраняется ли рост?',['qoq_net_growth','yoy_net_growth'],'monthly_trend','Кварталы закрыты полностью; прошлогодняя сезонность не является прогнозом.'),
        ('plan','Выполнены ли утверждённые цели?',['q3_net_plan_attainment','q3_profit_plan_attainment'],'plan_actual','План посчитан один раз по месяцу, региону и продукту; плана по каналам нет.'),
        ('products','Какие продукты изменили выручку?',['best_product_contribution','worst_product_contribution'],'product_contribution','Вклад — абсолютная разница к II кварталу, а не темп роста.'),
        ('regions','Где проверить региональные предпосылки?',['worst_region_plan_gap'],'region_plan_gap','Показано абсолютное отклонение от плана, а не вклад региона в квартальный рост.'),
        ('channels','Где рост требует проверки экономики?',['partners_net_growth','partners_margin_change'],'channel_profitability','Изменение условий программы — событие контекста; его причинный эффект не доказан.'),
        ('concentration','Насколько результат зависит от ведущего продукта?',['top_product_revenue_share'],'product_structure','Доля рассчитана по net-выручке; концентрация не доказывает риск оттока.'),
        ('returns','Какова нагрузка возвратов?',['q3_refund_share'],'refunds','Знаменатель — выручка до скидок и возвратов, не net.'),
        ('priorities','Какие направления обсудить первыми?',['q3_profit','best_product_contribution'],'priorities','Приоритеты — предложение; эффект инвестиций не рассчитан.'),
        ('risks','Какие ограничения меняют решение?',['partners_margin_change','worst_region_plan_gap'],None,'Нет данных для CAC, удержания и причинной оценки рекламы. Не более двух параллельных внедрений.'),
        ('actions','Что проверить за 90 дней?',['q3_margin','q3_net_plan_attainment'],None,'Лимит 3 млн RUB; предлагаемые потолки 0,6/0,9/0,5 млн, резерв 1 млн. Это не прогноз эффекта.'),
    ]
    def display(identifier):
        f=result['facts'][identifier]
        value='не определено' if f['exact'] is None else str(Decimal(f['exact']).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
        return value+' '+f['unit']
    labels=dict(zip([a['id'] for a in expected['answers']],['Чистая выручка','Валовая прибыль','Валовая маржа',
        'Рост выручки к II кварталу','Рост выручки к III кварталу 2025','Выполнение плана выручки','Выполнение плана прибыли',
        'Наибольший вклад продукта','Наименьший вклад продукта','Наибольшее отрицательное отклонение региона',
        'Доля ведущего продукта','Рост выручки партнёров','Изменение маржи партнёров','Доля возвратов от gross-выручки','Изменение общей маржи']))
    slides=[]
    context_sections={'decision':2,'kpi':6,'trend':3,'plan':6,'products':1,'regions':3,'channels':3,
                      'concentration':5,'returns':6,'priorities':7,'risks':7,'actions':4}
    for i,(identifier,question,facts,view,caveat) in enumerate(definitions,1):
        slides.append(dict(id=identifier,position=i,purpose=question,
            answer='; '.join(labels[k]+': '+display(k) for k in facts),fact_ids=facts,view_id=view,
            interpretation=caveat,context_refs=['business-context.txt#'+str(context_sections[identifier])],
            statement_kind='proposal' if identifier in ('decision','priorities','actions') else 'observation',
            suggested_asset_role={'products':'product_image','channels':'process','actions':'generated_illustration'}.get(identifier,'none'),
            action={'owner_role':'Коммерческий директор','deadline':'2026-12-31',
                'criterion':'Сверены фактические маржа и план по согласованным определениям; соблюдён бюджет'} if identifier=='actions' else None))
    write(output/'story-plan.json',{'status':'draft_for_agreement','slides':slides,'appendix':{
        'full_data':'../data-v1/sales.csv','catalog':'../data-v1/catalog.csv','do_not_append_all_raw_rows':True}})
    write(output/'four-examples.json',{'status':'content_examples_not_visual_acceptance','examples':[
        {'type':kind,'slide':slides[index],'analysis':result['views'][view], 'lineage':result['lineage'][view],
         'explanation':{'ru':explain_business('view.'+('comparison' if kind=='comparison' else kind)),
                        'en':explain_business('view.'+('comparison' if kind=='comparison' else kind),locale='en')}}
        for kind,index,view in [('kpi',1,'quarter_kpi'),('trend',2,'monthly_trend'),
                               ('comparison',4,'product_contribution'),('table',9,'priorities')]],
         'actions':[
             {'action':'Проверить партнёрские скидки и себестоимость','owner_role':'Коммерческий директор и финансовый контролёр',
              'deadline':'2026-10-31','budget_cap_rub':600000,'context_ref':'business-context.txt#4',
              'criterion':'Согласованы определения и условия; представлены маржа до и после изменений без причинных обещаний'},
             {'action':'Проверить готовность внедрения аналитики','owner_role':'Руководитель продукта','deadline':'2026-11-30',
              'budget_cap_rub':900000,'context_ref':'business-context.txt#4','criterion':'Согласована очередь внедрений; одновременно не более двух интеграционных проектов'},
             {'action':'Проверить региональные предпосылки плана','owner_role':'Региональные директора','deadline':'2026-12-31',
              'budget_cap_rub':500000,'context_ref':'business-context.txt#4','criterion':'Подготовлены предпосылки по шести регионам; исходный план сохранён для сравнения'}]})
    return result


if __name__=='__main__':
    build(ROOT/'samples/business-acceptance/data-v1')
