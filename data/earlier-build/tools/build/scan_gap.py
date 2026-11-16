"""Amendment scan of the ΦΕΚ Α΄ issues that legalize-gr lacks, read from the Gazette PDFs themselves.

legalize-gr (commit 36cb88a374cd) holds every ΦΕΚ Α΄ issue of 2000-2025, but of 2026 only nos. 1-57, 128-142, 145,
146, 149-173, 176 and 177. fetch_laws.py `gap` caches the missing ones (58-127, 143, 144, 147, 148, 174, 175). This
scan reads each from its text layer (line-end hyphens joined, whitespace collapsed), splits it at "Άρθρο N" headings
and, for each law given, prints every mention of it: marked AMEND when the article names one of its provisions outside
a «…» quotation and carries an amending verb or heading (the test of scan_legalize_gr.py), else REF. Every AMEND (and
any doubtful REF) must then be read in the issue itself.

    python -X utf8 scripts/greece-law/scan_gap.py 2026 58-127,143,144,147,148,174,175 5178/2025 5188/2025 ...
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fitz  # noqa: E402  (PyMuPDF)

import fetch_laws as FL  # noqa: E402
from scan_legalize_gr import VERB  # noqa: E402


def issue_text(year: int, num: int) -> str | None:
    p = FL._key(FL.fek_url(year, num), None)
    if not p.exists():
        return None
    t = '\n'.join(page.get_text() for page in fitz.open(p))
    t = re.sub(r'(?<=[α-ωά-ώ])[-‐]\s*\n\s*(?=[α-ωά-ώ])', '', t)
    return re.sub(r'\s+', ' ', t)


def nums(spec: str) -> list[int]:
    out = []
    for part in spec.split(','):
        a, _, b = part.partition('-')
        out += list(range(int(a), int(b or a) + 1))
    return out


def main(argv: list[str]) -> None:
    year, issues, laws = int(argv[0]), nums(argv[1]), argv[2:]
    cites = {}
    for law in laws:
        n, y = law.split('/')
        cites[law] = (re.compile(rf'(?<!\d){n}\s*/\s*{y}(?!\d)'),
                      re.compile(r'(?:παρ\.|παράγραφ\w+|άρθρ\w+|περ\.|περίπτωσ\w+|εδάφι\w+)\s*[^\s,]{0,6}\s+'
                                 rf'(?:\S+\s+){{0,6}}?του\s+(?:ν\.|νόμου)\s*{n}\s*/\s*{y}'))
    absent = []
    for num in issues:
        t = issue_text(year, num)
        if t is None:
            absent.append(num)
            continue
        head = re.search(r'ΝΟΜΟΣ ΥΠ’ ΑΡΙΘΜ\. ?(\d+)', t[:4000])
        arts = re.split(r'(?= Άρθρο \d+[Α-Ω]? )', t)
        for law, (any_m, cite) in cites.items():
            for art in arts:
                for m in any_m.finditer(art):
                    pre = art[:m.start()]
                    quoted = pre.count('«') - pre.count('»') > 0
                    amend = (not quoted and cite.search(art) is not None and VERB.search(art[:600]) is not None)
                    print(f'Α΄ {num}/{year} (ν. {head.group(1) if head else "?"})\t{law}\t{"AMEND" if amend else "REF"}'
                          f'\t{art[:70].strip()}\t…{art[max(0, m.start() - 160):m.end() + 60]}')
    print(f'issues read: {len(issues) - len(absent)}; not in the cache: {absent}')


if __name__ == '__main__':
    main(sys.argv[1:])
