"""GR-A task 4: the et.gr relation index (search.et.gr backend /timeline/<search_ID>/<d>) for every ΦΕΚ Α΄ issue
from 1975 on (<= 1 req/s), newest year first. Hidden, detached, resumable.

    python -X utf8 -I labels_job.py [--from 2026] [--to 1975]

/timeline/<id>/0 lists the documents that act on this issue (Direction -1: «Τροποποίηση» 0, «Αντικατάσταση» 5,
«Ακύρωση» 3, ...), newest first, CAPPED AT 100 rows (mostly Β΄ decisions); /timeline/<id>/1 lists what this issue
acts on (Direction 1). /0 is fetched for every issue; /1 too when /0 hit the cap, so that Α΄ amenders hidden by the
cap are still found by inverting other issues' /1 lists (label.py does the inversion).
Writes <SRC>/index/timeline/01/<year>/<search_ID>-<d>.json (the parsed rows). Holds
<SRC>/index/HOST-searchetv99.lock (its PID) while running; refuses to start if another lock exists. Stop file
<WORK>/STOP-LABELS. Log <WORK>/labels.log.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import SEARCH, SRC, WORK, http_get, now, write_json_atomic  # noqa: E402

LOCK = SRC / 'index' / 'HOST-searchetv99.lock'
HDR = {'Origin': 'https://search.et.gr', 'Referer': 'https://search.et.gr/'}
STOP = WORK / 'STOP-LABELS'
CAP = 100


def log(msg: str) -> None:
    with open(WORK / 'labels.log', 'a', encoding='utf-8') as f:
        f.write(f'{now()} [{os.getpid()}] {msg}\n')


def get(sid: str, d: int, year: int) -> list | None:
    out = SRC / 'index' / 'timeline' / '01' / str(year) / f'{sid}-{d}.json'
    if out.exists():
        return json.loads(out.read_text(encoding='utf-8'))['rows']
    raw = SRC / 'index' / '.raw' / f'tl-{sid}-{d}.json'
    for attempt in range(5):
        st = http_get(f'{SEARCH}/timeline/{sid}/{d}', raw, 1.05, headers=HDR)
        if st == '200':
            break
        log(f'{sid}/{d}: HTTP {st}, backoff {attempt}')
        if st in ('403', '429') or st.startswith('5') or st == '000':
            time.sleep([10, 60, 300, 900, 1800][attempt])
            continue
        return None
    else:
        raise SystemExit(f'{sid}/{d}: host keeps failing; stopped')
    d0 = json.loads(raw.read_text(encoding='utf-8'))
    data = d0.get('data') or []
    rows = json.loads(data) if isinstance(data, str) else data
    write_json_atomic(out, {'search_ID': sid, 'direction_param': d, 'fetched': now(), 'count': len(rows),
                            'capped': len(rows) >= CAP, 'rows': rows})
    raw.unlink(missing_ok=True)
    return rows


def main(argv: list[str]) -> None:
    y_from = int(argv[argv.index('--from') + 1]) if '--from' in argv else 2026
    y_to = int(argv[argv.index('--to') + 1]) if '--to' in argv else 1975
    if LOCK.exists() and str(os.getpid()) not in LOCK.read_text():
        other = LOCK.read_text().strip()
        if 'GR-A' not in other:
            raise SystemExit(f'host lock held by someone else: {other}')
    LOCK.write_text(f'{os.getpid()} GR-A labels_job {now()}\n')
    log(f'start {y_from}->{y_to}')
    try:
        for year in range(y_from, y_to - 1, -1):
            rows = json.loads((SRC / 'index' / '01' / f'{year}.json').read_text(encoding='utf-8'))['rows']
            n = capped = 0
            for r in rows:
                if STOP.exists():
                    log('stop file')
                    return
                got = get(r['search_ID'], 0, year)
                n += 1
                if got is not None and len(got) >= CAP:
                    capped += 1
                    get(r['search_ID'], 1, year)
            log(f'{year}: {n} issues, {capped} capped at {CAP}')
        (WORK / 'LABELS-DONE').write_text(now() + '\n')
        log('DONE')
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == '__main__':
    main(sys.argv[1:])
