"""Debug: write every item's (issue, n, section, heading, issuer, title, first body line) of a year as JSON lines."""
import glob, json, sys, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
import ga_order, split_b
SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
year, out = sys.argv[1], sys.argv[2]
with open(out, 'w', encoding='utf-8') as o:
    for f in sorted(glob.glob(str(SRC / 'text' / '02' / year / '*.json.gz'))):
        iid = Path(f).name[:-8]
        meta = json.loads((SRC / 'meta' / '02' / year / f'{iid}.json').read_text(encoding='utf-8'))
        r = split_b.split_issue(ga_order.reading_order(ga_order.load(Path(f))), meta)
        for it in r['items']:
            o.write(json.dumps({'issue': meta['number'], 'n': it['n'], 'section': it['section'], 'heading': it['heading'],
                                'issuer': ' / '.join(it['issuer_lines']), 'title': it['title'],
                                'body0': ' '.join(l['t'] for l in it['body'][:3]), 'nbody': len(it['body']),
                                'problems': r['problems']}, ensure_ascii=False) + '\n')
