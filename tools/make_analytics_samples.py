"""Deterministic synthetic D6 sources, independent controls and integration examples."""
import argparse
import csv
import io
import json
import random
import sys
import zipfile
from pathlib import Path
from statistics import median
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from designer.analytics import AnalysisRequest, AnalysisResult, Dataset, analyze, import_datasets


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def csv_bytes(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows([columns, *rows])
    return stream.getvalue().encode("utf-8")


def xlsx_bytes(sheets):
    """Small deterministic, valid OOXML fixtures; no formula evaluation."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))+'</Types>',
        '_rels/.rels': f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'+''.join(f'<sheet name="{escape(name)}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, (name, _, _) in enumerate(sheets))+'</sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i+1}" Type="{rel}/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(len(sheets)))+'</Relationships>',
    }
    for i, (_, header, rows) in enumerate(sheets):
        parts = []
        for row_id, row in enumerate([header, *rows], 1):
            cells = []
            for c, value in enumerate(row):
                ref = f'{chr(65+c)}{row_id}'
                if value is None:
                    continue
                cells.append(f'<c r="{ref}"><v>{value}</v></c>' if isinstance(value, (int, float)) else
                             f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
            parts.append(f'<row r="{row_id}">'+''.join(cells)+'</row>')
        files[f'xl/worksheets/sheet{i+1}.xml'] = f'<worksheet xmlns="{ns}"><sheetData>'+''.join(parts)+'</sheetData></worksheet>'
    stream = io.BytesIO()
    # Stored entries make fixtures byte-identical across Python/zlib versions.
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content.encode())
    return stream.getvalue()


def build(output):
    contract = output / 'contract'
    datasets = output / 'datasets'
    contract.mkdir(parents=True, exist_ok=True)
    datasets.mkdir(parents=True, exist_ok=True)
    write_json(contract/'analysis-result.schema.json', AnalysisResult.model_json_schema())
    write_json(contract/'dataset.schema.json', Dataset.model_json_schema())
    write_json(contract/'analysis-request.schema.json', AnalysisRequest.model_json_schema())
    examples = [
        ('time-series', 'dynamics', ['month', 'sales'], [['2026-01', 100], ['2026-02', 120], ['2026-03', 150]]),
        ('categories', 'comparison', ['region', 'sales'], [['North', 10], ['South', 20], ['West', 30]]),
        ('shares', 'shares', ['channel', 'sales'], [['Online', 60], ['Offline', 40]]),
    ]
    for name, task, header, rows in examples:
        raw = csv_bytes(header, rows)
        (contract/(name+'.csv')).write_bytes(raw)
        ds = import_datasets(raw, name+'.csv').datasets[0]
        request = AnalysisRequest(goal=task, task=task, dimension='c1', metrics=['c2'], unit='units', locale='en')
        result = analyze(ds, request)
        for suffix, obj in [('dataset', ds), ('request', request), ('result', result)]:
            write_json(contract/(name+'.'+suffix+'.json'), obj.model_dump(mode='json'))
    rng = random.Random(20261017)
    orders = [[i+1, rng.randint(100, 1000), rng.randint(1, 48)] for i in range(60)]
    catalog = [[f'SKU-{i+1:04}', f'Product {i+1}', ['A', 'B', 'C'][i % 3], i+1] for i in range(240)]
    time_rows = [[f'2026-{month:02}', region, month*factor] for month in range(1, 7) for region, factor in [('North', 100), ('South', 200)]]
    source_sets = [
        ('01-sales', ['month', 'region', 'sales'], time_rows,
         AnalysisRequest(goal='показать рост', dimension='c1', metrics=['c3'], unit='RUB')),
        ('02-regions', ['region', 'sales'], [['Northern region with a long label', 80], ['South', 120], ['West', 60]],
         AnalysisRequest(goal='сравнить регионы', dimension='c1', metrics=['c2'], unit='RUB')),
        ('03-channels', ['channel', 'sales'], [['Online', 60], ['Retail', 30], ['Partners', 10]],
         AnalysisRequest(goal='структура долей', dimension='c1', metrics=['c2'], unit='RUB')),
        ('04-orders', ['order_id', 'amount', 'hours'], orders,
         AnalysisRequest(goal='распределение', metrics=['c2'], unit='RUB', bins=6)),
        ('05-catalog', ['sku', 'product', 'category', 'sales'], catalog,
         AnalysisRequest(goal='справочная таблица', task='reference', page_size=10)),
        ('06-missing', ['month', 'sales'], [['2026-01', 100], ['2026-02', 110], ['2026-03', None], ['2026-04', 120], ['2026-05', 130], ['2026-06', 1000]],
         AnalysisRequest(goal='динамика', dimension='c1', metrics=['c2'], unit='RUB')),
    ]
    for name, header, rows, request in source_sets:
        raw = csv_bytes(header, rows)
        (datasets/(name+'.csv')).write_bytes(raw)
        ds = import_datasets(raw, name+'.csv').datasets[0]
        write_json(datasets/(name+'.request.json'), request.model_dump(mode='json'))
        write_json(datasets/(name+'.result.json'), analyze(ds, request).model_dump(mode='json'))
    text = '# Synthetic sales report / Синтетические данные\nSales by channel, RUB.\n\n| channel | sales |\n| --- | --- |\n| Online | 60 |\n| Retail | 30 |\n| Partners | 10 |\n\nAll channels are included.\n'
    (datasets/'07-report.md').write_text(text, encoding='utf-8', newline='\n')
    request = AnalysisRequest(goal='доли', dimension='c1', metrics=['c2'], unit='RUB')
    ds = import_datasets(text.encode(), '07-report.md').datasets[0]
    write_json(datasets/'07-report.request.json', request.model_dump(mode='json'))
    write_json(datasets/'07-report.result.json', analyze(ds, request).model_dump(mode='json'))
    write_json(datasets/'01-sales.json', [dict(zip(['month', 'region', 'sales'], r)) for r in time_rows])
    (datasets/'01-sales.xlsx').write_bytes(xlsx_bytes([('Sales', ['month', 'region', 'sales'], time_rows)]))
    controls = {
        'synthetic': True, 'seed': 20261017,
        '01-sales': {'row_count': 12, 'monthly_totals': [300, 600, 900, 1200, 1500, 1800],
                     'growth_percent': 500, 'region_totals': {'North': 2100, 'South': 4200}},
        '02-regions': {'order': ['South', 'Northern region with a long label', 'West'], 'values': [120, 80, 60]},
        '03-channels': {'total': 100, 'percent': {'Online': 60, 'Retail': 30, 'Partners': 10}},
        '04-orders': {'count': 60, 'amount_sum': sum(r[1] for r in orders), 'amount_median': median(r[1] for r in orders),
                      'xy': [[r[1], r[2]] for r in orders]},
        '05-catalog': {'row_count': 240, 'sales_sum': 28920, 'pages_at_10': 24},
        '06-missing': {'missing_csv_rows': [4], 'outlier_csv_rows': [7], 'sum_nonmissing': 1460,
                       'values': [100, 110, None, 120, 130, 1000]},
        '07-report': {'table_rows': 3, 'values': {'Online': 60, 'Retail': 30, 'Partners': 10}},
    }
    write_json(datasets/'controls.json', controls)
    # The manifest lists honest supported formats and independent acceptance criteria.
    write_json(datasets/'manifest.json', {'synthetic': True, 'logical_dataset_count': 7,
        'same_table_formats': ['01-sales.csv', '01-sales.json', '01-sales.xlsx'],
        'controls': 'controls.json', 'mutation_checks': ['change a source value', 'swap category values',
            'reorder rows', 'add nulls', 'change analysis goal', 'change presentation template externally']})
    mutations = datasets/'mutations'
    mutations.mkdir(exist_ok=True)
    altered = [list(r) for r in time_rows]
    altered[-1][-1] += 500
    (mutations/'01-sales-changed-value.csv').write_bytes(csv_bytes(['month', 'region', 'sales'], altered))
    (mutations/'01-sales-reversed.csv').write_bytes(csv_bytes(['month', 'region', 'sales'], list(reversed(time_rows))))
    (mutations/'03-channels-swapped.csv').write_bytes(csv_bytes(['channel', 'sales'], [['Online', 30], ['Retail', 60], ['Partners', 10]]))
    (mutations/'03-channels-missing.csv').write_bytes(csv_bytes(['channel', 'sales'], [['Online', None], ['Retail', 30], ['Partners', 10]]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'samples'/'analytics')
    build(parser.parse_args().output)
