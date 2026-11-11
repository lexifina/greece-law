"""GR-A: build staged parts for every Α΄ year whose issues are all fetched + extracted (or recorded as scanned).

    python -X utf8 -I build_years.py <from> <to>

A year is ready when each distinct issue number in index/01/<year>.json has a meta file. Each ready year is built
twice (stage/ and stage2/) and the bytes compared (gate 1). Summary appended to <WORK>/build-summary.tsv:
year, issues, acts, held, sha256, deterministic.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_part as B  # noqa: E402
from common import SRC, WORK, now  # noqa: E402


def ready(year: int) -> bool:
    rows = json.loads((SRC / 'index' / '01' / f'{year}.json').read_text(encoding='utf-8'))['rows']
    nums = {int(r['search_DocumentNumber']) for r in rows}
    return all((SRC / 'meta' / '01' / str(year) / f'{year}01{n:05d}.json').exists() for n in nums)


def main(argv: list[str]) -> None:
    y0, y1 = int(argv[0]), int(argv[1])
    for year in range(y0, y1 - 1, -1):
        if not ready(year):
            print(f'{year}: not ready')
            continue
        part, rep = B.build(year)
        a = B.dump(part)
        B.write(B.STAGE / f'b-a-{year}.json', a)
        B.write(WORK / 'held' / f'b-a-{year}.json', B.dump(rep))
        part2, _ = B.build(year)
        b = B.dump(part2)
        same = a == b
        sha = hashlib.sha256(a).hexdigest()
        line = f'{now()}\t{year}\t{rep["issues"]}\t{rep["acts"]}\t{len(rep["held"])}\t{sha}\t{"identical" if same else "DIFFERENT"}'
        with open(WORK / 'build-summary.tsv', 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        print(line, flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
