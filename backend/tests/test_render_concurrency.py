"""All public PDF entrypoints share one lock around native document lifetimes."""
from concurrent.futures import ThreadPoolExecutor
import io
import threading
import time

from PIL import Image
from pypdf import PdfWriter

from designer import render


def test_pdf_entrypoints_serialize_native_documents(tmp_path, monkeypatch):
    path = tmp_path / 'page.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=320, height=180)
    with path.open('wb') as file:
        writer.write(file)
    original = render._document
    counter_lock = threading.Lock()
    active = maximum = 0

    def document(filename):
        nonlocal active, maximum
        with counter_lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.005)  # Allows competing entrypoints to expose an absent lock.
        pdf = original(filename)
        close = pdf.close
        def release():
            nonlocal active
            try:
                close()
            finally:
                with counter_lock:
                    active -= 1
        pdf.close = release
        return pdf

    monkeypatch.setattr(render, '_document', document)
    operations = [lambda: render.page_count(path), lambda: render.page_size(path, 0),
        lambda: render.page_images(path, width=160), lambda: render.render_page(path, 0, 160),
        lambda: render.text_runs(path, 0)] * 3
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda operation: operation(), operations))
    assert maximum == 1
    assert active == 0
    assert results[0] == 1
    assert results[1] == (320, 180)
    with Image.open(io.BytesIO(results[3])) as image:
        assert image.size == (160, 90)
