"""Gazette page reader with full-width bands (used by parse_n5160.py, parse_single.py and parse_n3471.py).

parse_n4624.read_lines reads each page as two columns and drops any line that spans both, such as the full-width
commencement article on a law's last page or a table set across the page. Here a page is cut into horizontal bands
at every full-width line: inside a band the left column is read before the right one, and each full-width line is
read in its place between bands. Lines of a table (smaller type, set across the page) are kept when KEEP_SMALL is on.
The rest is parse_n4624.read_lines unchanged (same filters, same fields), so pages with two clean columns read the
same.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

import parse as P  # noqa: E402  (is_junk)
import parse_n4624 as N  # noqa: E402

KEEP_SMALL = False


def read_lines(path: Path) -> list[dict]:
    out = []
    doc = fitz.open(path)
    sizes: dict[float, int] = {}
    for page in doc:
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        k = round(s['size'] * 2) / 2
                        sizes[k] = sizes.get(k, 0) + len(s['text'])
    body = max(sizes, key=lambda k: (sizes[k], -k))
    for pno, page in enumerate(doc):
        lines = []
        for b in page.get_text('dict')['blocks']:
            if b['type'] != 0:
                continue
            for l in b['lines']:
                spans = [s for s in l['spans'] if s['text'].strip()]
                if not spans:
                    continue
                t = N.norm_line(''.join(s['text'] for s in l['spans']))
                size = max(s['size'] for s in spans)
                x0, y0, x1, _ = l['bbox']
                small = size < body - 0.6
                if P.is_junk(t) or size > body + 1.5 or (small and not KEEP_SMALL) or y0 < 75:
                    continue
                bold_chars = sum(len(s['text']) for s in spans if s['flags'] & 16)
                lines.append({'x0': x0, 'y0': y0, 'x1': x1, 't': t, 'page': pno, 'small': small,
                              'bold': bold_chars * 2 > sum(len(s['text']) for s in spans)})
        if not lines:
            continue
        lo = min(l['x0'] for l in lines)
        hi = max(l['x1'] for l in lines)
        mid = (lo + hi) / 2
        wide = sorted((l for l in lines if l['x0'] < mid - 6 and l['x1'] > mid + 6), key=lambda l: l['y0'])
        cols = [l for l in lines if not (l['x0'] < mid - 6 and l['x1'] > mid + 6)]
        cuts = [w['y0'] for w in wide] + [10 ** 9]
        prev = -1.0
        wi = 0
        for cut in cuts:
            band = [l for l in cols if prev <= l['y0'] < cut]
            left = [l for l in band if l['x1'] <= mid + 6]
            right = [l for l in band if l['x0'] >= mid - 6]
            for col in (left, right):
                if not col:
                    continue
                # the column's left edge: the most common line start (a stray fragment set a little to the left
                # must not shift every indent)
                lo_x = min(l['x0'] for l in col)
                xs = [round(l['x0']) for l in col if l['x0'] <= lo_x + 12]
                edge = min(xs, key=lambda x: (-xs.count(x), x))
                edge = min(l['x0'] for l in col if l['x0'] >= edge - 1.5)
                for l in sorted(col, key=lambda l: l['y0']):
                    l['indent'] = l['x0'] - edge
                    out.append(l)
            if wi < len(wide):
                w = wide[wi]
                w['indent'] = w['x0'] - lo
                out.append(w)
                wi += 1
            prev = cut
    return out
