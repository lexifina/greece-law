"""GR-A: read one ΦΕΚ PDF's text layer into per-page line data (the text/<series>/<year>/<id>.json.gz format).

Format (shared with GR-OCR, which writes the same shape with text_source "OCR (tesseract ell, <ver>)"):

    {"id": "20190100141", "series": "01", "year": 2019, "number": 141, "text_source": "text layer",
     "reader": "PyMuPDF <ver>", "sha256": "<pdf sha256>", "pages": N,
     "page_info": [{"page": 0, "w": 595.3, "h": 841.9, "text": true, "legacy": false}, ...],
     "lines": [{"p": 0, "t": "text", "x0": .., "y0": .., "x1": .., "y1": .., "size": 9.0, "bold": false, "b": 3}, ...]}

`lines` are in the text layer's own order (blocks, then lines); reading order (columns) is made by
split.reading_order(), which needs only p, t, x0, y0, x1, y1 (size/bold/b optional, so OCR lines plug in).
`t` is the line as the PDF gives it, NFC, with the legacy Windows-1253 font mapped back (see legacy()); no other
normalisation (look-alike letters etc. are normalised by the splitter).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF

READER = f'PyMuPDF {fitz.version[0]} (MuPDF {fitz.version[1]})'
LEGACY_MARK = set('≡⌠▄▀ß≤≥╟╠╤╔╙┼')
LETTER = re.compile(r'[^\W\d_]')


def legacy(text: str) -> str:
    """The ~2000-2001 legacy Greek font: PyMuPDF on this machine returns its Windows-1253 bytes as code page 437
    glyphs (scripts/greece-law/coverage.py legacy()). Map each back to its byte and decode as Windows-1253; byte 0x88
    (undefined there) is the font's ano teleia."""
    out = []
    for ch in text:
        if ord(ch) < 0x80:
            out.append(ch)
            continue
        try:
            b = ch.encode('cp437')[0]
        except UnicodeEncodeError:
            out.append(ch)
            continue
        out.append('·' if b == 0x88 else bytes([b]).decode('cp1253', errors='replace'))
    return ''.join(out)


def is_legacy(text: str) -> bool:
    return sum(text.count(c) for c in LEGACY_MARK) > 0.03 * max(1, len(text))


def page_has_text(text: str) -> bool:
    """A page has a usable text layer when it holds at least 40 letters (a scan carries at most a barcode)."""
    return len(LETTER.findall(text)) >= 40


def read_pdf(path: Path, meta: dict) -> dict:
    data = Path(path).read_bytes()
    doc = fitz.open(stream=data, filetype='pdf')
    info, lines = [], []
    for pno, page in enumerate(doc):
        raw = page.get_text()
        leg = is_legacy(raw)
        has = page_has_text(legacy(raw) if leg else raw)
        info.append({'page': pno, 'w': round(page.rect.width, 1), 'h': round(page.rect.height, 1), 'text': has,
                     'legacy': leg})
        if not has:
            continue
        for b in page.get_text('dict')['blocks']:
            if b['type'] != 0:
                continue
            for l in b['lines']:
                spans = [s for s in l['spans'] if s['text'].strip()]
                if not spans:
                    continue
                t = ''.join(s['text'] for s in l['spans'])
                if leg:
                    t = legacy(t)
                t = unicodedata.normalize('NFC', t)
                n = sum(len(s['text']) for s in spans)
                x0, y0, x1, y1 = l['bbox']
                lines.append({'p': pno, 't': t, 'x0': round(x0, 2), 'y0': round(y0, 2), 'x1': round(x1, 2),
                              'y1': round(y1, 2), 'size': round(max(s['size'] for s in spans), 2),
                              'bold': sum(len(s['text']) for s in spans if s['flags'] & 16) * 2 > n,
                              'b': b['number']})
    return {**meta, 'text_source': 'text layer', 'reader': READER, 'sha256': hashlib.sha256(data).hexdigest(),
            'pages': doc.page_count, 'page_info': info, 'lines': lines}
