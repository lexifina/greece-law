"""Debug: classify every item of a year; print kind/privacy stats and samples."""
import glob, json, sys, warnings, collections, random
warnings.filterwarnings('ignore')
from pathlib import Path
import ga_order, split_b, classify_b as C
SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
year, out = sys.argv[1], sys.argv[2]
kinds = collections.Counter(); priv = collections.Counter(); rows = []
for f in sorted(glob.glob(str(SRC / 'text' / '02' / year / '*.json.gz'))):
    iid = Path(f).name[:-8]
    meta = json.loads((SRC / 'meta' / '02' / year / f'{iid}.json').read_text(encoding='utf-8'))
    r = split_b.split_issue(ga_order.reading_order(ga_order.load(Path(f))), meta)
    for it in r['items']:
        k = C.kind(it)
        body = '\n'.join(l['t'] for l in it['body']) + '\n'.join(l['t'] for a in it['annexes'] for l in a)
        p = C.privacy(it, k, body)
        kinds[k] += 1
        priv[(p or 'kept').split(' (')[0]] += 1
        rows.append({'issue': meta['number'], 'n': it['n'], 'kind': k, 'issuer': C.issuer_slug(it, k),
                     'proto': C.protocol(it), 'title': it['title'][:160], 'priv': p,
                     'names': C.person_names(it['title']) + C.person_names(body)})
print(kinds); print(priv)
with open(out, 'w', encoding='utf-8') as o:
    for r in rows: o.write(json.dumps(r, ensure_ascii=False) + '\n')
