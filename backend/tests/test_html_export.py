import shutil
from pathlib import Path

from lxml import html

from designer.exporting import export_html

# Страница 720×405 pt со встроенным подмножеством шрифта Play: «186 минут» и строка,
# похожая на разметку, — чтобы проверить экранирование текстового слоя.
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'text-slide.pdf'


def text_pdf(path):
    shutil.copyfile(FIXTURE, path)


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
    # Слайд — растр плюс текстовый слой: страница с двумя строками не должна
    # весить больше, чем нужно для резкой картинки на экране ноутбука.
    assert output.stat().st_size <= 400 * 1024


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
