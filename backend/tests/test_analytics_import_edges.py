"""Additional D1/D2 acceptance: real spreadsheet shapes and source fidelity."""
import io
import zipfile

from designer.analytics import AnalysisRequest, analyze, import_datasets, profile_dataset
from tests.test_analytics import archive
from make_analytics_samples import xlsx_bytes


def test_blank_and_header_only_sheets_are_reported_without_losing_valid_sheets():
    raw = xlsx_bytes([('Data', ['name', 'sales'], [['A', 10]]), ('Empty', [], []), ('Headers', ['x', 'y'], [])])
    imported = import_datasets(raw, 'team-workbook.xlsx')
    assert [d.ref.table for d in imported.datasets] == ['Data']
    assert {n.params['sheet'] for n in imported.rejected} == {'Empty', 'Headers'}


def test_xlsx_report_title_is_context_not_a_data_row():
    raw = xlsx_bytes([('Sales', ['Monthly sales report'], [['month', 'sales'], ['2026-01', 10], ['2026-02', 20]])])
    imported = import_datasets(raw, 'report.xlsx')
    ds = imported.datasets[0]
    assert [c.name for c in ds.columns] == ['month', 'sales']
    assert ds.rows == [['2026-01', 10], ['2026-02', 20]]
    assert ds.row_ids == [3, 4]
    assert 'Monthly sales report' in ds.context


def test_formula_only_row_without_cached_value_is_not_silently_dropped():
    raw = xlsx_bytes([('Values', ['value'], [[10], [20]])])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = {n: z.read(n) for n in z.namelist()}
    key = 'xl/worksheets/sheet1.xml'
    files[key] = files[key].replace(b'<c r="A3"><v>20</v></c>', b'<c r="A3"><f>A2*2</f></c>')
    result = import_datasets(archive(files), 'formulas.xlsx')
    assert result.datasets[0].rows == [[10], [None]]
    assert result.datasets[0].row_ids == [2, 3]


def test_excel_csv_separator_directive_and_multiline_provenance():
    raw = b'sep=;\nname;sales\n"North\nWest";10\nSouth;20\n'
    result = import_datasets(raw, 'excel.csv')
    assert not result.rejected
    assert result.datasets[0].rows == [['North\nWest', '10'], ['South', '20']]
    assert result.datasets[0].row_ids == [3, 5]


def test_ambiguous_number_separator_requires_explicit_locale():
    ds = import_datasets(b'name;sales\nA;1,234\nB;2,345\n', 'prices.csv').datasets[0]
    result = analyze(ds, AnalysisRequest(task='comparison'))
    assert result.refusal.code == 'analysis.ambiguous_number'
    decimal = analyze(ds, AnalysisRequest(task='comparison', number_locale='decimal_comma'))
    thousands = analyze(ds, AnalysisRequest(task='comparison', number_locale='decimal_point'))
    assert decimal.data.series[0].values == [2.345, 1.234]
    assert thousands.data.series[0].values == [2345, 1234]


def test_numeric_distinct_count_is_independent_of_cell_format():
    ds = import_datasets(b'name,sales\nA,1\nB,1.0\nC,1.00', 'data.csv').datasets[0]
    assert profile_dataset(ds).columns[1].distinct == 1


def test_leading_zero_identifiers_are_not_metrics_or_merged():
    ds = import_datasets(b'customer,sales\n001,10\n01,20\n1,30', 'data.csv').datasets[0]
    p = profile_dataset(ds)
    assert p.columns[0].role == 'identifier'
    r = analyze(ds, AnalysisRequest(task='comparison', dimension='c1', metrics=['c2']))
    assert set(r.data.categories) == {'001', '01', '1'}


def test_excel_percent_format_is_scaled_with_explicit_metadata():
    raw = xlsx_bytes([('Rates', ['month', 'conversion'], [['2026-01', 0.10], ['2026-02', 0.15]])])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files['xl/styles.xml'] = b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="0"/><xf numFmtId="10"/></cellXfs></styleSheet>'
    path = 'xl/worksheets/sheet1.xml'
    files[path] = files[path].replace(b'<c r="B2">', b'<c r="B2" s="1">').replace(b'<c r="B3">', b'<c r="B3" s="1">')
    ds = import_datasets(archive(files), 'rates.xlsx').datasets[0]
    assert ds.rows == [['2026-01', 10], ['2026-02', 15]]
    assert ds.columns[1].normalization == 'excel_percentage_points'
    result = analyze(ds, AnalysisRequest(task='dynamics'))
    assert next(f.value for f in result.facts if f.evidence.operation == 'percentage_points') == 5
    files[path] = files[path].replace(b'<c r="B3" s="1">', b'<c r="B3">')
    mixed = import_datasets(archive(files), 'mixed.xlsx')
    assert mixed.rejected[0].code == 'import.inconsistent_cell_units'


def test_invalid_numeric_xml_and_deep_json_have_readable_rejections():
    raw = xlsx_bytes([('Data', ['name', 'value'], [['A', 10]])])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = {n: z.read(n) for n in z.namelist()}
    path = 'xl/worksheets/sheet1.xml'
    files[path] = files[path].replace(b'<v>10</v>', b'<v>not-a-number</v>')
    assert import_datasets(archive(files), 'invalid.xlsx').rejected[0].code == 'import.invalid_data'
    assert import_datasets(b'['*1500+b']'*1500, 'deep.json').rejected[0].code in {'import.invalid_data', 'import.ambiguous_json'}


def test_extreme_numeric_exponents_are_not_evaluated_or_converted_to_zero():
    ds = import_datasets(b'name,value\nA,1e1000000\nB,1e-1000000', 'extreme.csv').datasets[0]
    assert analyze(ds, AnalysisRequest(task='comparison')).status == 'refused'


def test_large_json_integers_are_portable_exact_text_in_reference_tables():
    ds = import_datasets(b'[{"name":"A","value":9007199254740993}]', 'integers.json').datasets[0]
    assert ds.rows[0][1] == '9007199254740993'
    result = analyze(ds, AnalysisRequest(task='reference'))
    assert result.data.rows[0][1] == '9007199254740993'
    assert '"9007199254740993"' in result.model_dump_json()


def test_cell_budget_counts_data_not_header_cells(monkeypatch):
    import designer.analytics.importing as importing
    monkeypatch.setattr(importing, 'MAX_CELLS', 4)
    assert len(import_datasets(b'name,value\nA,1\nB,2', 'edge.csv').datasets[0].rows) == 2
    raw = xlsx_bytes([('Data', ['name', 'value'], [['A', 1], ['B', 2]])])
    assert len(import_datasets(raw, 'edge.xlsx').datasets[0].rows) == 2


def test_excel_datetime_preserves_midnight_and_time_only_is_an_explicit_day_fraction():
    raw = xlsx_bytes([('Data', ['timestamp', 'sales'], [[46023, 10], [46023.5, 20]])])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = {n: z.read(n) for n in z.namelist()}
    styles = b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="0"/><xf numFmtId="22"/></cellXfs></styleSheet>'
    files['xl/styles.xml'] = styles
    path = 'xl/worksheets/sheet1.xml'
    files[path] = files[path].replace(b'<c r="A2">', b'<c r="A2" s="1">').replace(b'<c r="A3">', b'<c r="A3" s="1">')
    ds = import_datasets(archive(files), 'clock.xlsx').datasets[0]
    assert all('T' in row[0] for row in ds.rows)
    assert len(analyze(ds, AnalysisRequest(task='dynamics')).data.categories) == 2
    files['xl/styles.xml'] = styles.replace(b'numFmtId="22"', b'numFmtId="20"')
    clock = import_datasets(archive(files), 'clock-only.xlsx').datasets[0]
    assert clock.columns[0].unit == 'day'
    assert clock.columns[0].normalization == 'excel_day_fraction'
    assert profile_dataset(clock).columns[0].kind == 'number'


def test_percent_literals_and_mixed_unknown_units_are_not_confused_with_fractions():
    ds = import_datasets(b'month,conversion\n2026-01,10%\n2026-02,15%', 'rates.csv').datasets[0]
    result = analyze(ds, AnalysisRequest(task='dynamics'))
    assert result.profile.columns[1].unit == '%'
    assert next(f.value for f in result.facts if f.evidence.operation == 'percentage_points') == 5
    mixed = import_datasets(b'month,conversion\n2026-01,0.1\n2026-02,15%', 'mixed.csv').datasets[0]
    assert analyze(mixed, AnalysisRequest(task='dynamics')).status == 'refused'
