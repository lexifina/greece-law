"""Debug: show one item's parts: python show_item.py <year> <issue no> <item n> [all]"""
import json, sys, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
import ga_order, split_b
SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
y, no, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
iid = f'{y}02{no:05d}'
meta = json.loads((SRC / 'meta' / '02' / y / f'{iid}.json').read_text(encoding='utf-8'))
r = split_b.split_issue(ga_order.reading_order(ga_order.load(SRC / 'text' / '02' / y / f'{iid}.json.gz')), meta)
it = r['items'][n - 1]
full = len(sys.argv) > 4
for k in ('section', 'heading', 'protocol_raw', 'title', 'issuer_lines', 'signed', 'place', 'pages'):
    print(k, '=', it[k])
def show(name, ls):
    print(f'--- {name} ({len(ls)})')
    sel = ls if full or len(ls) <= 12 else ls[:6] + [{'t': '...', 'indent': 0}] + ls[-6:]
    for l in sel:
        print(f"  {l.get('indent', 0):6.1f} {l['t']}")
show('preamble', it['preamble']); show('body', it['body'])
for a in it['annexes']: show('annex', a)
