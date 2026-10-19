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
        if actual!=answer['exact']:raise ValueError((answer['id'],actual,answer['exact']))
        comparisons.append({'id':answer['id'],'exact_match':True})
    output=directory.parent/'review-v1';output.mkdir(exist_ok=True)
    write(output/'business-analysis.json',result)
    write(output/'reference-comparison.json',comparisons)
    from designer.analytics.business_story import build_business_story
    from designer.analytics.business_contract import BusinessResult
    BusinessResult.model_validate(result)
    write(output/'business-sidecar.schema.json',BusinessResult.model_json_schema())
    context=(directory/'business-context.txt').read_text(encoding='utf-8')
    story=build_business_story(result,context)
    write(output/'story-plan.json',story)
    examples=[]
    for kind,index,view in [('kpi',1,'quarter_kpi'),('trend',2,'monthly_trend'),('comparison',4,'product_contribution'),('table',9,None)]:
        item=result['views'][view] if view else {k:v for k,v in story['decision_table'].items() if k!='lineage'}
        examples.append({'type':kind,'slide':story['slides'][index],'analysis':item,
            'lineage':result['lineage'][view] if view else story['decision_table']['lineage'],
            'explanation':{language:explain_business('view.'+kind,locale=language) for language in ('ru','en')}})
    write(output/'four-examples.json',{'status':'content_examples_not_visual_acceptance','examples':examples,'actions':story['actions']})
    modified=build_business_analysis(load(directory/'updated','sales'),load(directory/'updated','plan'),*rows[2:])
    write(output/'updated-story-plan.json',build_business_story(modified,context))
    return result


if __name__=='__main__':
    build(ROOT/'samples/business-acceptance/data-v1')
