"""GR-OCR benchmark: run recipe variants over sample pages, write text + timing.

    python -X utf8 -I bench.py <outdir> <cfgs comma list|all> <pdf>:<page> [...]
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitz  # noqa: E402
import ocr  # noqa: E402

CFGS = {
    'A': dict(model='ell', columns=False, up=1.0),
    'B': dict(model='ell', psm=4, up=1.0),
    'C': dict(model='grc', psm=4, up=1.0),
    'D': dict(model='ell+grc', psm=4, up=1.0),
    'E': dict(model='grc', psm=6, up=1.0),
    'F': dict(model='grc', psm=4, up=1.5),
    'G': dict(model='ell', psm=4, up=1.5),
    'H': dict(model='grc+ell', psm=4, up=1.0),
    'I': dict(model='ell', psm=6, up=1.0),
    'J': dict(model='grc', psm=4, up=1.0, variant='fast'),
    'K': dict(model='ell', psm=4, up=1.0, variant='fast'),
    'L': dict(model='grc', psm=4, up=2.0),
    'M': dict(model='ell', psm=4, thick=2),
    'N': dict(model='ell', psm=4, thick=3),
    'O': dict(model='ell', psm=4, up=1.5, thick=2),
    'P': dict(model='ell', psm=6, thick=2),
    'Q': dict(model='ell', psm=4, thick=2, variant='fast'),
    'R': dict(model='grc', psm=4, thick=2),
    'S': dict(model='grc', psm=4, thick=3),
    'T': dict(model='ell', psm=4, up=1.5, thick=3),
    'U': dict(model='grc+ell', psm=4, thick=2),
    'V': dict(model='ell', psm=6, thick=3),
    'W': dict(model='ell+eng', psm=4),
    'X': dict(model='ell+eng', psm=6, thick=2),
}


def one(job):
    out, cfg, pdf, pno = job
    t = time.time()
    doc = fitz.open(pdf)
    lines, info = ocr.ocr_page(doc, pno, fold='no', **CFGS[cfg])
    dt = time.time() - t
    name = f'{Path(pdf).stem}-p{pno}__{cfg}'
    (out / f'{name}.txt').write_text('\n'.join(f"{L['t']}" for L in lines), encoding='utf-8')
    return name, round(dt, 1), info['mean_conf'], info['polytonic_share'], info['boxes']


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    cfgs = list(CFGS) if sys.argv[2] == 'all' else sys.argv[2].split(',')
    jobs = []
    for spec in sys.argv[3:]:
        pdf, pno = spec.rsplit(':', 1)
        for c in cfgs:
            jobs.append((out, c, pdf, int(pno)))
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    with open(out / 'bench.jsonl', 'a', encoding='utf-8') as f:
        for r in res:
            print(*r)
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
