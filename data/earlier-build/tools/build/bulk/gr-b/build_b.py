"""GR-B: build the corpus parts for one year of ΦΕΚ Β΄ (secondary legislation) from text/02/<year>/*.json.gz.

    python -X utf8 -I build_b.py <year> [--force]       parse + stage: stage/b-b-<year>-<k>.json, held/b-b-<year>.json,
                                                        state/refs-<year>.json (amendment/correction citations)
    python -X utf8 -I build_b.py <year> --promote       copy the staged parts atomically into scripts/greece-law/corpus.d
                                                        (only after the gates: two identical builds, 20 spot checks),
                                                        write each part's .PUBLISH and append READY.txt lines

A year is built only when every issue in index/02/<year>.json has been fetched and read (meta status ok and a text
file), unless --force (then the missing issues are listed in the held file and no part may be promoted).
Deterministic: the same text/meta/state files give the same bytes (no clocks; sorted everywhere).

Corpus model (CONVENTIONS + SCHEMA): one act per item of an issue, as published (gazette-only; no consolidation):
  slug   <kind>-<year>-<id>; kinds ya, kya, apofasi, kanonismos, diorthosi, pd (classify_b); year = the year of the
         issue; id = the ASCII-folded protocol number when it is unique within year + kind, else b<issue>-<k>
         (k = the item's number in the issue, zero-padded to 2)
  folder <kind>/<year>/<id>
  units  prooimio (issuing authority + recitals up to «αποφασίζουμε»), art-NNN per top-level «Άρθρο N», else
         para-NNN per top-level numbered paragraph (para-000: text before paragraph 1), else keimeno;
         parartima-NN per annex; one paragraph per line. Signatures are not carried.
  from   the decision's own commencement clause when it plainly states publication or one fixed date (not before
         publication), else the publication day; the version note says which.
  labels status "amended, not consolidated" + amended_by when a later Β΄ item (this year or a later year already
         built) says in its title that it amends / supplements / replaces this decision, matched strictly: the
         same protocol number AND (the same Β΄ issue number, in the cited date's year or the next) or (the same
         signing date); exactly one candidate. Corrections: corrected_by on the corrected act (same match).
Privacy: classify_b.privacy(); excluded items are listed in the held file without title or names.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import warnings  # noqa: E402

warnings.filterwarnings('ignore')
import ga_order  # noqa: E402
import ga_split as GA  # noqa: E402
import split_b as S  # noqa: E402
import classify_b as C  # noqa: E402

SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-b')
CORPUS = Path(r'C:\Users\alany\Documents\lexifina\scripts\greece-law\corpus.d')
STAGE = Path(os.environ['GRB_OUT']) / 'stage' if os.environ.get('GRB_OUT') else HERE / 'stage'
STATE = WORK / 'state'
OUTW = Path(os.environ['GRB_OUT']) if os.environ.get('GRB_OUT') else WORK  # held/refs of a gate re-run
PART_MAX = 35_000_000  # bytes per part (GitHub: 100 MB per file; the brief: <= ~40 MB)
LICENCE = ('Official legislative and administrative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 '
           'παρ. 5). Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).')
LABEL = {'ya': 'Υ.Α.', 'kya': 'Κ.Υ.Α.', 'apofasi': 'Απόφαση', 'kanonismos': 'Κανονισμός',
         'diorthosi': 'Διόρθωση σφαλμάτων', 'pd': 'Π.Δ.'}
NAME = {'ya': 'υπουργική απόφαση', 'kya': 'κοινή υπουργική απόφαση', 'apofasi': 'απόφαση', 'kanonismos': 'κανονισμός',
        'diorthosi': 'διόρθωση σφαλμάτων', 'pd': 'προεδρικό διάταγμα'}


# ---------------------------------------------------------------- units

def is_art(t: str):
    h = GA.art_heading(t)
    return h if h and len(t) < 40 else None


NUM_PARA = re.compile(r'^(\d{1,3})\.\s+\S')


def units_of(it: dict, kind: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    pre = [{'t': t, 'indent': 0, 'bold': True} for t in it['issuer_lines']] + it['preamble']
    if pre:
        out['prooimio'] = GA.paragraphs(pre)
    body = it['body']
    if kind == 'diorthosi':
        if body:
            out['keimeno'] = GA.paragraphs(body)
        return {k: v for k, v in out.items() if v}
    # top-level annexes inside the body (after the operative text): ΠΑΡΑΡΤΗΜΑ headings outside quotations
    annexes: list[list[dict]] = []
    depth = 0
    cut = None
    for i, l in enumerate(body):
        if depth == 0 and S.ANNEX.match(l['t']) and i > 0:
            cut = i
            break
        depth = max(0, depth + GA.quote_delta(l['t']))
    if cut is not None:
        cur: list[dict] = []
        for l in body[cut:]:
            if S.ANNEX.match(l['t']) and cur:
                annexes.append(cur)
                cur = []
            cur.append(l)
        if cur:
            annexes.append(cur)
        body = body[:cut]
    annexes += it['annexes']
    # articles: «Άρθρο 1», «Άρθρο 2» ... in sequence, outside quotations
    arts: list[tuple[str, list[dict]]] = []
    lead: list[dict] = []
    prev_n, prev_suf, depth = 0, '', 0
    for l in body:
        t = l['t']
        h = is_art(t) if depth == 0 else None
        ok = False
        if h:
            n, suf, _ = h
            ok = (n == prev_n + 1 and not suf) or (prev_n and n == prev_n and suf and suf != prev_suf) or \
                 (prev_n and n == prev_n + 1 and suf)
            if not arts and not (n == 1 and not suf):
                ok = False
        if ok:
            key = GA.art_key(n, suf)
            if key in dict(arts):
                ok = False
            else:
                arts.append((key, [l]))
                prev_n, prev_suf = n, suf
                depth = 0
                continue
        (arts[-1][1] if arts else lead).append(l)
        depth = max(0, depth + GA.quote_delta(t))
    if arts:
        if lead:
            out['para-000'] = GA.paragraphs(lead)
        for key, ls in arts:
            out[key] = GA.paragraphs(ls)
    elif body:
        paras = GA.paragraphs(body)
        groups: list[tuple[str, list[str]]] = []
        want = 1
        head: list[str] = []
        for p in paras:
            m = NUM_PARA.match(p)
            if m and int(m.group(1)) == want and GA.quote_delta(p) <= 0:
                groups.append((f'para-{want:03d}', [p]))
                want += 1
            elif groups:
                groups[-1][1].append(p)
            else:
                head.append(p)
        if len(groups) >= 2:
            if head:
                out['para-000'] = head
            for k, ps in groups:
                out[k] = ps
        else:
            out['keimeno'] = paras
    for k, a in enumerate(annexes, 1):
        out[f'parartima-{k:02d}'] = GA.paragraphs(a)
    return {k: v for k, v in out.items() if v}


def unit(key: str, paras: list[str]) -> dict:
    if key.startswith('art-'):
        label, kind = paras[0] if re.match(r'^(Άρθρο|ΑΡΘΡΟ)', paras[0]) else key, 'art'
    elif key == 'para-000':
        label, kind = 'Εισαγωγικό κείμενο', 'text'
    elif key.startswith('para-'):
        label, kind = f'Παρ. {int(key[5:])}', 'paragraph'
    elif key.startswith('parartima'):
        label, kind = (paras[0][:80] if paras[0].upper().startswith('ΠΑΡΑΡΤΗΜΑ') else 'Παράρτημα'), 'annex'
    elif key == 'prooimio':
        label, kind = 'Προοίμιο', 'preamble'
    else:
        label, kind = 'Κείμενο', 'text'
    return {'label': label, 'kind': kind, 'text': '\n'.join(paras) + '\n'}


# ---------------------------------------------------------------- commencement

ISX = re.compile(r'(?:(?:Η\s+ισχύς|Η\s+έναρξη\s+(?:της\s+)?ισχύος|Η\s+ισχύ)\s+(?:της\s+παρούσας|της\s+παρούσης|της\s+'
                 r'απόφασης|της\s+αποφάσεως|αυτής|της\s+παρούσας\s+απόφασης|του\s+παρόντος|του\s+κανονισμού|του\s+'
                 r'παρόντος\s+κανονισμού)(?:\s+απόφασης|\s+αποφάσεως|\s+πράξης)?\s*,?\s*(?:που\s+[^,]*,\s*)?(?:αρχίζει|'
                 r'ξεκινά)\s+(?:από|την|κατά)\s+|(?:Η\s+παρούσα|Η\s+απόφαση\s+αυτή|Η\s+παρούσα\s+απόφαση|Η\s+παρούσα\s+'
                 r'πράξη|Ο\s+παρών\s+[Κκ]ανονισμός|Ο\s+[Κκ]ανονισμός\s+αυτός|Το\s+παρόν|Η\s+παρούσα\s+κοινή\s+'
                 r'(?:υπουργική\s+)?απόφαση|Η\s+παρούσα\s+υπουργική\s+απόφαση)\s+(?:ισχύει|τίθεται\s+σε\s+ισχύ|'
                 r'ισχύει\s+και\s+εφαρμόζεται)\s+(?:από|με)\s+)(.{0,140})')
TO_PUB = re.compile(r'^(τη|την|της)\s+(ημερομηνία\s+(της\s+)?)?(δημοσίευσ|δημοσιεύσε)')
FIXED = re.compile(r'^(?:την\s+|τη\s+)?(\d{1,2})(?:η|ης|ην)?\s*(?:(?:\.|/|-)(\d{1,2})(?:\.|/|-)(\d{4})|\s+'
                   r'([Α-Ωα-ωάέήίόύώϊΐ]+)\s+(\d{4}))')


def commencement(units: dict[str, list[str]], published: str) -> tuple[str, str]:
    keys = [k for k in units if k != 'prooimio' and not k.startswith('parartima')]
    for k in reversed(keys):
        text = '\n'.join(units[k])
        for m in ISX.finditer(text):
            rest = m.group(1)
            if TO_PUB.match(rest):
                extra = (' (other provisions start as they state; not applied)'
                         if re.search(r'εκτός|επιφύλαξη|εξαιρ|διαφορετικά', rest[:140]) else '')
                return published, f'commencement clause ({k}): from publication{extra}'
            f = FIXED.match(rest)
            if f:
                d = (f'{int(f.group(3)):04d}-{int(f.group(2)):02d}-{int(f.group(1)):02d}' if f.group(2)
                     else GA.parse_date(f.group(1), f.group(4), f.group(5)))
                try:
                    import datetime as dt
                    dt.date.fromisoformat(d or '')
                except ValueError:
                    d = None
                if d:
                    if d < published:
                        return published, (f'commencement clause ({k}) states {d}, before publication: dated from '
                                           f'publication')
                    return d, f'commencement clause ({k}): fixed date {d}'
            return published, f'commencement clause ({k}) not a plain date ({rest[:50]!r}): publication day'
    return published, 'no commencement clause found: publication day'


# ---------------------------------------------------------------- citations (amendments, corrections)

AMEND_TITLE = re.compile(r'^(\d+[ηα]?\s+)?(τροποποιηση|συμπληρωση|αντικατασταση)\b')
CITE = re.compile(r'(?:υπ[’\']?\s*αρ(?:ιθμ)?\.?|υπό\s+στοιχεία|με\s+αρ(?:ιθμ)?\.?|αριθμ\.)\s*(.{3,90}?)(?=\s*\(Β|\s*\(ΦΕΚ|'
                  r'\s+(?:κοιν|υπουργ|απόφασ|αποφάσ|πράξ|διαπιστωτ|ανακοίν|του\s|της\s|των\s)|\s*«|,|$)')
DATE_TAIL = re.compile(r'^(.*?)\s*[/ ]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{4})\s*$')
FEK_B = re.compile(r'\(\s*(?:ΦΕΚ\s+)?Β[’΄\']\s*(\d{1,5})')


def norm_proto(p: str) -> str:
    p = re.sub(r'^(απόφ\.|αποφ\.|πράξης)\s*', '', p.strip(), flags=re.I)
    m = DATE_TAIL.match(p)
    if m:
        p = m.group(1)
    p = re.sub(r'\s*/\s*(19|20)\d\d$', '', p)  # «99/2025» and «99» name one decision (the year is matched apart)
    return re.sub(r'[^0-9a-z]', '', C.ascii_fold(p))


def cite_of(text: str) -> dict | None:
    """The first decision cited in text: protocol (normalised), date (ISO) if given, Β΄ issue number if given."""
    m = CITE.search(text)
    if not m:
        return None
    raw = m.group(1).strip().rstrip('.,')
    date = None
    dm = DATE_TAIL.match(raw)
    if dm:
        try:
            import datetime as dt
            date = dt.date(int(dm.group(4)), int(dm.group(3)), int(dm.group(2))).isoformat()
        except ValueError:
            date = None
    fek = FEK_B.search(text[m.start():m.end() + 160])
    proto = norm_proto(raw)
    if not proto or len(proto) < 2:
        return None
    return {'proto': proto, 'raw': raw, 'date': date, 'fek': int(fek.group(1)) if fek else None}


def match_target(cite: dict, index: dict[str, list[dict]], self_slug: str) -> dict | None:
    """Strict match (module doc): same normalised protocol and (same Β΄ issue in the cited year or the next, or the
    same signing date); exactly one candidate."""
    cands = [t for t in index.get(cite['proto'], []) if t['slug'] != self_slug]
    ok = []
    for t in cands:
        if cite['fek'] is not None:
            years = {int(cite['date'][:4]), int(cite['date'][:4]) + 1} if cite['date'] else None
            if t['issue'] == cite['fek'] and (years is None or t['year'] in years) and (
                    years is not None or t['signed'] == cite['date']):
                ok.append(t)
        elif cite['date'] and t['signed'] == cite['date']:
            ok.append(t)
    return ok[0] if len(ok) == 1 else None


# ---------------------------------------------------------------- the year

def index_rows(year: int) -> list[dict]:
    d = json.loads((SRC / 'index' / '02' / f'{year}.json').read_text(encoding='utf-8'))
    return d['rows']


def parse_year(year: int) -> tuple[list[dict], list[dict], dict]:
    """Every item of every fetched issue: (items, missing issues, stats)."""
    items, missing = [], []
    rows = index_rows(year)
    nums = sorted({int(r['search_DocumentNumber']) for r in rows})
    retrieved = []
    for no in nums:
        iid = f'{year}02{no:05d}'
        mp = SRC / 'meta' / '02' / str(year) / f'{iid}.json'
        tp = SRC / 'text' / '02' / str(year) / f'{iid}.json.gz'
        if not mp.exists() or not tp.exists():
            missing.append({'issue': no, 'why': 'not fetched / no text yet'})
            continue
        meta = json.loads(mp.read_text(encoding='utf-8'))
        if meta.get('fetched'):
            retrieved.append(meta['fetched'][:10])
        doc = ga_order.load(tp)
        r = S.split_issue(ga_order.reading_order(doc), meta)
        if not r['items']:
            missing.append({'issue': no, 'why': 'no items found: ' + '; '.join(r['problems'])[:200]})
            continue
        for it in r['items']:
            it['_issue'] = no
            it['_meta'] = meta
            it['_text_source'] = doc.get('text_source', 'text layer')
            it['_problems'] = r['problems']
            it['_no_text'] = set(meta.get('no_text_pages') or [])
            items.append(it)
    return items, missing, {'issues': len(nums), 'retrieved': max(retrieved) if retrieved else ''}


def published_of(meta: dict) -> str:
    return GA.issue_date(meta)


def body_text(it: dict) -> str:
    return '\n'.join(l['t'] for l in it['body']) + '\n' + '\n'.join(l['t'] for a in it['annexes'] for l in a)


def correction_title(it: dict) -> str:
    first = GA.P.tidy_para(GA.N.join_lines([l['t'] for l in it['body'][:4]]))
    first = re.split(r'(?:,\s*)?(?:γίνεται|γίνονται|διορθώνεται|διορθώνονται)\b|:', first)[0].strip()
    return ('Διόρθωση σφάλματος: ' + first)[:300].rstrip(' ,')


QUOTED = re.compile(r'«([^»]{6,200})»')


def build(year: int, force: bool = False) -> tuple[list[dict], dict, dict]:
    items, missing, st = parse_year(year)
    if missing and not force:
        raise SystemExit(f'{year}: {len(missing)} issue(s) not fetched/read yet (first: {missing[:3]}); use --force '
                         f'for a trial build')
    # pass 1: classify, privacy, protocol ids
    recs = []
    for it in items:
        k = C.kind(it)
        bt = body_text(it)
        why = C.privacy(it, k, bt)
        if not why and k == 'diorthosi':
            # a correction of an individual act: the corrected act's subject quoted in the correction
            for q in QUOTED.findall(bt[:1500]):
                if C.INDIVIDUAL_TITLE.match(C.fold(q)):
                    why = 'corrects an individual act naming a person'
                    break
        proto = C.protocol(it)
        recs.append({'it': it, 'kind': k, 'why': why, 'proto': proto, 'pid': C.protocol_id(proto) if proto else ''})
    counts: dict[tuple[str, str], int] = {}
    for r in recs:
        if r['pid']:
            counts[(r['kind'], r['pid'])] = counts.get((r['kind'], r['pid']), 0) + 1
    for r in recs:
        it = r['it']
        bid = f'b{it["_issue"]}-{it["n"]:02d}'
        pid = r['pid']
        r['id'] = pid if pid and counts[(r['kind'], pid)] == 1 and not re.match(r'^b\d+-\d+$', pid) else bid
        r['slug'] = f'{r["kind"]}-{year}-{r["id"]}'
    # pass 2: acts
    acts, held, excluded = [], [], []
    for r in recs:
        it, k = r['it'], r['kind']
        meta = it['_meta']
        issue = f'Β΄ {it["_issue"]}/{year}'
        row = {'issue': issue, 'n': it['n'], 'slug': r['slug'], 'kind': k,
               'issuer': C.issuer_slug(it, k), 'protocol': r['proto'], 'url': meta['api_url']}
        if r['why']:
            excluded.append({**row, 'why': r['why']})
            continue
        units = units_of(it, k)
        text = '\n'.join('\n'.join(v) for v in units.values())
        pages = it['pages']
        hold = None
        if GA.CONTROL.search(text):
            hold = 'text layer has control characters (unmapped font): needs OCR or a font map'
        elif it['_no_text'] and any(pages[0] <= p <= pages[1] for p in it['_no_text']):
            hold = f'pages without a text layer inside the item ({sorted(it["_no_text"])[:5]}): needs OCR'
        elif not any(key != 'prooimio' for key in units):
            hold = 'no operative text found'
        elif k != 'diorthosi' and not it['title']:
            hold = 'no title found'
        if hold:
            held.append({**row, 'title': it['title'][:200], 'why': hold})
            continue
        r['units'] = units
        r['published'] = published_of(meta)
        r['from'], r['from_rule'] = commencement(units, r['published'])
        r['title'] = it['title'] if k != 'diorthosi' else correction_title(it)
        r['row'] = row
        acts.append(r)
    # citations of this year's items (kept or not: an excluded item may still amend a kept one)
    refs = []
    for r in recs:
        it = r['it']
        t = C.fold(it['title'])
        src = None
        if r['kind'] == 'diorthosi':
            src = ('corrects', ' '.join(l['t'] for l in it['body'][:6]))
        elif AMEND_TITLE.match(t):
            src = ('amends', it['title'])
        if not src:
            continue
        c = cite_of(src[1])
        if c:
            refs.append({'rel': src[0], 'from': r['slug'], 'kept': not r['why'] and 'units' in r,
                         'title': (r.get('title') or it['title'])[:300], 'url': it['_meta']['api_url'],
                         'issue': it['_issue'], 'year': year, **c})
    stats = {**st, 'items': len(recs), 'acts': len(acts), 'excluded': len(excluded), 'held': len(held),
             'missing': missing}
    return acts, {'excluded': excluded, 'held': held, 'refs': refs}, stats


def label_of(r: dict, year: int) -> str:
    it = r['it']
    issue = f'Β΄ {it["_issue"]}/{year}'
    if r['kind'] in ('diorthosi', 'kanonismos', 'pd') or not r['proto']:
        return f'{LABEL[r["kind"]]} ({issue})'
    return f'{LABEL[r["kind"]]} {r["proto"]} ({issue})'


def make_part_acts(year: int, acts: list[dict], refs_all: list[dict]) -> tuple[list[dict], dict, list[str]]:
    # target index of this year's kept acts by normalised protocol
    index: dict[str, list[dict]] = {}
    for r in acts:
        if r['proto']:
            index.setdefault(norm_proto(r['proto']), []).append(
                {'slug': r['slug'], 'issue': r['it']['_issue'], 'year': year, 'signed': r['it']['signed']})
    amended: dict[str, list[dict]] = {}
    corrected: dict[str, list[dict]] = {}
    corrects: dict[str, str] = {}
    for ref in sorted(refs_all, key=lambda x: (x['year'], x['issue'], x['from'])):
        t = match_target(ref, index, ref['from'])
        if not t:
            continue
        if ref['year'] < year or (ref['year'] == year and ref['issue'] < t['issue']):
            continue  # an amending act is later than the act it amends
        entry = {'ref': ref['from'], 'title': ref['title'], 'url': ref['url']}
        if ref['rel'] == 'amends':
            if ref['kept']:
                amended.setdefault(t['slug'], []).append(entry)
        else:
            corrected.setdefault(t['slug'], []).append(entry)
            if ref['year'] == year:
                corrects[ref['from']] = t['slug']
    out, laws, label_log = [], {}, []
    for r in acts:
        it = r['it']
        meta = it['_meta']
        lab = label_of(r, year)
        key = r['slug']
        issue = f'Β΄ {it["_issue"]}/{year}'
        laws[key] = {'label': lab, 'kind': 'decree', 'title': r['title'], 'enacted': it['signed'] or r['published'],
                     'published': r['published'], 'url': meta['api_url'], 'temporary_until': None,
                     'restores': None, 'note': None}
        note = (f'{NAME[r["kind"]].capitalize()} as published in ΦΕΚ {issue}, item {it["n"]} ({it["_text_source"]}): '
                f'as enacted, later amendments are not applied. In force: {r["from_rule"]}.')
        if not it['signed']:
            note += ' No signing date found in the item: enacted = publication day.'
        act = {'slug': r['slug'], 'folder': f'{r["kind"]}/{year}/{r["id"]}', 'short': lab, 'title': r['title'],
               'url': meta['api_url'], 'sha256': meta['sha256'], 'text_source': it['_text_source'], 'issue': issue,
               'item': it['n'], 'kind_name': NAME[r['kind']], 'issuer': r['row']['issuer'],
               'issuer_text': ' '.join(it['issuer_lines'])[:300], 'protocol': r['proto'], 'signed': it['signed'],
               'first_law': key, 'earlier_laws': []}
        if r['slug'] in amended:
            act['status'] = 'amended, not consolidated'
            act['label'] = 'amended, not consolidated'
            act['amended_by'] = amended[r['slug']]
            label_log.append(r['slug'])
        if r['slug'] in corrected:
            act['corrected_by'] = corrected[r['slug']]
        if r['slug'] in corrects:
            act['corrects'] = corrects[r['slug']]
        act['versions'] = [{'from': r['from'], 'source_url': meta['api_url'], 'sha256': meta['sha256'],
                            'units': {k: unit(k, v) for k, v in r['units'].items()}, 'note': note}]
        out.append(act)
    return out, laws, label_log


def dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def part_header(year: int, st: dict, k: int, n: int) -> dict:
    return {
        'sources': [{'name': f'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: τεύχος Β΄ {year} '
                             f'({st["issues"]} issues read; part {k} of {n})',
                     'url': f'https://api.et.gr/apiFEK/2/{year}/', 'retrieved': st['retrieved'], 'licence': LICENCE,
                     'notes': 'Every issue of the year in the search.et.gr index was fetched from the official ΦΕΚ '
                              'API (api.et.gr); items read from the PDF text layer (or OCR, labelled per act).'}],
        'decisions': [
            f'ΦΕΚ Β΄ {year}: each item of an issue (ministerial and joint ministerial decisions, regulations, decisions '
            f'of other authorities, corrections) is one act, published as enacted (gazette-only: no official '
            f'consolidated texts exist); amendments are not applied.',
            'Acts are filed as <kind>/<year>/<id> (kinds: ya single-minister decision, kya joint ministerial '
            'decision, kanonismos regulation, apofasi decision of another authority, diorthosi correction of errors, '
            'pd decree printed in Β΄); id = the protocol number folded to ASCII when unique within the year and kind, '
            'else b<issue>-<item>. The issuing authority is recorded per act, not in the path (ministries are '
            'renamed and merged over time; joint decisions have several issuers).',
            'In-force day: the decision\'s own commencement clause when it plainly states publication or one fixed '
            'date not before publication; otherwise the publication day (each version note says which).',
            'Units: prooimio holds the issuing authority and the recitals (Έχοντας υπόψη) up to the deciding words; '
            'then one unit per Άρθρο, else per top-level numbered paragraph, else one text unit; annexes as '
            'parartima-NN. Signature blocks are not carried. Tables are carried as text lines.',
            'Individual acts that name private persons (citizenship, appointments and transfers of named staff, '
            'fines, honours, permits and grants to named persons, named committee members) are not published; they '
            'are counted in the worker\'s held list without their names.',
            'An act is labelled "amended, not consolidated" only when a later Β΄ item says in its title that it '
            'amends, supplements or replaces it and cites it by protocol number together with its Β΄ issue (in the '
            'cited year or the next) or its signing date, with exactly one match.',
        ],
        'ai_use': ['none: rule-based splitting, classification and parsing; no model output is used as legal text.'],
        'applies': [],
    }


def split_parts(year: int, acts: list[dict], laws: dict, st: dict) -> list[bytes]:
    """Acts in issue/item order, cut into parts under PART_MAX bytes (header + acts + their laws)."""
    groups: list[list[dict]] = [[]]
    size = 0
    for a in acts:
        s = len(dump(a)) + len(dump(laws[a['first_law']]))
        if groups[-1] and size + s > PART_MAX:
            groups.append([])
            size = 0
        groups[-1].append(a)
        size += s
    n = len(groups)
    out = []
    for k, g in enumerate(groups, 1):
        part = {'laws': {a['first_law']: laws[a['first_law']] for a in g}, **part_header(year, st, k, n), 'acts': g}
        out.append(dump(part))
    return out


def load_refs(year: int) -> list[dict]:
    refs = []
    for f in sorted(STATE.glob('refs-*.json')):
        y = int(f.stem.split('-')[1])
        if y > year:
            refs += json.loads(f.read_text(encoding='utf-8'))
    return refs


def main(argv: list[str]) -> None:
    year = int(argv[0])
    if '--promote' in argv:
        promote(year)
        return
    acts, extra, st = build(year, force='--force' in argv)
    refs_all = load_refs(year) + extra['refs']
    out, laws, labelled = make_part_acts(year, acts, refs_all)
    parts = split_parts(year, out, laws, st)
    for old in STAGE.glob(f'b-b-{year}-*.json'):
        old.unlink()
    for k, data in enumerate(parts, 1):
        write(STAGE / f'b-b-{year}-{k}.json', data)
    write(OUTW / 'state' / f'refs-{year}.json', dump(sorted(extra['refs'], key=lambda x: (x['issue'], x['from'], x['rel']))))
    kinds: dict[str, int] = {}
    for a in out:
        kinds[a['slug'].split('-')[0]] = kinds.get(a['slug'].split('-')[0], 0) + 1
    ex_kinds: dict[str, int] = {}
    for e in extra['excluded']:
        w = e['why'].split(' (')[0]
        ex_kinds[w] = ex_kinds.get(w, 0) + 1
    rep = {'year': year, **{k: v for k, v in st.items() if k != 'missing'}, 'kinds': kinds, 'labelled': len(labelled),
           'excluded_by_reason': ex_kinds, 'parts': [{'file': f'b-b-{year}-{k}.json', 'bytes': len(d),
                                                      'sha256': hashlib.sha256(d).hexdigest()}
                                                     for k, d in enumerate(parts, 1)],
           'missing': st['missing'], 'held': extra['held'], 'excluded': extra['excluded']}
    write(OUTW / 'held' / f'b-b-{year}.json', dump(rep))
    print(json.dumps({k: rep[k] for k in ('year', 'issues', 'items', 'acts', 'excluded', 'held', 'kinds',
                                           'labelled', 'excluded_by_reason')}, ensure_ascii=False))
    for p in rep['parts']:
        print(p['file'], p['bytes'], p['sha256'])


def promote(year: int) -> None:
    rep = json.loads((WORK / 'held' / f'b-b-{year}.json').read_text(encoding='utf-8'))
    if rep['missing']:
        raise SystemExit(f'{year}: built with missing issues; not promoted')
    gate = WORK / 'gates' / f'{year}.json'
    if not gate.exists() or not json.loads(gate.read_text(encoding='utf-8')).get('passed'):
        raise SystemExit(f'{year}: gates not passed ({gate})')
    g = json.loads(gate.read_text(encoding='utf-8'))
    ready = WORK / 'READY.txt'
    lines = ready.read_text(encoding='utf-8').splitlines() if ready.exists() else []
    for p in rep['parts']:
        data = (STAGE / p['file']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == p['sha256'], p['file']
        write(CORPUS / p['file'], data)
        n = len(json.loads(data.decode('utf-8'))['acts'])
        marker = (f'GR-B {g["date"]}: ΦΕΚ Β΄ {year} part {p["file"]} ({n} acts), split/classified by rule from the '
                  f'official PDF text layer; deterministic (two builds byte-identical, sha256 {p["sha256"]}); '
                  f'{g["spot_checks"]} hand spot checks of the year against the PDF text all hold; individual acts '
                  f'naming private persons excluded ({rep["excluded"]} items).\n')
        write(CORPUS / (p['file'][:-5] + '.PUBLISH'), marker.encode('utf-8'))
        line = f'{p["file"]} {n} {p["sha256"]}'
        lines = [x for x in lines if not x.startswith(p['file'] + ' ')] + [line]
        print('promoted', line)
    write(ready, ('\n'.join(lines) + '\n').encode('utf-8'))


if __name__ == '__main__':
    main(sys.argv[1:])
