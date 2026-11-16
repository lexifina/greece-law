"""GR-A task 4: "amended, not consolidated" labels from the et.gr relation index (labels_job.py output).

relations() -> {(year, issue number): {(other label, relation): row}} for ΦΕΚ Α΄ issues, from
  - each issue's /0 list: rows with Direction -1 (the other document acts on this issue), and
  - every Α΄ issue's /1 list (fetched when its /0 list was capped): rows with Direction 1 naming an Α΄ issue are
    inverted (the fetched issue acts on the named one).
Kept relations: RelationshipTypeID 0 «Τροποποίηση», 5 «Αντικατάσταση», 3 «Ακύρωση», from documents labelled Α or Β
(task 4). Each row: {ref: 'ΦΕΚ Α΄ 27/2020' (or 'ΦΕΚ Β΄ 6604/2026'), title: the relation's Greek label, url: the
official API PDF of that issue}.
Rules (build_part applies them): only laws and π.δ. published 1975 or later are labelled; an issue's relations go
to its act only when the issue holds exactly one law/π.δ. in the part (relations are per issue, not per act);
status "amended, not consolidated" for any kept relation; "repealed" is never set from the index (it does not say
whether a whole act was annulled). Rows sorted by (year, series, number, relation).
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from common import SRC

KEEP = {'0': 'Τροποποίηση', '5': 'Αντικατάσταση', '3': 'Ακύρωση'}
LABEL = re.compile(r'^([ΑΒ])\s+(\d+)/(\d{4})$')
SERIES = {'Α': ('Α΄', 1), 'Β': ('Β΄', 2)}
_cache: dict | None = None


def _row(series: str, num: int, year: int, rel: str) -> dict:
    s, n = SERIES[series]
    return {'ref': f'ΦΕΚ {s} {num}/{year}', 'title': KEEP[rel], 'url': f'https://api.et.gr/apiFEK/{n}/{year}/{num}/pdf'}


def relations() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    sid_issue: dict[str, tuple[int, int]] = {}
    for f in glob.glob(str(SRC / 'index' / '01' / '*.json')):
        d = json.loads(Path(f).read_text(encoding='utf-8'))
        for r in d['rows']:
            sid_issue[r['search_ID']] = (d['year'], int(r['search_DocumentNumber']))
    out: dict[tuple[int, int], dict] = {}
    capped: set = set()
    for f in sorted(glob.glob(str(SRC / 'index' / 'timeline' / '01' / '*' / '*.json'))):
        d = json.loads(Path(f).read_text(encoding='utf-8'))
        me = sid_issue.get(d['search_ID'])
        if not me:
            continue
        if d['direction_param'] == 0 and d.get('capped'):
            capped.add(me)
        for r in d['rows']:
            rel = str(r.get('timeline_RelationshipTypeID'))
            m = LABEL.match((r.get('timeline_PrimaryLabel') or '').strip())
            if rel not in KEEP or not m:
                continue
            series, num, year = m.group(1), int(m.group(2)), int(m.group(3))
            if d['direction_param'] == 0 and str(r.get('timeline_Direction')) == '-1':
                out.setdefault(me, {})[(series, year, num, rel)] = _row(series, num, year, rel)
            elif d['direction_param'] == 1 and str(r.get('timeline_Direction')) == '1' and series == 'Α':
                out.setdefault((year, num), {})[('Α', me[0], me[1], rel)] = _row('Α', me[1], me[0], rel)
    _cache = {'by_issue': {k: [v[x] for x in sorted(v)] for k, v in out.items()}, 'capped': capped}
    return _cache
