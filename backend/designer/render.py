"""Растр и текстовый слой страниц PDF.

Единственное место, где сервис открывает PDF и рисует картинки. Держится на
pypdfium2 (Apache-2.0 / BSD-3-Clause, внутри — PDFium от Google) и Pillow
(MIT-CMU): обе лицензии пермиссивные, поэтому проект можно распространять
под MIT. PDF по-прежнему делает LibreOffice отдельным процессом.
"""
from __future__ import annotations

import io
from pathlib import Path

# Точек PDF в дюйме: размер страницы PDF задаётся в пунктах.
POINTS_PER_INCH = 72


def _document(pdf_path: Path):
    import pypdfium2 as pdfium

    return pdfium.PdfDocument(str(pdf_path))


def png(image) -> bytes:
    """Картинка Pillow в PNG."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def page_count(pdf_path: Path) -> int:
    document = _document(pdf_path)
    try:
        return len(document)
    finally:
        document.close()


def page_size(pdf_path: Path, index: int) -> tuple[float, float]:
    """Размер страницы в пунктах PDF."""
    document = _document(pdf_path)
    try:
        return tuple(document[index].get_size())
    finally:
        document.close()


def page_images(pdf_path: Path, width: int | None = None, dpi: float | None = None):
    """Страницы как картинки Pillow (RGB): по ширине в пикселях или по dpi."""
    document = _document(pdf_path)
    images = []
    try:
        for page in document:
            points = page.get_width() or 1
            scale = (width / points) if width else ((dpi or POINTS_PER_INCH) / POINTS_PER_INCH)
            bitmap = page.render(scale=scale)
            images.append(bitmap.to_pil().convert("RGB"))
            page.close()
    finally:
        document.close()
    return images


def render_page(pdf_path: Path, index: int, width: int = 1280) -> bytes:
    """Одна страница PDF — PNG заданной ширины, без рендера остальных."""
    document = _document(pdf_path)
    try:
        page = document[index]
        bitmap = page.render(scale=width / (page.get_width() or 1))
        image = bitmap.to_pil().convert("RGB")
        page.close()
        return png(image)
    finally:
        document.close()


def render_pages(pdf_path: Path, width: int = 1280) -> list[bytes]:
    """Каждая страница PDF — PNG заданной ширины."""
    return [png(image) for image in page_images(pdf_path, width=width)]


def text_runs(pdf_path: Path, index: int) -> list[dict]:
    """Строки текста страницы с положением — для выделяемого слоя поверх растра.

    Координаты в пунктах от левого верхнего угла, как в SVG: у PDF начало
    отсчёта внизу, поэтому ось Y переворачивается.
    """
    document = _document(pdf_path)
    try:
        page = document[index]
        _, height = page.get_size()
        textpage = page.get_textpage()
        runs = []
        for number in range(textpage.count_rects()):
            left, bottom, right, top = textpage.get_rect(number)
            text = textpage.get_text_bounded(left, bottom, right, top).strip()
            if not text or right <= left or top <= bottom:
                continue
            runs.append(
                {
                    "x": left,
                    "y": height - top,
                    "width": right - left,
                    "height": top - bottom,
                    "text": " ".join(text.split()),
                }
            )
        textpage.close()
        page.close()
        return runs
    finally:
        document.close()


def image_from_bytes(blob: bytes):
    """PNG или JPEG как картинка Pillow; прозрачность сохраняется в RGBA."""
    from PIL import Image

    image = Image.open(io.BytesIO(blob))
    image.load()
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        return image.convert("RGBA")
    return image.convert("RGB")
