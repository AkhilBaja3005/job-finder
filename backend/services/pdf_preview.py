"""PDF pages as images (for the in-app preview) and how full the page is. Needs pypdfium2; every function answers
None / [] instead of raising when it is missing or the file is not a PDF."""
from __future__ import annotations

import base64
import io
from typing import List, Optional


def _open(pdf_path: str):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(pdf_path)


def render_pages(pdf_path: str, scale: float = 1.4, max_pages: int = 3) -> List[str]:
    """Each page (up to max_pages) as a PNG data URI."""
    try:
        pdf = _open(pdf_path)
        out = []
        for i in range(min(len(pdf), max_pages)):
            buf = io.BytesIO()
            pdf[i].render(scale=scale).to_pil().convert("RGB").save(buf, "PNG", optimize=True)
            out.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
        return out
    except Exception:
        return []


def fill_ratio(pdf_path: str) -> Optional[float]:
    """How far down the (last) page the ink goes, 0..1; None when it cannot be measured."""
    try:
        from PIL import ImageChops, Image
        pdf = _open(pdf_path)
        img = pdf[len(pdf) - 1].render(scale=1.0).to_pil().convert("L")
        bbox = ImageChops.invert(img).point(lambda p: 255 if p > 40 else 0).getbbox()
        return round(bbox[3] / img.size[1], 3) if bbox else 0.0
    except Exception:
        return None


def page_count(pdf_path: str) -> Optional[int]:
    try:
        return len(_open(pdf_path))
    except Exception:
        return None
