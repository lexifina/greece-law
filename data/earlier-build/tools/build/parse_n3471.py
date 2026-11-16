"""Build the ν. 3471/2006 part of the Greece corpus (corpus.d/31-n3471.json) from the cache of fetch_laws.py.

ν. 3471/2006 (personal data and privacy in electronic communications, the e-Privacy Directive 2002/58/EC; ΦΕΚ Α΄
133/28.6.2006) as enacted, then every amendment, each applied from the amending law's own ΦΕΚ text:

    ν. 3783/2009 (Α΄ 136/7.8.2009), art. 8          art. 5 par. 7 replaced
    ν. 3917/2011 (Α΄ 22/21.2.2011), art. 16          art. 11 par. 1 (two words struck), par. 2 first sentence replaced;
                                                     in force on the first day of the month after six months (art. 16
                                                     par. 3): 1.9.2011
    ν. 4070/2012 (Α΄ 82/10.4.2012), arts. 168-173    arts. 2, 3 par. 1, 4 par. 5, 5 and 6 (replaced), 11 (pars. 3-4
                                                     replaced, 5-6 and 8 added, old 5 renumbered 7), 12 (title, pars.
                                                     3-10 added, old 3 renumbered 11)

Its art. 31 puts the law in force on publication, but Chapter One (arts. 1-17) one month later: so the first version
(28.6.2006) holds arts. 18-31 and the second (28.7.2006) adds arts. 1-17.

The issues are read with fek_reader (full-width bands; the 2012 issue's columns then come out in page order). The
2006 issue sets article titles in plain type, centred: a line between "Άρθρο N" and the first indented paragraph is
the title when it is not at the paragraph indent. Each instruction's target must be found once; each quoted text
must then be present in the new version; replaced provisions read as the amending law quotes them.

    python -X utf8 scripts/greece-law/parse_n3471.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_laws as FL  # noqa: E402
import parse as P  # noqa: E402
import parse_n4624 as N  # noqa: E402
import fek_reader as R  # noqa: E402

N.CACHE = FL.CACHE
OUT = HERE / 'corpus.d' / '31-n3471.json'
LOG: list[str] = []
MONTHS = ['Ιανουαρίου', 'Φεβρουαρίου', 'Μαρτίου', 'Απριλίου', 'Μαΐου', 'Ιουνίου', 'Ιουλίου', 'Αυγούστου',
          'Σεπτεμβρίου', 'Οκτωβρίου', 'Νοεμβρίου', 'Δεκεμβρίου']
ISSUES = {'n-3471-2006': (2006, 133), 'n-3783-2009': (2009, 136), 'n-3917-2011': (2011, 22),
          'n-4070-2012': (2012, 82)}
ART = re.compile(r'^Άρθρο (\d+)([Α-Ω])?$')
STRUCT = re.compile(r'^(ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ)\b')


def raw_text(year: int, num: int) -> str:
    import fitz
    return ''.join(p.get_text() for p in fitz.open(N.cpath(FL.fek_url(year, num))))


def flat(year: int, num: int) -> str:
    t = re.sub(r'[-−‐]\s*\n(?=[α-ωά-ώ])', '', raw_text(year, num))
    t = re.sub(r'\s+', ' ', t)
    return re.sub(r'(?<=[α-ωά-ώ])[-−‐] (?=[α-ωά-ώ])', '', t)


def masthead(year: int, num: int) -> str:
    t = re.sub(r'\s+', ' ', raw_text(year, num)[:600])
    m = re.search(r'Αρ\. Φύλλου (\d+) (\d{1,2}) (\w+) (\d{4})', t)
    if not m or int(m.group(1)) != num or int(m.group(4)) != year:
        raise SystemExit(f'masthead of Α΄ {num}/{year} not as expected: {t[:200]}')
    return f'{year}-{MONTHS.index(m.group(3)) + 1:02d}-{int(m.group(2)):02d}'


def law_number_title(year: int, num: int) -> tuple[int, str]:
    t = re.sub(r'\s+', ' ', re.sub(r'[-−]\s*\n(?=[α-ωά-ώ])', '', raw_text(year, num)[:1500]))
    t = re.sub(r'(?<=[α-ωά-ώ])[-−‐] (?=[α-ωά-ώ])', '', t)
    m = re.search(r'[ΝN][OΟ][ΜM][OΟ]Σ ΥΠ’ ΑΡΙΘ(?:Μ)?\. (\d+) (.+?)\.? (?:Ο|Η) ΠΡΟΕΔΡΟΣ', t)
    if not m:
        raise SystemExit(f'Α΄ {num}/{year}: no law number and title')
    return int(m.group(1)), N.norm_line(m.group(2)).rstrip('.') + '.'


def signed(year: int, num: int) -> str:
    t = re.sub(r'\s+', ' ', raw_text(year, num))
    m = re.search(r'Αθήνα, (\d{1,2}) (\w+) (\d{4})', t)
    return f'{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}' if m else None


def lines_of(year: int, num: int) -> list[dict]:
    ls = R.read_lines(N.cpath(FL.fek_url(year, num)))
    # an overprinted fragment ("ξης") the 2012 issue leaves between two lines of a column
    return [l for l in ls if not (len(l['t']) <= 4 and re.fullmatch(r'[α-ωά-ώ]+', l['t']))]


def paragraphs(lines: list[dict]) -> list[dict]:
    """[{kind: art|title|head|p, text}] from lines: a paragraph starts at the first-line indent (4-12 points),
    continues at the column edge; a line set further in (centred) is a heading or, after "Άρθρο N", the title."""
    out: list[dict] = []
    cur: list[str] = []
    kind = None
    after_art = False
    after_head = False

    def flush():
        nonlocal cur, kind
        if cur:
            out.append({'kind': kind, 'text': P.tidy_para(N.join_lines(cur))})
        cur, kind = [], None

    for l in lines:
        t, ind = l['t'], l['indent']
        if ART.match(t):
            flush()
            out.append({'kind': 'art', 'text': t})
            after_art, after_head = True, False
            continue
        if STRUCT.match(t) and ind > 12:
            flush()
            out.append({'kind': 'head', 'text': t})
            after_art, after_head = False, True
            continue
        if after_head:  # a chapter's name runs to the next article heading
            if kind != 'head':
                flush()
                kind = 'head'
            cur.append(t)
            continue
        title_more = ((kind == 'title' or after_art) and ind > 1.5 and abs(ind - 7.8) > 1.2
                      and not re.match(r'^(\d+\.\s|[α-ω]{1,2}\)\s|«)', t))
        if ind > 12 or title_more:
            k = 'title' if after_art else 'head'
            if kind != k:
                flush()
                kind = k
            cur.append(t)
            continue
        after_art = False
        if 4 <= ind <= 12 or not cur or kind in ('title', 'head'):
            flush()
            cur, kind = [t], 'p'
        else:
            cur.append(t)
    flush()
    return out


def units_from(paras: list[dict]) -> dict[str, list[str]]:
    units: dict[str, list[str]] = {}
    pending: list[str] = []
    key = None
    for p in paras:
        if p['kind'] == 'head':
            pending.append(p['text'])
            continue
        if p['kind'] == 'art':
            m = ART.match(p['text'])
            key = f'art-{int(m.group(1)):03d}'
            if key in units:
                raise SystemExit(f'{key} twice')
            units[key] = pending + [p['text']]
            pending = []
            continue
        if key is None:
            raise SystemExit(f'text before the first article: {p["text"][:60]}')
        units[key].append(p['text'])
    return units


def enacted() -> dict[str, list[str]]:
    ls = lines_of(2006, 133)
    i0 = next(i for i, l in enumerate(ls) if l['t'].startswith('ΚΕΦΑΛΑΙΟ ΠΡΩΤΟ'))
    i1 = next(i for i, l in enumerate(ls) if re.match(r'^(Παραγγέλλομε τη δημοσίευση|Αθήνα, \d)', l['t']))
    u = units_from(paragraphs(ls[i0:i1]))
    if list(u) != [f'art-{n:03d}' for n in range(1, 32)]:
        raise SystemExit(f'Α΄ 133/2006: articles are not 1-31: {list(u)}')
    return u


def amending(year: int, num: int, art: int) -> list[dict]:
    """The paragraphs of article `art` of the law in Α΄ num/year (the law's own article, not a quoted one)."""
    ls = lines_of(year, num)
    hits = [i for i, l in enumerate(ls) if l['t'] == f'Άρθρο {art}']
    if not hits:
        raise SystemExit(f'Α΄ {num}/{year}: no Άρθρο {art}')
    i = hits[-1]
    j = next((k for k in range(i + 1, len(ls)) if re.match(rf'^Άρθρο {art + 1}$', ls[k]['t'])
              or re.match(r'^ΜΕΡΟΣ ', ls[k]['t'])), len(ls))
    return paragraphs(ls[i:j])[1:]


def quotes(paras: list[str]) -> list[list[str]]:
    """«…» quotations that run over whole paragraphs (outer marks removed)."""
    out, cur, depth = [], None, 0
    for t in paras:
        if cur is None:
            if not t.startswith('«'):
                continue
            cur, depth = [], 0
        depth += t.count('«') - t.count('»')
        cur.append(t)
        if depth <= 0:
            cur[0] = cur[0][1:]
            cur[-1] = re.sub(r'»\.?$', '', cur[-1])
            out.append(cur)
            cur = None
    if cur is not None:
        raise SystemExit(f'unclosed quotation: {cur[0][:60]}')
    return out


def par_range(lines: list[str], num: str, what: str) -> tuple[int, int]:
    """(i, j): the lines of paragraph `num` ("7. …") up to the next numbered paragraph."""
    hits = [i for i, l in enumerate(lines) if l.startswith(f'{num}. ')]
    if len(hits) != 1:
        raise SystemExit(f'{what}: par. {num} found {len(hits)} times')
    i = hits[0]
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+\. ', lines[j]):
        j += 1
    return i, j


def head_title(lines: list[str]) -> int:
    """Index of the first body line (after headings, "Άρθρο N" and the title)."""
    i = next(i for i, l in enumerate(lines) if ART.match(l))
    return i + 2 if i + 1 < len(lines) and not re.match(r'^(\d+\. |«|[α-ω]\) )', lines[i + 1]) and len(lines[i + 1]) < 120 else i + 1


def present(u: dict, key: str, quoted: list[str], what: str) -> None:
    text = '\n'.join(u[key])
    for q in quoted:
        if q not in text:
            raise SystemExit(f'{what}: quoted text not in {key}: {q[:70]}')


def need(text: str, phrase: str, what: str) -> None:
    if phrase not in text:
        raise SystemExit(f'{what}: expected wording not found: {phrase!r}')


def am_3783(u: dict) -> dict:
    body = [p['text'] for p in amending(2009, 136, 8)]
    ins = ' '.join(body)
    need(ins, 'Η παράγραφος 7 του άρθρου 5 του ν. 3471/2006 (ΦΕΚ 133 Α’) τροποποιείται ως εξής:', 'ν. 3783/2009 art. 8')
    (q,) = quotes(body)
    if len(q) != 1 or not q[0].startswith('7. '):
        raise SystemExit('ν. 3783/2009 art. 8: quotation is not one par. 7')
    u = {k: list(v) for k, v in u.items()}
    i, j = par_range(u['art-005'], '7', 'art. 5')
    u['art-005'][i:j] = q
    present(u, 'art-005', q, 'ν. 3783/2009 art. 8')
    LOG.append('ν. 3783/2009 art. 8: art. 5 par. 7 replaced')
    return u


def am_3917(u: dict) -> dict:
    body = [p['text'] for p in amending(2011, 22, 16)]
    ins = ' '.join(body)
    need(ins, '1. Στην παρ. 1 του άρθρου 11 του ν. 3471/2006 διαγράφονται οι λέξεις «με ή».', 'ν. 3917/2011 art. 16')
    need(ins, '2. Το πρώτο εδάφιο της παρ. 2 του άρθρου 11 του ν.3471/2006 αντικαθίσταται ως εξής:', 'ν. 3917/2011 art. 16')
    m = re.search(r'αντικαθίσταται ως εξής: «([^»]+)»', ins)
    new_s = m.group(1)
    u = {k: list(v) for k, v in u.items()}
    a = u['art-011']
    i, j = par_range(a, '1', 'art. 11')
    par1 = ' '.join(a[i:j])
    if len(re.findall(r'(?<!\w)με ή (?=\w)', par1)) != 1:
        raise SystemExit('art. 11 par. 1: «με ή» is not there exactly once')
    a[i:j] = [re.sub(r'(?<!\w)με ή (?=\w)', '', par1, count=1)]
    i, j = par_range(a, '2', 'art. 11')
    par2 = ' '.join(a[i:j])
    s = N.sentences(par2)
    a[i:j] = [' '.join(['2. ' + new_s] + s[1:])]
    LOG.append(f'ν. 3917/2011 art. 16: art. 11 par. 1 «με ή» struck; par. 2 first sentence replaced (it read: '
               f'«{s[0][3:][:90]}…»); in force 1.9.2011 (art. 16 par. 3)')
    present(u, 'art-011', [new_s], 'ν. 3917/2011 art. 16')
    return u


def am_4070(u: dict) -> dict:
    u = {k: list(v) for k, v in u.items()}
    # art. 168: art. 2 items
    body = [p['text'] for p in amending(2012, 82, 168)]
    ins = ' '.join(body)
    need(ins, '1. Στο άρθρο 2 του ν. 3471/2006 (A’133):', 'ν. 4070/2012 art. 168')
    need(ins, 'β) Το στοιχείο αρ. 6 διαγράφεται και τα στοιχεία με αρ. 7 έως 11 αναριθμούνται σε στοιχεία με αρ. 6 '
              'έως 10.', 'ν. 4070/2012 art. 168')
    qs = quotes(body)
    if len(qs) != 3:
        raise SystemExit(f'ν. 4070/2012 art. 168: {len(qs)} quotations, expected 3')
    q4, q8, q11 = qs[0], qs[1], qs[2]
    a = u['art-002']
    items = {}
    for idx, l in enumerate(a):
        m = re.match(r'^(\d+)\. ', l)
        if m:
            items[int(m.group(1))] = idx
    if sorted(items) != list(range(1, 12)):
        raise SystemExit(f'art. 2: items are {sorted(items)}, expected 1-11')
    if not all(items[k] + 1 == items[k + 1] for k in range(1, 11)) or items[11] != len(a) - 1:
        raise SystemExit('art. 2: an item runs over more than one line')
    new = a[:items[1]]
    for k in range(1, 12):
        line = a[items[k]]
        if k == 4:
            line = q4[0]
        if k == 6:
            continue
        if k > 6:
            line = re.sub(r'^\d+\. ', f'{k - 1}. ', line)
        if k - 1 == 8 and k > 6:
            line = line + ' ' + q8[0]
        new.append(line)
    new += q11
    a[:] = new
    present(u, 'art-002', q4 + q8 + q11, 'ν. 4070/2012 art. 168')
    LOG.append('ν. 4070/2012 art. 168: art. 2 item 4 replaced, item 6 struck and 7-11 renumbered 6-10, a sentence '
               'added to the new item 8, item 11 added')
    # art. 169: art. 3 par. 1
    body = [p['text'] for p in amending(2012, 82, 169)]
    need(' '.join(body), 'Η παρ. 1 του άρθρου 3 του ν. 3471/2006 αντικαθίσταται ως εξής:', 'ν. 4070/2012 art. 169')
    (q,) = quotes(body)
    i, j = par_range(u['art-003'], '1', 'art. 3')
    u['art-003'][i:j] = q
    present(u, 'art-003', q, 'ν. 4070/2012 art. 169')
    # art. 170: art. 4 par. 5
    body = [p['text'] for p in amending(2012, 82, 170)]
    need(' '.join(body), 'Στο άρθρο 4 του ν. 3471/2006, η παράγραφος 5 αντικαθίσταται ως εξής:', 'ν. 4070/2012 art. 170')
    (q,) = quotes(body)
    i, j = par_range(u['art-004'], '5', 'art. 4')
    u['art-004'][i:j] = q
    present(u, 'art-004', q, 'ν. 4070/2012 art. 170')
    # art. 171: arts. 5 and 6 replaced (headings, "Άρθρο N" and title kept)
    body = [p['text'] for p in amending(2012, 82, 171)]
    ins = ' '.join(body)
    need(ins, '1. Το άρθρο 5 του ν. 3471/2006 αντικαθίσταται ως εξής:', 'ν. 4070/2012 art. 171')
    need(ins, '2. Το άρθρο 6 του ν. 3471/2006 αντικαθίσταται ως εξής:', 'ν. 4070/2012 art. 171')
    q5, q6 = quotes(body)
    for key, q, n in (('art-005', q5, 5), ('art-006', q6, 6)):
        if not q[0].startswith('1. '):
            raise SystemExit(f'ν. 4070/2012 art. 171: art. {n} quotation does not open with par. 1')
        k0 = head_title(u[key])
        u[key] = u[key][:k0] + q
        present(u, key, q, f'ν. 4070/2012 art. 171 (art. {n})')
    LOG.append(f'ν. 4070/2012 arts. 169-171: art. 3 par. 1, art. 4 par. 5 replaced; arts. 5 ({len(q5)} paragraphs) and '
               f'6 ({len(q6)}) restated whole')
    # art. 172: art. 11
    body = [p['text'] for p in amending(2012, 82, 172)]
    ins = ' '.join(body)
    for w in ('1. Οι παράγραφοι 3 και 4 του άρθρου 11 του ν. 3471/ 2006 αντικαθίστανται ως εξής:',
              '2. Μετά την παράγραφο 4 προστίθενται παράγραφοι, 5 και 6, ως εξής:',
              '3. Η παρ. 5 του άρθρου 11 του ν. 3471/2006 αναριθμείται σε παράγραφο 7.',
              '4. Στο άρθρο 11 του ν. 3471/2006, προστίθεται παράγραφος 8, ως εξής:'):
        need(ins.replace('3471/2006', '3471/2006').replace('3471/ 2006', '3471/ 2006'), w, 'ν. 4070/2012 art. 172')
    q34, q56, q8 = quotes(body)
    a = u['art-011']
    i3, _ = par_range(a, '3', 'art. 11')
    i5, j5 = par_range(a, '5', 'art. 11')
    if j5 != len(a):
        raise SystemExit('art. 11: par. 5 is not the last')
    old5 = a[i5:j5]
    old5[0] = re.sub(r'^5\. ', '7. ', old5[0])
    a[i3:] = q34 + q56 + old5 + q8
    present(u, 'art-011', q34 + q56 + q8, 'ν. 4070/2012 art. 172')
    LOG.append('ν. 4070/2012 art. 172: art. 11 pars. 3-4 replaced, 5-6 added, old 5 renumbered 7, 8 added')
    # art. 173: art. 12
    body = [p['text'] for p in amending(2012, 82, 173)]
    ins = ' '.join(body)
    need(ins, '1. Ο τίτλος του άρθρου 12 του ν. 3471/2006 αντικαθίσταται ως εξής: «Ασφάλεια Επεξεργασίας».',
         'ν. 4070/2012 art. 173')
    need(ins, '2. Μετά την παρ. 2 του άρθρου 12 του ν. 3471/2006 προστίθενται παράγραφοι 3 έως 10, ως εξής:',
         'ν. 4070/2012 art. 173')
    need(ins, '3. Η παρ. 3 του άρθρου 12 του ν. 3471/2006 αναριθμείται ως παράγραφος 11.', 'ν. 4070/2012 art. 173')
    qs = [q for q in quotes(body) if q != ['Ασφάλεια Επεξεργασίας']]
    (q310,) = qs
    a = u['art-012']
    ia = next(i for i, l in enumerate(a) if ART.match(l))
    if a[ia + 1] != 'Ασφάλεια':
        raise SystemExit(f'art. 12: title is {a[ia + 1]!r}')
    a[ia + 1] = 'Ασφάλεια Επεξεργασίας'
    i3, j3 = par_range(a, '3', 'art. 12')
    if j3 != len(a):
        raise SystemExit('art. 12: par. 3 is not the last')
    old3 = a[i3:j3]
    old3[0] = re.sub(r'^3\. ', '11. ', old3[0])
    a[i3:] = q310 + old3
    present(u, 'art-012', q310, 'ν. 4070/2012 art. 173')
    LOG.append('ν. 4070/2012 art. 173: art. 12 title replaced, pars. 3-10 added, old 3 renumbered 11')
    return u


def as_units(u: dict) -> dict:
    out = {}
    for k, lines in u.items():
        label = next(l for l in lines if ART.match(l))
        out[k] = {'label': label, 'kind': 'art', 'text': '\n'.join(lines) + '\n'}
    return dict(sorted(out.items()))


def changed(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def main() -> None:
    laws, pub = {}, {}
    for key, (y, n) in ISSUES.items():
        num, title = law_number_title(y, n)
        if key != f'n-{num}-{y}':
            raise SystemExit(f'Α΄ {n}/{y} is ν. {num}/{y}, not {key}')
        pub[key] = masthead(y, n)
        laws[key] = {'label': f'ν. {num}/{y}', 'kind': 'law', 'title': title, 'enacted': signed(y, n),
                     'published': pub[key], 'url': FL.fek_url(y, n), 'temporary_until': None, 'restores': None,
                     'note': None}
    t06 = flat(2006, 133)
    need(t06, 'Η ισχύς των διατάξεων του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
              'Κυβερνήσεως, εκτός των διατάξεων του Πρώτου Κεφαλαίου, που αρχίζει μετά την πάροδο ενός μηνός από τη '
              'δημοσίευσή του', 'ν. 3471/2006 art. 31')
    for key, phrase in (('n-3783-2009', 'Ο παρών νόμος ισχύει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, '
                                        'εκτός από το άρθρο 14'),
                        ('n-3917-2011', 'Η ισχύς του παρόντος άρθρου αρχίζει την πρώτη του επόμενου μήνα μετά την '
                                        'πάροδο εξαμήνου από τη δημοσίευση του παρόντος νόμου.'),
                        ('n-4070-2012', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                                        'Κυβερνήσεως, εκτός αν άλλως ορίζεται σε επί μέρους διατάξεις του.')):
        y, n = ISSUES[key]
        need(re.sub(r'\s+', ' ', re.sub(r'[-−]\s*\n(?=[α-ωά-ώ])', '', raw_text(y, n))), phrase, key)
    if pub['n-3471-2006'] != '2006-06-28' or pub['n-3917-2011'] != '2011-02-21':
        raise SystemExit(f'unexpected publication days {pub}')
    u0 = enacted()
    u_pre = {k: v for k, v in u0.items() if int(k[4:]) >= 18}
    u1 = am_3783(u0)
    u2 = am_3917(u1)
    u3 = am_4070(u2)
    steps = [('2006-06-28', u_pre, 'n-3471-2006', (2006, 133)), ('2006-07-28', u0, 'n-3471-2006', (2006, 133)),
             (pub['n-3783-2009'], u1, 'n-3783-2009', (2009, 136)), ('2011-09-01', u2, 'n-3917-2011', (2011, 22)),
             (pub['n-4070-2012'], u3, 'n-4070-2012', (2012, 82))]
    notes = {
        '2006-06-28': 'ν. 3471/2006 as published in ΦΕΚ Α΄ 133/28.6.2006: arts. 18-31, in force on publication (art. 31). '
                      'Chapter One (arts. 1-17) follows a month later.',
        '2006-07-28': 'Chapter One of ν. 3471/2006 (arts. 1-17) takes effect one month after publication (art. 31).',
        pub['n-3783-2009']: 'ν. 3783/2009 art. 8 (ΦΕΚ Α΄ 136/7.8.2009) replaces art. 5 par. 7; in force on publication '
                            '(art. 15).',
        '2011-09-01': 'ν. 3917/2011 art. 16 (ΦΕΚ Α΄ 22/21.2.2011) amends art. 11 pars. 1 and 2, in force on the first day '
                      'of the month after six months from publication (art. 16 par. 3).',
        pub['n-4070-2012']: 'ν. 4070/2012 arts. 168-173 (ΦΕΚ Α΄ 82/10.4.2012, transposing Directive 2009/136/EC) amend '
                            'arts. 2, 3, 4, 5, 6, 11 and 12; in force on publication (art. 188).',
    }
    versions, prev = [], None
    for day, u, law, (y, n) in steps:
        units = as_units(u)
        v = {'from': day, 'source_url': FL.fek_url(y, n), 'sha256': N.sha(FL.fek_url(y, n))}
        if prev is None:
            v['units'] = units
        else:
            ch = changed(prev, units)
            v['changes'] = {k: units.get(k) for k in ch}
            v['credits'] = {k: [law] for k in ch}
        v['note'] = notes[day]
        versions.append(v)
        prev = units
    sources = [{
        'name': 'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: issues for ν. 3471/2006 and its amending laws',
        'url': 'https://ia37rg02wpsa01.blob.core.windows.net/fek/', 'retrieved': '2026-10-30', 'requests': 10,
        'licence': 'Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). '
                   'Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).',
        'notes': 'Series Α΄ issues 133/2006, 136/2009, 22/2011 and 82/2012, each with a text layer; issue number, date '
                 'and law number checked against each issue. Also read, and found not to amend ν. 3471/2006 (they only '
                 'cite it): Α΄ 152/2007, 34/2015, 137/2019, 184/2020, 202/2024, 195/2024 and 175/2025.'},
        {'name': 'Αρχή Προστασίας Δεδομένων Προσωπικού Χαρακτήρα: ν. 3471/2006 (PDF with the amendments and editorial '
                 'footnotes, uploaded 2019-09)',
         'url': 'https://www.dpa.gr/sites/default/files/2019-09/%CE%9D3471_06.PDF', 'retrieved': '2026-10-30',
         'requests': 1,
         'licence': 'Hellenic Data Protection Authority publication; used only to check the history, no text copied.',
         'notes': 'Linked from https://www.dpa.gr/el/enimerwtiko/nomothesia/proswpikon_dedomenon. Its footnotes name '
                  'ν. 3917/2011 and ν. 4070/2012 arts. 168-173.'}]
    decisions = [
        'ν. 3471/2006 is built from the Government Gazette alone: the act as published (ΦΕΚ Α΄ 133/2006) and, for each '
        'amendment, the amending law\'s own issue. Greece publishes no official consolidated text.',
        'Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue 2006-2026 in legalize-gr '
        '(commit 36cb88a374cd) for an article naming a provision of the law outside a quotation with an amending verb '
        'or heading; legalize-gr\'s `amended_by` field (copied from the official search.et.gr index), which lists Α΄ '
        '34/2015 and 22/2011; and the official index\'s timeline for the issue, which also lists Α΄ 136/2009, '
        '152/2007, 184/2020, 195/2024, 202/2024 and 175/2025. Every candidate was read in its own issue: ν. 3783/2009, '
        'ν. 3917/2011 and ν. 4070/2012 amend the law; the others only cite it (Α΄ 34/2015 restates provisions of '
        'ν. 2472/1997 as amended by ν. 3471/2006).',
        'Art. 31 of ν. 3471/2006 puts the law in force on publication (28.6.2006) except Chapter One, one month later: '
        'arts. 1-17 are added on 28.7.2006. Arts. 18-30 amend ν. 2472/1997 and are kept as enacted.',
        'Units are articles (art-NNN): the chapter headings that open an article, "Άρθρο N", its title on one line (the '
        '2006 issue sets titles in plain type, centred), then one paragraph or item per line.',
        'ν. 4070/2012 art. 168 numbers the definitions of art. 2 anew: item 6 is struck and 7-11 become 6-10, the new '
        'item 8 (the old 9) gains a sentence, and item 11 is added. Arts. 5 and 6 are restated whole (art. 171); their '
        'titles stay.',
        'The 2012 issue was read with full-width bands, so its two columns come out in page order; one overprinted '
        'fragment ("ξης", a stray line) is dropped. Each quoted text is checked to be present in the new version.',
    ]
    decisions.append('Check against the Data Protection Authority text of ν. 3471/2006 (PDF, 2019): compared word by '
                     'word with the latest version (10.4.2012), every article agrees except for the Authority footnote '
                     'numbers and notes, its dropping of the second accent the Gazette prints in phrases such '
                     'as «συγκατάθεσή του», art. 11 par. 1, where it still prints the words «με ή» that ν. 3917/2011 '
                     'struck (with a footnote saying so), and four one-word readings where the Gazette is followed '
                     '(art. 13 «παρόχων», art. 16 «οff-line», art. 25 «1 ι΄», art. 27 «του»).')
    decisions += [f'Parse log: {l}' for l in LOG]
    part = {'laws': laws, 'sources': sources, 'acts': [{
        'slug': 'nomos-3471-2006', 'short': 'ν. 3471/2006', 'title': laws['n-3471-2006']['title'],
        'url': FL.fek_url(2006, 133), 'first_law': 'n-3471-2006', 'earlier_laws': [], 'versions': versions}],
        'applies': [], 'decisions': decisions,
        'ai_use': ['ν. 3471/2006 part: none. No model wrote or altered legal text; a model (Claude) wrote '
                   'parse_n3471.py, which reads every word from the Gazette PDFs.']}
    tmp = OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(part, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    os.replace(tmp, OUT)
    print('\n'.join(LOG))
    print(f'wrote {OUT} ({len(versions)} versions, {len(versions[1]["changes"]) + len(versions[0]["units"])} articles)')


if __name__ == '__main__':
    main()
