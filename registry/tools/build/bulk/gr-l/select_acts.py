"""GR-L: classify every harvested decision of an org; write the regulatory ones to <SRC>/diavgeia/selected/<org>.jsonl
and the per-org counts to <WORK>/select-stats/<org>.json. Deterministic (sorted by ADA).

    python -X utf8 -I select_acts.py            (every org whose harvest is complete: meta/<org>/counts.json)
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from classify import VERSION, classify  # noqa: E402
from common_l import ATH, META, SEL, WORK  # noqa: E402


def org_rows(uid: str) -> list[dict]:
    out = []
    for p in sorted((META / uid).glob('*.jsonl.gz')):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            out += [json.loads(l) for l in f if l.strip()]
    return out


def year_of(ms: int | None) -> int:
    return dt.datetime.fromtimestamp(ms / 1000, ATH).year if ms else 0


def select(uid: str) -> dict:
    rows = org_rows(uid)
    sel, stats = [], {'org': uid, 'classifier': VERSION, 'total': len(rows), 'a2': 0, 'by_category': {},
                      'excluded': {}}
    for r in sorted(rows, key=lambda r: r['ada']):
        if r.get('decisionTypeId') == 'Α.2':
            stats['a2'] += 1
        c, why = classify(r.get('subject') or '')
        if c is None:
            stats['excluded'][why] = stats['excluded'].get(why, 0) + 1
            continue
        stats['by_category'][c] = stats['by_category'].get(c, 0) + 1
        sel.append({'ada': r['ada'], 'org': uid, 'year': year_of(r.get('issueDate')), 'category': c,
                    'subject': r.get('subject'), 'issueDate': r.get('issueDate'),
                    'publishTimestamp': r.get('publishTimestamp'), 'protocolNumber': r.get('protocolNumber'),
                    'decisionTypeId': r.get('decisionTypeId'), 'privateData': r.get('privateData'),
                    'unitIds': r.get('unitIds'), 'versionId': r.get('versionId'),
                    'correctedVersionId': r.get('correctedVersionId'), 'extra': r.get('extra')})
    stats['selected'] = len(sel)
    SEL.mkdir(parents=True, exist_ok=True)
    tmp = SEL / f'{uid}.jsonl.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for r in sel:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    os.replace(tmp, SEL / f'{uid}.jsonl')
    d = WORK / 'select-stats'
    d.mkdir(exist_ok=True)
    (d / f'{uid}.json').write_text(json.dumps(stats, ensure_ascii=False, sort_keys=True, indent=1), encoding='utf-8')
    return stats


def main(argv: list[str]) -> None:
    uids = argv or sorted(p.parent.name for p in META.glob('*/counts.json'))
    for uid in uids:
        s = select(uid)
        print(uid, s['total'], s['selected'], s['by_category'])


if __name__ == '__main__':
    main(sys.argv[1:])
