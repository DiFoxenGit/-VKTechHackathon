"""Independent period and changed-condition acceptance, no service/UI mutations."""
import copy
import csv
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest
from designer.analytics.business import build_business_analysis,verify_business_analysis,BusinessInputError
from designer.analytics.business_story import build_business_story,verify_business_story
from designer.analytics.business_periods import BusinessPeriods
from designer.analytics.business_conditions import normalize_conditions

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from business_reference import calculate

DATA=ROOT/'samples/business-acceptance/data-v1'
EXT=ROOT/'samples/business-acceptance/period-context-v1'


def load(name,directory=DATA):
    with (directory/(name+'.csv')).open(encoding='utf8',newline='') as stream:return list(csv.DictReader(stream))


def read(path):return json.loads(path.read_text(encoding='utf8'))


@pytest.fixture(scope='module')
def inputs():return [load(n) for n in ('sales','plan','products','regions')]


@pytest.fixture(scope='module')
def settings():return BusinessPeriods.model_validate(read(EXT/'settings.json'))


def test_all_fifteen_answers_for_another_period_and_version_b(inputs,settings):
    results=[]
    for version in ('baseline','version-b'):
        folder=EXT/version
        analysis=build_business_analysis(load('sales',folder),load('plan',folder),*inputs[2:],settings=settings)
        expected=calculate(folder,periods=settings.periods())
        assert len(expected['answers'])==15
        assert expected==read(folder/'expected-results.json')
        for answer in expected['answers']:
            assert analysis['facts'][answer['id']]['exact']==answer['exact'],answer['id']
        assert analysis['facts']['q3_net']['period']==['2026-04','2026-06']
        results.append(analysis)
    assert Decimal(results[1]['facts']['q3_net']['exact'])-Decimal(results[0]['facts']['q3_net']['exact'])==1260000
    assert Decimal(results[1]['facts']['q3_profit']['exact'])-Decimal(results[0]['facts']['q3_profit']['exact'])==990000
    assert not verify_business_analysis(load('sales',EXT/'baseline'),load('plan',EXT/'baseline'),*inputs[2:],results[0])
    assert verify_business_analysis(load('sales',EXT/'baseline'),load('plan',EXT/'baseline'),*inputs[2:],results[0],settings=settings)


@pytest.mark.parametrize('changed',[
    {'current':['2026-13','2026-15']},{'previous':['2026-01','2026-02']},
    {'previous':['2026-06','2026-08']},{'year_ago':['2025-04','2025-06']},
    {'history':['2026-01','2026-09']},{'plan':['2026-01','2026-06']},
])
def test_invalid_or_incomparable_periods_are_refused(inputs,changed):
    with pytest.raises(BusinessInputError,match='business.period_settings'):build_business_analysis(*inputs,settings=changed)


def test_two_requests_do_not_mutate_global_periods(inputs,settings):
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(build_business_analysis,*inputs)
        two=pool.submit(build_business_analysis,*inputs,settings=settings)
        default,configured=one.result(),two.result()
    assert default['facts']['q3_net']['period']==['2026-07','2026-09']
    assert configured['facts']['q3_net']['period']==['2026-04','2026-06']
    assert default['facts']['q3_net']['exact']!=configured['facts']['q3_net']['exact']


def test_shifted_years_recalculate_without_2026_constants(inputs,tmp_path):
    sources=copy.deepcopy(inputs)
    for table in sources[:2]:
        for row in table:row['month']=str(int(row['month'][:4])-2)+row['month'][4:]
    settings=BusinessPeriods(current=('2024-07','2024-09'),previous=('2024-04','2024-06'),
        year_ago=('2023-07','2023-09'),history=('2023-01','2024-09'),plan=('2024-01','2024-12'))
    for name,rows in zip(('sales','plan'),sources):
        with (tmp_path/(name+'.csv')).open('w',encoding='utf8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    result=build_business_analysis(*sources,settings=settings)
    for expected in calculate(tmp_path,periods=settings.periods())['answers']:
        assert result['facts'][expected['id']]['exact']==expected['exact']
    assert result['views']['quarter_kpi']['dataset']['rows'][0][0]=='2024-07 – 2024-09'


@pytest.mark.parametrize('version,expected',[('baseline',{'engineers':2,'analysts':1,'max_parallel_implementations':2}),
                                           ('version-b',{'engineers':3,'analysts':2,'max_parallel_implementations':1})])
def test_reworded_context_updates_all_resource_constraints(inputs,settings,version,expected):
    folder=EXT/version
    analysis=build_business_analysis(load('sales',folder),load('plan',folder),*inputs[2:],settings=settings)
    text=(folder/'context.txt').read_text(encoding='utf8');conditions=read(folder/'conditions.json')
    assert not text.startswith('1. ')
    story=build_business_story(analysis,text,conditions=conditions)
    assert story['capacity']==expected
    risk=next(s for s in story['slides'] if s['id']=='risks')['interpretation']
    assert f"инженеров — {expected['engineers']}" in risk
    criterion=next(a for a in story['actions'] if a['id']=='implementation')['criterion']
    assert f"не более {expected['max_parallel_implementations']}" in criterion
    assert story['actions'][0]['deadline']=='2026-07-31'
    assert story['actions'][2]['deadline']=='2026-09-30'
    assert '2026-04' in story['slides'][1]['purpose']
    assert not any(s['kind']=='hypothesis' for s in story['slides'][6]['statements'])
    assert verify_business_story(analysis,text,story,conditions=conditions)


def test_changed_text_rejects_stale_conditions_and_period_scope(inputs,settings):
    folder=EXT/'baseline';text=(folder/'context.txt').read_text(encoding='utf8');conditions=read(folder/'conditions.json')
    analysis=build_business_analysis(*inputs,settings=settings)
    for quote in ['двумя инженерами внедрения','одним аналитиком','не более двух параллельных внедрений']:
        with pytest.raises(BusinessInputError,match='business.context_binding'):
            build_business_story(analysis,text.replace(quote,'другие условия'),conditions=conditions)
    with pytest.raises(BusinessInputError,match='business.context_binding'):
        build_business_story(build_business_analysis(*inputs),text,conditions=conditions)
    with pytest.raises(BusinessInputError,match='business.context_conditions'):
        build_business_story(analysis,(DATA/'business-context.txt').read_text(encoding='utf8'))


def test_condition_value_cannot_be_changed_without_supporting_quote():
    folder=EXT/'baseline';text=(folder/'context.txt').read_text(encoding='utf8');conditions=read(folder/'conditions.json')
    conditions['capacity']['engineers']['value']=9
    with pytest.raises(BusinessInputError,match='business.context_binding'):normalize_conditions(text,conditions)


def test_changed_owner_and_zero_capacity_reach_actions(inputs,settings):
    folder=EXT/'baseline';text=(folder/'context.txt').read_text(encoding='utf8');conditions=read(folder/'conditions.json')
    for key,old,new,value in [('engineers','двумя инженерами внедрения','0 инженеров внедрения',0)]:
        text=text.replace(old,new);conditions['capacity'][key]={'value':value,'quote':new}
        conditions['sections']={k:v.replace(old,new) for k,v in conditions['sections'].items()}
    old='Руководитель продукта определяет готовность внедрения';new='Операционный директор определяет готовность внедрения'
    text=text.replace(old,new);conditions['owners']['implementation']={'value':'Операционный директор','quote':new}
    conditions['sections']={k:v.replace(old,new) for k,v in conditions['sections'].items()}
    story=build_business_story(build_business_analysis(*inputs,settings=settings),text,conditions=conditions)
    action=next(a for a in story['actions'] if a['id']=='implementation')
    assert action['owner_role']=='Операционный директор'
    assert action['capacity_status']=='no_capacity_reported'


def test_legacy_capacity_mutation_does_not_retain_two_projects(inputs):
    text=(DATA/'business-context.txt').read_text(encoding='utf8').replace('не более двух параллельных внедрений','до 3 параллельных внедрений')
    story=build_business_story(build_business_analysis(*inputs),text)
    assert story['capacity']['max_parallel_implementations']==3
    assert 'не более 3 интеграционных проектов' in next(a for a in story['actions'] if a['id']=='implementation')['criterion']


def test_future_rows_are_retained_but_never_drawn_or_counted(inputs,settings):
    analysis=build_business_analysis(*inputs,settings=settings)
    assert len(analysis['source_scope']['included_sales_rows'])==1296
    assert len(analysis['source_scope']['excluded_sales_rows'])==216
    assert analysis['views']['monthly_trend']['dataset']['rows'][-1][0]=='2026-06'
    changed=copy.deepcopy(inputs)
    for row in changed[0]:
        if row['month']>'2026-06':row['gross_revenue_rub']=str(int(row['gross_revenue_rub'])+1000000)
    modified=build_business_analysis(*changed,settings=settings)
    assert modified['facts']['q3_net']['exact']==analysis['facts']['q3_net']['exact']
    assert modified['views']==analysis['views']
    assert modified['fingerprints']!=analysis['fingerprints']


def test_changed_event_cannot_reuse_expansion_hypothesis(inputs,settings):
    folder=EXT/'baseline';conditions=read(folder/'conditions.json')
    event='С апреля уменьшена скидка партнёрам.'
    text=(folder/'context.txt').read_text(encoding='utf8')+'\n'+event
    conditions['channel_event']=event
    story=build_business_story(build_business_analysis(*inputs,settings=settings),text,conditions=conditions)
    hypothesis=next(s for s in story['slides'][6]['statements'] if s['kind']=='hypothesis')
    assert hypothesis['event_quote']==event and hypothesis['not_proven']
    assert 'Расширение' not in hypothesis['text']
