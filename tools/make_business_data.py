"""Reproducible synthetic business acceptance inputs; no model or network calls."""
import copy
import csv
import hashlib
import io
import json
import random
import zipfile
from pathlib import Path
from business_reference import calculate

ROOT=Path(__file__).resolve().parents[1]
SEED=20261018
SALES=['month','region_id','product_id','channel','gross_revenue_rub','discount_rub','refund_rub','cogs_rub','orders_count','currency']
PLAN=['month','region_id','product_id','net_revenue_plan_rub','gross_profit_plan_rub','currency']


def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def write_csv(path, columns, rows):
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream,lineterminator='\n');writer.writerow(columns);writer.writerows(rows)


def stable_zip(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED) as archive:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.create_system=3
            info.external_attr=0o600<<16
            archive.writestr(info,data)
    return stream.getvalue()


def build(output):
    output.mkdir(parents=True,exist_ok=True)
    rng=random.Random(SEED)
    months=[f'{year}-{m:02}' for year in (2025,2026) for m in range(1,13) if year==2025 or m<=9]
    sales=[]
    season=[82,86,100,103,108,114,107,111,124,120,132,148]
    for t,month in enumerate(months):
        for region in range(6):
            for product in range(4):
                for channel in range(3):
                    growth=[2,4,1,-1][product]
                    base=(220000+region*21000+product*47000)*(120 if region==0 else 100)//100
                    gross=base*season[t%12]*(100+t*growth)//10000+rng.randrange(1000,14000)
                    if t>=18 and channel==2:
                        gross=gross*145//100
                    discount=gross*[2,4,9][channel]//100
                    refund=gross*(1+(region+product+t)%4)//100
                    net=gross-discount-refund
                    margin=[36,48,28,19][product]+[2,0,-5][channel]-(3 if region==5 else 0)
                    if t>=18 and channel==2:
                        margin-=13
                    cogs=net*(100-margin)//100
                    orders=max(1,gross//(17000+product*2500))
                    sales.append([month,f'R{region+1}',f'P{product+1}', ['direct','online','partners'][channel],gross,discount,refund,cogs,orders,'RUB'])
    plans=[]
    for m in range(1,13):
        for region in range(6):
            for product in range(4):
                # Fixed ex-ante targets depend on assumptions, not realized quarterly totals.
                target=(220000+region*21000+product*47000)*season[m-1]*3//100
                target=target*(160 if region==5 else 130)//100
                plans.append([f'2026-{m:02}',f'R{region+1}',f'P{product+1}',target,target*[30,40,24,18][product]//100,'RUB'])
    products=[['P1','Операции','Командный портал','Единый рабочий кабинет продаж','Средний бизнес','Внедрение до 4 недель'],
              ['P2','Аналитика','Аналитика сделок','Воронка и отчётность руководителя','Растущие B2B-команды','Нужны согласованные справочники'],
              ['P3','Интеграции','Интеграционный шлюз','Обмен заказами между системами','Компании с несколькими системами','Не более 2 параллельных внедрений'],
              ['P4','Поддержка','Сервис сопровождения','Поддержка пользователей и процессов','Действующие клиенты','Ограничен штат сопровождения']]
    regions=[['R1','Москва и Московская область','Директор центральных продаж','Высокая концентрация выручки'],
             ['R2','Санкт-Петербург и Ленинградская область','Директор северо-западных продаж','Длинный цикл согласований'],
             ['R3','Поволжье','Директор региональных продаж','Ограничен ресурс внедрения'],
             ['R4','Уральский федеральный округ','Директор региональных продаж','Разница часовых поясов'],
             ['R5','Сибирь и Дальневосточный федеральный округ','Директор восточных продаж','Удалённое сопровождение'],
             ['R6','Южный и Северо-Кавказский федеральные округа','Директор южных продаж','Проверить завышенный план']]
    catalog=[]
    functions=['Пользователи','Хранилище','Интеграции','Отчётность','Сопровождение']
    levels=['Старт','Команда','Бизнес','Корпорация']
    for p in range(4):
        for f,feature in enumerate(functions):
            for level,tier in enumerate(levels):
                for duration in (1,6,12):
                    catalog.append([f'OPT-{p+1}{f+1}{level+1}-{duration:02}',f'P{p+1}',feature,tier,duration,
                                    (p+1)*(f+1)*(level+1)*900*duration,'RUB','Тарифная опция, не детализация продаж'])
    tables={'sales':(SALES,sales),'plan':(PLAN,plans),
        'products':(['product_id','group','name','description','audience','constraint'],products),
        'regions':(['region_id','name','owner_role','constraint'],regions),
        'catalog':(['option_id','product_id','feature','tier','term_months','list_price_rub','currency','note'],catalog)}
    for name,(columns,rows) in tables.items():write_csv(output/f'{name}.csv',columns,rows)
    (output/'business-context.txt').write_bytes((ROOT/'samples/business-acceptance/business-context.txt').read_bytes())
    (output/'data-dictionary.md').write_bytes((ROOT/'samples/business-acceptance/data-dictionary.md').read_bytes())
    # Existing team material; preserve originals, retain provenance and intended use.
    source_pack=ROOT/'samples/content-pack/visual-pack.zip'
    with zipfile.ZipFile(source_pack) as archive:
        chosen=['illustrations/data.svg','illustrations/discussion.svg','illustrations/plan.svg',
                'icons/plug.svg','icons/support.svg','icons/target.svg']
        assets={name:archive.read(name) for name in chosen}
        meta=json.loads(archive.read('manifest.json'))
        manifest={'name':'Бизнес-сценарий: существующие командные материалы','version':1,
            'source':'samples/content-pack/visual-pack.zip','source_sha256':hashlib.sha256(source_pack.read_bytes()).hexdigest(),
            'assets':[{**a,'provenance':'existing_team_pack','role':'illustration' if a['file'].startswith('illustrations/') else 'icon'}
                      for a in meta['assets'] if a['file'] in chosen]}
        assets['manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
        (output/'content-pack.zip').write_bytes(stable_zip(assets))
    dump(output/'sales.json',[dict(zip(SALES,r)) for r in sales])
    fragment=[r for r in sales if r[0] in ('2026-06','2026-07','2026-09') and r[1]=='R1' and r[2] in ('P1','P2')]
    write_csv(output/'representative-fragment.csv',SALES,fragment)
    (output/'sales-table.md').write_text('# Доли каналов: сентябрь 2026, Москва, Командный портал\n\n'+
        '|'+ '|'.join(SALES)+'|\n|'+ '|'.join(['---']*len(SALES))+'|\n'+
        ''.join('|'+ '|'.join(map(str,r))+'|\n' for r in sales if r[:3]==['2026-09','R1','P1']),encoding='utf-8',newline='\n')
    # Data fixture workbook, not a presentation or financial model. No formula caches needed.
    from openpyxl import Workbook
    workbook=Workbook();workbook.remove(workbook.active)
    for name,(columns,rows) in tables.items():
        sheet=workbook.create_sheet(name);sheet.append(columns)
        for row in rows:sheet.append(row)
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for column in sheet.columns:sheet.column_dimensions[column[0].column_letter].width=24
    workbook.properties.created=workbook.properties.modified=__import__('datetime').datetime(2026,10,18)
    stream=io.BytesIO();workbook.save(stream)
    with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as archive:
        entries={n:archive.read(n) for n in archive.namelist()}
    # openpyxl rewrites modified metadata on save; normalize it for reproducibility.
    import re
    entries['docProps/core.xml']=re.sub(rb'<dcterms:modified[^>]*>.*?</dcterms:modified>',
        b'<dcterms:modified xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="dcterms:W3CDTF">2026-10-18T00:00:00Z</dcterms:modified>',entries['docProps/core.xml'])
    (output/'business-data.xlsx').write_bytes(stable_zip(entries))
    dump(output/'expected-results.json',calculate(output))
    mutations=[]
    revised=copy.deepcopy(sales)
    for i,row in enumerate(revised):
        if row[0]>='2026-07' and row[2]=='P2' and row[3]=='partners':
            before=row[4];row[4]+=70000;row[7]+=15000
            mutations.append(dict(source_row=i+2,key=row[:4],changes={'gross_revenue_rub':[before,row[4]],'cogs_rub':[sales[i][7],row[7]]}))
    updated=output/'updated';updated.mkdir(exist_ok=True)
    write_csv(updated/'sales.csv',SALES,revised);write_csv(updated/'plan.csv',PLAN,plans)
    dump(updated/'changes.json',mutations);dump(updated/'expected-results.json',calculate(updated))
    scenarios={
        'missing_value':('business.missing_value',lambda r:r[0].__setitem__(4,'')),
        'duplicate_key':('business.duplicate_key',lambda r:r.append(copy.deepcopy(r[0]))),
        'mixed_currency':('business.currency',lambda r:r[0].__setitem__(9,'USD')),
        'negative_adjustment':('business.negative_component',lambda r:r[0].__setitem__(6,-100)),
        'ambiguous_number':('business.invalid_number',lambda r:r[0].__setitem__(4,'1,234')),
        'zero_denominator':('business.zero_denominator',lambda r:[x.__setitem__(4,x[5]+x[6]) for x in r if '2026-07'<=x[0]<='2026-09']),
    }
    negative=output/'negative';negative.mkdir(exist_ok=True)
    for name,(_,mutate) in scenarios.items():
        rows=copy.deepcopy(sales);mutate(rows);write_csv(negative/f'{name}.csv',SALES,rows)
    dump(negative/'expected-behaviour.json',{n:{'code':code,'behaviour':'refuse' if n!='zero_denominator' else 'null ratios with warning; keep absolute totals'} for n,(code,_) in scenarios.items()})
    files={str(p.relative_to(output)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    dump(output/'manifest.json',dict(version='1.0-draft',synthetic=True,seed=SEED,
        origin='Original team-generated synthetic scenario, not VK sales',rows={k:len(v[1]) for k,v in tables.items()},files=files))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'samples/business-acceptance/data-v1')
    build(parser.parse_args().output)
