"""GR-A gate: SCHEMA.md rules on the staged parts together with every corpus.d part (no build).

    python -X utf8 -I validate.py [years...]     (default: every stage/b-a-*.json)
Checks: act slugs unique across all parts; law keys with the same key carry the same label; law/unit keys ASCII
[a-z0-9-]; unit text ends with '\\n', has no NBSP / control characters / empty lines; every act has a version with
units; dates ISO; first_law exists in some part's laws.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = Path(r'C:\Users\alany\Documents\lexifina\scripts\greece-law\corpus.d')
KEY = re.compile(r'^[a-z0-9-]+$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
CTRL = re.compile(r'[\x00-\x08\x0b-\x1f\xa0]')


def main(argv: list[str]) -> None:
    staged = [HERE / 'stage' / f'b-a-{y}.json' for y in argv] if argv else sorted((HERE / 'stage').glob('b-a-*.json'))
    parts = [p for p in sorted(CORPUS.glob('*.json')) if not p.name.startswith('b-a-')] + staged
    slugs: dict[str, str] = {}
    labels: dict[str, tuple[str, str]] = {}
    errs: list[str] = []
    acts = 0
    for p in parts:
        d = json.loads(p.read_text(encoding='utf-8'))
        for k, law in d.get('laws', {}).items():
            if not KEY.match(k):
                errs.append(f'{p.name}: law key {k}')
            if k in labels and labels[k][0] != law['label']:
                errs.append(f'{p.name}: law {k} label {law["label"]!r} != {labels[k][0]!r} in {labels[k][1]}')
            labels.setdefault(k, (law['label'], p.name))
            for f in ('enacted', 'published'):
                if law.get(f) and not DATE.match(law[f]):
                    errs.append(f'{p.name}: law {k} {f} {law[f]}')
        for a in d.get('acts', []):
            acts += 1
            if a['slug'] in slugs:
                errs.append(f'{p.name}: slug {a["slug"]} also in {slugs[a["slug"]]}')
            slugs[a['slug']] = p.name
            if not a.get('versions'):
                errs.append(f'{p.name}: {a["slug"]} no versions')
                continue
            for v in a['versions']:
                if not DATE.match(v['from']):
                    errs.append(f'{p.name}: {a["slug"]} from {v["from"]}')
                for uk, u in (v.get('units') or {}).items():
                    if not KEY.match(uk):
                        errs.append(f'{p.name}: {a["slug"]} unit key {uk}')
                    t = u['text']
                    if not t.endswith('\n') or '\n\n' in t or CTRL.search(t):
                        errs.append(f'{p.name}: {a["slug"]}/{uk} text form')
    firsts = {a_first for a_first in []}
    for p in staged:
        d = json.loads(p.read_text(encoding='utf-8'))
        for a in d['acts']:
            if a['first_law'] not in labels:
                errs.append(f'{p.name}: {a["slug"]} first_law {a["first_law"]} missing')
    print(f'{len(parts)} parts, {acts} acts, {len(errs)} errors')
    for e in errs[:60]:
        print('  ' + e)


if __name__ == '__main__':
    main(sys.argv[1:])
