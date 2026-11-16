"""GR-B: write gr-b/OCR-REQUESTS.tsv (GR-A's columns: id, url, pages, reason, slugs) from the held files of built
years: items held for pages without a text layer (those pages, 1-based ranges) or for an unmapped font (the whole
issue). Deterministic; rewritten whole each run.   python -X utf8 -I ocr_requests.py"""
import glob, json, os
from pathlib import Path
SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-b')


def ranges(ps):
    ps, out = sorted(set(ps)), []
    for p in ps:
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return ','.join(f'{a}-{b}' if a != b else str(a) for a, b in out)


rows = {}
for f in sorted(glob.glob(str(WORK / 'held' / 'b-b-*.json'))):
    rep = json.loads(Path(f).read_text(encoding='utf-8'))
    y = rep['year']
    for h in rep['held']:
        if 'text layer' not in h['why'] and 'control characters' not in h['why']:
            continue
        no = int(h['issue'].split()[1].split('/')[0])
        iid = f'{y}02{no:05d}'
        meta = json.loads((SRC / 'meta' / '02' / str(y) / f'{iid}.json').read_text(encoding='utf-8'))
        if 'control characters' in h['why']:
            pages, reason = list(range(1, int(meta['pages']) + 1)), 'unmapped font'
        else:
            pages, reason = [p + 1 for p in meta.get('no_text_pages') or []], 'scan pages'
        r = rows.setdefault(iid, {'url': meta['blob_url'], 'pages': set(), 'reason': set(), 'slugs': []})
        r['pages'] |= set(pages); r['reason'].add(reason); r['slugs'].append(h['slug'])
out = ['id\turl\tpages\treason\tslugs'] + [
    f"{i}\t{r['url']}\t{ranges(r['pages'])}\t{'; '.join(sorted(r['reason']))}\t{','.join(sorted(set(r['slugs'])))}"
    for i, r in sorted(rows.items(), reverse=True)]
tmp = WORK / 'OCR-REQUESTS.tsv.tmp'
tmp.write_text('\n'.join(out) + '\n', encoding='utf-8', newline='\n')
os.replace(tmp, WORK / 'OCR-REQUESTS.tsv')
print(len(rows), 'issues,', sum(len(r['slugs']) for r in rows.values()), 'items')
