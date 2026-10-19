"""Independent acceptance oracle. Standard library only; never imports designer."""
import csv
import json
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path


def calculate(directory, periods=None):
    directory = Path(directory)
    with (directory / 'sales.csv').open(encoding='utf-8', newline='') as stream:
        sales = list(csv.DictReader(stream))
    with (directory / 'plan.csv').open(encoding='utf-8', newline='') as stream:
        plans = list(csv.DictReader(stream))
    periods = periods or {'q3': ('2026-07', '2026-09'), 'q2': ('2026-04', '2026-06'),
               'year_ago': ('2025-07', '2025-09')}
    answers = []

    def select(period, **where):
        lo, hi = periods[period]
        return [(i+2, r) for i, r in enumerate(sales) if lo <= r['month'] <= hi
                and all(r[k] == v for k, v in where.items())]

    def totals(rows):
        gross = sum(Decimal(r['gross_revenue_rub']) for _, r in rows)
        discount = sum(Decimal(r['discount_rub']) for _, r in rows)
        refunds = sum(Decimal(r['refund_rub']) for _, r in rows)
        net = gross-discount-refunds
        profit = net-sum(Decimal(r['cogs_rub']) for _, r in rows)
        return {'net': net, 'profit': profit, 'margin': profit/net*100 if net else None,
                'gross': gross, 'refunds': refunds}

    def answer(identifier, value, unit, formula, period='q3', where=None, extra=None):
        rows = select(period, **(where or {}))
        answers.append(dict(id=identifier, exact=None if value is None else str(value), unit=unit,
            display=None if value is None else str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            rounding='ROUND_HALF_UP; 2 decimal places; round only for display', formula=formula,
            period=list(periods[period]), filters=where or {}, source_file='sales.csv',
            source_rows=[i for i, _ in rows], source_fields=['gross_revenue_rub','discount_rub','refund_rub','cogs_rub'],
            **(extra or {})))

    with localcontext() as ctx:
        ctx.prec = 50
        current, previous, year = (totals(select(p)) for p in ('q3', 'q2', 'year_ago'))
        for metric, unit in [('net', 'RUB'), ('profit', 'RUB'), ('margin', '%')]:
            answer('q3_'+metric, current[metric], unit,
                   {'net':'SUM(gross-discount-refund)','profit':'SUM(gross-discount-refund-cogs)',
                    'margin':'100*SUM(gross-discount-refund-cogs)/SUM(gross-discount-refund)'}[metric])
        for label, baseline, period in [('qoq',previous,'q2'), ('yoy',year,'year_ago')]:
            answer(label+'_net_growth', (current['net']-baseline['net'])/baseline['net']*100, '%',
                   '100*(net_Q3-net_base)/net_base', extra={'base_period':list(periods[period]),
                   'base_source_rows':[i for i, _ in select(period)]})
        selected_plan = [(i+2,r) for i,r in enumerate(plans) if periods['q3'][0] <= r['month'] <= periods['q3'][1]]
        for metric, column in [('net','net_revenue_plan_rub'),('profit','gross_profit_plan_rub')]:
            plan = sum(Decimal(r[column]) for _,r in selected_plan)
            answer('q3_'+metric+'_plan_attainment', current[metric]/plan*100, '%', '100*SUM(actual)/SUM(plan)',
                   extra={'plan_file':'plan.csv','plan_source_rows':[i for i,_ in selected_plan], 'plan_field':column,
                          'plan_total_exact':str(plan),'join_keys':['month','region_id','product_id']})
        changes = {p:totals(select('q3', product_id=p))['net']-totals(select('q2',product_id=p))['net']
                   for p in sorted({r['product_id'] for r in sales})}
        for label, picker in [('best', max),('worst',min)]:
            product = picker(changes, key=changes.get)
            answer(label+'_product_contribution', changes[product], 'RUB', 'net_Q3(product)-net_Q2(product)',
                   where={'product_id':product}, extra={'base_source_rows':[i for i,_ in select('q2',product_id=product)]})
        gaps = {}
        for region in sorted({r['region_id'] for r in sales}):
            planned = sum(Decimal(r['net_revenue_plan_rub']) for _,r in selected_plan if r['region_id']==region)
            gaps[region] = totals(select('q3', region_id=region))['net']-planned
        region = min(gaps, key=gaps.get)
        answer('worst_region_plan_gap', gaps[region], 'RUB', 'net_Q3(region)-plan_Q3(region)',
               where={'region_id':region}, extra={'plan_file':'plan.csv',
               'plan_source_rows':[i for i,r in selected_plan if r['region_id']==region]})
        product = max(changes, key=lambda p:totals(select('q3', product_id=p))['net'])
        answer('top_product_revenue_share', totals(select('q3',product_id=product))['net']/current['net']*100,
               '%','100*net_Q3(top_product)/net_Q3(all)', where={'product_id':product},
               extra={'denominator_source_rows':[i for i,_ in select('q3')]})
        channel = 'partners'
        now, before = totals(select('q3',channel=channel)), totals(select('q2',channel=channel))
        for identifier,value,unit,formula in [
            ('partners_net_growth',(now['net']-before['net'])/before['net']*100,'%','100*(net_Q3-net_Q2)/net_Q2'),
            ('partners_margin_change',now['margin']-before['margin'],'pp','margin_Q3-margin_Q2')]:
            answer(identifier,value,unit,formula,where={'channel':channel},
                   extra={'base_source_rows':[i for i,_ in select('q2',channel=channel)]})
        answer('q3_refund_share',current['refunds']/current['gross']*100,'%','100*SUM(refund)/SUM(gross)')
        answer('qoq_margin_change',current['margin']-previous['margin'],'pp','margin_Q3-margin_Q2',
               extra={'base_source_rows':[i for i,_ in select('q2')]})
    return dict(version='1.0-draft', synthetic=True, oracle='stdlib Decimal; precision=50; no production imports', answers=answers)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    print(json.dumps(calculate(args.directory),ensure_ascii=False,indent=2,allow_nan=False))
