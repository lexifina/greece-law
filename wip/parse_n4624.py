"""Build the ν. 4624/2019 part of the Greece corpus (corpus.d/20-n4624.json) from the cache of fetch_n4624.py.

ν. 4624/2019 (personal data protection; ΦΕΚ Α΄ 137/29.8.2019) as enacted, then every amendment, each applied from
the amending law's own ΦΕΚ text:

    ν. 4829/2021 (Α΄ 166/10.9.2021), art. 20 par. 1 περ. λβ   repeals art. 18 par. 6
    ν. 5002/2022 (Α΄ 228/9.12.2022), arts. 34-45              arts. 6, 43, 44, 45 (Τμήμα ΙΙ title), 45Α, 46, 47,
                                                              49, 52, 53, 58, 71, 73, 84, 84Α
    ν. 5197/2025 (Α΄ 76/16.5.2025), art. 56                   art. 84Α par. 7
    ν. 5221/2025 (Α΄ 133/28.7.2025), art. 154                 art. 18

Each amending provision is located in its issue by its own article number and heading; the quoted «…» text it
enacts is placed into the act, and the parse stops unless (a) the instruction's target is found exactly once, (b) for
the instructions that describe a word change and then restate the result ("… και … διαμορφώνεται ως εξής"), the
described change applied to the old text gives the restated text word for word, and (c) every quoted text then appears
word for word in the resulting version. The Hellenic Data Protection Authority's consolidated text is used to check
the versions (see check_dpa); legalize-gr's file is compared and the result reported, but its text is not used.

    python -X utf8 scripts/greece-law/parse_n4624.py [--dump DIR]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import parse as P  # noqa: E402  (the Constitution's text helpers: norm_line, tidy_para, join_lines, is_junk)
import fetch_n4624 as F  # noqa: E402

CACHE = F.CACHE
OUT = HERE / 'corpus.d' / '20-n4624.json'


def cpath(url: str) -> Path:
    return CACHE / hashlib.sha256(url.encode('utf-8')).hexdigest()


def sha(url: str) -> str:
    return hashlib.sha256(cpath(url).read_bytes()).hexdigest()


# ---------------------------------------------------------------- PDF to lines and paragraphs

def read_lines(path: Path) -> list[dict]:
    """Body lines in reading order (per page, left column then right column), with bold and x position."""
    out = []
    doc = fitz.open(path)
    sizes: dict[float, int] = {}
    for page in doc:
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        k = round(s['size'] * 2) / 2
                        sizes[k] = sizes.get(k, 0) + len(s['text'])
    body = max(sizes, key=lambda k: (sizes[k], -k))
    for pno, page in enumerate(doc):
        lines = []
        for b in page.get_text('dict')['blocks']:
            if b['type'] != 0:
                continue
            for l in b['lines']:
                spans = [s for s in l['spans'] if s['text'].strip()]
                if not spans:
                    continue
                t = P.norm_line(''.join(s['text'] for s in l['spans']))
                size = max(s['size'] for s in spans)
                x0, y0, x1, _ = l['bbox']
                if P.is_junk(t) or size > body + 1.5 or size < body - 0.6 or y0 < 75:
                    continue
                bold_chars = sum(len(s['text']) for s in spans if s['flags'] & 16)
                lines.append({'x0': x0, 'y0': y0, 'x1': x1, 't': t, 'page': pno,
                              'bold': bold_chars * 2 > sum(len(s['text']) for s in spans)})
        if not lines:
            continue
        lo = min(l['x0'] for l in lines)
        hi = max(l['x1'] for l in lines)
        mid = (lo + hi) / 2
        left = [l for l in lines if l['x1'] <= mid + 6]
        right = [l for l in lines if l['x0'] >= mid - 6]
        for col in (left, right):
            if not col:
                continue
            edge = min(l['x0'] for l in col)
            for l in sorted(col, key=lambda l: l['y0']):
                l['indent'] = l['x0'] - edge
                out.append(l)
    return out


ART = re.compile(r'^(«?)\s*Άρθρο\s+(\d+)\s*([Α-Ω])?$')
STRUCT = re.compile(r'^«?(ΜΕΡΟΣ|ΤΜΗΜΑ|ΚΕΦΑΛΑΙΟ)\b')
BODY_START = re.compile(r'^«?(\d+[Α-Ω]?\.\s|[α-ω]{1,3}[)’.]\s|\([α-ω]{1,3}\)\s|\[)')


def paragraphs(lines: list[dict]) -> list[dict]:
    """Paragraphs {kind: art|title|struct|stitle|p, text}. An article heading is followed by its title: the bold
    lines after it (the act as published) or, inside a quotation, the lines set at the heading's own left edge."""
    paras: list[dict] = []
    cur: list[str] = []
    kind = None
    mode = None
    head = None

    def flush():
        nonlocal cur, kind
        if cur:
            paras.append({'kind': kind, 'text': P.tidy_para(P.join_lines(cur))})
        cur, kind = [], None

    for l in lines:
        t = l['t']
        if ART.match(t):
            flush()
            paras.append({'kind': 'art', 'text': t})
            mode, head = 'title', l
            continue
        if STRUCT.match(t):
            flush()
            paras.append({'kind': 'struct', 'text': P.tidy_para(t)})
            mode, head = 'stitle', l
            continue
        if mode == 'title':
            if head['bold'] and l['bold'] or (not head['bold'] and abs(l['x0'] - head['x0']) < 2.5
                                               and not BODY_START.match(t)):
                if kind != 'title':
                    flush()
                    kind = 'title'
                cur.append(t)
                continue
            mode = None
        if mode == 'stitle':
            if kind != 'stitle':
                flush()
                kind = 'stitle'
            cur.append(t)
            if l['bold'] or head['bold']:
                continue
            mode = None
            continue
        if l['indent'] > 4 or not cur or kind in ('title', 'stitle'):
            flush()
            cur, kind = [t], 'p'
        else:
            cur.append(t)
    flush()
    return paras


def fek_paras(year: int, num: int) -> list[dict]:
    return paragraphs(read_lines(cpath(F.fek_url(year, num))))


def masthead(year: int, num: int) -> str:
    """The issue number and date from page 1, checked against the expected issue."""
    t = fitz.open(cpath(F.fek_url(year, num)))[0].get_text()
    m = re.search(r'\n(\d{1,2}) (\w+) (\d{4})\s*\nΤΕΥΧΟΣ\s+ΠΡΩΤΟ\s*\nΑρ\. Φύλλου (\d+)\n', t)
    if not m or int(m.group(4)) != num or int(m.group(3)) != year:
        raise SystemExit(f'masthead of Α΄ {num}/{year} not as expected')
    months = ['Ιανουαρίου', 'Φεβρουαρίου', 'Μαρτίου', 'Απριλίου', 'Μαΐου', 'Ιουνίου', 'Ιουλίου', 'Αυγούστου',
              'Σεπτεμβρίου', 'Οκτωβρίου', 'Νοεμβρίου', 'Δεκεμβρίου']
    return f'{year}-{months.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}'


def law_number(year: int, num: int) -> int:
    first = fek_paras(year, num)[0]['text']
    m = re.match(r'^ΝΟΜΟΣ ΥΠ’ ΑΡΙΘΜ\. (\d+)$', first)
    if not m:
        raise SystemExit(f'Α΄ {num}/{year}: no law number on its first line: {first}')
    return int(m.group(1))


# ---------------------------------------------------------------- the act as enacted

def art_key(num: str, suffix: str | None) -> str:
    k = f'art-{int(num):03d}'
    if suffix:
        k += '-' + {'Α': 'a', 'Β': 'b', 'Γ': 'c', 'Δ': 'd'}[suffix]
    return k


ROMAN = str.maketrans({'Ι': 'I', 'Χ': 'X'})


def heading_line(p: dict) -> str:
    t = p['text']
    if p['kind'] == 'struct':
        m = re.match(r'^(ΤΜΗΜΑ) ([ΙVΧIX]+)$', t)
        if m:  # the Gazette sets these numerals with Greek Ι beside Latin V; write them in Latin
            t = f'{m.group(1)} {m.group(2).translate(ROMAN)}'
    return t


def article_lines(paras: list[dict]) -> dict[str, list[str]]:
    """{key: lines} for a run of paragraphs holding whole articles; headings go with the article they open."""
    units: dict[str, list[str]] = {}
    pending: list[str] = []
    key = None
    for p in paras:
        if p['kind'] in ('struct', 'stitle'):
            pending.append(heading_line(p))
            continue
        if p['kind'] == 'art':
            m = ART.match(p['text'])
            key = art_key(m.group(2), m.group(3))
            if key in units:
                raise SystemExit(f'{key} twice')
            units[key] = pending + [f'Άρθρο {int(m.group(2))}{m.group(3) or ""}']
            pending = []
            continue
        if key is None:
            raise SystemExit(f'text before the first article: {p["text"][:60]}')
        units[key].append(p['text'])
    if pending:
        raise SystemExit(f'headings after the last article: {pending}')
    return units


def enacted() -> dict[str, list[str]]:
    paras = fek_paras(2019, 137)
    i0 = next(i for i, p in enumerate(paras) if p['kind'] == 'struct')
    i1 = next(i for i, p in enumerate(paras) if p['text'].startswith('Παραγγέλλομε τη δημοσίευση'))
    units = article_lines(paras[i0:i1])
    want = [art_key(str(n), None) for n in range(1, 88)]
    if list(units) != want:
        raise SystemExit(f'Α΄ 137/2019: articles are not 1-87 in order: {list(units)[:5]}…')
    return units


# ---------------------------------------------------------------- amending provisions

def amending_article(year: int, num: int, art: str, must: str) -> list[dict]:
    """The paragraphs of article `art` of the law in Α΄ num/year (its own article, not a quoted one); its title must
    contain `must` (the provision of ν. 4624/2019 it names)."""
    paras = fek_paras(year, num)
    hits = [i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == f'Άρθρο {art}']
    if len(hits) != 1:
        raise SystemExit(f'Α΄ {num}/{year}: article {art} found {len(hits)} times')
    i = hits[0]
    j = i + 1
    while j < len(paras) and not (paras[j]['kind'] == 'art' and not paras[j]['text'].startswith('«')
                                  or paras[j]['kind'] == 'struct' and not paras[j]['text'].startswith('«')):
        j += 1
    body = paras[i + 1:j]
    title = body[0]['text'] if body and body[0]['kind'] == 'title' else ''
    if must not in title:
        raise SystemExit(f'Α΄ {num}/{year} art. {art}: title {title!r} does not name {must!r}')
    return body[1:]


def quotes(body: list[dict]) -> list[list[dict]]:
    """The «…» quotations of an amending article that run over whole paragraphs, outer marks removed."""
    out: list[list[dict]] = []
    cur: list[dict] | None = None
    depth = 0
    for p in body:
        t = p['text']
        if cur is None:
            if not t.startswith('«'):
                continue
            cur = []
            depth = 0
        depth += t.count('«') - t.count('»')
        cur.append(dict(p))
        if depth == 0:
            cur[0]['text'] = cur[0]['text'][1:]
            last = cur[-1]['text']
            m = re.search(r'»\.?$', last)
            if not m:
                raise SystemExit(f'quotation does not end in »: {last[-40:]}')
            cur[-1]['text'] = last[:m.start()]
            if cur[0]['kind'] == 'art' or ART.match('«' + cur[0]['text']):
                cur[0]['kind'] = 'art'
            out.append(cur)
            cur = None
    if cur is not None:
        raise SystemExit('unclosed quotation')
    return out


def instruction(body: list[dict]) -> str:
    """The amending article's own words before its first quotation."""
    out = []
    for p in body:
        if p['text'].startswith('«'):
            break
        out.append(p['text'])
    return ' '.join(out)


def quoted_article(q: list[dict], num: str) -> list[str]:
    if q[0]['kind'] != 'art' or q[0]['text'].lstrip('«') != f'Άρθρο {num}':
        raise SystemExit(f'quotation does not open with Άρθρο {num}: {q[0]["text"][:40]}')
    return [f'Άρθρο {num}'] + [p['text'] for p in q[1:]]


# ---------------------------------------------------------------- editing a unit

def head_split(lines: list[str]) -> tuple[list[str], list[str]]:
    """(headings before the article line, the article from its 'Άρθρο N' line on)."""
    i = next(i for i, l in enumerate(lines) if re.match(r'^Άρθρο \d+[Α-Ω]?$', l))
    return lines[:i], lines[i:]


def find_one(lines: list[str], start: str, what: str) -> int:
    hits = [i for i, l in enumerate(lines) if l.startswith(start)]
    if len(hits) != 1:
        raise SystemExit(f'{what}: {start!r} found {len(hits)} times')
    return hits[0]


def replace_lines(lines: list[str], start: str, stop: str | None, new: list[str], what: str) -> list[str]:
    """Replace the run of lines from the one starting with `start` up to (not including) the next line matching the
    regex `stop` (or only that line when stop is None)."""
    i = find_one(lines, start, what)
    j = i + 1
    if stop:
        while j < len(lines) and not re.match(stop, lines[j]):
            j += 1
    return lines[:i] + new + lines[j:]


def sq(s: str) -> str:
    """Words only, for comparing texts typeset differently (quotes, dashes, spacing, accents on capitals kept)."""
    s = P.norm_line(s).replace('`', '’')
    return re.sub(r'[\s\-–—«»"“”’\'.,·;:()\[\]]', '', s).lower()


def same_words(a: str, b: str, what: str) -> None:
    if sq(a) != sq(b):
        x, y = sq(a), sq(b)
        i = next((i for i in range(min(len(x), len(y))) if x[i] != y[i]), min(len(x), len(y)))
        raise SystemExit(f'{what}: texts differ at {i}: {x[max(0, i - 40):i + 40]!r} vs {y[max(0, i - 40):i + 40]!r}')


RESTATED: list[str] = []


def restated(expected: str, new: str, what: str, limit: int = 3) -> None:
    """An instruction that describes a change and then restates the result: the described change applied to the old
    text must give the restated text, except for at most `limit` small differences of wording the restatement makes
    on its own. Those are recorded (RESTATED) for the decisions; more than `limit` stops the parse."""
    import difflib
    a = [w for w in (sq(x) for x in expected.split()) if w]
    b = [w for w in (sq(x) for x in new.split()) if w]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    diffs = [(' '.join(a[i1:i2]), ' '.join(b[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal']
    if len(diffs) > limit:
        raise SystemExit(f'{what}: {len(diffs)} differences beyond the described change: {diffs[:6]}')
    for x, y in diffs:
        RESTATED.append(f'{what}: the restated text reads «{y}» where the old text, as the instruction describes the '
                        f'change, reads «{x}»')


def present(units: dict, key: str, quoted: list[str], what: str) -> None:
    text = '\n'.join(units[key])
    for q in quoted:
        if q not in text:
            raise SystemExit(f'{what}: quoted text not in {key}: {q[:60]}')


def words_replaced(text: str, pairs: list[tuple[str, str]]) -> str:
    """Every whole-word occurrence of each old word replaced by the new one."""
    for a, b in pairs:
        if not re.search(rf'(?<!\w){a}(?!\w)', text):
            raise SystemExit(f'{a!r} not in the old text')
        text = re.sub(rf'(?<!\w){a}(?!\w)', b, text)
    return text


def sentences(par: str) -> list[str]:
    """A paragraph's εδάφια: split after a full stop followed by a space and a capital."""
    m = re.match(r'^\d+[Α-Ω]?\. ', par)
    num = m.group(0) if m else ''
    out = re.split(r'(?<=\.) (?=[Α-ΩΆ-Ώ])', par[len(num):])
    out[0] = num + out[0]
    return out


def need(text: str, phrase: str, what: str) -> None:
    if phrase not in text:
        raise SystemExit(f'{what}: expected wording not found: {phrase!r}')


# ---------------------------------------------------------------- the amendments, one function per amending law

LOG: list[str] = []


def am_4829(u: dict) -> dict:
    """ν. 4829/2021 art. 20 par. 1 περ. λβ: «Από την έναρξη ισχύος του παρόντος καταργούνται: … λβ. η παρ. 6 του
    άρθρου 18 του ν. 4624/2019 (Α’ 137)…»."""
    body = amending_article(2021, 166, '20', '')
    texts = [p['text'] for p in body]
    if texts[0] != '1. Από την έναρξη ισχύος του παρόντος καταργούνται:':
        raise SystemExit(f'ν. 4829/2021 art. 20: par. 1 opens {texts[0]!r}')
    i_par2 = next(i for i, t in enumerate(texts) if t.startswith('2. '))
    hit = [t for t in texts[:i_par2] if t.startswith('λβ. η παρ. 6 του άρθρου 18 του ν. 4624/2019 (Α’ 137)')]
    if len(hit) != 1:
        raise SystemExit('ν. 4829/2021 art. 20 par. 1: item λβ not found once')
    u = dict(u)
    u['art-018'] = replace_lines(u['art-018'], '6. ', None, [], 'ν. 4829/2021: art. 18 par. 6')
    LOG.append('ν. 4829/2021 art. 20 par. 1 λβ: art. 18 par. 6 removed')
    return u


def am_5002(u: dict) -> dict:
    u = dict(u)
    Y, N = 2022, 228
    PAR = r'^\d+[Α-Ω]?\. '
    PT = r'^[α-ω]{1,3}\) '

    def one(art, must, n_quotes, wording):
        body = amending_article(Y, N, art, must)
        qs = quotes(body)
        if len(qs) != n_quotes:
            raise SystemExit(f'ν. 5002/2022 art. {art}: {len(qs)} quotations, expected {n_quotes}')
        for w in wording:
            need(instruction(body) if art != '36' else ' '.join(p['text'] for p in body), w, f'ν. 5002/2022 art. {art}')
        return [[p['text'] for p in q] for q in qs], qs

    def whole(key, num, q, what):
        head, _ = head_split(u[key]) if key in u else ([], [])
        new = quoted_article(q, num)
        u[key] = head + new
        present(u, key, new, what)

    # art. 34: art. 6 par. 5 replaced
    (q,), _ = one('34', 'άρθρου 6 ν. 4624/2019', 1,
                  ['Η παρ. 5 του άρθρου 6 του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    if not (len(q) == 1 and q[0].startswith('5. ')):
        raise SystemExit('ν. 5002/2022 art. 34: quotation is not one par. 5')
    u['art-006'] = replace_lines(u['art-006'], '5. ', PAR, q, 'art. 6 par. 5')
    present(u, 'art-006', q, 'ν. 5002/2022 art. 34')
    # art. 35: art. 43 replaced
    _, (qa,) = one('35', 'άρθρου 43 ν. 4624/2019', 1, ['Το άρθρο 43 του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    whole('art-043', '43', qa, 'ν. 5002/2022 art. 35')
    # art. 36: arts. 44, 53, 58 and 71
    texts, qs = one('36', 'άρθρων 44, 53, 58 και 71 ν. 4624/2019', 7, [
        '1. Διαγράφεται ο αριθμός 1 προ της μόνης παραγράφου του άρθρου 44 του ν. 4624/2019 (Α’ 137).',
        '2. Η περ. ιδ) του άρθρου 44 του ν. 4624/2019 αντικαθίσταται ως εξής:',
        '3. Η περ. ιε) του άρθρου 44 του ν. 4624/2019 αντικαθίσταται ως εξής:',
        '4. Η περ. ιζ) του άρθρου 44 του ν. 4624/2019, περί ορισμού της «συγκατάθεσης» καταργείται.',
        'η λέξη «δημόσια» αντικαθίσταται με τη λέξη «αρμόδια» και η περ. ζ) διαμορφώνεται ως εξής:',
        'οι λέξεις «δημόσια» και «δημόσιες» αντικαθίστανται, αντιστοίχως, με τις λέξεις «αρμόδια» και «αρμόδιες» και η περ. θ) διαμορφώνεται ως εξής:',
        'η λέξη «δημόσιας» αντικαθίσταται από τη λέξη «αρμόδιας» και το άρθρο 53 διαμορφώνεται ως εξής:',
        'η λέξη «δημόσιες» αντικαθίσταται από τη λέξη «αρμόδιες» και η παρ. 1 διαμορφώνεται ως εξής:',
        'η λέξη «δημόσια» αντικαθίσταται από τη λέξη «αρμόδια» και το άρθρο 71 διαμορφώνεται ως εξής:'])
    a44 = u['art-044']
    i = find_one(a44, '1. Για τους σκοπούς του παρόντος Κεφαλαίου', 'art. 44 par. 1')
    if any(re.match(r'^2\. ', l) for l in a44):
        raise SystemExit('art. 44 has a par. 2; "the only paragraph" does not hold')
    a44 = a44[:i] + [a44[i][3:]] + a44[i + 1:]
    q_id, q_ie, q_z, q_th = texts[0], texts[1], texts[2], texts[3]
    if not (q_id[0].startswith('ιδ) ') and q_ie[0].startswith('ιε) ') and q_z[0].startswith('ζ) ') and q_th[0].startswith('θ) ')):
        raise SystemExit('ν. 5002/2022 art. 36: quotations not in the order ιδ, ιε, ζ, θ')
    a44 = replace_lines(a44, 'ιδ) ', PT, q_id, 'art. 44 ιδ')
    a44 = replace_lines(a44, 'ιε) ', PT, q_ie, 'art. 44 ιε')
    a44 = replace_lines(a44, 'ιζ) ', PT, [], 'art. 44 ιζ')
    old_z = a44[find_one(a44, 'ζ) ', 'art. 44 ζ')]
    restated(words_replaced(old_z, [('δημόσια', 'αρμόδια')]), q_z[0], 'art. 44 ζ: word change')
    a44 = replace_lines(a44, 'ζ) ', PT, q_z, 'art. 44 ζ')
    old_th = a44[find_one(a44, 'θ) ', 'art. 44 θ')]
    restated(words_replaced(old_th, [('δημόσια', 'αρμόδια'), ('δημόσιες', 'αρμόδιες')]), q_th[0], 'art. 44 θ: word change')
    a44 = replace_lines(a44, 'θ) ', PT, q_th, 'art. 44 θ')
    u['art-044'] = a44
    for q in (q_id, q_ie, q_z, q_th):
        present(u, 'art-044', q, 'ν. 5002/2022 art. 36')
    # 36(5)(γ): art. 53 restated
    head, old = head_split(u['art-053'])
    new53 = quoted_article(qs[4], '53')
    restated(words_replaced('\n'.join(old), [('δημόσιας', 'αρμόδιας')]), '\n'.join(new53), 'art. 53: word change')
    whole('art-053', '53', qs[4], 'ν. 5002/2022 art. 36(5)(γ)')
    # 36(5)(δ): art. 58 par. 1 restated
    q58 = texts[5]
    old58 = u['art-058'][find_one(u['art-058'], '1. ', 'art. 58 par. 1')]
    restated(words_replaced(old58, [('δημόσιες', 'αρμόδιες')]), '\n'.join(q58), 'art. 58 par. 1: word change')
    u['art-058'] = replace_lines(u['art-058'], '1. ', PAR, q58, 'art. 58 par. 1')
    present(u, 'art-058', q58, 'ν. 5002/2022 art. 36(5)(δ)')
    # 36(5)(ε): art. 71 restated
    head, old = head_split(u['art-071'])
    new71 = quoted_article(qs[6], '71')
    restated(words_replaced('\n'.join(old), [('δημόσια', 'αρμόδια')]), '\n'.join(new71), 'art. 71: word change')
    whole('art-071', '71', qs[6], 'ν. 5002/2022 art. 36(5)(ε)')
    # art. 37: the title of Τμήμα ΙΙ of Κεφάλαιο Δ’ (it opens art. 46)
    (q,), _ = one('37', 'Τμήματος ΙΙ', 1,
                  ['Ο τίτλος του Τμήματος ΙΙ του Κεφαλαίου Δ’ του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    a46 = u['art-046']
    i = a46.index('ΤΜΗΜΑ II')
    if a46[i + 1] != 'ΝΟΜΙΚΕΣ ΒΑΣΕΙΣ ΤΗΣ ΕΠΕΞΕΡΓΑΣΙΑΣ':
        raise SystemExit(f'Τμήμα ΙΙ title is {a46[i + 1]!r}')
    u['art-046'] = a46[:i + 1] + q + a46[i + 2:]
    # art. 38: art. 45Α added after art. 45
    _, (qa,) = one('38', 'άρθρου 45Α', 1, ['Μετά το άρθρο 45 του ν. 4624/2019 (Α’ 137) προστίθεται άρθρο 45Α ως εξής:'])
    if 'art-045-a' in u:
        raise SystemExit('art. 45Α exists already')
    whole('art-045-a', '45Α', qa, 'ν. 5002/2022 art. 38')
    # art. 39: art. 46 replaced (its headings stay)
    _, (qa,) = one('39', 'άρθρου 46 ν. 4624/2019', 1, ['Το άρθρο 46 του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    whole('art-046', '46', qa, 'ν. 5002/2022 art. 39')
    # art. 40: art. 47, second sentence repealed, article restated
    _, (qa,) = one('40', 'άρθρου 47 ν. 4624/2019', 1, [
        'Το δεύτερο εδάφιο του άρθρου 47 του ν. 4624/2019 (Α’ 137) καταργείται και το άρθρο 47 διαμορφώνεται ως εξής:'])
    head, old = head_split(u['art-047'])
    new47 = quoted_article(qa, '47')
    if len(old) != 3:
        raise SystemExit('art. 47 is not one paragraph')
    s = sentences(old[2])
    if len(s) < 2:
        raise SystemExit('art. 47 has no second sentence')
    restated('\n'.join(old[:2] + [' '.join(s[:1] + s[2:])]), '\n'.join(new47), 'ν. 5002/2022 art. 40, art. 47', limit=6)
    whole('art-047', '47', qa, 'ν. 5002/2022 art. 40')
    # art. 41: art. 49 replaced
    _, (qa,) = one('41', 'άρθρου 49 ν. 4624/2019', 1, ['Το άρθρο 49 του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    whole('art-049', '49', qa, 'ν. 5002/2022 art. 41')
    # art. 42: art. 52 replaced (the instruction misprints the law as "ν. 4264/2019"; its heading names 4624)
    _, (qa,) = one('42', 'άρθρου 52 ν. 4624/2019', 1, ['Το άρθρο 52 του ν. 4264/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    whole('art-052', '52', qa, 'ν. 5002/2022 art. 42')
    # art. 43: art. 73 replaced
    _, (qa,) = one('43', 'άρθρου 73 ν. 4624/2019', 1, ['Το άρθρο 73 του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    whole('art-073', '73', qa, 'ν. 5002/2022 art. 43')
    # art. 44: art. 84 replaced
    _, (qa,) = one('44', 'άρθρου 84 ν. 4624/2019', 1, ['Το άρθρο 84 του ν. 4624/2019 (Α’ 137) αντικαθίσταται ως εξής:'])
    whole('art-084', '84', qa, 'ν. 5002/2022 art. 44')
    # art. 45: art. 84Α added
    _, (qa,) = one('45', 'άρθρου 84Α', 1, ['Στον ν. 4624/2019 (Α’ 137) προστίθεται άρθρο 84Α ως εξής:'])
    if 'art-084-a' in u:
        raise SystemExit('art. 84Α exists already')
    whole('art-084-a', '84Α', qa, 'ν. 5002/2022 art. 45')
    LOG.append('ν. 5002/2022 arts. 34-45 applied: arts. 6(5), 43, 44 (par. number, ζ, θ, ιδ, ιε, ιζ), Τμήμα ΙΙ '
               'title, 45Α, 46, 47, 49, 52, 53, 58(1), 71, 73, 84, 84Α; every word-change instruction checked')
    return u


def am_5197(u: dict) -> dict:
    body = amending_article(2025, 76, '56', 'παρ. 7 άρθρου 84Α ν. 4624/2019')
    need(instruction(body), 'Στην παρ. 7 του άρθρου 84Α του ν. 4624/2019 (Α’ 137), περί δημοσιοποίησης προσωπικών '
         'δεδομένων από την εισαγγελική αρχή, προστίθεται τρίτο εδάφιο και η παρ. 7 διαμορφώνεται ως εξής:', 'ν. 5197/2025 art. 56')
    (q,) = [[p['text'] for p in x] for x in quotes(body)]
    if not (len(q) == 1 and q[0].startswith('7. ')):
        raise SystemExit('ν. 5197/2025 art. 56: quotation is not one par. 7')
    u = dict(u)
    old = u['art-084-a'][find_one(u['art-084-a'], '7. ', 'art. 84Α par. 7')]
    new_s = sentences(q[0])
    if len(new_s) != 3 or len(sentences(old)) != 2:
        raise SystemExit('art. 84Α par. 7: expected two sentences before and three after')
    restated(old, ' '.join(new_s[:2]), 'ν. 5197/2025 art. 56, art. 84Α par. 7 sentences 1-2')
    u['art-084-a'] = replace_lines(u['art-084-a'], '7. ', r'^\d+\. ', q, 'art. 84Α par. 7')
    present(u, 'art-084-a', q, 'ν. 5197/2025 art. 56')
    LOG.append('ν. 5197/2025 art. 56: art. 84Α par. 7 gains a third sentence; the first two checked unchanged')
    return u


def am_5221(u: dict) -> dict:
    body = amending_article(2025, 133, '154', 'άρθρου 18 ν. 4624/2019')
    ins = instruction(body)
    for w in ['Στο άρθρο 18 του ν. 4624/2019 (Α’ 137), περί της Γραμματείας της Αρχής Προστασίας Δεδομένων '
              'Προσωπικού Χαρακτήρα, επέρχονται οι ακόλουθες τροποποιήσεις: α) στην παρ. 3, αα) στο πρώτο εδάφιο, οι λέξεις',
              'αβ) το δεύτερο, τέταρτο και πέμπτο εδάφιο διαγράφονται, β) προστίθεται παρ. 9, και, μετά από νομοτεχνικές '
              'βελτιώσεις, το άρθρο 18 διαμορφώνεται ως εξής:']:
        need(ins, w, 'ν. 5221/2025 art. 154')
    m = re.search(r'οι λέξεις «([^»]+)» αντικαθίστανται από τις λέξεις «([^»]+)»', ins)
    (qa,) = quotes(body)
    new = quoted_article(qa, '18')
    u = dict(u)
    head, old = head_split(u['art-018'])
    # par. 3 as the instruction describes it: words replaced in sentence 1, sentences 2, 4 and 5 struck
    o3 = old[find_one(old, '3. ', 'art. 18 par. 3')]
    n3 = new[find_one(new, '3. ', 'art. 18 par. 3 (new)')]
    s = sentences(o3)
    if m.group(1) not in s[0]:
        raise SystemExit('art. 18 par. 3: the replaced words are not in its first sentence')
    s[0] = s[0].replace(m.group(1), m.group(2))
    restated(' '.join([s[0], s[2]] + s[5:]), n3, 'art. 18 par. 3 as amended')
    # par. 9 added; par. 6 reads «[Καταργείται]» (repealed by ν. 4829/2021); the rest: the "νομοτεχνικές βελτιώσεις"
    if not new[-1].startswith('9. ') or any(l.startswith('9. ') for l in old):
        raise SystemExit('art. 18: par. 9 is not new')
    if '6. [Καταργείται].' not in new:
        raise SystemExit('art. 18: par. 6 is not marked repealed')
    for n in range(1, 9):
        if n in (3, 6):
            continue
        a = [l for l in old if l.startswith(f'{n}. ')]
        b = [l for l in new if l.startswith(f'{n}. ')]
        if len(a) != 1 or len(b) != 1:
            raise SystemExit(f'art. 18 par. {n}: not found once before and after')
        restated(a[0], b[0], f'ν. 5221/2025 art. 154 ("νομοτεχνικές βελτιώσεις"), art. 18 par. {n}')
    restated('\n'.join(old[:2]), '\n'.join(new[:2]), 'ν. 5221/2025 art. 154, art. 18 heading')
    u['art-018'] = head + new
    present(u, 'art-018', new, 'ν. 5221/2025 art. 154')
    LOG.append('ν. 5221/2025 art. 154: art. 18 restated; par. 3 checked against the described word change and '
               'struck sentences; par. 9 new')
    return u
