"""Debug: split the issues of a year and print each item's head fields."""
import glob, json, sys, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
import ga_order, split_b
SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
year = sys.argv[1]
pat = sys.argv[2] if len(sys.argv) > 2 else '*'
for f in sorted(glob.glob(str(SRC / 'text' / '02' / year / f'{pat}.json.gz'))):
    iid = Path(f).name[:-8]
    meta = json.loads((SRC / 'meta' / '02' / year / f'{iid}.json').read_text(encoding='utf-8'))
    r = split_b.split_issue(ga_order.reading_order(ga_order.load(Path(f))), meta)
    print(f'== {iid} items={len(r["items"])} contents={len(r["contents"] or [])} {r["problems"]}')
    for it in r['items']:
        print(f'  ({it["n"]}) [{it["section"][:10]}] {it["heading"][:40]!r} | {it["title"][:70]!r} | '
              f'{" / ".join(it["issuer_lines"])[:60]!r} | pre={len(it["preamble"])} body={len(it["body"])} '
              f'ann={len(it["annexes"])} {it["place"]} {it["signed"]}')
