from pathlib import Path

import pymupdf
from lxml import html

from designer.exporting import export_html


def text_pdf(path):
    font = Path(__file__).resolve().parents[1] / 'designer/assets/fonts/Play-Regular.ttf'
    with pymupdf.open() as document:
        page = document.new_page(width=720, height=405)
        page.insert_font(fontname='Play', fontfile=str(font))
        page.insert_text((40, 90), '186 минут', fontname='Play', fontsize=28)
        page.insert_text((40, 140), '<script>alert("x")</script> & результат', fontname='Play', fontsize=18)
        document.save(path)


def test_html_contains_live_searchable_cyrillic_without_size_regression(tmp_path):
    pdf, output = tmp_path / 'slide.pdf', tmp_path / 'slide.html'
    text_pdf(pdf)
    export_html(pdf, output, 'Результат', language='ru')
    text = output.read_text(encoding='utf-8')
    document = html.fromstring(text)
    assert '186 минут' in text
    assert '186 минут' in document.text_content()
    assert document.xpath('//svg//text')
    assert not document.xpath('//script')
    assert '<script>alert("x")</script>' in document.text_content()
    with pymupdf.open(pdf) as source:
        prior_svg = source[0].get_svg_image(text_as_path=True).encode('utf-8')
    assert output.stat().st_size <= len(prior_svg) * 1.5


def test_html_language_and_title_are_escaped(tmp_path):
    pdf, output = tmp_path / 'slide.pdf', tmp_path / 'slide.html'
    text_pdf(pdf)
    export_html(pdf, output, '<b>Title</b>', language='en-GB')
    document = html.fromstring(output.read_text(encoding='utf-8'))
    assert document.attrib['lang'] == 'en-GB'
    assert document.xpath('//title')[0].text == '<b>Title</b>'
    export_html(pdf, output, 'Title', language='en" onload="alert(1)')
    document = html.fromstring(output.read_text(encoding='utf-8'))
    assert 'onload' not in document.attrib


def test_export_endpoint_uses_generation_language_and_replaces_old_cache(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from designer.app import create_app
    monkeypatch.delenv('DESIGNER_API_KEY', raising=False)
    monkeypatch.delenv('DESIGNER_SEED_TEMPLATES', raising=False)
    with TestClient(create_app(tmp_path / 'data')) as client:
        store = client.app.state.store
        identifier = store.new_id()
        store.put('presentations', {'id': identifier, 'revision': 1, 'title': 'Timing',
                                   'variant': 'classic', 'generation': {'language': 'en-GB'}})
        folder = store.directory('presentations', identifier)
        (folder / 'r1.pptx').write_bytes(b'cached source')
        text_pdf(folder / 'r1.pdf')
        (folder / 'r1.html').write_text('<html lang="ru">old path-based export</html>', encoding='utf-8')
        response = client.get(f'/api/v1/presentations/{identifier}/export/html')
        assert response.status_code == 200
        assert html.fromstring(response.text).attrib['lang'] == 'en-GB'
        assert '186 минут' in response.text
        assert 'old path-based export' not in response.text
        # A second read keeps the valid artifact cache.
        modified = (folder / 'r1.html').stat().st_mtime_ns
        assert client.get(f'/api/v1/presentations/{identifier}/export/html').status_code == 200
        assert (folder / 'r1.html').stat().st_mtime_ns == modified
