"""Explicit business views, separate from service planning/layout and the test oracle.

No inference of joins, currencies or causal effects. Inputs use the published v1
business grain. Output is draft sidecar metadata plus ordinary AnalysisResults.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
from pathlib import Path
import re

from . import AnalysisRequest, analyze, import_datasets
from .business_periods import resolve_periods, months as period_months

KEY=('month','region_id','product_id')
SALES_MONEY=('gross_revenue_rub','discount_rub','refund_rub','cogs_rub')


class BusinessInputError(ValueError):
    def __init__(self, code, **params):
        self.code,self.params=code,params
        super().__init__(code)


def _amount(row, column, line):
    raw=row.get(column)
    if raw is None or raw=='':raise BusinessInputError('business.missing_value',row=line,column=column)
    if isinstance(raw,bool) or not re.fullmatch(r'-?\d+(?:\.\d{1,2})?',str(raw)):
        raise BusinessInputError('business.invalid_number',row=line,column=column)
    try:value=Decimal(str(raw))
    except InvalidOperation as exc:raise BusinessInputError('business.invalid_number',row=line,column=column) from exc
    if abs(value)>Decimal('1000000000000'):
        raise BusinessInputError('business.number_limit',row=line,column=column)
    if value<0:raise BusinessInputError('business.negative_component',row=line,column=column)
    return value


def _validate(rows, fields, *, sales):
    if not rows or len(rows)>100000:raise BusinessInputError('business.row_limit')
    seen=set();result=[]
    for line,row in enumerate(rows,2):
        if not isinstance(row,dict):raise BusinessInputError('business.invalid_row',row=line)
        if not sales and 'channel' in row:raise BusinessInputError('business.plan_grain',row=line)
        key=tuple(row.get(k) for k in (*KEY, 'channel') if sales or k!='channel')
        if any(not isinstance(k,str) or not k for k in key):raise BusinessInputError('business.missing_key',row=line)
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',row['month']):raise BusinessInputError('business.period',row=line)
        if key in seen:raise BusinessInputError('business.duplicate_key',row=line)
        seen.add(key)
        if row.get('currency')!='RUB':raise BusinessInputError('business.currency',row=line)
        value={**row,**{f:_amount(row,f,line) for f in fields},'_row':line}
        if sales:
            orders=_amount(row,'orders_count',line)
            if orders!=orders.to_integral_value():raise BusinessInputError('business.orders_integer',row=line)
            value['orders_count']=orders
            value['net']=value['gross_revenue_rub']-value['discount_rub']-value['refund_rub']
            value['profit']=value['net']-value['cogs_rub']
        result.append(value)
    return result


def _sum(rows,field):return sum((r[field] for r in rows),Decimal(0))


def _ratio(numerator,denominator,warnings,identifier):
    if denominator<=0:
        warnings.append({'code':'business.zero_denominator','params':{'metric':identifier}})
        return None
    return numerator/denominator*100


def _fingerprint(rows):
    return sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def explain_business(code,params=None,locale='ru'):
    """Localized whole sentences; diagnostics retain code and structured parameters."""
    language='ru' if locale=='ru' else 'en'
    messages=json.loads((Path(__file__).parent/'locales'/f'business.{language}.json').read_text(encoding='utf-8'))
    return messages.get(code,messages['business.unknown']).format_map(defaultdict(lambda:'—',params or {}))


def build_business_analysis(sales, plan, products, regions, *, locale='ru', settings=None):
    """Return immutable calculated views; templates and model credentials are irrelevant.

    Callers persist original bytes separately. Fingerprints here cover canonical
    input rows, not raw file bytes. Every derived cell has multi-source lineage.
    """
    try: configured=resolve_periods(settings)
    except ValueError as exc:raise BusinessInputError('business.period_settings') from exc
    with localcontext() as ctx:
        ctx.prec=50
        return _build(sales,plan,products,regions,locale,configured)


def _build(raw_sales,raw_plan,products,regions,locale,settings):
    periods=settings.periods()
    sales=_validate(raw_sales,SALES_MONEY,sales=True)
    plan=_validate(raw_plan,('net_revenue_plan_rub','gross_profit_plan_rub'),sales=False)
    names={}
    for table,key in [(products,'product_id'),(regions,'region_id')]:
        if not table or len(table)>256:raise BusinessInputError('business.dictionary')
        lookup={}
        for row in table:
            if not isinstance(row,dict) or not isinstance(row.get(key),str) or not isinstance(row.get('name'),str):
                raise BusinessInputError('business.dictionary')
            if row[key] in lookup:raise BusinessInputError('business.duplicate_key',table=key)
            lookup[row[key]]=row['name']
        names[key]=lookup
    if len(names['product_id'])*len(names['region_id'])*3>10000:
        raise BusinessInputError('business.row_limit')
    for row in sales+plan:
        for key in names:
            if row[key] not in names[key]:raise BusinessInputError('business.unknown_key',column=key,value=row[key])
    actual_by_key=defaultdict(list)
    for row in sales:actual_by_key[tuple(row[k] for k in KEY)].append(row)
    plan_by_key={tuple(r[k] for k in KEY):r for r in plan}
    # Only closed comparable quarters enter plan comparisons. No silent inner join.
    for key in actual_by_key:
        if any(bounds[0]<=key[0]<=bounds[1] for bounds in (settings.current,settings.previous)) and key not in plan_by_key:
            raise BusinessInputError('business.plan_key_missing',key=list(key))
    quarter={p:[r for r in sales if bounds[0]<=r['month']<=bounds[1]] for p,bounds in periods.items()}
    for period,rows in quarter.items():
        if not rows:raise BusinessInputError('business.period_missing',period=period)
    # Detect missing cells/cohort changes before comparing quarters.
    cohorts=[]
    for period,rows in quarter.items():
        months=sorted({r['month'] for r in rows})
        bounds=periods[period]
        expected=period_months(bounds)
        if months!=expected:raise BusinessInputError('business.incomplete_period',period=period)
        by_month=[{(r['region_id'],r['product_id'],r['channel']) for r in rows if r['month']==m} for m in months]
        if any(c!=by_month[0] for c in by_month):raise BusinessInputError('business.incomplete_cohort',period=period)
        cohorts.append(by_month[0])
    if any(c!=cohorts[0] for c in cohorts):raise BusinessInputError('business.incomplete_cohort')
    expected_cohort={(r,p,c) for r in names['region_id'] for p in names['product_id'] for c in ('direct','online','partners')}
    if cohorts[0]!=expected_cohort:raise BusinessInputError('business.incomplete_cohort')
    expected_months=set(period_months(settings.history))
    monthly_cohorts=defaultdict(set)
    for row in sales:
        if settings.history[0]<=row['month']<=settings.history[1]:monthly_cohorts[row['month']].add((row['region_id'],row['product_id'],row['channel']))
    if set(monthly_cohorts)!=expected_months or any(c!=expected_cohort for c in monthly_cohorts.values()):
        raise BusinessInputError('business.incomplete_history')
    expected_plan={(month,region,product) for month in period_months(settings.plan) for region in names['region_id'] for product in names['product_id']}
    if set(plan_by_key)!=expected_plan:raise BusinessInputError('business.incomplete_plan')
    source_scope={'included_sales_rows':[r['_row'] for r in sales if r['month'] in expected_months],
                  'excluded_sales_rows':[r['_row'] for r in sales if r['month'] not in expected_months],
                  'history':list(settings.history)}
    sales=[r for r in sales if r['month'] in expected_months]
    warnings=[];facts={};lineage={};views={}
    if source_scope['excluded_sales_rows']:
        warnings.append({'code':'business.outside_history','params':{'count':len(source_scope['excluded_sales_rows'])}})
    fingerprints={n:_fingerprint(rows) for n,rows in [('sales',raw_sales),('plan',raw_plan),('products',products),('regions',regions)]}

    def evidence(rows,fields,table='sales',role='numerator'):
        return dict(table=table,row_ids=[r['_row'] for r in rows],fields=fields,role=role,fingerprint=fingerprints[table])

    def fact(identifier,value,unit,formula,inputs,period='q3'):
        facts[identifier]=dict(id=identifier,exact=None if value is None else str(value),
            value=None if value is None else float(value),unit=unit,period=list(periods[period]),
            formula=formula,evidence=inputs,rounding='unrounded Decimal(precision=50); display ROUND_HALF_UP 2dp',category=None)
        return value

    def view(identifier,columns,rows,task,metric_columns,unit,cell_evidence,dimension='c1'):
        # Existing contract remains unchanged: derived source + external lineage sidecar.
        if any(isinstance(v,(int,float)) and abs(v)>2**53-1 for row in rows for v in row):
            raise BusinessInputError('business.number_limit',view=identifier)
        raw=json.dumps({'columns':columns,'rows':rows},ensure_ascii=False,allow_nan=False).encode()
        dataset=import_datasets(raw,identifier+'.json').datasets[0]
        request=AnalysisRequest(task=task,goal=task,dimension=dimension,metrics=metric_columns,
            unit=unit,locale=locale,column_types={'c1':'category'} if task!='dynamics' else {})
        result=analyze(dataset,request)
        if result.status=='refused':
            warnings.append({'code':'business.view_refused','params':{'view':identifier,'reason':result.refusal.code}})
        views[identifier]=dict(dataset=dataset.model_dump(mode='json'),request=request.model_dump(mode='json'),result=result.model_dump(mode='json'))
        lineage[identifier]=cell_evidence

    now,previous,year=(quarter[p] for p in ('q3','q2','year_ago'))
    net,profit=_sum(now,'net'),_sum(now,'profit')
    for metric,value in [('net',net),('profit',profit)]:
        fact('q3_'+metric,value,'RUB','SUM(gross-discount-refund'+('-cogs' if metric=='profit' else '')+')',[evidence(now,list(SALES_MONEY))])
    margin=_ratio(profit,net,warnings,'q3_margin')
    fact('q3_margin',margin,'%','100*SUM(profit)/SUM(net)',[evidence(now,list(SALES_MONEY))])
    for label,base in [('qoq',previous),('yoy',year)]:
        growth=_ratio(net-_sum(base,'net'),_sum(base,'net'),warnings,label)
        fact(label+'_net_growth',growth,'%','100*(net_current-net_base)/net_base',
             [evidence(now,list(SALES_MONEY)),evidence(base,list(SALES_MONEY),role='baseline')])
    matched=[r for r in plan if settings.current[0]<=r['month']<=settings.current[1]]
    if {tuple(r[k] for k in KEY) for r in matched}!={tuple(r[k] for k in KEY) for r in now}:
        raise BusinessInputError('business.plan_grain')
    for metric,column,amount in [('net','net_revenue_plan_rub',net),('profit','gross_profit_plan_rub',profit)]:
        fact('q3_'+metric+'_plan_attainment',_ratio(amount,_sum(matched,column),warnings,'plan_'+metric),'%',
             '100*SUM(actual at month-region-product grain)/SUM(plan once per key)',
             [evidence(now,list(SALES_MONEY)),evidence(matched,[column],table='plan',role='denominator')])
    fact('q3_refund_share',_ratio(_sum(now,'refund_rub'),_sum(now,'gross_revenue_rub'),warnings,'refunds'),
         '%','100*SUM(refund)/SUM(gross)',[evidence(now,['refund_rub','gross_revenue_rub'])])
    base_margin=_ratio(_sum(previous,'profit'),_sum(previous,'net'),warnings,'base_margin')
    fact('qoq_margin_change',None if margin is None or base_margin is None else margin-base_margin,'pp',
         'margin_current-margin_previous',[evidence(now,list(SALES_MONEY)),evidence(previous,list(SALES_MONEY),role='baseline')])
    months=sorted({r['month'] for r in sales})
    if len(months)>120:raise BusinessInputError('business.period_limit')
    monthly=[];monthly_proof=[]
    for month in months:
        rows=[r for r in sales if r['month']==month]
        monthly.append([month,float(_sum(rows,'net')),float(_sum(rows,'profit'))])
        monthly_proof.append(dict(derived_row=len(monthly)+1,evidence=[evidence(rows,list(SALES_MONEY))]))
    view('monthly_trend',['month','net_revenue_rub','gross_profit_rub'],monthly,'dynamics',['c2','c3'],'RUB',monthly_proof)
    priorities=[];channel_rows=[];channel_proof=[]
    for key,identifier in [('product_id','product_contribution'),('region_id','region_contribution'),('channel','channel_economics')]:
        rows=[];proof=[];deltas={}
        for category in sorted({r[key] for r in now}):
            current=[r for r in now if r[key]==category];base=[r for r in previous if r[key]==category]
            current_net,base_net=_sum(current,'net'),_sum(base,'net')
            current_profit=_sum(current,'profit');delta=current_net-base_net;deltas[category]=delta
            label=names.get(key,{}).get(category,category)
            inputs=[evidence(current,list(SALES_MONEY)),evidence(base,list(SALES_MONEY),role='baseline')]
            fact(identifier+'.'+category,delta,'RUB','net_current(category)-net_previous(category)',inputs)
            rows.append([label,float(delta) if key!='channel' else float(current_net)])
            proof.append(dict(derived_row=len(rows)+1,evidence=inputs))
            if key=='product_id':priorities.append([label,float(current_net),float(current_profit)])
            if key=='channel' and category=='partners':
                current_margin=_ratio(current_profit,current_net,warnings,'partners_margin')
                previous_margin=_ratio(_sum(base,'profit'),base_net,warnings,'partners_base_margin')
                fact('partners_net_growth',_ratio(current_net-base_net,base_net,warnings,'partners_growth'),'%',
                     '100*(net_current/net_previous-1)',inputs)
                fact('partners_margin_change',None if current_margin is None or previous_margin is None else current_margin-previous_margin,
                     'pp','margin_current-margin_previous',inputs)
            if key=='channel':
                channel_rows.append([label,float(current_net),float(current_profit),
                    None if current_net<=0 else float(current_profit/current_net*100)])
                channel_proof.append(dict(derived_row=len(channel_rows)+1,evidence=inputs))
        view(identifier,[key,'net_change_rub' if key!='channel' else 'net_revenue_rub'],rows,'comparison',['c2'],'RUB',proof)
        if key=='product_id':
            for label,picker in [('best',max),('worst',min)]:
                category=picker(deltas,key=deltas.get)
                facts[label+'_product_contribution']={**facts[identifier+'.'+category],'id':label+'_product_contribution','category':category}
            category=max(deltas,key=lambda c:_sum([r for r in now if r[key]==c],'net'))
            selected=[r for r in now if r[key]==category]
            fact('top_product_revenue_share',_ratio(_sum(selected,'net'),net,warnings,'concentration'),'%','100*net_top/net_all',
                 [evidence(selected,list(SALES_MONEY)),evidence(now,list(SALES_MONEY),role='denominator')])
            facts['top_product_revenue_share']['category']=category
    gaps={}
    for region in sorted(names['region_id']):
        actual=[r for r in now if r['region_id']==region];target=[r for r in matched if r['region_id']==region]
        gap=_sum(actual,'net')-_sum(target,'net_revenue_plan_rub');gaps[region]=gap
        fact('region_plan_gap.'+region,gap,'RUB','net_current(region)-SUM(plan(region))',
             [evidence(actual,list(SALES_MONEY)),evidence(target,['net_revenue_plan_rub'],table='plan',role='baseline')])
    worst=min(gaps,key=gaps.get)
    facts['worst_region_plan_gap']={**facts['region_plan_gap.'+worst],'id':'worst_region_plan_gap','category':worst}
    view('region_plan_gap',['region','plan_gap_rub'],[[names['region_id'][r],float(gaps[r])] for r in sorted(gaps)],
         'comparison',['c2'],'RUB',[dict(derived_row=i+2,evidence=facts['region_plan_gap.'+r]['evidence']) for i,r in enumerate(sorted(gaps))])
    view('channel_profitability',['channel','net_revenue_rub','gross_profit_rub','gross_margin_pct'],channel_rows,
         'reference',[],'',channel_proof)
    view('plan_actual',['metric','actual_rub','plan_rub'],[
         ['Net revenue',float(net),float(_sum(matched,'net_revenue_plan_rub'))],
         ['Gross profit',float(profit),float(_sum(matched,'gross_profit_plan_rub'))]],
         'comparison',['c2','c3'],'RUB',[dict(derived_row=i+2,evidence=[evidence(now,list(SALES_MONEY)),
         evidence(matched,[column],table='plan',role='baseline')]) for i,column in enumerate(('net_revenue_plan_rub','gross_profit_plan_rub'))])
    view('product_structure',['product','net_revenue_rub'],[[names['product_id'][p],float(_sum([r for r in now if r['product_id']==p],'net'))]
         for p in sorted(names['product_id'])],'shares',['c2'],'RUB',
         [dict(derived_row=i+2,evidence=[evidence([r for r in now if r['product_id']==p],list(SALES_MONEY)),
          evidence(now,list(SALES_MONEY),role='denominator')]) for i,p in enumerate(sorted(names['product_id']))])
    view('refunds',['period','gross_revenue_rub','refund_rub','refund_share_pct'],
         [[settings.label(),float(_sum(now,'gross_revenue_rub')),float(_sum(now,'refund_rub')),
           facts['q3_refund_share']['value']]],'reference',[],'',
         [dict(derived_row=2,evidence=[evidence(now,['gross_revenue_rub','refund_rub'])])])
    view('priorities',['product','net_revenue_rub','gross_profit_rub'],priorities,'reference',[],'RUB',
         [dict(derived_row=i+2,evidence=[evidence([r for r in now if r['product_id']==p],list(SALES_MONEY))]) for i,p in enumerate(sorted(names['product_id']))])
    view('quarter_kpi',['period','net_revenue_rub','gross_profit_rub'],[[settings.label(),float(net),float(profit)]],
         'summary',['c2','c3'],'RUB',[dict(derived_row=2,evidence=[evidence(now,list(SALES_MONEY))])])
    explanations={language:json.loads((Path(__file__).parent/'locales'/f'business-views.{language}.json').read_text(encoding='utf8')) for language in ('ru','en')}
    explanations={language:{key:text.format(current_period=settings.label(),previous_period=' – '.join(settings.previous),history_count=len(period_months(settings.history))) for key,text in messages.items()} for language,messages in explanations.items()}
    return dict(schema_version='business-draft-1',status='draft_for_contract_review',explanations=explanations,period_settings=settings.model_dump(mode='json'),source_scope=source_scope,
        fingerprints=fingerprints,facts=facts,views=views,lineage=lineage,warnings=warnings,entities=names,
        unsupported=['CAC','marketing_causality','SKU_sales_join','currency_conversion','automatic_arbitrary_joins'])


def verify_business_analysis(sales,plan,products,regions,result,*,locale='ru',settings=None):
    return build_business_analysis(sales,plan,products,regions,locale=locale,settings=settings)==result
