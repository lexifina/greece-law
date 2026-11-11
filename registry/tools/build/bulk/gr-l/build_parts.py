"""GR-L: build the corpus parts of one local unit (δήμος / περιφέρεια / αποκεντρωμένη διοίκηση) from its selected
decisions and their stored text.

    python -X utf8 -I build_parts.py <org uid> [...] [--out DIR]     (default out: bulk/gr-l/stage/)
    python -X utf8 -I build_parts.py --promote <part file name> [...]  (copy staged parts into corpus.d + .PUBLISH)
    python -X utf8 -I build_parts.py --coverage                       (write <WORK>/coverage.csv)

Writes <out>/b-l-<unit-slug>-<k>.json (k = 1, 2, ... each <= 35 MB; acts ordered by posting day then slug) and
<WORK>/held/<unit-slug>.json (every selected decision not published, with the reason: metadata only).
Deterministic: the same inputs give the same bytes (no clock reads; json sorted where order is not meaningful).
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common_l import ATH, CORPUS, META, SEL, SRC, TEXT, WORK, ada_ascii, norm_line, unit_slug  # noqa: E402
from parse_acts import parse  # noqa: E402

STAGE = HERE / 'stage'
MAX_BYTES = 35_000_000
LICENCE = ('Diavgeia (diavgeia.gov.gr) open data, Creative Commons Attribution 4.0 (CC BY 4.0), Ministry of Digital '
           'Governance; official administrative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5).')
KIND = {'kanonismos': 'kanonismos', 'oey': 'kanonismos', 'kanonistiki': 'apofasi', 'teli': 'apofasi',
        'kykloforia': 'apofasi'}
CAT_EN = {'kanonismos': 'regulation (κανονισμός)', 'oey': 'internal services organisation (ΟΕΥ)',
          'kanonistiki': 'regulatory decision (κανονιστική απόφαση)', 'teli': 'fees and rates (τέλη, συντελεστές)',
          'kykloforia': 'traffic and parking rules (κυκλοφοριακές ρυθμίσεις)'}
AMEND = re.compile(r'τροποπο|συμπληρ|αντικατ[άα]στ|αντικαθ[ίι]στ')
ADA_TOKEN = re.compile(r'[0-9Α-ΩA-Z]{4,12}\s?[-–]\s?[0-9Α-ΩA-Z]{1,4}')
LAT2GR = str.maketrans('ABEHIKMNOPTXYZ', 'ΑΒΕΗΙΚΜΝΟΡΤΧΥΖ')


def orgs() -> dict[str, dict]:
    o = json.load(open(SRC / 'diavgeia' / 'organizations.json', encoding='utf-8'))
    o = o['organizations'] if isinstance(o, dict) else o
    return {x['uid']: x for x in o}


def day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, ATH).date().isoformat()


def dmy(iso: str) -> str:
    y, m, d = iso.split('-')
    return f'{int(d)}.{int(m)}.{y}'


def label_name(org: dict) -> str:
    """'ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ' -> 'Δήμος Αθηναίων' is not attempted (accents): the official label is used as given."""
    return ' '.join(org['label'].split())


def norm_ada(s: str) -> str:
    return re.sub(r'\s', '', s.upper().translate(LAT2GR)).replace('–', '-')


def unit_obj(key: str, paras: list[str], n: int) -> dict:
    if key == 'prooimio':
        label, kind = 'Προοίμιο', 'preamble'
    elif key.startswith('art-'):
        m = re.match(r'^((?:Άρθρο|ΑΡΘΡΟ|Αρθρο|ΆΡΘΡΟ)\s*\S+)', paras[0])
        label, kind = (m.group(1) if m else 'Άρθρο ' + key[4:].lstrip('0')), 'art'
    elif key.startswith('parartima-'):
        label, kind = f'Παράρτημα {int(key.split("-")[1])}', 'annex'
    else:
        label, kind = f'Διατακτικό, μέρος {int(key.split("-")[1])}', 'text'
    lines = [re.sub(r'\s+', ' ', p).strip() for p in paras]
    return {'label': label, 'kind': kind, 'text': '\n'.join(p for p in lines if p) + '\n'}


def load_text(r: dict) -> dict | None:
    p = TEXT / r['org'] / str(r['year']) / f'{ada_ascii(r["ada"])}.json.gz'
    if not p.exists():
        return None
    with gzip.open(p, 'rt', encoding='utf-8') as f:
        return json.load(f)


def amend_index(uid: str, published: dict[str, dict]) -> dict[str, list[dict]]:
    """{earlier ADA: [later decisions that say they amend it]} from every harvested subject of the org and from the
    operative text of the org's published acts. Strict: the later decision names the earlier one's ΑΔΑ, says
    τροποποίηση/συμπλήρωση/αντικατάσταση within 200 characters before it, and was posted later."""
    out: dict[str, list[dict]] = {}
    targets = {norm_ada(a): a for a in published}

    def scan(text: str, src: dict) -> None:
        for m in ADA_TOKEN.finditer(text):
            a = targets.get(norm_ada(m.group(0)))
            if not a or a == src['ada']:
                continue
            if not AMEND.search(text[max(0, m.start() - 200):m.start()].lower()):
                continue
            if (src.get('publishTimestamp') or 0) <= (published[a].get('publishTimestamp') or 0):
                continue
            lst = out.setdefault(a, [])
            if all(x['ada'] != src['ada'] for x in lst):
                lst.append(src)

    for p in sorted((META / uid).glob('*.jsonl.gz')):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                scan(r.get('subject') or '', r)
    for a, r in published.items():
        for key, paras in r['_units'].items():
            if key != 'prooimio':
                scan('\n'.join(paras), r)
    for lst in out.values():
        lst.sort(key=lambda x: (x.get('publishTimestamp') or 0, x['ada']))
    return out


def build(uid: str) -> tuple[list[tuple[str, dict]], dict]:
    org = orgs()[uid]
    slug_u = unit_slug(org)
    name = label_name(org)
    rows = [json.loads(l) for l in open(SEL / f'{uid}.jsonl', encoding='utf-8') if l.strip()]
    held, ok = [], {}
    for r in rows:
        a_ascii = ada_ascii(r['ada'])
        base = {'ada': r['ada'], 'category': r['category'], 'subject': ' '.join((r.get('subject') or '').split()),
                'issued': day(r['issueDate']) if r.get('issueDate') else None,
                'posted': day(r['publishTimestamp']) if r.get('publishTimestamp') else None,
                'url': f'https://diavgeia.gov.gr/doc/{r["ada"]}'}
        if a_ascii is None:
            held.append({**base, 'why': 'ΑΔΑ with characters outside the Greek capitals'})
            continue
        if r.get('privateData'):
            held.append({**base, 'why': 'marked by the publisher as containing personal data (privateData)'})
            continue
        if not r.get('publishTimestamp'):
            held.append({**base, 'why': 'no posting time in the record'})
            continue
        d = load_text(r)
        if d is None:
            held.append({**base, 'why': 'document not fetched yet'})
            continue
        res = parse(d)
        if res.get('hold'):
            held.append({**base, 'why': res['hold']})
            continue
        ok[r['ada']] = {**r, '_units': res['units'], '_doc': d, '_base': base}
    amended = amend_index(uid, ok)
    acts, laws = [], {}
    for a, r in sorted(ok.items(), key=lambda kv: (kv[1]['publishTimestamp'], kv[0])):
        d, base = r['_doc'], r['_base']
        a_ascii = ada_ascii(a)
        year = int(r['year'])
        kind = KIND[r['category']]
        slug = f'{kind}-{year}-{a_ascii}'
        key = f'ada-{a_ascii}'
        title = norm_line(' '.join((r.get('subject') or '').split()))
        src_url = f'https://diavgeia.gov.gr/opendata/decisions/{a}/document'
        posted, issued = base['posted'], base['issued'] or base['posted']
        laws[key] = {'label': f'{name}, ΑΔΑ {a}', 'kind': 'decree', 'title': title, 'enacted': issued,
                     'published': posted, 'url': base['url'], 'temporary_until': None, 'restores': None,
                     'note': None}
        note = (f'{name}: decision posted on Diavgeia on {dmy(posted)} (ΑΔΑ {a}; issued {dmy(issued)}), as posted: '
                f'later amendments are not applied. In force from its posting (ν. 4727/2020 άρθρο 78 παρ. 2; ν. '
                f'3861/2010 άρθρο 2 παρ. 4). Text: {d.get("text_source")}.')
        if r['category'] == 'oey':
            note += (' An internal services organisation (ΟΕΥ) also takes effect only once published in the ΦΕΚ '
                     '(τεύχος Β΄); this version is dated by its Diavgeia posting.')
        act = {'slug': slug, 'short': f'ΑΔΑ {a}', 'title': title, 'url': base['url'], 'folder':
               f'local/{slug_u}/{year}/{a_ascii}', 'issuer': name, 'ada': a, 'category': CAT_EN[r['category']],
               'sha256': d['sha256'], 'text_source': d.get('text_source'), 'first_law': key, 'earlier_laws': [],
               'versions': [{'from': posted, 'source_url': src_url, 'sha256': d['sha256'],
                             'units': {k: unit_obj(k, v, i) for i, (k, v) in enumerate(r['_units'].items(), 1)},
                             'note': note}]}
        if a in amended:
            act['label'] = 'amended, not consolidated'
            act['amended_by'] = [{'ref': f'ΑΔΑ {x["ada"]}', 'title': ' '.join((x.get('subject') or '').split()),
                                  'url': f'https://diavgeia.gov.gr/doc/{x["ada"]}'} for x in amended[a]]
        acts.append(act)
    rep = {'unit': slug_u, 'org': uid, 'name': name, 'selected': len(rows), 'published': len(acts),
           'held': sorted(held, key=lambda h: h['ada'])}
    retrieved = max((r['_doc'].get('fetched', '')[:10] for r in ok.values()), default='')
    parts, cur, size = [], [], 0
    for act in acts:
        b = len(json.dumps(act, ensure_ascii=False))
        if cur and size + b > MAX_BYTES:
            parts.append(cur)
            cur, size = [], 0
        cur.append(act)
        size += b
    if cur:
        parts.append(cur)
    out = []
    for k, chunk in enumerate(parts, 1):
        part = {
            'laws': {a['first_law']: laws[a['first_law']] for a in chunk},
            'sources': [{'name': f'Διαύγεια (diavgeia.gov.gr): {name}, κανονιστικές πράξεις (types Α.2, 2.4.1, 2.4.6)',
                         'url': f'https://diavgeia.gov.gr/opendata/search.json?org={uid}', 'retrieved': retrieved,
                         'licence': LICENCE,
                         'notes': ('Every decision of the body posted 2010-10 onward under the regulatory-act types '
                                   'was listed through the official open-data API; genuine regulations were selected '
                                   'by deterministic subject rules and their PDFs read from the text layer.')}],
            'acts': chunk, 'applies': [],
            'decisions': [
                f'{name}: local regulatory acts from Diavgeia. Only decisions whose subject shows a regulation, a '
                'regulatory decision, fees or rates set for everyone, permanent traffic or parking rules, or the '
                'internal services organisation are carried (deterministic rules, gr-l classify.py); individual '
                'permits, payments, appointments, contracts and temporary measures are not.',
                'Each act is the decision as posted on Diavgeia, one version, in force from its posting day '
                '(ν. 4727/2020 άρθρο 78 παρ. 2; ν. 3861/2010 άρθρο 2 παρ. 4); amendments are not applied. An act is '
                'labelled "amended, not consolidated" only when a later decision of the same body names its ΑΔΑ as '
                'the decision it amends.',
                'Units: the recitals, attendance and discussion are the unit prooimio; numbered articles are art-NNN; '
                'without articles the operative part after the decision formula is para-NNN, split at its top-level '
                'enumeration. Signatures, the Diavgeia signature stamp, running heads and distribution lists are not '
                'carried. Tables are carried as the text layer gives them, one cell or row per line.',
                'Decisions whose text names private persons (applicants, owners, residents, identity or tax numbers, '
                'vehicle plates), whose PDF has no usable text layer, or whose decision formula is preparatory '
                '(εισηγείται, γνωμοδοτεί) or a rejection are held: listed with the reason, not published.',
                'Some Diavgeia PDFs (2011-2019) carry a broken font map; their Greek letters are read again from the '
                'glyph ids through the same Windows font (named in each version note) and kept only if the result '
                'reads as Greek.'],
            'ai_use': ['none: rule-based selection and parsing; no model output is used as legal text.'],
        }
        out.append((f'b-l-{slug_u}-{k}.json', part))
    return out, rep


def dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


VALIDATE = r'C:\Users\alany\Documents\lexifina\scripts\greece-law\bulk\gr-a\validate.py'
KEY = re.compile(r'^[a-z0-9-]+$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
CTRL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f\xa0]')


def check_part(path: Path) -> list[str]:
    """Promotion gate: the GR-A validate.py rules (SCHEMA.md text form) on one part, then validate.py itself on the
    staged part together with every corpus.d part (slug collisions, law labels)."""
    import subprocess
    d = json.loads(path.read_text(encoding='utf-8'))
    errs = []
    for k in d.get('laws', {}):
        if not KEY.match(k):
            errs.append(f'law key {k}')
    for a in d['acts']:
        for v in a['versions']:
            if not DATE.match(v['from']):
                errs.append(f'{a["slug"]} from {v["from"]}')
            for uk, u in v['units'].items():
                t = u['text']
                if not KEY.match(uk):
                    errs.append(f'{a["slug"]} unit key {uk}')
                if not t.endswith('\n') or '\n\n' in t or t.startswith('\n') or CTRL.search(t):
                    errs.append(f'{a["slug"]}/{uk} text form')
    if not errs:
        r = subprocess.run([sys.executable, '-X', 'utf8', '-I', VALIDATE],
                           capture_output=True, text=True, encoding='utf-8', creationflags=0x08000000)
        # the corpus.d copy of this part is about to be replaced: its own old errors do not block
        bad = [l.strip() for l in r.stdout.splitlines() if l.startswith('  ') and 'b-l-' in l and path.name not in l]
        errs += [f'validate.py: {l}' for l in bad]
    return errs


def coverage() -> None:
    o = orgs()
    import harvest2
    lines = ['unit,org,name,decisions_harvested,a2_total,regulatory_classified,published,held,parts']
    for org in harvest2.ordered_orgs():
        uid = org['uid']
        st = WORK / 'select-stats' / f'{uid}.json'
        s = json.loads(st.read_text(encoding='utf-8')) if st.exists() else {}
        rp = WORK / 'held' / f'{unit_slug(o[uid])}.json'
        rep = json.loads(rp.read_text(encoding='utf-8')) if rp.exists() else {}
        nparts = len(list(STAGE.glob(f'b-l-{unit_slug(o[uid])}-*.json')))
        lines.append(','.join(str(x) for x in [unit_slug(o[uid]), uid, '"' + o[uid]['label'] + '"',
                                               s.get('total', ''), s.get('a2', ''), s.get('selected', ''),
                                               rep.get('published', ''), len(rep.get('held', [])) if rep else '',
                                               nparts or '']))
    write(WORK / 'coverage.csv', ('\n'.join(lines) + '\n').encode('utf-8'))


def main(argv: list[str]) -> None:
    if '--coverage' in argv:
        coverage()
        return
    if '--promote' in argv:
        for name in argv[argv.index('--promote') + 1:]:
            errs = check_part(STAGE / name)
            if errs:
                print(f'NOT promoted {name}: {len(errs)} errors', *errs[:20], sep='\n  ')
                sys.exit(1)
            write(CORPUS / name, (STAGE / name).read_bytes())
            write(CORPUS / (name[:-5] + '.PUBLISH'), b'')
            print('promoted', name)
        import subprocess
        r = subprocess.run([sys.executable, '-X', 'utf8', '-I', VALIDATE], capture_output=True, text=True,
                           encoding='utf-8', creationflags=0x08000000)
        print('validate.py after promotion:', r.stdout.strip()[:3000])
        return
    out = Path(argv[argv.index('--out') + 1]) if '--out' in argv else STAGE
    skip = {argv.index('--out') + 1} if '--out' in argv else set()
    for uid in [a for i, a in enumerate(argv) if not a.startswith('--') and i not in skip]:
        parts, rep = build(uid)
        for old in out.glob(f'b-l-{rep["unit"]}-*.json'):
            if old.name not in {n for n, _ in parts}:
                old.unlink()
        for n, part in parts:
            write(out / n, dump(part))
        write(WORK / 'held' / f'{rep["unit"]}.json', dump(rep))
        print(f'{uid} {rep["unit"]}: {rep["selected"]} selected, {rep["published"]} published, '
              f'{len(rep["held"])} held, {len(parts)} part(s)')


if __name__ == '__main__':
    main(sys.argv[1:])
