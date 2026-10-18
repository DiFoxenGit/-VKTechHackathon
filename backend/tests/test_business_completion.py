"""Criterion-level regressions for Dima's new D1–D4 boundary."""
import copy
import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
from designer.analytics import Dataset,AnalysisRequest,AnalysisResult,verify_result
from designer.analytics.business import build_business_analysis,BusinessInputError,verify_business_analysis
from designer.analytics.business_story import build_business_story,verify_business_story
from designer.analytics.business_contract import BusinessResult

DATA=Path(__file__).resolve().parents[2]/'samples/business-acceptance/data-v1'


def load(name,directory=DATA):
    with (directory/(name+'.csv')).open(encoding='utf8',newline='') as stream:return list(csv.DictReader(stream))


@pytest.fixture(scope='module')
def inputs():return [load(n) for n in ('sales','plan','products','regions')]


@pytest.fixture(scope='module')
def analysis(inputs):return build_business_analysis(*inputs)


@pytest.fixture(scope='module')
def context():return (DATA/'business-context.txt').read_text(encoding='utf8')


def test_every_history_month_and_full_year_plan_are_required(inputs):
    sales,plan,products,regions=copy.deepcopy(inputs)
    sales[:]=[r for r in sales if r['month']!='2025-02']
    with pytest.raises(BusinessInputError,match='business.incomplete_history'):
        build_business_analysis(sales,plan,products,regions)
    sales=copy.deepcopy(inputs[0]);plan[:]=[r for r in plan if r['month']!='2026-12']
    with pytest.raises(BusinessInputError,match='business.incomplete_plan'):
        build_business_analysis(sales,plan,products,regions)


def test_strict_sidecar_schema_and_complete_lineage(analysis):
    assert BusinessResult.model_validate(analysis).model_dump(mode='json')==analysis
    for view,proofs in analysis['lineage'].items():
        assert [p['derived_row'] for p in proofs]==list(range(2,len(analysis['views'][view]['dataset']['rows'])+2))
        for proof in proofs:
            for evidence in proof['evidence']:
                assert evidence['fingerprint']==analysis['fingerprints'][evidence['table']]
                assert all(i>=2 for i in evidence['row_ids'])
    invalid=copy.deepcopy(analysis);invalid['facts']['q3_net']['evidence'][0]['fingerprint']='wrong'
    with pytest.raises(ValueError):BusinessResult.model_validate(invalid)


def test_story_can_be_built_without_tools_or_oracle(analysis,context):
    story=build_business_story(analysis,context)
    assert len(story['slides'])==12
    assert len({s['purpose'] for s in story['slides']})==12
    for slide in story['slides']:
        assert slide['title'] and slide['answer'] and slide['interpretation'] and slide['evidence']
        action=next(a for a in story['actions'] if a['id']==slide['action_ref'])
        assert action['criterion'] and action['owner_role'] and slide['next_step']
        assert slide['context_evidence']['text'] in context
        assert slide['metrics'][0]['evidence']==analysis['facts'][slide['fact_ids'][0]]['evidence']
    products=story['slides'][4]['answer'];region=story['slides'][5]['answer']
    best=analysis['facts']['best_product_contribution']['category']
    assert analysis['entities']['product_id'][best] in products
    worst=analysis['facts']['worst_region_plan_gap']['category']
    assert analysis['entities']['region_id'][worst] in region
    assert len({s['next_step'] for s in story['slides']})==12


def test_compact_action_table_and_limits_come_from_context(analysis,context):
    story=build_business_story(analysis,context)
    assert story['budget']['total']==3000000
    assert sum(a['budget_cap_rub'] for a in story['actions'])+story['budget']['reserve']==3000000
    table=story['decision_table']
    assert len(table['dataset']['rows'])==3 and len(table['dataset']['columns'])==6
    assert verify_result(Dataset.model_validate(table['dataset']),AnalysisRequest.model_validate(table['request']),AnalysisResult.model_validate(table['result']))
    assert story['slides'][9]['view_id']=='decision_table'
    assert all(a['provenance']=='proposal_from_context; effect_not_estimated' for a in story['actions'])
    changed=context.replace('не более 3 000 000 рублей','не более 1 000 000 рублей')
    with pytest.raises(BusinessInputError,match='business.context_budget'):build_business_story(analysis,changed)


def test_hypotheses_and_observations_are_distinct(analysis,context):
    story=build_business_story(analysis,context)
    statements=story['slides'][6]['statements']
    assert {s['kind'] for s in statements}=={'observation','hypothesis','proposal'}
    assert next(s for s in statements if s['kind']=='hypothesis')['not_proven']
    assert not any(s['origin']=='model' for slide in story['slides'] for s in slide['statements'])


def test_version_b_changes_story_titles_and_metric_proofs(inputs,analysis,context):
    updated=build_business_analysis(load('sales',DATA/'updated'),load('plan',DATA/'updated'),*inputs[2:])
    first,second=build_business_story(analysis,context),build_business_story(updated,context)
    assert first['slides'][1]['title']!=second['slides'][1]['title']
    assert first['slides'][6]['answer']!=second['slides'][6]['answer']
    assert not verify_business_story(updated,context,first)
    altered=copy.deepcopy(first);altered['slides'][1]['metrics'][0]['formatted']='999 ₽'
    assert not verify_business_story(analysis,context,altered)


def test_negative_profit_is_preserved_and_refunds_deducted_once(inputs):
    rows=copy.deepcopy(inputs)
    quarter=[r for r in rows[0] if '2026-07'<=r['month']<='2026-09']
    for row in quarter:row['cogs_rub']=row['gross_revenue_rub']
    result=build_business_analysis(*rows)
    expected=-sum(Decimal(r['discount_rub'])+Decimal(r['refund_rub']) for r in quarter)
    assert Decimal(result['facts']['q3_profit']['exact'])==expected<0
    assert result['facts']['q3_margin']['value']<0


def test_nonpositive_comparison_base_refuses_growth_not_absolute_totals(inputs):
    rows=copy.deepcopy(inputs)
    for row in rows[0]:
        if '2026-04'<=row['month']<='2026-06':
            row['gross_revenue_rub']=str(int(row['discount_rub'])+int(row['refund_rub']))
    result=build_business_analysis(*rows)
    assert result['facts']['qoq_net_growth']['value'] is None
    assert result['facts']['q3_net']['value']>0


def test_long_labels_and_legend_cannot_detach_from_numbers(inputs,analysis):
    labels=analysis['views']['region_plan_gap']['result']['data']['categories']
    assert 'Южный и Северо-Кавказский федеральные округа' in labels
    assert set(labels)=={r['name'] for r in inputs[3]}
    modified=copy.deepcopy(analysis)
    modified['views']['monthly_trend']['result']['data']['series'][0]['name']='Подменённый смысл'
    assert not verify_business_analysis(*inputs,modified)


def test_all_product_contributions_reconcile_to_quarter_change(analysis):
    changes=sum(Decimal(f['exact']) for k,f in analysis['facts'].items() if k.startswith('product_contribution.'))
    rows=analysis['views']['monthly_trend']['dataset']['rows']
    quarter=lambda start,end:sum(Decimal(str(r[1])) for r in rows if start<=r[0]<=end)
    assert changes==quarter('2026-07','2026-09')-quarter('2026-04','2026-06')


def test_every_view_has_specific_bilingual_explanation(analysis):
    assert set(analysis['explanations']['ru'])==set(analysis['views'])==set(analysis['explanations']['en'])
    assert 'план' in analysis['explanations']['ru']['plan_actual']
    assert 'gross' in analysis['explanations']['ru']['refunds']
