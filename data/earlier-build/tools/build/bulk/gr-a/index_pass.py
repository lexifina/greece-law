"""GR-A task 1: the ΦΕΚ issue index from search.et.gr's backend (one POST per year and series, <= 1 req/s).

    python -X utf8 index_pass.py            # series 01 (Α), 04 (Δ), 02 (Β), years 1833..2026; resumable

Writes <SRC>/index/<series>/<year>.json: {series, year, fetched, count, max_number, rows:[...]} (rows sorted by
issue number; the API returns the whole year: checked by count == number of distinct issue numbers), then
<SRC>/index/DONE-A. Holds <SRC>/index/HOST-searchetv99.lock (its PID) while running. Stop file: <WORK>/STOP-INDEX.
"""
from __future__ import annotations

import json
import os
import sys
import time

from common import SEARCH, SRC, WORK, curl, now, write_json_atomic

LOCK = SRC / 'index' / 'HOST-searchetv99.lock'
HDR = {'Origin': 'https://search.et.gr', 'Referer': 'https://search.et.gr/'}
ISSUE_PARAM = {'01': '1', '02': '2', '04': '4'}


def body(year: int, series: str) -> str:
    return json.dumps({"selectYear": [str(year)], "selectIssue": [ISSUE_PARAM[series]], "documentNumber": "",
                       "searchText": "", "datePublished": "", "dateReleased": "", "tags": [], "categoryIds": []},
                      ensure_ascii=False, separators=(',', ':'))


def one(series: str, year: int) -> dict:
    out = SRC / 'index' / series / f'{year}.json'
    raw = SRC / 'index' / '.raw' / f'{series}-{year}.json'
    for attempt in range(5):
        st = curl(f'{SEARCH}/simplesearch', raw, 1.05, data=body(year, series), headers=HDR, timeout=300)
        if st == '200':
            break
        if st in ('403', '429') or st.startswith('5') or st == '000':
            time.sleep([5, 20, 60, 180, 600][attempt])
            continue
        raise SystemExit(f'{series}/{year}: HTTP {st}')
    else:
        raise SystemExit(f'{series}/{year}: gave up after retries (last {st}); host stopped')
    d = json.loads(raw.read_text(encoding='utf-8'))
    if d.get('status') != 'ok':
        raise SystemExit(f'{series}/{year}: status {d.get("status")} {d.get("message")}')
    rows = json.loads(d['data']) if d.get('data') else []
    rows.sort(key=lambda r: (int(r['search_DocumentNumber']), r['search_ID']))
    nums = [int(r['search_DocumentNumber']) for r in rows]
    rec = {'series': series, 'year': year, 'fetched': now(), 'count': len(rows), 'distinct': len(set(nums)),
           'max_number': max(nums) if nums else 0, 'rows': rows}
    write_json_atomic(out, rec)
    raw.unlink()
    return rec


def main() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(f'{os.getpid()} GR-A index_pass {now()}\n')
    try:
        for series in ('01', '04', '02'):
            for year in range(2026, 1832, -1):
                if (WORK / 'STOP-INDEX').exists():
                    print('stop file'); return
                if (SRC / 'index' / series / f'{year}.json').exists():
                    continue
                rec = one(series, year)
                print(f'{now()} {series}/{year}: {rec["count"]} rows, max {rec["max_number"]}', flush=True)
        (SRC / 'index' / 'DONE-A').write_text(f'GR-A index pass done {now()}\n')
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
