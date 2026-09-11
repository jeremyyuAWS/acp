"""Bounded page evidence for a uniquely page-associated tagged Figure.

Multiple tagged Figures on one page need region mapping first. A page image cannot
honestly identify which of those figures an alt-text proposal describes.
"""
from io import BytesIO


def render_pdf_page(data: bytes, page_index: int) -> bytes | None:
    try:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(data) as pdf:
            if not 0 <= page_index < len(pdf):
                return None
            page = pdf[page_index]
            try:
                width, height = page.get_size()
                if not 0 < width <= 20000 or not 0 < height <= 20000:
                    return None
                bitmap = page.render(scale=min(1.5, 1500 / max(width, height)))
                try:
                    image = bitmap.to_pil().convert('RGB')
                    try:
                        stream = BytesIO()
                        image.save(stream, format='PNG')
                        rendered = stream.getvalue()
                        if len(rendered) > 1024 * 1024:
                            stream = BytesIO()
                            image.save(stream, format='JPEG', quality=80)
                            rendered = stream.getvalue()
                        return rendered if len(rendered) <= 1024 * 1024 else None
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    except Exception:
        return None
