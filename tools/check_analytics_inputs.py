"""Audit available team files without copying their content into the report."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from designer.analytics import AnalysisRequest, analyze, import_datasets, verify_result
from designer.analytics.importing import MAX_BYTES


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def inventory(team_root):
    found = []
    for directory, dirs, files in os.walk(team_root):
        dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', 'tmp', 'analytics', '__pycache__', 'target'}
                   and not d.startswith('.venv')]
        found.extend(Path(directory)/name for name in files if Path(name).suffix.lower() in {'.csv', '.xlsx'})
    return sorted(found)


def inspect(path):
    entry = {'path': os.path.relpath(path, ROOT).replace('\\', '/'), 'size_bytes': path.stat().st_size,
             'source_sha256': digest(path)}
    if entry['size_bytes'] > MAX_BYTES:
        entry.update(check='size_preflight_only', rejected=[{'code': 'import.file_limit'}], datasets=[])
        return entry
    raw = path.read_bytes()
    result = import_datasets(raw, path.name)
    datasets = []
    for dataset in result.datasets:
        request = AnalysisRequest(task='reference')
        analysis = analyze(dataset, request)
        datasets.append({'table': dataset.ref.table, 'rows': len(dataset.rows), 'columns': len(dataset.columns),
                         'context_preserved': dataset.context == raw.decode('utf-8-sig') if path.suffix.lower() in {'.md', '.txt'} else None,
                         'reference_status': analysis.status, 'reference_rows_equal': analysis.data.rows == dataset.rows,
                         'verified': verify_result(dataset, request, analysis),
                         'warnings': [n.code for n in dataset.warnings]})
    entry.update(check='import_and_reference_analysis', datasets=datasets,
                 rejected=[n.model_dump(mode='json') for n in result.rejected])
    return entry


def audit(team_root):
    sources = [ROOT/'samples'/'source'/'материал-инициатива.md', ROOT/'samples'/'source'/'материал-продукт.md',
               ROOT/'docs'/'API.md', ROOT/'docs'/'test-run.md', ROOT/'samples'/'content-pack'/'visual-pack.zip',
               team_root/'final-tasks.md', team_root/'Презентации сервиса 27.09.zip', team_root/'Переделка чужой презентации 27.09.zip']
    tabular = inventory(team_root)
    checked = list(dict.fromkeys(p.resolve() for p in sources+tabular if p.is_file()))
    return {'scope': 'available team files; technical documentation is not business data',
            'external_business_values_verified': False,
            'csv_xlsx_outside_generated_samples': [os.path.relpath(p, team_root).replace('\\', '/') for p in tabular],
            'files': [inspect(p) for p in checked],
            'limitations': ['No real business totals can be certified without source data and expected answers.',
                            'Synthetic XLSX edge cases are tested separately.', 'This does not exercise HTTP, model, layout or export.']}


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--team-root', type=Path, default=ROOT.parent)
    parser.add_argument('--output', type=Path, default=ROOT/'tmp'/'analytics-input-audit.json')
    args = parser.parse_args()
    save(args.output, audit(args.team_root))
