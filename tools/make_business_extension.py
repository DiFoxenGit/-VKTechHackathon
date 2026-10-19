"""Explicit Q2 request + freely headed context + independent answers and version B."""
import copy
import csv
import json
import re
import sys
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from designer.analytics.business import build_business_analysis
from designer.analytics.business_story import build_business_story,_context
from designer.analytics.business_periods import BusinessPeriods
from designer.analytics.business_conditions import ContextConditions
from business_reference import calculate


def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')


def load(directory,name):
    with (directory/(name+'.csv')).open(encoding='utf8',newline='') as stream:return list(csv.DictReader(stream))


def write_csv(path,rows):
    with path.open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)


def build(output):
    output.mkdir(parents=True,exist_ok=True)
    data=ROOT/'samples/business-acceptance/data-v1'
    settings=BusinessPeriods(current=('2026-04','2026-06'),previous=('2026-01','2026-03'),year_ago=('2025-04','2025-06'),history=('2025-01','2026-06'))
    original=(data/'business-context.txt').read_text(encoding='utf8')
    headings=['Компания','Решение руководителя','События','Ресурсы','Клиенты','Определения','Риски','Вопросы']
    sections={k:re.sub(r'^\d\. .+','## '+headings[int(k)-1],v).replace('IV квартала','следующего квартала').replace('октябрь — декабрь','июль — сентябрь') for k,v in _context(original).items()}
    period_quote='Отчётный период: 2026-04 — 2026-06.'
    context='СИНТЕТИЧЕСКИЙ СЦЕНАРИЙ. Изменённые заголовки не являются инструкциями модели.\n'+period_quote+'\n\n'+'\n\n'.join(sections.values())+'\n'
    def bound(value,quote):return {'value':value,'quote':quote}
    conditions={'sections':sections,'reporting_period':bound(list(settings.current),period_quote),'channel_event':None,
        'budget':{'total':bound(3000000,'не более 3 000 000 рублей'),
                  'partners':bound(600000,'партнёрской экономики — 600 000 рублей'),
                  'implementation':bound(900000,'аналитики — 900 000 рублей'),
                  'regions':bound(500000,'региональных гипотез — 500 000 рублей'),
                  'reserve':bound(1000000,'резерв — 1 000 000 рублей')},
        'capacity':{'max_parallel_implementations':bound(2,'не более двух параллельных внедрений'),
                    'engineers':bound(2,'двумя инженерами внедрения'),'analysts':bound(1,'одним аналитиком')},
        'owners':{'partners':bound('Коммерческий директор','Коммерческий директор отвечает за условия скидок'),
                  'implementation':bound('Руководитель продукта','Руководитель продукта определяет готовность внедрения'),
                  'regions':bound('Региональные руководители','Региональные руководители уточняют плановые предпосылки')}}
    dump(output/'settings.json',settings.model_dump(mode='json'))
    dump(output/'conditions.schema.json',ContextConditions.model_json_schema())
    dump(output/'periods.schema.json',BusinessPeriods.model_json_schema())
    sources=[load(data,n) for n in ('sales','plan','products','regions')]
    for name in ('baseline','version-b'):
        folder=output/name;folder.mkdir(exist_ok=True)
        rows=copy.deepcopy(sources);text=context;contract=copy.deepcopy(conditions);changes=[]
        if name=='version-b':
            for index,row in enumerate(rows[0],2):
                if '2026-04'<=row['month']<='2026-06' and row['product_id']=='P2' and row['channel']=='partners':
                    before={k:row[k] for k in ('gross_revenue_rub','cogs_rub')}
                    row['gross_revenue_rub']=str(int(row['gross_revenue_rub'])+70000)
                    row['cogs_rub']=str(int(row['cogs_rub'])+15000)
                    changes.append({'row':index,'before':before,'after':{k:row[k] for k in before}})
            replacements={'не более двух параллельных внедрений':('до 1 параллельных внедрений',1),
                          'двумя инженерами внедрения':('тремя инженерами внедрения',3),
                          'одним аналитиком':('двумя аналитиками',2)}
            for old,(new,value) in replacements.items():
                text=text.replace(old,new)
                for slot in contract['capacity'].values():
                    if slot['quote']==old:slot.update(value=value,quote=new)
                contract['sections']={k:v.replace(old,new) for k,v in contract['sections'].items()}
        write_csv(folder/'sales.csv',rows[0]);write_csv(folder/'plan.csv',rows[1])
        (folder/'context.txt').write_text(text,encoding='utf8',newline='\n')
        dump(folder/'conditions.json',contract);dump(folder/'changes.json',changes)
        expected=calculate(folder,periods=settings.periods());dump(folder/'expected-results.json',expected)
        analysis=build_business_analysis(*rows,settings=settings)
        for answer in expected['answers']:
            if analysis['facts'][answer['id']]['exact']!=answer['exact']:raise ValueError(answer['id'])
        dump(folder/'analysis.json',analysis)
        dump(folder/'story.json',build_business_story(analysis,text,conditions=contract))
    dump(output/'context-controls.json',{'baseline':{'engineers':2,'analysts':1,'max_parallel_implementations':2},
        'version-b':{'engineers':3,'analysts':2,'max_parallel_implementations':1},
        'net_delta_rub':1260000,'profit_delta_rub':990000,'synthetic':True,
        'source_dictionaries':'../data-v1/products.csv and regions.csv; sales and plan copied for standalone oracle replay'})
    entries={str(p.relative_to(output)).replace('\\','/'):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
             for p in sorted(output.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    dump(output/'manifest.json',{'synthetic':True,'version':'period-context-1','files':entries,
        'dictionary_sources':{name:hashlib.sha256((data/(name+'.csv')).read_bytes()).hexdigest() for name in ('products','regions')}})


if __name__=='__main__':build(ROOT/'samples/business-acceptance/period-context-v1')
