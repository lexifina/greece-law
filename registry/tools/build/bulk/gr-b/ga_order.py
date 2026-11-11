"""GR-A: stored page lines (text/<series>/<year>/<id>.json.gz, text layer or OCR) -> body lines in reading order.

reading_order(doc) -> [{'p', 't', 'x0', 'y0', 'x1', 'indent', 'bold', 'small', 'wide'}]
  - t normalised by scripts/greece-law/parse_n4624.norm_line (look-alike Latin letters inside Greek words,
    soft hyphens, NBSP, apostrophes) - used as a library, not modified;
  - running heads/page numbers dropped (top band of each page, P.is_junk patterns);
  - a page where >= 40% of lines cross the middle is single-column: read top to bottom;
  - else each page is cut into bands at full-width lines (as fek_reader.read_lines): inside a band the left column, then the
    right one; each full-width line read in its place; justified lines split into fragments are joined
    (fek_reader.justified_runs). Smaller type (tables, footnotes) is kept (flag 'small').
Only p, t, x0, y0, x1, y1 are required of a stored line, so OCR lines plug in unchanged (size/bold/b optional).
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

GR = Path(r'C:\Users\alany\Documents\lexifina\scripts\greece-law')
if str(GR) not in sys.path:
    sys.path.insert(0, str(GR))
import parse as P  # noqa: E402
import parse_n4624 as N  # noqa: E402
from fek_reader import justified_runs, _edge  # noqa: E402

TOP = 75 / 842  # running-head band (fraction of page height): the hand-built readers drop y0 < 75 on A4


def load(path: Path) -> dict:
    with gzip.open(path, 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def body_size(lines: list[dict]) -> float | None:
    sizes: dict[float, int] = {}
    for l in lines:
        if l.get('size'):
            k = round(l['size'] * 2) / 2
            sizes[k] = sizes.get(k, 0) + len(l['t'])
    return max(sizes, key=lambda k: (sizes[k], -k)) if sizes else None


def reading_order(doc: dict) -> list[dict]:
    lines = doc['lines']
    body = body_size(lines)
    heights = {pi['page']: pi['h'] for pi in doc.get('page_info', [])}
    pages: dict[int, list[dict]] = {}
    for l in lines:
        t = N.norm_line(l['t'])
        h = heights.get(l['p'], 842.0)
        if not t or l['y0'] < TOP * h:
            continue
        if P.is_junk(t):
            continue
        size = l.get('size')
        pages.setdefault(l['p'], []).append({
            'p': l['p'], 'page': l['p'], 't': t, 'x0': l['x0'], 'y0': l['y0'], 'x1': l['x1'],
            'bold': bool(l.get('bold')), 'small': bool(body and size and size < body - 0.6),
            'big': bool(body and size and size > body + 1.5), '_blk': l.get('b', 0)})
    out: list[dict] = []
    for pno in sorted(pages):
        pl = pages[pno]
        lo = min(l['x0'] for l in pl)
        hi = max(l['x1'] for l in pl)
        mid = (lo + hi) / 2
        is_wide = lambda l: l['x0'] < mid - 6 and l['x1'] > mid + 6  # noqa: E731
        nwide = sum(1 for l in pl if is_wide(l))
        if nwide >= 0.4 * len(pl):
            # a single-column page (most lines cross the middle): read top to bottom, indents from the page edge
            col = sorted(pl, key=lambda l: (l['y0'], l['x0']))
            edge = _edge(col)
            for l in justified_runs(col, edge, max(l['x1'] for l in col)):
                l['indent'] = l['x0'] - edge
                l['wide'] = is_wide(l)
                out.append(l)
            continue
        wide = sorted((l for l in pl if is_wide(l)), key=lambda l: l['y0'])
        cols = [l for l in pl if not is_wide(l)]
        cuts = [w['y0'] for w in wide] + [10 ** 9]
        prev, wi = -1.0, 0
        for cut in cuts:
            band = [l for l in cols if prev <= l['y0'] < cut]
            for col in ([l for l in band if l['x1'] <= mid + 6], [l for l in band if l['x0'] >= mid - 6]):
                if not col:
                    continue
                col = sorted(col, key=lambda l: (l['y0'], l['x0']))
                edge = _edge(col)
                for l in justified_runs(col, edge, max(l['x1'] for l in col)):
                    l['indent'] = l['x0'] - edge
                    l['wide'] = False
                    out.append(l)
            if wi < len(wide):
                w = wide[wi]
                w['indent'] = w['x0'] - lo
                w['wide'] = True
                out.append(w)
                wi += 1
            prev = cut
    for l in out:
        l.pop('_blk', None)
    return out
