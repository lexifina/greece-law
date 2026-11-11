"""GR-A: the OCR request list for GR-OCR: every held Α΄ act that needs OCR (pages without a text layer, or a text
layer in an unmapped/garbled font), by issue, with the page range to OCR (0-based, inclusive).

    python -X utf8 -I ocr_requests.py      -> <WORK>/OCR-REQUESTS.tsv (id, url, pages, reason, slugs), newest first
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import SRC, WORK  # noqa: E402

rows: dict[str, dict] = {}
for f in sorted(glob.glob(str(WORK / 'held' / 'b-a-*.json'))):
    for h in json.loads(Path(f).read_text(encoding='utf-8'))['held']:
        why = h['why']
        if not ('pages without' in why or 'unreadable' in why or 'control characters' in why):
            continue
        iid = h.get('id')
        if not iid:
            continue
        meta = json.loads((SRC / 'meta' / '01' / iid[:4] / f'{iid}.json').read_text(encoding='utf-8'))
        r = rows.setdefault(iid, {'url': meta['url'], 'pages': set(), 'why': set(), 'slugs': []})
        lo, hi = h['pages']
        if 'pages without' in why:
            # only the pages without a text layer (the act's text-layer pages are read already)
            r['pages'].update(p for p in meta.get('no_text_pages', []) if lo <= p <= hi + 1)
            r['why'].add('scan pages')
        else:
            r['pages'].update(range(lo, hi + 1))
            r['why'].add('garbled font')
        r['slugs'].append(h['slug'])
out = ['id\turl\tpages\treason\tslugs']
for iid in sorted(rows, reverse=True):
    r = rows[iid]
    ps = sorted(r['pages'])
    spans, a = [], ps[0]
    for x, y in zip(ps, ps[1:] + [None]):
        if y != x + 1:
            spans.append(f'{a}-{x}' if a != x else str(a))
            a = y
    out.append(f'{iid}\t{r["url"]}\t{",".join(spans)}\t{"+".join(sorted(r["why"]))}\t{",".join(r["slugs"])}')
(WORK / 'OCR-REQUESTS.tsv').write_text('\n'.join(out) + '\n', encoding='utf-8')
print(len(out) - 1, 'issues')
