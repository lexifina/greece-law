"""GR-L metadata harvest v2 (replaces harvest_meta.py, whose 12-org queries took ~20 s per page server-side; one org
per query takes ~3 s).

    python -X utf8 -I harvest2.py

For every MUNICIPALITY, REGION and ADMINISTRATIVEREGION organisation (priority order: the 7 decentralised
administrations, the 13 regions, the 30 largest municipalities, then every other municipality by uid), all decisions
of types Α.2;2.4.1;2.4.6 issued 2010-10-01 -> today, in 180-day windows (/opendata/search.json, size 500).
One org is collected in memory, deduped by ADA (windows overlap by their end day) and written at once as
<SRC>/diavgeia/meta/<org>/<year>.jsonl.gz (trimmed fields, sorted by ADA, gzip mtime 0) plus <org>/counts.json.
Resumable by org (<WORK>/harvest2-state[-k].json). `--worker k --of n` runs the orgs with index % n == k (several
workers in parallel: the server takes ~9-25 s per query, so throughput needs concurrency, while each worker paces its
own requests at n s, keeping the harvest at <= 0.5 request/s in total; the fetcher takes <= 1/s). Stop file <WORK>/STOP-HARVEST. Log <WORK>/harvest.log.
Rate: <= 0.5 request/s (GR-L fetcher <= 1/s: host total <= 1.5/s). Every request is logged.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, r'C:\Users\alany\Documents\lexifina\scripts\greece-law\bulk\gr-a')
from common import SRC, curl, free_gb, now  # noqa: E402

WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-l')
OUT = SRC / 'diavgeia' / 'meta'
TMP = SRC / 'diavgeia' / 'tmp'
STATE = WORK / 'harvest2-state.json'
TYPES = 'Α.2;2.4.1;2.4.6'
INTERVAL = 2.0  # multiplied by the number of workers: 3 workers -> one request per 6 s each, <= 0.5/s in total
# 30 largest municipalities (2021 census, ELSTAT), by Diavgeia uid.
TOP30 = ['6013', '6114', '6241', '6243', '6325', '6167', '6247', '6058', '6050', '6132', '6125', '6066', '6215',
         '6129', '6318', '6265', '6107', '6146', '6317', '6007', '6104', '6314', '6211', '6026', '6149', '6014',
         '6242', '6130', '6272', '6207']
KEEP = ('ada', 'subject', 'issueDate', 'publishTimestamp', 'organizationId', 'unitIds', 'signerIds', 'decisionTypeId',
        'protocolNumber', 'privateData', 'status', 'versionId', 'correctedVersionId', 'documentChecksum',
        'thematicCategoryIds')
XKEEP = ('kanonistikipraxitype', 'kanonistikipraxiaa', 'fek', 'relatedDecisions', 'documentType')


def log(msg: str) -> None:
    with open(WORK / 'harvest.log', 'a', encoding='utf-8') as f:
        f.write(f'{now()} {msg}\n')


def ordered_orgs() -> list[dict]:
    orgs = json.load(open(SRC / 'diavgeia' / 'organizations.json', encoding='utf-8'))
    if isinstance(orgs, dict):
        orgs = orgs['organizations']
    by = {o['uid']: o for o in orgs}
    out = sorted((o for o in orgs if o.get('category') == 'ADMINISTRATIVEREGION'), key=lambda o: o['uid'])
    out += sorted((o for o in orgs if o.get('category') == 'REGION'), key=lambda o: int(o['uid']))
    out += [by[u] for u in TOP30]
    out += sorted((o for o in orgs if o.get('category') == 'MUNICIPALITY' and o['uid'] not in TOP30),
                  key=lambda o: int(o['uid']))
    return out


def windows():
    start, today = dt.date(2010, 10, 1), dt.date.today()
    while start <= today:
        end = min(start + dt.timedelta(days=179), today + dt.timedelta(days=1))
        yield start, end
        start = end


def trim(r: dict) -> dict:
    x = r.get('extraFieldValues') or {}
    out = {k: r.get(k) for k in KEEP}
    out['extra'] = {k: x.get(k) for k in XKEEP if x.get(k) not in (None, {}, [])}
    out['attachments'] = len(r.get('attachments') or [])
    return out


def harvest_org(uid: str, interval: float) -> dict | None:
    rows: dict[str, dict] = {}
    fails = 0
    for a, b in windows():
        page = 0
        while True:
            if (WORK / 'STOP-HARVEST').exists():
                return None
            while free_gb() < 50.5:
                log('disk below 50.5 GB, waiting')
                time.sleep(300)
            q = urllib.parse.urlencode({'org': uid, 'type': TYPES, 'from_issue_date': a.isoformat(),
                                        'to_issue_date': b.isoformat(), 'size': 500, 'page': page,
                                        'status': 'published'})
            tmp = TMP / f'{os.getpid()}-{uid}.json'
            st = curl(f'https://diavgeia.gov.gr/opendata/search.json?{q}', tmp, interval, timeout=180)
            if st != '200':
                fails += 1
                log(f'HTTP {st} org {uid} window {a} page {page} (fail {fails})')
                if st in ('403', '429') or fails >= 8:
                    log('FAILED: blocked or too many errors; stopping (no evasion)')
                    sys.exit(1)
                time.sleep(30 * 2 ** min(fails, 4))
                continue
            fails = 0
            d = json.load(open(tmp, encoding='utf-8'))
            tmp.unlink()
            for r in d.get('decisions', []):
                rows[r['ada']] = trim(r)
            total = d.get('info', {}).get('total', 0)
            if (page + 1) * 500 >= total or not d.get('decisions'):
                break
            page += 1
    return rows


def write_org(uid: str, rows: dict) -> dict:
    d = OUT / uid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    by: dict[int, list] = {}
    for r in rows.values():
        y = dt.datetime.fromtimestamp(r['issueDate'] / 1000, dt.timezone(dt.timedelta(hours=3))).year \
            if r.get('issueDate') else 0
        by.setdefault(y, []).append(r)
    counts = {'org': uid, 'total': len(rows), 'by_year': {}, 'by_type': {}, 'harvested': now()}
    for y, rs in sorted(by.items()):
        rs.sort(key=lambda r: r['ada'])
        counts['by_year'][str(y)] = len(rs)
        p = d / f'{y}.jsonl.gz'
        with open(p.with_suffix('.tmp'), 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as f:
                for r in rs:
                    f.write((json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))
        os.replace(p.with_suffix('.tmp'), p)
    for r in rows.values():
        counts['by_type'][r['decisionTypeId']] = counts['by_type'].get(r['decisionTypeId'], 0) + 1
    (d / 'counts.json').write_text(json.dumps(counts, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    return counts


def main(argv: list[str]) -> None:
    k = int(argv[argv.index('--worker') + 1]) if '--worker' in argv else 0
    n = int(argv[argv.index('--of') + 1]) if '--of' in argv else 1
    TMP.mkdir(parents=True, exist_ok=True)
    orgs = ordered_orgs()
    done = set()
    for f in WORK.glob('harvest2-state*.json'):
        done |= set(json.load(open(f, encoding='utf-8'))['done'])
    mine = WORK / f'harvest2-state-{k}.json'
    state = json.load(open(mine, encoding='utf-8')) if mine.exists() else {'done': []}
    log(f'harvest2 start pid {os.getpid()} worker {k}/{n}: {len(orgs)} orgs, {len(done)} done')
    for i, o in enumerate(orgs):
        if o['uid'] in done or i % n != k:
            continue
        t0 = time.time()
        rows = harvest_org(o['uid'], INTERVAL * n)
        if rows is None:
            log('stop file')
            return
        c = write_org(o['uid'], rows)
        done.add(o['uid'])
        state['done'] = sorted(set(state['done']) | {o['uid']})
        t = mine.with_suffix('.tmp')
        t.write_text(json.dumps(state), encoding='utf-8')
        os.replace(t, mine)
        log(f'org {i + 1}/{len(orgs)} {o["uid"]} {o["label"]}: {c["total"]} decisions ({time.time() - t0:.0f} s)')
    log(f'harvest2 worker {k}/{n} done')


if __name__ == '__main__':
    main(sys.argv[1:])
