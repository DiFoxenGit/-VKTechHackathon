"""Acceptance regressions discovered outside the initial synthetic happy paths."""
from pathlib import Path
import pytest

from designer.analytics import AnalysisRequest, analyze, import_datasets, profile_dataset, verify_result

ROOT = Path(__file__).resolve().parents[2]


def table(raw):
    imported = import_datasets(raw.encode(), 'acceptance.csv')
    assert not imported.rejected
    return imported.datasets[0]


def test_team_prose_is_not_mistaken_for_a_ragged_table():
    for name in ['материал-инициатива.md', 'материал-продукт.md']:
        source = ROOT/'samples'/'source'/name
        result = import_datasets(source.read_bytes(), name)
        assert not result.datasets
        assert [n.code for n in result.rejected] == ['import.no_table']


def test_actual_api_document_tables_survive_surrounding_code_and_prose():
    source = ROOT/'docs'/'API.md'
    result = import_datasets(source.read_bytes(), source.name)
    assert not result.rejected
    assert result.datasets
    for dataset in result.datasets:
        assert dataset.context == source.read_bytes().decode('utf-8-sig')
        assert all(len(row) == len(dataset.columns) for row in dataset.rows)


def test_currency_column_prevents_summing_incompatible_observations():
    ds = table('region,currency,sales\nA,RUB,10\nB,USD,20')
    result = analyze(ds, AnalysisRequest(task='summary', metrics=['c3']))
    assert result.status == 'refused'
    assert result.refusal.code == 'analysis.incompatible_units'


def test_growth_does_not_compare_changed_regional_coverage():
    ds = table('month,region,sales\n2026-01,A,10\n2026-01,B,20\n2026-02,A,40')
    result = analyze(ds, AnalysisRequest(task='dynamics', dimension='c1', metrics=['c3']))
    assert not any(f.evidence.operation == 'growth_percent' for f in result.facts)
    assert any(w.code == 'analysis.growth_not_comparable' for w in result.warnings)


def test_different_days_in_adjacent_months_are_not_regular_monthly_periods():
    ds = table('date,sales\n2026-01-01,10\n2026-02-28,20')
    assert profile_dataset(ds).columns[0].periodicity == 'irregular'
    result = analyze(ds, AnalysisRequest(task='dynamics'))
    assert not any(f.evidence.operation == 'growth_percent' for f in result.facts)


def test_missing_month_has_explicit_gap_in_the_visual_data():
    ds = table('month,sales\n2026-01,10\n2026-03,20')
    result = analyze(ds, AnalysisRequest(task='dynamics'))
    assert result.data.categories == ['2026-01-01', '2026-02-01', '2026-03-01']
    assert result.data.series[0].values == [10, None, 20]
    assert result.data.series[0].fact_ids[1] == ''
    assert any(w.code == 'analysis.time_gaps' for w in result.warnings)


def test_large_integers_are_not_silently_merged_by_plot_precision():
    ds = table('name,value\nA,9007199254740992\nB,9007199254740993')
    result = analyze(ds, AnalysisRequest(task='comparison'))
    assert result.status == 'refused'
    assert result.refusal.code == 'analysis.numeric_precision'


def test_explicit_goal_in_content_is_used_and_brief_takes_precedence():
    raw = b'Goal: show shares\n\nmonth,sales\n2026-01,10\n2026-02,20\n'
    ds = import_datasets(raw, 'report.txt').datasets[0]
    assert analyze(ds).analysis.task == 'shares'
    assert analyze(ds, AnalysisRequest(goal='show growth')).analysis.task == 'dynamics'


def test_growth_by_region_goal_does_not_default_to_category_comparison():
    ds = table('month,region,sales\n2026-01,A,10\n2026-02,A,20')
    result = analyze(ds, AnalysisRequest(goal='показать рост продаж по регионам', metrics=['c3']))
    assert result.analysis.task == 'dynamics'


def test_secondary_series_without_any_first_series_values_does_not_crash():
    ds = table('region,a,b\nA,,10\nB,,20')
    result = analyze(ds, AnalysisRequest(task='comparison', dimension='c1', metrics=['c2', 'c3'], column_types={'c2': 'number'}))
    assert result.status != 'refused'
    assert result.presentation.conclusion_fact_ids


def test_known_and_unknown_metric_units_are_not_assumed_equal():
    ds = table('region,revenue [RUB],duration\nA,10,20\nB,30,40')
    result = analyze(ds, AnalysisRequest(task='comparison', dimension='c1', metrics=['c2', 'c3']))
    assert result.status == 'refused'


def test_one_week_is_not_compared_to_a_six_week_total():
    ds = table('period,requests\n1 week,11\n6 weeks,38')
    result = analyze(ds, AnalysisRequest(task='comparison', dimension='c1', metrics=['c2']))
    assert result.refusal.code == 'analysis.incomparable_periods'


def test_year_gaps_and_count_series_keep_nulls():
    ds = table('year,sales\n2024,10\n2026,20')
    result = analyze(ds, AnalysisRequest(task='dynamics', aggregation='count'))
    assert result.data.series[0].values == [1, None, 1]


def test_known_currency_aliases_are_compatible():
    ds = table('region,currency,sales [RUB]\nA,руб.,10\nB,RUB,20')
    result = analyze(ds, AnalysisRequest(task='summary', metrics=['c3'], unit='₽'))
    assert result.facts[0].value == 30 and result.facts[0].unit == 'RUB'


def test_na_country_code_is_not_a_missing_numeric_value():
    ds = table('country,sales\nNA,10\nZA,20')
    result = analyze(ds, AnalysisRequest(task='comparison'))
    assert set(result.data.categories) == {'NA', 'ZA'}
    assert result.profile.columns[0].missing == 0


def test_missing_currency_is_not_assumed_to_match_other_rows():
    ds = table('region,currency,sales\nA,RUB,10\nB,,20')
    assert analyze(ds, AnalysisRequest(task='summary', metrics=['c3'])).refusal.code == 'analysis.incompatible_units'


def test_many_series_have_pages_and_budget_without_truncation():
    rows = ['month,region,sales'] + [f'2026-{month:02},R{region},{region+month}' for month in range(1, 4) for region in range(8)]
    ds = table('\n'.join(rows))
    req = AnalysisRequest(task='dynamics', dimension='c1', series_dimension='c2', metrics=['c3'])
    result = analyze(ds, req)
    assert len(result.data.series) == 8
    assert result.data.series_pages == [[0, 1, 2, 3, 4], [5, 6, 7]]
    assert analyze(ds, req.model_copy(update={'slide_budget': 1})).refusal.code == 'analysis.slide_limit'


def test_high_cardinality_series_refuse_before_building_large_visuals():
    ds = table('group,id_label,sales\n'+'\n'.join(f'A,R{i},1' for i in range(1000)))
    result = analyze(ds, AnalysisRequest(task='comparison', dimension='c1', series_dimension='c2', metrics=['c3']))
    assert result.refusal.code == 'analysis.slide_limit'
    assert not result.facts


def test_plain_language_goal_outside_the_table_controls_analysis():
    raw = 'Сравнить регионы\n\nmonth,region,sales\n2026-01,A,10\n2026-02,A,20\n2026-01,B,50\n'
    ds = import_datasets(raw.encode(), 'goal.txt').datasets[0]
    result = analyze(ds, AnalysisRequest(metrics=['c3']))
    assert result.analysis.task == 'comparison'
    assert result.data.categories == ['B', 'A']


def test_table_cell_goal_does_not_override_the_brief_or_become_an_instruction():
    raw = 'region,sales\nShow growth,10\nB,20\n'
    ds = import_datasets(raw.encode(), 'data.txt').datasets[0]
    assert analyze(ds).analysis.task == 'comparison'


def test_close_decimal_values_cannot_collapse_into_an_identical_plotted_number():
    ds = table('name,sales\nA,1.00000000000000001\nB,1.00000000000000002')
    result = analyze(ds, AnalysisRequest(task='comparison'))
    assert result.refusal.code == 'analysis.numeric_precision'


def test_filters_use_the_selected_time_span_not_the_whole_source_span():
    ds = table('year,sales\n1000,10\n2025,20\n2026,30')
    result = analyze(ds, AnalysisRequest(task='dynamics', filters={'c1': ['2025', '2026']}))
    assert result.status != 'refused'
    assert result.data.categories == ['2025-01-01', '2026-01-01']


def test_filtering_out_a_known_daily_period_preserves_a_gap():
    ds = table('date,sales\n2026-01-01,10\n2026-01-02,20\n2026-01-03,30')
    result = analyze(ds, AnalysisRequest(task='dynamics', filters={'c1': ['2026-01-01', '2026-01-03']}))
    assert result.data.series[0].values == [10, None, 30]


@pytest.mark.parametrize('target', ['title', 'categories', 'unit', 'period', 'evidence'])
def test_proof_verification_rejects_tampering_beyond_numeric_whitelists(target):
    ds = table('month,sales\n2026-01,10\n2026-02,20')
    req = AnalysisRequest(task='dynamics', unit='RUB')
    result = analyze(ds, req).model_copy(deep=True)
    if target == 'title':
        result.presentation.title = 'Рост на 999%'
    elif target == 'categories':
        result.data.categories.reverse()
    elif target == 'unit':
        result.facts[0].unit = 'USD'
    elif target == 'period':
        result.facts[0].period = ['2020-01-01', '2020-02-01']
    else:
        result.facts[0].evidence.row_ids = [999]
    assert not verify_result(ds, req, result)


def test_full_100000_row_source_participates_in_the_sum():
    ds = table('region,sales\n'+'\n'.join(f'A,{i}' for i in range(1, 100001)))
    result = analyze(ds, AnalysisRequest(task='summary', metrics=['c2'], unit='units'))
    assert len(ds.rows) == 100000
    assert result.facts[0].value == 100000*100001//2
    assert len(result.facts[0].evidence.row_ids) == 100000
    assert result.facts[0].evidence.row_ids[0] == 2
    assert result.facts[0].evidence.row_ids[-1] == 100001


def test_intraday_timestamps_are_not_silently_aggregated_into_one_day():
    ds = table('timestamp,sales\n2026-01-01T00:00:00,10\n2026-01-01T01:00:00,20')
    result = analyze(ds, AnalysisRequest(task='dynamics'))
    assert result.data.categories == ['2026-01-01T00:00:00', '2026-01-01T01:00:00']
    assert result.data.series[0].values == [10, 20]
    assert result.profile.columns[0].periodicity == 'hourly'


def test_aware_timestamps_normalize_to_utc_and_mixed_timezones_are_not_guessed():
    ds = table('timestamp,sales\n2026-01-01T00:00:00+03:00,10\n2026-01-01T01:00:00+03:00,20')
    result = analyze(ds, AnalysisRequest(task='dynamics'))
    assert result.data.categories == ['2025-12-31T21:00:00Z', '2025-12-31T22:00:00Z']
    mixed = table('timestamp,sales\n2026-01-01T00:00:00,10\n2026-01-01T01:00:00+03:00,20')
    assert analyze(mixed, AnalysisRequest(task='dynamics')).status == 'refused'
