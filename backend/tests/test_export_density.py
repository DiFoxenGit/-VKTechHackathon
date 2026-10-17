"""Regressions found by rendering a real eight-slide model-generated deck."""
import shutil

import pytest

from designer.exporting import convert_pdf, export_pptx, value_axis_title
from designer.layout import compose
from designer.models import Outline
from designer.parsing import parse_template
from designer.render import text_runs
from tests.test_pipeline import template_bytes


def test_axis_keeps_unit_instead_of_repeating_a_slide_conclusion():
    visual = {'unit': 'мин', 'series': [{'name': 'Автоматическая вёрстка повышает эффективность и соблюдение стиля, как показал пилот'}]}
    assert value_axis_title(visual) == 'мин'
    assert value_axis_title({'unit': 'мин', 'series': [{'name': 'Сборка'}]}) == 'Сборка, мин'


@pytest.mark.skipif(not (shutil.which('libreoffice') or shutil.which('soffice')), reason='LibreOffice required')
def test_dense_table_stays_inside_its_frame_after_pdf_conversion(tmp_path):
    source = tmp_path / 'template.pptx'
    source.write_bytes(template_bytes())
    template = parse_template(source.read_bytes(), 'sample.pptx')
    outline = Outline.model_validate({'title': 'Dense table', 'slides': [{
        'title': 'Seven rows fit the planned frame', 'source_refs': ['brief'],
        'visual': {'kind': 'table', 'columns': ['Metric', 'Value'],
                   'rows': [[f'Metric {index}', f'Value {index}'] for index in range(6)]},
    }]})
    deck = compose(outline.model_dump(), template, 'classic')
    visual = next(element for element in deck['slides'][0]['elements'] if element['kind'] == 'table')
    visual['box'] = [36, 200, 600, 133]
    pptx, pdf = tmp_path / 'dense.pptx', tmp_path / 'dense.pdf'
    export_pptx(source, template, deck, pptx)
    convert_pdf(pptx, pdf)
    runs = [run for run in text_runs(pdf, 0) if 'Metric 5' in run['text'] or 'Value 5' in run['text']]
    assert runs, 'All table rows must remain visible'
    assert max(run['y'] + run['height'] for run in runs) <= 334
