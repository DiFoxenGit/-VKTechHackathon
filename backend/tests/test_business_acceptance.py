"""Business questions tested against an independently calculated source oracle."""
import copy
import csv
import json
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from designer.analytics import import_datasets, AnalysisRequest, verify_result, Dataset
from designer.analytics.business import BusinessInputError, build_business_analysis, verify_business_analysis

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'samples/business-acceptance/data-v1'
sys.path.insert(0,str(ROOT/'tools'))
from business_reference import calculate


def read(name,directory=DATA):
    with (directory/(name+'.csv')).open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))


@pytest.fixture(scope='module')
def sources():return [read(n) for n in ('sales','plan','products','regions')]


@pytest.fixture(scope='module')
def result(sources):return build_business_analysis(*sources)


def test_independent_fifteen_answers_and_manual_integer_reconciliation(result):
    expected=calculate(DATA)
    assert len(expected['answers'])==15
    for answer in expected['answers']:
        assert result['facts'][answer['id']]['exact']==answer['exact'],answer['id']
    # Separate explicit integer reductions, no production helper or oracle call.
    quarter=[r for r in read('sales') if '2026-07'<=r['month']<='2026-09']
    net=sum(int(r['gross_revenue_rub'])-int(r['discount_rub'])-int(r['refund_rub']) for r in quarter)
    costs=sum(int(r['cogs_rub']) for r in quarter)
    assert net==116241720
    assert net-costs==31763784
    assert Decimal(result['facts']['q3_net']['exact'])==net


def test_source_grain_volume_context_and_catalog(sources):
    sales,plan,products,regions=sources
    assert len(sales)==1512 and len(plan)==288 and len(products)==4 and len(regions)==6
    assert len({tuple(r[k] for k in ('month','region_id','product_id','channel')) for r in sales})==1512
    assert len(read('catalog'))==240
    assert 6000<=len((DATA/'business-context.txt').read_text(encoding='utf-8'))<=10000


def test_weighted_margin_and_plan_denominator_not_repeated(result):
    margin=result['facts']['q3_margin']
    expected=Decimal('31763784')/Decimal('116241720')*100
    assert abs(Decimal(margin['exact'])-expected)<Decimal('1e-24')
    plan_evidence=result['facts']['q3_net_plan_attainment']['evidence'][1]
    assert len(plan_evidence['row_ids'])==72
    assert len(set(plan_evidence['row_ids']))==72
    assert len(result['facts']['q3_net']['evidence'][0]['row_ids'])==216


def test_partner_growth_margin_decline_and_seasonality_are_real_properties(result,sources):
    assert Decimal(result['facts']['partners_net_growth']['exact'])>0
    assert Decimal(result['facts']['partners_margin_change']['exact'])<0
    december=sum(int(r['gross_revenue_rub']) for r in sources[0] if r['month']=='2025-12')
    january=sum(int(r['gross_revenue_rub']) for r in sources[0] if r['month']=='2025-01')
    assert december>january


def test_changed_source_predictably_changes_totals(sources,result):
    modified=[read('sales',DATA/'updated'),read('plan',DATA/'updated'),*sources[2:]]
    updated=build_business_analysis(*modified)
    for answer in calculate(DATA/'updated')['answers']:
        assert updated['facts'][answer['id']]['exact']==answer['exact']
    assert Decimal(updated['facts']['q3_net']['exact'])-Decimal(result['facts']['q3_net']['exact'])==1260000
    assert Decimal(updated['facts']['q3_profit']['exact'])-Decimal(result['facts']['q3_profit']['exact'])==990000
    assert not verify_business_analysis(*modified,result)


@pytest.mark.parametrize('name,code',[
    ('missing_value','business.missing_value'),('duplicate_key','business.duplicate_key'),
    ('mixed_currency','business.currency'),('negative_adjustment','business.negative_component'),
    ('ambiguous_number','business.invalid_number')])
def test_negative_source_is_refused_explicitly(sources,name,code):
    with pytest.raises(BusinessInputError) as exc:
        build_business_analysis(read(name,DATA/'negative'),*sources[1:])
    assert exc.value.code==code


def test_zero_denominator_is_not_infinite_growth(sources):
    result=build_business_analysis(read('zero_denominator',DATA/'negative'),*sources[1:])
    assert result['facts']['q3_margin']['value'] is None
    assert any(w['code']=='business.zero_denominator' for w in result['warnings'])
    assert result['views']['product_structure']['result']['status']=='refused'
    assert len(result['views']['product_structure']['dataset']['rows'])==4


@pytest.mark.parametrize('mutation,code',[
    ('missing_plan','business.plan_key_missing'),('duplicate_plan','business.duplicate_key'),
    ('cohort','business.incomplete_cohort'),('foreign_key','business.unknown_key')])
def test_invalid_join_or_incomparable_period_is_not_silently_dropped(sources,mutation,code):
    sales,plan,products,regions=copy.deepcopy(sources)
    if mutation=='missing_plan':plan[:]=[r for r in plan if not(r['month']=='2026-07' and r['region_id']=='R1' and r['product_id']=='P1')]
    if mutation=='duplicate_plan':plan.append(copy.deepcopy(plan[0]))
    if mutation=='cohort':sales[:]=[r for r in sales if not(r['month']=='2026-07' and r['region_id']=='R1' and r['product_id']=='P1' and r['channel']=='direct')]
    if mutation=='foreign_key':sales[0]['product_id']='UNKNOWN'
    with pytest.raises(BusinessInputError) as exc:build_business_analysis(sales,plan,products,regions)
    assert exc.value.code==code


def test_every_ready_view_has_matching_labels_data_and_replayable_lineage(result):
    for name,view in result['views'].items():
        from designer.analytics import AnalysisResult
        dataset=Dataset.model_validate(view['dataset'])
        request=AnalysisRequest.model_validate(view['request'])
        assert verify_result(dataset,request,AnalysisResult.model_validate(view['result']))
        assert len(result['lineage'][name])==len(dataset.rows)
        assert all(proof['evidence'] for proof in result['lineage'][name])
    assert result['views']['monthly_trend']['result']['visualization']['selected']=='line'
    assert result['views']['product_contribution']['result']['visualization']['selected']=='bar'
    assert result['views']['priorities']['result']['visualization']['selected']=='table'
    assert result['views']['quarter_kpi']['result']['visualization']['selected']=='kpi'


def test_mutation_of_label_or_evidence_fails_verification(sources,result):
    changed=copy.deepcopy(result)
    changed['lineage']['monthly_trend'][0]['evidence'][0]['row_ids']=[999999]
    assert not verify_business_analysis(*sources,changed)
    changed=copy.deepcopy(result);changed['views']['product_contribution']['result']['data']['categories'].reverse()
    assert not verify_business_analysis(*sources,changed)


def test_xlsx_csv_json_and_text_carry_equivalent_cells(sources):
    imported=import_datasets((DATA/'business-data.xlsx').read_bytes(),'business-data.xlsx')
    assert not imported.rejected
    assert len(imported.datasets)==5
    table=next(d for d in imported.datasets if d.ref.table=='sales')
    assert [[str(v) for v in row] for row in table.rows]==[list(r.values()) for r in sources[0]]
    table_json=import_datasets((DATA/'sales.json').read_bytes(),'sales.json').datasets[0]
    assert table.rows==table_json.rows
    table_md=import_datasets((DATA/'sales-table.md').read_bytes(),'sales-table.md').datasets[0]
    assert len(table_md.rows)==3


def test_reference_implementation_does_not_import_the_analyzer():
    import ast
    tree=ast.parse((ROOT/'tools/business_reference.py').read_text(encoding='utf-8'))
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert all(n and not n.startswith('designer') for n in imports)


def test_user_explanations_have_both_languages_and_no_technical_payload():
    from designer.analytics.business import explain_business
    directory=ROOT/'backend/designer/analytics/locales'
    ru=json.loads((directory/'business.ru.json').read_text(encoding='utf-8'))
    en=json.loads((directory/'business.en.json').read_text(encoding='utf-8'))
    assert ru.keys()==en.keys()
    assert 'RUB' in explain_business('business.currency',locale='en')
    assert 'строке 12' in explain_business('business.missing_value',{'row':12,'column':'gross_revenue_rub'})


def test_generated_assets_and_manifest_are_distinct_and_reproducible(tmp_path):
    import zipfile,hashlib
    from make_business_data import build
    build(tmp_path/'a');build(tmp_path/'b')
    for path in (tmp_path/'a').rglob('*'):
        if path.is_file():assert path.read_bytes()==(tmp_path/'b'/path.relative_to(tmp_path/'a')).read_bytes()
    with zipfile.ZipFile(DATA/'content-pack.zip') as archive:
        assets=[n for n in archive.namelist() if n.endswith('.svg')]
        assert len(assets)==6
        assert len({hashlib.sha256(archive.read(n)).hexdigest() for n in assets})==6
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name,entry in manifest['files'].items():
        assert hashlib.sha256((DATA/name).read_bytes()).hexdigest()==entry['sha256']


def test_twelve_distinct_questions_and_four_content_examples(result):
    review=DATA.parent/'review-v1'
    slides=json.loads((review/'story-plan.json').read_text(encoding='utf-8'))['slides']
    assert len(slides)==12 and len({s['purpose'] for s in slides})==12
    assert all(s['answer'] and s['interpretation'] and all(f in result['facts'] for f in s['fact_ids']) for s in slides)
    assert len(json.loads((review/'four-examples.json').read_text(encoding='utf-8'))['examples'])==4
