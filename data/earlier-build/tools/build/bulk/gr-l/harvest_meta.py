"""GR-L task 1: harvest Diavgeia metadata of local bodies' regulatory-type decisions (Α.2 and the older 2.4.1, 2.4.6)
for every MUNICIPALITY, REGION and ADMINISTRATIVEREGION organisation, 2010-10-01 -> today.

    python -X utf8 -I harvest_meta.py

Queries: /opendata/search.json?org=<id;id;...>&type=Α.2;2.4.1;2.4.6&from_issue_date&to_issue_date&size=500&page=N
(180-day windows, overlapping by one day since the end date is cut at 00:00; deduped by ADA), <= 1 req / 0.8 s.
Output: <SRC>/diavgeia/meta/<org>/<year>.jsonl (one decision per line, sorted by ADA when a window set is complete).
Resumable: <WORK>/harvest-state.json lists finished (group, window) keys. Stop file <WORK>/STOP-HARVEST.
Log <WORK>/harvest.log. Every request logged to <SRC>/requests-diavgeia.gov.gr.jsonl.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, r'C:\Users\alany\Documents\lexifina\scripts\greece-law\bulk\gr-a')
from common import SRC, curl, free_gb, now  # noqa: E402

WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-l')
OUT = SRC / 'diavgeia' / 'meta'
TMP = SRC / 'diavgeia' / 'tmp'
STATE = WORK / 'harvest-state.json'
CATS = ('MUNICIPALITY', 'REGION', 'ADMINISTRATIVEREGION')
TYPES = 'Α.2;2.4.1;2.4.6'
GROUP = 12
INTERVAL = 0.8


def log(msg: str) -> None:
    with open(WORK / 'harvest.log', 'a', encoding='utf-8') as f:
        f.write(f'{now()} {msg}\n')


def windows():
    start, today = dt.date(2010, 10, 1), dt.date.today()
    while start <= today:
        end = min(start + dt.timedelta(days=179), today + dt.timedelta(days=1))
        yield start, end
        start = end - dt.timedelta(days=1) + dt.timedelta(days=1)  # end is exclusive (cut at 00:00)


def main() -> None:
    orgs = json.load(open(SRC / 'diavgeia' / 'organizations.json', encoding='utf-8'))
    if isinstance(orgs, dict):
        orgs = orgs['organizations']
    orgs = sorted((o for o in orgs if o.get('category') in CATS), key=lambda o: (CATS.index(o['category']), o['uid']))
    groups = [orgs[i:i + GROUP] for i in range(0, len(orgs), GROUP)]
    state = json.load(open(STATE, encoding='utf-8')) if STATE.exists() else {'done': []}
    done = set(state['done'])
    log(f'start pid {os.getpid()}: {len(orgs)} orgs in {len(groups)} groups')
    fails = 0
    for gi, g in enumerate(groups):
        ids = ';'.join(o['uid'] for o in g)
        for a, b in windows():
            key = f'{gi}:{a}'
            if key in done:
                continue
            if (WORK / 'STOP-HARVEST').exists():
                log('stop file')
                return
            while free_gb() < 50.5:
                log('disk below 50.5 GB, waiting')
                time.sleep(300)
            rows, page = [], 0
            while True:
                q = urllib.parse.urlencode({'org': ids, 'type': TYPES, 'from_issue_date': a.isoformat(),
                                            'to_issue_date': b.isoformat(), 'size': 500, 'page': page,
                                            'status': 'published'})
                tmp = TMP / f'{os.getpid()}.json'
                st = curl(f'https://diavgeia.gov.gr/opendata/search.json?{q}', tmp, INTERVAL, timeout=120)
                if st != '200':
                    fails += 1
                    log(f'HTTP {st} group {gi} window {a} page {page} (fail {fails})')
                    if st in ('403', '429') or fails >= 8:
                        log('FAILED: blocked or too many errors; stopping (no evasion)')
                        sys.exit(1)
                    time.sleep(30 * fails)
                    continue
                fails = 0
                d = json.load(open(tmp, encoding='utf-8'))
                tmp.unlink()
                rows += d.get('decisions', [])
                info = d.get('info', {})
                if (page + 1) * 500 >= info.get('total', 0) or not d.get('decisions'):
                    break
                page += 1
            by: dict = {}
            for r in rows:
                y = dt.datetime.fromtimestamp(r['issueDate'] / 1000, dt.timezone.utc).year if r.get('issueDate') else 0
                by.setdefault((r['organizationId'], y), []).append(r)
            for (org, y), rs in by.items():
                p = OUT / org / f'{y}.jsonl'
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, 'a', encoding='utf-8') as f:
                    for r in rs:
                        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
            done.add(key)
            state['done'] = sorted(done)
            t = STATE.with_suffix('.tmp')
            t.write_text(json.dumps(state), encoding='utf-8')
            os.replace(t, STATE)
        log(f'group {gi + 1}/{len(groups)} done')
    log('done: all groups (dedupe by ADA when reading: windows overlap)')


if __name__ == '__main__':
    main()
