"""GR-B spot checks: pick N acts of a staged year (seeded), print each act's fields and units next to the issue's
raw text (reading order) so a person can compare them line by line.

    python spot.py <year> <seed> <n> [slug ...]   -> gr-b/spot/<year>-<seed>.txt
"""
import glob, json, random, sys, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
import ga_order
HERE = Path(__file__).resolve().parent
SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-b')
year, seed, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
acts = []
for f in sorted(glob.glob(str(HERE / 'stage' / f'b-b-{year}-*.json'))):
    acts += json.loads(Path(f).read_text(encoding='utf-8'))['acts']
pick = [a for a in acts if a['slug'] in sys.argv[4:]] or random.Random(seed).sample(acts, n)
out = []
for a in pick:
    no = int(a['issue'].split()[1].split('/')[0])
    doc = ga_order.load(SRC / 'text' / '02' / year / f'{year}02{no:05d}.json.gz')
    raw = [f"{l['p']:>2} {l['t']}" for l in ga_order.reading_order(doc)]
    v = a['versions'][0]
    out.append('=' * 100)
    out.append(f"{a['slug']} | {a['short']} | issuer={a['issuer']} | protocol={a['protocol']!r} | signed={a['signed']} "
               f"| from={v['from']} | label={a.get('label')} | amended_by={[x['ref'] for x in a.get('amended_by', [])]}")
    out.append(f"TITLE: {a['title']}")
    out.append(f"NOTE: {v['note']}")
    for k, u in v['units'].items():
        t = u['text'].rstrip('\n').split('\n')
        out.append(f"--- {k} [{u['label'][:40]}] {len(t)} lines")
        out += ['    ' + x[:160] for x in (t if len(t) <= 8 else t[:4] + ['...'] + t[-3:])]
    out.append(f'--- RAW issue {a["issue"]} ({len(raw)} lines; item {a["item"]}): window around the item')
    key = a['title'][:25] if a['slug'].split('-')[0] != 'diorthosi' else a['title'][20:45]
    start = next((i for i, x in enumerate(raw) if key[:20] in x and i > 3), 0)
    lastu = list(v['units'].values())[-1]['text'].rstrip().split('\n')[-1][-30:]
    end = next((i for i in range(start, len(raw)) if lastu[-20:] in raw[i]), start + 40)
    win = list(range(max(0, start - 4), min(len(raw), start + 25))) + list(range(max(start + 25, end - 12), min(len(raw), end + 10)))
    prev = None
    for i in win:
        if prev is not None and i != prev + 1:
            out.append('  ...')
        out.append(f'  {i:4d} ' + raw[i][:160]); prev = i
(WORK / 'spot').mkdir(exist_ok=True)
p = WORK / 'spot' / f'{year}-{seed}.txt'
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print(p, len(pick))
