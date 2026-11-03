"""Find the laws that amend a Greek law, in a checkout of legalize-gr (github.com/legalize-dev/legalize-gr).

legalize-gr holds one Markdown file per Government Gazette issue Α΄ since 2000, each as published. This scan lists
every article, in issues from the law's year on, that names a provision of the law (παρ./άρθρο/περ./εδάφιο … του ν.
N/YYYY) outside a «…» quotation and carries an amending verb or heading in its first 600 characters; and, from each
file's `amends` front-matter field (copied from the official search.et.gr relation index), every issue listed as
amending the law's own issue. Its output is a candidate list only: each candidate must be read in its own ΦΕΚ.

legalize-gr's text is extracted from the PDFs and loses or interleaves text in places (see corpus decisions), so the
scan can miss an amendment; the parse also checks against the Data Protection Authority's consolidated text.

    python -X utf8 scripts/greece-law/scan_legalize_gr.py <legalize-gr checkout> 4624/2019 "Α 137/2019"
    (the checkout used: commit 36cb88a374cd2413cf8b128b7561d1b2bd0129cd)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

VERB = re.compile(r'(καταργ|αντικαθίστα|προστίθε|τροποποι|διαγράφ|συμπληρώνε|διαμορφώνε|αναριθμ|Καταργ|Τροποπ|Αντικατ|Προσθήκ)')


def scan(root: Path, law: str, issue: str) -> None:
    num, year = law.split('/')
    cite = re.compile(r'(?:παρ\.|παράγραφ\w+|άρθρ\w+|περ\.|περίπτωσ\w+|εδάφι\w+)\s*[^\s,]{0,6}\s+(?:\S+\s+){0,6}?'
                      rf'του\s+(?:ν\.|νόμου)\s*{num}\s*/\s*{year}')
    files = sorted(root.glob('gr/FEK-A-*.md'), key=lambda p: (int(p.stem.split('-')[3]), int(p.stem.split('-')[2])))
    for f in files:
        y = int(f.stem.split('-')[3])
        if y < int(year):
            continue
        t = f.read_text(encoding='utf-8')
        m = re.search(r'^amends: "([^"]*)"', t[:6000], re.M)
        if m and issue in [a.strip() for a in m.group(1).split(',')]:
            print(f'{f.stem}\tamends-field')
        if num not in t:
            continue
        j = re.sub(r'\s+', ' ', t)
        for art in re.split(r'(?=##### Άρθρο )', j):
            for c in cite.finditer(art):
                pre = art[:c.start()]
                if pre.count('«') - pre.count('»') > 0:
                    continue
                if VERB.search(art[:600]):
                    print(f'{f.stem}\t{art[6:80]}\t…{art[max(0, c.start() - 80):c.end() + 30]}')
                    break


if __name__ == '__main__':
    scan(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
