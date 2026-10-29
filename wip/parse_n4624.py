"""Build the ν. 4624/2019 part of the Greece corpus (corpus.d/20-n4624.json) from the cache of fetch_n4624.py.

ν. 4624/2019 (personal data protection; ΦΕΚ Α΄ 137/29.8.2019) as enacted, then every amendment, each applied from
the amending law's own ΦΕΚ text:

    ν. 4829/2021 (Α΄ 166/10.9.2021), art. 20 par. 1 περ. λβ   repeals art. 18 par. 6
    ν. 5002/2022 (Α΄ 228/9.12.2022), arts. 34-45              arts. 6, 43, 44, 45Α, 46 (and the Τμήμα ΙΙ title),
                                                              47, 49, 52, 53, 58, 71, 73, 84, 84Α
    ν. 5043/2023 (Α΄ 91/13.4.2023), art. 123 par. 2 περ. γ    repeals art. 11 par. 6
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


ACCENTED = set('άέήίόύώΐΰ')


def join_lines(lines: list[str]) -> str:
    """parse.join_lines, except that a line-end hyphen between two accented parts is kept: a Greek word carries one
    accent, so "κράτους-" + "μέλους" is the compound κράτους-μέλους, not one word broken across lines."""
    s = ''
    for t in lines:
        if not s:
            s = t
        elif re.search(r'[Α-Ωα-ωά-ώϊϋΐΰς]-$', s) and P.GREEK_LOWER.match(t):
            left = s.rsplit(' ', 1)[-1][:-1]
            right = t.split(' ', 1)[0]
            s = (s + t) if (ACCENTED & set(left) and ACCENTED & set(right)) else (s[:-1] + t)
        else:
            s = s + ' ' + t
    return s


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
            paras.append({'kind': kind, 'text': P.tidy_para(join_lines(cur))})
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
    if must not in title or not title:
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
    a = [w for w in (sq(x) for x in re.split(r'[\s\-–—’]+', expected)) if w]
    b = [w for w in (sq(x) for x in re.split(r'[\s\-–—’]+', new)) if w]
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


def am_5043(u: dict) -> dict:
    """ν. 5043/2023 art. 123: «Από την έναρξη ισχύος του παρόντος καταργούνται: … 2. … γ) η παρ. 6 του άρθρου 11
    του ν. 4624/2019 (Α’ 137) …»."""
    body = amending_article(2023, 91, '123', 'Καταργούμενες διατάξεις')
    texts = [p['text'] for p in body]
    if texts[0] != 'Από την έναρξη ισχύος του παρόντος καταργούνται:':
        raise SystemExit(f'ν. 5043/2023 art. 123 opens {texts[0]!r}')
    hit = [t for t in texts if t.startswith('γ) η παρ. 6 του άρθρου 11 του ν. 4624/2019 (Α’ 137)')]
    i2 = next(i for i, t in enumerate(texts) if t.startswith('2. '))
    if len(hit) != 1 or texts.index(hit[0]) < i2:
        raise SystemExit('ν. 5043/2023 art. 123 par. 2: item γ not found once')
    u = dict(u)
    u['art-011'] = replace_lines(u['art-011'], '6. ', r'^\d+\. ', [], 'ν. 5043/2023: art. 11 par. 6')
    LOG.append('ν. 5043/2023 art. 123 par. 2 γ: art. 11 par. 6 removed')
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


# ---------------------------------------------------------------- in-force clauses

def in_force_checks() -> list[str]:
    """Each law's own commencement clause, read from its issue; the parse stops if the wording is not there."""
    out = []

    def text_of(y, n):
        return '\n'.join(p['text'] for p in fek_paras(y, n))

    t = text_of(2019, 137)
    need(t, 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, εκτός αν άλλη '
            'διάταξη ορίζει διαφορετικά.', 'ν. 4624/2019 art. 87')
    need(t, '6. Η ισχύς του παρόντος αρχίζει την 1.9.2019.', 'ν. 4624/2019 art. 86 par. 6')
    out.append('ν. 4624/2019 art. 87: «Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
               'Κυβερνήσεως, εκτός αν άλλη διάταξη ορίζει διαφορετικά.» Art. 86 par. 6: «Η ισχύς του παρόντος αρχίζει '
               'την 1.9.2019.» Art. 87 already covers the law as a whole, so art. 86 par. 6 is read as the article\'s '
               'own commencement: art. 86 enters the history on 2019-09-01, everything else on 2019-08-29.')
    t = text_of(2021, 166)
    need(t, 'Οι διατάξεις του παρόντος τίθενται σε ισχύ από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, με την '
            'εξαίρεση:', 'ν. 4829/2021 commencement')
    need(t, 'β) της περ. λε’ της παρ. 1 του άρθρου 20 που τίθεται σε ισχύ από την 1η.7.2022.', 'ν. 4829/2021 commencement')
    out.append('ν. 4829/2021, last article: in force on publication, except Chapter Δ of Part Α and art. 20 par. 1 '
               'περ. λε; περ. λβ (art. 18 par. 6 of ν. 4624/2019) is not excepted, so 2021-09-10. Art. 20 par. 1 '
               'itself repeals «Από την έναρξη ισχύος του παρόντος».')
    t = text_of(2022, 228)
    need(t, '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος νόμου άρχεται από τη δημοσίευσή του στην Εφημερίδα '
            'της Κυβερνήσεως, εκτός αν προβλέπεται διαφορετικά στις επιμέρους διατάξεις.', 'ν. 5002/2022 art. 51')
    need(t, '2. Η ισχύς του άρθρου 27 άρχεται από την 1η.4.2023.', 'ν. 5002/2022 art. 51')
    out.append('ν. 5002/2022 art. 51: in force on publication, except art. 27 (not one of arts. 34-45), so '
               '2022-12-09; none of arts. 34-45 sets a date of its own.')
    t = text_of(2023, 91)
    need(t, '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
            'Κυβερνήσεως.', 'ν. 5043/2023 art. 124')
    need(t, '2. Τα άρθρα 61 και 63 τίθενται σε ισχύ από 1η Ιουλίου 2023.', 'ν. 5043/2023 art. 124')
    out.append('ν. 5043/2023 art. 124: in force on publication, except arts. 61 and 63, so art. 123 from 2023-04-13; '
               'art. 123 itself repeals «Από την έναρξη ισχύος του παρόντος».')
    t = text_of(2025, 76)
    need(t, 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται '
            'διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 5197/2025 commencement')
    out.append('ν. 5197/2025, last article: in force on publication unless a provision says otherwise; art. 56 '
               'sets no date, so 2025-05-16.')
    paras = fek_paras(2025, 133)
    t = '\n'.join(p['text'] for p in paras)
    need(t, '1. Με την επιφύλαξη των παρ. 2, 3 και 4 η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην '
            'Εφημερίδα της Κυβερνήσεως.', 'ν. 5221/2025 art. 168')
    need(t, '3. Το Μέρος Α’ και τα άρθρα 150 και 151 τίθενται σε ισχύ από την 1η Ιανουαρίου 2026.', 'ν. 5221/2025 art. 168')
    need(t, '4. Τα άρθρα 87 έως 89 και 122 έως 125 τίθενται σε ισχύ από την 1η Νοεμβρίου 2025.', 'ν. 5221/2025 art. 168')
    parts = [(i, p['text']) for i, p in enumerate(paras) if p['kind'] == 'struct' and p['text'].startswith('ΜΕΡΟΣ ')]
    a154 = next(i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == 'Άρθρο 154')
    part = [name for i, name in parts if i < a154][-1]
    if part != 'ΜΕΡΟΣ Γ’':
        raise SystemExit(f'ν. 5221/2025 art. 154 is in {part}')
    out.append('ν. 5221/2025 art. 168: in force on publication, except Part Β (on a ministerial decision), Part Α and '
               'arts. 150-151 (1.1.2026) and arts. 87-89 and 122-125 (1.11.2025); art. 154 is in Part Γ, so 2025-07-28.')
    return out


# ---------------------------------------------------------------- checks against other texts

def text_lines(units: dict, key: str) -> str:
    return '\n'.join(units[key])


def check_dpa(units: dict) -> tuple[list[str], list[str]]:
    """Compare a version with the Hellenic Data Protection Authority's consolidated text, article by article (the
    article from its heading on) and heading by heading, by words. Returns (articles that differ, notes)."""
    doc = fitz.open(cpath(F.DPA_CONSOLIDATED))
    raw = '\n'.join(p.get_text() for p in doc)
    raw = raw.replace('\xa0', ' ')
    # the Authority's notes: "***Το άρθρο … (ΦΕΚ A` 228/09.12.2022)" and one "ΠΑΡΑΤΗΡΗΣΗ"
    notes = re.findall(r'\*{3}\s*ΠΑΡΑΤΗΡΗΣΗ:.*?απορρήτου\.', raw, flags=re.S)
    for n in notes:
        raw = raw.replace(n, '\n', 1)
    notes = re.findall(r'\*{3}.*?\d{2}\.\d{2}\.\d{4}\)?\.?', raw, flags=re.S)
    if any(len(n) > 600 for n in notes):
        raise SystemExit('DPA text: a note did not end where expected')
    for n in notes:
        raw = raw.replace(n, '\n', 1)
    raw = re.sub(r'\[[^\[\]]*\]', '', raw)  # provisions it shows as repealed, in brackets
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    end = next(i for i, l in enumerate(lines) if l.startswith('Παραγγέλλομε'))
    lines = lines[:end]
    arts: dict[str, list[str]] = {}
    heads: list[str] = []
    cur = None
    i = 0
    while i < len(lines):
        l = lines[i]
        m = re.match(r'^«?Άρθρο (\d+)([Α-Ω])?$', l)
        if m:
            cur = art_key(m.group(1), m.group(2))
            arts[cur] = [f'Άρθρο {m.group(1)}{m.group(2) or ""}']
        elif re.match(r'^«?(ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ) \S+$', l):
            j = i + 1
            while j < len(lines) and not re.match(r'^«?(Άρθρο \d+[Α-Ω]?|ΚΕΦΑΛΑΙΟ \S+|ΤΜΗΜΑ \S+)$', lines[j]):
                j += 1
            heads += [l, ' '.join(lines[i + 1:j])]
            cur = None
            i = j - 1
        elif cur:
            arts[cur].append(l)
        i += 1
    import difflib
    import unicodedata

    def words(s):
        s = unicodedata.normalize('NFD', s)
        s = ''.join(c for c in s if not unicodedata.combining(c))  # accents: the Authority's text drops some
        return [w for w in (sq(x) for x in re.split(r'[\s\-–—’]+', s)) if w]

    ours_heads = [l for k in units for l in head_split(units[k])[0]]
    roman = str.maketrans({'Ι': 'I', 'Χ': 'X'})
    hq = [''.join(words(h.translate(roman))) for h in heads]
    oq = [''.join(words(h.translate(roman))) for h in ours_heads]
    notes_out = []
    if hq != oq:
        notes_out.append(f'headings differ: {[h for h, x in zip(heads, hq) if x not in oq]}')
    differ = {}
    for k in units:
        if k not in arts:
            differ[k] = 'missing in the Authority\'s text'
            continue
        ours = [l for l in head_split(units[k])[1] if not re.match(r'^\d+\. \[Καταργείται\]\.$', l)]
        a, b = words('\n'.join(ours)), words('\n'.join(arts[k]))
        if ''.join(a) != ''.join(b):  # spacing differences (e.g. «του·ή» in the Gazette) do not count
            sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
            differ[k] = [(' '.join(a[i1:i2]), ' '.join(b[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes()
                         if op != 'equal']
    for k in arts:
        if k not in units:
            differ[k] = 'only in the Authority\'s text'
    return differ, notes_out


def check_legalize(units: dict) -> tuple[int, list[str], list[str]]:
    """legalize-gr's text of ΦΕΚ Α΄ 137/2019 against the act as enacted, article by article, by words."""
    arts: dict[str, list[str]] = {}
    cur = None
    for line in cpath(F.LEGALIZE_FILE).read_text(encoding='utf-8').splitlines():
        m = re.match(r'^#####\s+Άρθρο\s+(\d+)([Α-Ω])?\s*$', line)
        if m:
            cur = art_key(m.group(1), m.group(2))
            arts[cur] = []
        elif line.startswith('#'):
            cur = None
        elif cur and line.strip():
            arts[cur].append(line.replace('**', '').lstrip('- '))
    same, differ, missing = 0, [], []
    for k, v in units.items():
        if k not in arts:
            missing.append(k)
        elif sq(' '.join(head_split(v)[1][1:])) == sq(' '.join(arts[k])):
            same += 1
        else:
            differ.append(k)
    return same, differ, missing


# ---------------------------------------------------------------- the corpus part

def law_title(year: int, num: int) -> str:
    ps = fek_paras(year, num)
    i = next(i for i, p in enumerate(ps) if 'ΠΡΟΕΔΡΟΣ' in p['text'] or p['text'].startswith('Εκδίδομε'))
    return P.tidy_para(join_lines([p['text'] for p in ps[1:i]]))


def signed(year: int, num: int) -> str:
    """The day the President signed (the first «Αθήνα, …» line)."""
    ps = fek_paras(year, num)
    t = next(p['text'] for p in ps if p['text'].startswith('Αθήνα, '))
    m = re.match(r'^Αθήνα, (\d{1,2}) (\w+) (\d{4})$', t)
    months = ['Ιανουαρίου', 'Φεβρουαρίου', 'Μαρτίου', 'Απριλίου', 'Μαΐου', 'Ιουνίου', 'Ιουλίου', 'Αυγούστου',
              'Σεπτεμβρίου', 'Οκτωβρίου', 'Νοεμβρίου', 'Δεκεμβρίου']
    return f'{m.group(3)}-{months.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}'


def changed(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def as_units(u: dict) -> dict:
    out = {}
    for k, lines in u.items():
        label = next(l for l in lines if re.match(r'^Άρθρο \d+[Α-Ω]?$', l))
        out[k] = {'label': label, 'kind': 'art', 'text': '\n'.join(lines) + '\n'}
    return dict(sorted(out.items()))


LAW_FEK = {'n-4624-2019': (2019, 137), 'n-4829-2021': (2021, 166), 'n-5002-2022': (2022, 228),
           'n-5043-2023': (2023, 91), 'n-5197-2025': (2025, 76), 'n-5221-2025': (2025, 133)}


def main(argv: list[str]) -> None:
    dump = Path(argv[argv.index('--dump') + 1]) if '--dump' in argv else None
    laws = {}
    for key, (y, n) in LAW_FEK.items():
        num = law_number(y, n)
        if key != f'n-{num}-{y}':
            raise SystemExit(f'Α΄ {n}/{y} is ν. {num}/{y}, not {key}')
        laws[key] = {'label': f'ν. {num}/{y}', 'kind': 'law', 'title': law_title(y, n), 'enacted': signed(y, n),
                     'published': masthead(y, n), 'url': F.fek_url(y, n), 'temporary_until': None, 'restores': None,
                     'note': None}
    pub = {k: v['published'] for k, v in laws.items()}
    commencement = in_force_checks()

    u0 = enacted()
    u_pre = {k: v for k, v in u0.items() if k != 'art-086'}
    u1 = am_4829(u0)
    u2 = am_5002(u1)
    u2b = am_5043(u2)
    u3 = am_5197(u2b)
    u4 = am_5221(u3)
    steps = [('2019-08-29', u_pre, None, (2019, 137)), ('2019-09-01', u0, 'n-4624-2019', (2019, 137)),
             (pub['n-4829-2021'], u1, 'n-4829-2021', (2021, 166)), (pub['n-5002-2022'], u2, 'n-5002-2022', (2022, 228)),
             (pub['n-5043-2023'], u2b, 'n-5043-2023', (2023, 91)),
             (pub['n-5197-2025'], u3, 'n-5197-2025', (2025, 76)), (pub['n-5221-2025'], u4, 'n-5221-2025', (2025, 133))]
    if [s[0] for s in steps] != sorted(s[0] for s in steps):
        raise SystemExit('versions out of order')
    if steps[0][0] != pub['n-4624-2019']:
        raise SystemExit('ν. 4624/2019 publication day is not 2019-08-29')

    dpa_differ, dpa_notes = check_dpa(u4)
    print(f'DPA: latest differs in {dpa_differ} {dpa_notes}')
    import unicodedata
    third = ''.join(c for c in unicodedata.normalize('NFD', sq(sentences(u4['art-084-a'][-1])[2]))
                    if not unicodedata.combining(c))
    expected = {'art-018': [('85/2022', '50/2001')]}
    if (dpa_notes or set(dpa_differ) != {'art-018', 'art-084-a'} or dpa_differ['art-018'] != expected['art-018']
            or len(dpa_differ['art-084-a']) != 1 or dpa_differ['art-084-a'][0][1] != ''
            or sq(dpa_differ['art-084-a'][0][0]) != third):
        raise SystemExit(f'DPA consolidated text: unexpected differences {dpa_differ} {dpa_notes}')
    dpa_old = sorted(check_dpa(u2b)[0])
    if dpa_old != ['art-018']:
        raise SystemExit(f'DPA consolidated text vs the 2023 version: {dpa_old}')
    lg_same, lg_differ, lg_missing = check_legalize(u0)

    notes = {
        '2019-08-29': 'ν. 4624/2019 as published in ΦΕΚ Α΄ 137/29.8.2019, in force on publication (art. 87), '
                      'without art. 86, which sets its own start (art. 86 par. 6: 1.9.2019).',
        '2019-09-01': 'Art. 86 of ν. 4624/2019 takes effect (its par. 6: «Η ισχύς του παρόντος αρχίζει την 1.9.2019»).',
        pub['n-4829-2021']: 'Art. 18 par. 6 repealed by ν. 4829/2021 art. 20 par. 1 περ. λβ (ΦΕΚ Α΄ 166/10.9.2021), '
                            'in force on publication.',
        pub['n-5002-2022']: 'ν. 5002/2022 arts. 34-45 (ΦΕΚ Α΄ 228/9.12.2022), in force on publication (art. 51). '
                            'Each replaced or restated provision reads as the amending law quotes it.',
        pub['n-5043-2023']: 'Art. 11 par. 6 repealed by ν. 5043/2023 art. 123 par. 2 περ. γ (ΦΕΚ Α΄ 91/13.4.2023), '
                            'in force on publication.',
        pub['n-5197-2025']: 'ν. 5197/2025 art. 56 (ΦΕΚ Α΄ 76/16.5.2025) adds a third sentence to art. 84Α par. 7; '
                            'in force on publication.',
        pub['n-5221-2025']: 'ν. 5221/2025 art. 154 (ΦΕΚ Α΄ 133/28.7.2025) restates art. 18 "after technical '
                            'improvements" (μετά από νομοτεχνικές βελτιώσεις); in force on publication (art. 168, '
                            'Part Γ). Par. 6 reads «[Καταργείται]» as the restatement prints it.',
    }
    versions = []
    prev = None
    for day, u, law, (y, n) in steps:
        units = as_units(u)
        v = {'from': day, 'source_url': F.fek_url(y, n), 'sha256': sha(F.fek_url(y, n))}
        if prev is None:
            v['units'] = units
        else:
            ch = changed(prev, units)
            v['changes'] = {k: units.get(k) for k in ch}
            v['credits'] = {k: [law] for k in ch}
        v['note'] = notes[day]
        versions.append(v)
        prev = units
        if dump:
            d = dump / day
            d.mkdir(parents=True, exist_ok=True)
            for k, x in units.items():
                (d / f'{k}.md').write_text(x['text'], encoding='utf-8', newline='\n')

    blob_requests = sum(1 for l in (CACHE / 'requests.jsonl').read_text(encoding='utf-8').splitlines()
                        if 'blob.core.windows.net' in l)
    sources = [
        {'name': 'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: issues for ν. 4624/2019 and its amending laws',
         'url': 'https://ia37rg02wpsa01.blob.core.windows.net/fek/', 'retrieved': '2026-10-29',
         'requests': blob_requests,
         'licence': 'Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). '
                    'Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).',
         'notes': 'Series Α΄ issues 137/2019 (ν. 4624/2019), 166/2021 (ν. 4829/2021), 228/2022 (ν. 5002/2022), '
                  '91/2023 (ν. 5043/2023), 76/2025 (ν. 5197/2025) and 133/2025 (ν. 5221/2025), each with a text layer; issue number, date '
                  'and law number checked against each issue. Every word of the act is read from these issues. '
                  'Α΄ 223/2025 (ν. 5256/2025) was also read: a full-text candidate, it amends no provision of '
                  'ν. 4624/2019.'},
        {'name': 'Αρχή Προστασίας Δεδομένων Προσωπικού Χαρακτήρα: «ν. 4624/2019 με ενσωματωμένες όλες τις '
                 'τροποποιήσεις» (consolidated text, PDF last modified 2025-12-10)',
         'url': F.DPA_CONSOLIDATED, 'retrieved': '2026-10-29', 'requests': 1,
         'licence': 'Hellenic Data Protection Authority publication; used only to check the history, no text copied.',
         'notes': 'Linked from https://www.dpa.gr/el/enimerwtiko/nomothesia/proswpikon_dedomenon. Its amendment notes '
                  'name ν. 4829/2021, 5002/2022, 5043/2023 and 5221/2025; it does not include ν. 5197/2025 art. 56.'},
        {'name': f'legalize-gr (github.com/legalize-dev/legalize-gr), commit {F.LEGALIZE_COMMIT[:12]}',
         'url': f'https://github.com/legalize-dev/legalize-gr/tree/{F.LEGALIZE_COMMIT}', 'retrieved': '2026-10-29',
         'requests': 1,
         'licence': 'Pipeline MIT (github.com/legalize-dev/legalize-pipeline); legislative content: «Δημόσιος τομέας '
                    '(επίσημα κρατικά κείμενα)» (its LICENSE). Original source of each file: the ΦΕΚ PDF named in its '
                    'YAML `source` field.',
         'notes': 'One Markdown file per ΦΕΚ Α΄ issue since 2000, each as published (amendments are not merged; its '
                  '6,851 commits add files, dated by publication). Used to find amending laws (full-text scan of its '
                  '6,847 issues plus the `amends` relation field it copies from the official search.et.gr timeline: '
                  'scan_legalize_gr.py) and as a cross-check of the enacted text; its text is not used.'},
    ]
    decisions = [
        'ν. 4624/2019 is built from the Government Gazette alone: the act as published (ΦΕΚ Α΄ 137/2019) and, for '
        'each amendment, the amending law\'s own issue. Greece publishes no official consolidated text.',
        f'legalize-gr was to be the text source, but its file for ΦΕΚ Α΄ 137/2019 agrees word for word with the '
        f'issue in only {lg_same} of 87 articles: {len(lg_missing)} are missing ({", ".join(lg_missing)}) and '
        f'{len(lg_differ)} lose or interleave text across the two columns. So every word is read from the ΦΕΚ PDFs '
        f'with this folder\'s column reader, and legalize-gr is used only to find amending laws.',
        'Amending laws were found three ways: (1) scan_legalize_gr.py, a full-text scan of every ΦΕΚ Α΄ issue '
        '2019-2026 in legalize-gr for any article that names a provision of ν. 4624/2019 outside a quotation and '
        'carries an amending verb or heading; (2) the official search.et.gr relation index, as copied into '
        'legalize-gr\'s `amends` field; (3) the amendment notes of the Data Protection Authority\'s consolidated text. '
        '(1) finds ν. 4829/2021, 5002/2022, 5043/2023, 5197/2025 and 5221/2025 (plus Α΄ 77/2023, which only cites the '
        'law); (2) lists 5002/2022, 5197/2025 and 5221/2025 (its other rows, Α΄ 77/2023, 223/2025 and 9/2026, only '
        'cite ν. 4624/2019); (3) names 4829/2021, 5002/2022, 5043/2023 and 5221/2025. ν. 5043/2023 was first found '
        'through (3): it repeals in a list item, which the first version of the scan missed. Every one of the five '
        'was then read in its own issue.',
        'Article 86 of ν. 4624/2019 is dated from 2019-09-01 by its own par. 6; the rest of the act from its '
        'publication, 2019-08-29 (art. 87).',
        'Every other version is dated by the amending law\'s own commencement clause, read from its issue (see the '
        'parse log); each says publication in the Gazette for the provisions used here. The publication day is '
        'the date printed on the issue\'s masthead. Α΄ 228/2022 carries a digital signature of 10.12.2022 00:27 and '
        'Α΄ 76/2025 one of 19.05.2025; the masthead dates (9.12.2022 and 16.5.2025) are used.',
        'Units are articles (art-NNN, art-NNN-a for Α). An article\'s text is its heading lines (chapter and section '
        'headings that open it), "Άρθρο N", its title on one line, then one paragraph or lettered item per line. '
        'Section numerals, which the Gazette sets with Greek Ι beside Latin V, are written in Latin.',
        'A repealed paragraph or item is removed (art. 18 par. 6 in 2021, art. 44 περ. ιζ in 2022, art. 11 par. 6 '
        'in 2023). From 2025 '
        'art. 18 par. 6 reads «6. [Καταργείται].» because ν. 5221/2025 restates the article that way.',
        'ν. 5002/2022 art. 38 adds art. 45Α "after art. 45": it is placed before the Τμήμα ΙΙ heading, which opens '
        'art. 46, as the Data Protection Authority\'s text also places it.',
        'ν. 5002/2022 art. 42 misprints the law as "ν. 4264/2019 (Α’ 137)"; its heading and the issue number name '
        'ν. 4624/2019, so it is applied.',
        'Where an amending provision describes a change and then restates the result, the restated text is used, '
        'and the parse checks the description against the old text; the small wording changes the restatement '
        'makes on its own are listed below.',
        f'Check against the Data Protection Authority\'s consolidated text (PDF modified 2025-12-10): the latest '
        f'version, 2025-07-28, agrees with it word for word in every article and heading but two. Art. 84Α: the '
        f'Authority\'s text lacks the third sentence of par. 7 added by ν. 5197/2025 art. 56 (read in ΦΕΚ Α΄ '
        f'76/2025). Art. 18 par. 8: the Authority\'s text still cites «π.δ. 50/2001», which ν. 5221/2025 art. 154 '
        f'restates as «π.δ. 85/2022 (Α’ 39)». The 2023-04-13 version (before both) differs from it only in '
        f'{", ".join(dpa_old)}. Comparison is by words, ignoring punctuation, quote marks, accents, case and spacing.',
    ]
    decisions += [f'Parse log: {l}' for l in commencement + LOG]
    decisions += [f'Restated wording: {l}' for l in RESTATED]
    part = {
        'laws': laws,
        'sources': sources,
        'acts': [{
            'slug': 'nomos-4624-2019', 'short': 'ν. 4624/2019', 'title': laws['n-4624-2019']['title'],
            'url': F.fek_url(2019, 137), 'first_law': 'n-4624-2019', 'earlier_laws': [], 'versions': versions,
        }],
        'applies': [],
        'decisions': decisions,
        'ai_use': ['ν. 4624/2019 part: none. No model wrote or altered legal text; a model (Claude) wrote '
                   'parse_n4624.py, which reads every word from the Gazette PDFs.'],
    }
    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(part, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    os.replace(tmp, OUT)
    print('\n'.join(commencement + LOG))
    print(f'legalize-gr: {lg_same} same, {len(lg_differ)} differ, missing {lg_missing}')
    print(f'DPA: latest differs in {dpa_differ}; previous in {dpa_old}')
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes, {len(versions)} versions)')


if __name__ == '__main__':
    main(sys.argv[1:])
