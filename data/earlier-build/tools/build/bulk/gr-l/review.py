"""GR-L hand-check helper: for rows (jsonl with ada, org, year, category, subject) print the parse result and the
start of the operative text, for checking against the PDF.

    python -X utf8 -I review.py <rows.jsonl> [--full] > review.txt
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common_l import TEXT, ada_ascii  # noqa: E402
from parse_acts import parse  # noqa: E402


def main(argv: list[str]) -> None:
    full = '--full' in argv
    rows = [json.loads(l) for a in argv if not a.startswith('--') for l in open(a, encoding='utf-8') if l.strip()]
    for n, r in enumerate(rows, 1):
        p = TEXT / r['org'] / str(r['year']) / f'{ada_ascii(r["ada"])}.json.gz'
        print(f'#{n} [{r.get("category")}] {r["ada"]} org {r["org"]}')
        print('   SUBJECT:', ' '.join((r.get('subject') or '').split())[:300])
        if not p.exists():
            print('   (no text file)')
            continue
        d = json.load(gzip.open(p, 'rt', encoding='utf-8'))
        res = parse(d)
        print('   source:', d.get('text_source'), '| pages', d.get('pages'), '| HOLD:', res.get('hold'))
        u = res.get('units') or {}
        print('   units:', ' '.join(f'{k}({sum(len(x) for x in v)})' for k, v in u.items())[:300])
        op = [k for k in u if k != 'prooimio']
        if u.get('prooimio'):
            print('   prooimio end:', ' / '.join(u['prooimio'][-2:])[-300:])
        for k in (op if full else op[:2]):
            print(f'   {k}:', ' / '.join(u[k])[:500 if not full else 100000])
        print()


if __name__ == '__main__':
    main(sys.argv[1:])
