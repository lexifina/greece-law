"""GR-A: build the corpus part for one year of ΦΕΚ Α΄ from text/01/<year>/*.json.gz (text layer or OCR).

    python -X utf8 -I build_part.py <year> [--out DIR] [--promote]

Writes <out>/b-a-<year>.json (default out: bulk/gr-a/stage/) and <WORK>/held/b-a-<year>.json (acts not emitted, with
reasons; sections that are not acts). --promote copies the staged part atomically into scripts/greece-law/corpus.d
(only after the gates; see PROGRESS.md). Deterministic: the same text files give the same bytes.
Acts already hand-built on main (corpus.d parts not named b-*) are skipped.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import label as LB  # noqa: E402
import order  # noqa: E402
import split  # noqa: E402
from common import SRC, WORK  # noqa: E402

CORPUS = Path(r'C:\Users\alany\Documents\lexifina\scripts\greece-law\corpus.d')
STAGE = HERE / 'stage'
LICENCE = ('Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). Attribution: '
           'Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).')
LABEL = {'nomos': 'ν.', 'pd': 'π.δ.', 'an': 'α.ν.', 'nd': 'ν.δ.', 'nbd': 'ν.β.δ.', 'bd': 'β.δ.',
         'kanonismos': 'Κανονισμός', 'pys': 'Π.Υ.Σ.', 'ya': 'Υ.Α.', 'kya': 'Κ.Υ.Α.', 'apofasi': 'Απόφαση'}
LAW_KIND = {'nomos': 'law', 'an': 'law', 'pd': 'decree', 'pnp': 'decree', 'nd': 'decree', 'nbd': 'decree',
            'bd': 'decree', 'kanonismos': 'decree', 'pys': 'decree', 'ya': 'decree', 'kya': 'decree',
            'apofasi': 'decree'}
NAME = {'nomos': 'νόμος', 'pd': 'προεδρικό διάταγμα', 'pnp': 'πράξη νομοθετικού περιεχομένου',
        'an': 'αναγκαστικός νόμος', 'nd': 'νομοθετικό διάταγμα', 'nbd': 'νομοθετικό βασιλικό διάταγμα',
        'bd': 'βασιλικό διάταγμα', 'kanonismos': 'κανονισμός'}


# OCR text (GR-OCR) is merged only with GRA_USE_OCR=1: OCR acts need their own spot-check batch first
USE_OCR = os.environ.get('GRA_USE_OCR') == '1'
PUB = Path(r'C:\Users\alany\Documents\greece-law-pub')  # local clone of lexifina/greece-law (read only)
_main: dict | None = None


def on_main() -> dict[tuple[str, int, int], str]:
    """Every act folder on main (coordinator 11-11): nomos-NNNN-YYYY and nomos/YYYY/N -> ('nomos', N, YYYY);
    diatagma/YYYY/N -> ('pd', N, YYYY). Read with git ls-tree from the local clone, never fetched."""
    global _main
    if _main is None:
        import subprocess
        r = subprocess.run(['git', '-C', str(PUB), 'ls-tree', '-d', '-r', 'main', '--name-only'], capture_output=True,
                           text=True, encoding='utf-8', check=True, creationflags=0x08000000)
        _main = {}
        for d in r.stdout.split():
            m = re.match(r'^nomos-(\d+)-(\d{4})$', d)
            if m:
                _main[('nomos', int(m.group(1)), int(m.group(2)))] = d
                continue
            m = re.match(r'^(nomos|diatagma)/(\d{4})/(\d+)$', d)
            if m:
                _main[('nomos' if m.group(1) == 'nomos' else 'pd', int(m.group(3)), int(m.group(2)))] = d
    return _main


def handbuilt() -> set[tuple[str, int, int]]:
    out = set(on_main())
    for f in sorted(CORPUS.glob('*.json')):
        if f.name.startswith('b-'):
            continue
        for a in json.loads(f.read_text(encoding='utf-8')).get('acts', []):
            m = re.match(r'^nomos-(\d+)-(\d{4})$', a['slug'])
            if m:
                out.add(('nomos', int(m.group(1)), int(m.group(2))))
    return out


def unit(key: str, paras: list[str]) -> dict:
    if key.startswith('art-'):
        label, kind = paras[0] if re.match(r'^(Άρθρο|ΑΡΘΡΟ)', paras[0]) else next(
            (p for p in paras if re.match(r'^(Άρθρο|ΑΡΘΡΟ)\s', p)), key), 'art'
    elif key.startswith('parartima'):
        label, kind = next((p for p in paras if p.startswith('ΠΑΡΑΡΤΗΜΑ')), 'Παράρτημα'), 'annex'
    elif key == 'prooimio':
        label, kind = 'Προοίμιο', 'preamble'
    else:
        label, kind = 'Κείμενο', 'text'
    return {'label': label, 'kind': kind, 'text': '\n'.join(paras) + '\n'}


def dmy(iso: str) -> str:
    y, m, d = iso.split('-')
    return f'{int(d)}.{int(m)}.{y}'


def build(year: int) -> tuple[dict, dict]:
    skip = handbuilt()
    acts, laws, held, sections = [], {}, [], []
    slugs: dict[str, str] = {}
    n_issues = 0
    files = sorted(f for f in glob.glob(str(SRC / 'text' / '01' / str(year) / '*.json.gz'))
                   if not f.endswith('.ocr.json.gz'))
    # wholly scanned issues that GR-OCR read have only <id>.ocr.json.gz (or <id>.json.gz with an OCR text_source)
    have = {Path(f).name[:-8] for f in files}
    if USE_OCR:
        files += sorted(f for f in glob.glob(str(SRC / 'text' / '01' / str(year) / '*.ocr.json.gz'))
                        if Path(f).name[:-12] not in have)
    files.sort(key=lambda f: Path(f).name)
    for f in files:
        iid = Path(f).name.split('.')[0]
        meta = json.loads((SRC / 'meta' / '01' / str(year) / f'{iid}.json').read_text(encoding='utf-8'))
        doc = order.load(Path(f))
        ocr = SRC / 'text' / '01' / str(year) / f'{iid}.ocr.json.gz'
        if USE_OCR and ocr.exists() and Path(f) != ocr:
            # partial issue: GR-OCR's lines for the pages without a text layer are merged in (page order kept)
            o = order.load(ocr)
            want = set(meta.get('no_text_pages') or [])
            got = sorted({l['p'] for l in o['lines'] if l['p'] in want})
            doc = {**doc, 'lines': [l for l in doc['lines'] if l['p'] not in got]
                   + [l for l in o['lines'] if l['p'] in got],
                   'page_info': [({**pi, 'h': next((q['h'] for q in o.get('page_info', []) if q['page'] == pi['page']),
                                                   pi['h'])} if pi['page'] in got else pi)
                                 for pi in doc.get('page_info', [])],
                   'text_source': f'{doc["text_source"]} + {o["text_source"]} (pages {",".join(str(p + 1) for p in got)})'}
            doc['lines'].sort(key=lambda l: l['p'])
            meta = {**meta, 'no_text_pages': sorted(want - set(got))}
        elif doc.get('text_source', '').startswith('OCR'):
            meta = {**meta, 'no_text_pages': []}
        n_issues += 1
        res = split.split_issue(order.reading_order(doc), {**meta, 'text_source': doc['text_source']})
        issue = f'Α΄ {meta["number"]}/{year}'
        n_lawpd = sum(1 for a in res['acts'] if a['kind'] in ('nomos', 'pd'))
        for s in res['skipped']:
            sections.append({'issue': issue, **s})
        for a in res['acts']:
            kind, num = a['kind'], a['number']
            yr = year
            if kind == 'kanonismos':
                yr = int(re.search(r'/(\d{4})', a['heading']).group(1))
            if kind == 'pys':
                yr = int(a['ref'].split('/')[1])
            ident = str(num) if num is not None else f'a{meta["number"]}-{a["order"]:02d}'
            if kind == 'pys':
                ident = f'pys-{num}'
            slug = f'{"apofasi" if kind == "pys" else kind}-{yr}-{ident}'
            row = {'issue': issue, 'id': iid, 'slug': slug, 'heading': a['heading'], 'title': a['title'][:200],
                   'url': meta['api_url'], 'pages': a['pages']}
            if kind in ('nomos', 'pd') and (kind, num, yr) in skip:
                where = on_main().get((kind, num, yr), 'a hand-built corpus.d part')
                held.append({**row, 'why': f'on main already ({where}): skipped'})
                continue
            if a['held']:
                held.append({**row, 'why': a['held']})
                continue
            if slug in slugs:
                held.append({**row, 'why': f'same act already in {slugs[slug]} (a reprint?): not emitted'})
                continue
            slugs[slug] = issue
            if kind == 'pnp':
                if not a['signed']:
                    held.append({**row, 'why': 'π.ν.π. without a signing date'})
                    continue
                key = f'pnp-{a["signed"]}'
                label = f'Π.Ν.Π. της {dmy(a["signed"])}'
                k2 = 2
                while key in laws:
                    key, label = f'pnp-{a["signed"]}-{k2}', f'Π.Ν.Π. της {dmy(a["signed"])} ({k2})'
                    k2 += 1
            elif kind == 'pys':
                key = f'pys-{num}-{yr}'
                label = f'Π.Υ.Σ. {num}/{yr}'
            elif num is None:
                key = f'{kind}-{yr}-{ident}'
                label = f'{LABEL[kind]} {a.get("ref") or (dmy(a["signed"]) if a["signed"] else ident)} ({issue})'
            else:
                key = f'n-{num}-{yr}' if kind == 'nomos' else f'{kind}-{num}-{yr}'
                label = f'{LABEL[kind]} {num}/{yr}'
            laws[key] = {'label': label, 'kind': LAW_KIND[kind], 'title': a['title'],
                         'enacted': a['signed'] or a['published'], 'published': a['published'], 'url': meta['api_url'],
                         'temporary_until': None, 'restores': None, 'note': None}
            note = (f'{label} as published in ΦΕΚ {issue} ({doc["text_source"]}), as enacted: later amendments are not '
                    f'applied. In force: {a["from_rule"]}.')
            if 'OCR' in doc['text_source']:
                note += (f' Text read by OCR from the official scan ({doc["text_source"]}); OCR text is spot-checked '
                         f'per batch but may contain reading errors.')
            if not a['signed']:
                note += ' No signing date found in the issue: enacted = publication day.'
            if a.get('gap_lines'):
                note += (f' {a["gap_lines"]} printed line(s) whose text layer has no readable characters (unmapped '
                         f'font) are marked "{split.GAP}".')
            if a['gaps']:
                note += ' ' + '; '.join(a['gaps']) + ' (numbering as printed).'
            act = {
                'slug': slug, 'short': label, 'title': a['title'], 'url': meta['api_url'],
                'sha256': meta['sha256'], 'text_source': doc['text_source'], 'issue': issue,
                'first_law': key, 'earlier_laws': [],
                'versions': [{'from': a['from'], 'source_url': meta['api_url'], 'sha256': meta['sha256'],
                              'units': {k: unit(k, v) for k, v in a['units'].items()}, 'note': note}]}
            if kind in ('nomos', 'pd') and year >= 1975 and n_lawpd == 1:
                rels = [r for r in LB.relations()['by_issue'].get((year, meta['number']), [])
                        if r['ref'] != f'ΦΕΚ {issue}']
                if rels:
                    act['status'] = 'amended, not consolidated'
                    act['amended_by'] = rels
            acts.append(act)
    part = {
        'laws': laws,
        'sources': [{'name': f'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: τεύχος Α΄ {year} '
                             f'({n_issues} issues read)',
                     'url': f'https://api.et.gr/apiFEK/1/{year}/', 'retrieved': retrieved(year), 'licence': LICENCE,
                     'notes': 'Every issue of the year in the search.et.gr index was fetched (blob store copy of the '
                              'official API PDF); acts read from the text layer (or OCR, labelled per act).'}],
        'acts': acts, 'applies': [],
        'decisions': [
            f'ΦΕΚ Α΄ {year}: every act is published as enacted in its issue (gazette-only: Greece has no official '
            f'consolidated texts); amendments are not applied; acts named as amended in the et.gr relation index are '
            f'labelled "amended, not consolidated".',
            'In-force day: the act\'s own commencement clause when it plainly states publication or one fixed date '
            'for the whole act; a stated day before publication, or any other wording, gives the publication day '
            '(each version note says which).',
            'Laws: the enacting formula, the table of contents, the promulgation sentence, signatures and the Great '
            'Seal line are not carried (as the hand-built parts). Decrees and regulations: the recitals are the unit '
            'prooimio; a decree with no articles carries its operative text as unit keimeno.',
            'Acts whose pages have no text layer, or whose text layer holds unmapped-font control characters, are '
            'held until OCR text exists (listed in the GR-A held file, not published).',
            'Sections that are not acts (Ανακοινώσεις, Διορθώσεις σφαλμάτων) are not carried in this part.',
            'Labels: laws and presidential decrees (1975 on) that the et.gr relation index (search.et.gr) shows as '
            'amended (Τροποποίηση), replaced (Αντικατάσταση) or annulled (Ακύρωση) by a ΦΕΚ Α΄ or Β΄ document are '
            'labelled "amended, not consolidated" with those documents listed; relations are per issue, so only an '
            'issue holding a single law or decree is labelled; "repealed" is not inferred from the index.',
            'Tables are carried as their text layer reads them; where a table’s label and number columns are set '
            'apart, their cells may follow one another rather than row by row.'],
        'ai_use': ['none: rule-based splitting and parsing; no model output is used as legal text.'],
    }
    return part, {'year': year, 'issues': n_issues, 'acts': len(acts), 'held': held, 'sections': sections}


def retrieved(year: int) -> str:
    ds = []
    for f in glob.glob(str(SRC / 'meta' / '01' / str(year) / '*.json')):
        d = json.loads(Path(f).read_text(encoding='utf-8')).get('fetched')
        if d:
            ds.append(d[:10])
    return max(ds) if ds else ''


def dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main(argv: list[str]) -> None:
    year = int(argv[0])
    out = Path(argv[argv.index('--out') + 1]) if '--out' in argv else STAGE
    if '--promote' in argv:
        src = STAGE / f'b-a-{year}.json'
        write(CORPUS / src.name, src.read_bytes())
        print(f'promoted {src.name}')
        return
    part, rep = build(year)
    write(out / f'b-a-{year}.json', dump(part))
    write(WORK / 'held' / f'b-a-{year}.json', dump(rep))
    print(f'{year}: {rep["issues"]} issues, {rep["acts"]} acts, {len(rep["held"])} held, '
          f'{len(rep["sections"])} non-act sections')


if __name__ == '__main__':
    main(sys.argv[1:])
