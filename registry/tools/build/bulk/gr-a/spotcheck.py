"""GR-A gate: spot-check acts of a staged part against the official PDF's own text (re-fetched; the API re-serves
every issue). For each sampled act: the act's words (all units, in order) are matched in order against the plain
text of its issue (PyMuPDF get_text, legacy font mapped back, look-alikes normalised, line-end hyphens joined).
Reports precision (act words found in order) and recall (issue words between the act's first and last matched word
that the act carries), and every unmatched run longer than 5 words on either side, for reading by hand.

    python -X utf8 -I spotcheck.py <year> [--n 20] [--seed 1] [--slugs a,b,...]
Output: <WORK>/spot/b-a-<year>.txt
"""
from __future__ import annotations

import difflib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract  # noqa: E402
import order  # noqa: E402  (puts scripts/greece-law on sys.path)
import parse_n4624 as N  # noqa: E402
from common import WORK, http_get, pdf_url  # noqa: E402

import fitz  # noqa: E402

CACHE = Path(r'C:\Users\alany\AppData\Local\Temp\gr-a-spot')
TOK = re.compile(r'[0-9A-Za-zΑ-Ωα-ωΆ-Ώά-ώϊϋΐΰ]+')


def words(text: str) -> list[str]:
    text = re.sub(r'([Α-Ωα-ωά-ώϊϋΐΰ])-\n([α-ωά-ώϊϋΐΰ])', r'\1\2', text)
    return [w.lower() for w in TOK.findall(text)]


def pdf_words(path: Path) -> list[str]:
    out = []
    for page in fitz.open(path):
        t = page.get_text()
        if extract.is_legacy(t):
            t = extract.legacy(t)
        out.append('\n'.join(N.norm_line(l) for l in t.split('\n')))
    return words('\n'.join(out))


def main(argv: list[str]) -> None:
    year = int(argv[0])
    n = int(argv[argv.index('--n') + 1]) if '--n' in argv else 20
    seed = int(argv[argv.index('--seed') + 1]) if '--seed' in argv else 1
    part = json.loads((HERE / 'stage' / f'b-a-{year}.json').read_text(encoding='utf-8'))
    acts = part['acts']
    if '--slugs' in argv:
        want = argv[argv.index('--slugs') + 1].split(',')
        sample = [a for a in acts if a['slug'] in want]
    else:
        sample = random.Random(seed).sample(acts, min(n, len(acts)))
    lines = []
    for a in sample:
        num = int(re.search(r'Α΄ (\d+)/', a['issue']).group(1))
        pdf = CACHE / f'{year}01{num:05d}.pdf'
        if not pdf.exists():
            st = http_get(pdf_url('01', year, num), pdf, 2.0)  # blob shared with the downloader + GR-OCR
            if st != '200':
                lines.append(f'{a["slug"]}: fetch failed {st}')
                continue
        src = pdf_words(pdf)
        v = a['versions'][0]
        act = words('\n'.join(u['text'] for u in v['units'].values()))
        act = [w for w in act if w not in words('[Η πηγή δεν δίνει αναγνώσιμο κείμενο για αυτή τη γραμμή.]')]
        sm = difflib.SequenceMatcher(None, act, src, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size]
        matched = sum(b.size for b in blocks)
        lo = blocks[0].b if blocks else 0
        hi = blocks[-1].b + blocks[-1].size if blocks else 0
        prec = matched / max(1, len(act))
        rec = matched / max(1, hi - lo)
        lines.append(f'== {a["slug"]} ({a["issue"]}) act words {len(act)}, precision {prec:.4f}, recall {rec:.4f}, '
                     f'from {v["from"]}, units {len(v["units"])}')
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal' or (j1 < lo or j2 > hi) and tag == 'insert':
                continue
            if (i2 - i1) > 5 or (j2 - j1) > 5:
                lines.append(f'   {tag}: act[{i1}:{i2}] {" ".join(act[i1:i2])[:300]!r}')
                lines.append(f'          pdf[{j1}:{j2}] {" ".join(src[j1:j2])[:300]!r}')
    out = WORK / 'spot' / f'b-a-{year}.txt'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(l for l in lines if l.startswith('==')))


if __name__ == '__main__':
    main(sys.argv[1:])
