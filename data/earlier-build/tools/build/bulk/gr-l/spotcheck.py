"""GR-L spot-check of a staged part: 20 random acts (seeded by the part name), each compared with its stored document
text (every unit paragraph must occur in the document's text lines, as read and cleaned by parse_acts.lines_of) and printed for reading.

    python -X utf8 -I spotcheck.py <stage/b-l-...json> [--n 20] [--out file]

Writes <WORK>/handcheck/<part>.txt (the printout) and prints a one-line verdict: automatic text check ok/failed.
The reader then checks each printed act against its official page (url) and records the result in PROGRESS.md.
"""
from __future__ import annotations

import gzip
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common_l import TEXT, WORK  # noqa: E402
from parse_acts import lines_of  # noqa: E402


def squash(s: str) -> str:
    return re.sub(r'[\s\-‐-―]+', '', s)


def main(argv: list[str]) -> None:
    part = Path(argv[0])
    n = int(argv[argv.index('--n') + 1]) if '--n' in argv else 20
    d = json.loads(part.read_text(encoding='utf-8'))
    acts = d['acts']
    rnd = random.Random(part.name)
    pick = rnd.sample(acts, min(n, len(acts)))
    out, bad = [], 0
    for a in pick:
        folder = a['folder'].split('/')
        org_files = list(TEXT.glob(f'*/{folder[2]}/{folder[3]}.json.gz'))
        doc = json.load(gzip.open(org_files[0], 'rt', encoding='utf-8')) if org_files else None
        page = squash(' '.join(l['t'] for l in lines_of(doc))) if doc else ''
        v = a['versions'][0]
        misses = []
        for k, u in v['units'].items():
            for para in u['text'].splitlines():
                frag = squash(para)[:60]
                if frag and page.find(frag) < 0:
                    misses.append(f'{k}: {para[:70]}')
        bad += bool(misses)
        out.append(f'== {a["slug"]}  ({a["category"]})  from {v["from"]}  {a["url"]}')
        out.append(f'   title: {a["title"][:200]}')
        out.append(f'   label: {a.get("label")}  amended_by: {[x["ref"] for x in a.get("amended_by", [])]}')
        out.append('   units: ' + ' '.join(f'{k}({len(u["text"])})' for k, u in v['units'].items())[:300])
        for k, u in list(v['units'].items())[:4]:
            out.append(f'   {k}: ' + u['text'][:400].replace('\n', ' / '))
        out.append('   text check: ' + ('ok' if not misses else 'MISSING ' + '; '.join(misses[:3])))
        out.append('')
    dest = WORK / 'handcheck' / (part.stem + '.txt')
    dest.parent.mkdir(exist_ok=True)
    dest.write_text('\n'.join(out), encoding='utf-8')
    print(f'{part.name}: {len(pick)} acts checked, {bad} with text not found in the document; printout {dest}')


if __name__ == '__main__':
    main(sys.argv[1:])
