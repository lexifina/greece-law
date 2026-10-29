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


def word_change(old: str, pairs: list[tuple[str, str]], new: str, what: str) -> None:
    """The instruction's described word change, applied to the old text, must give the restated text."""
    t = old
    for a, b in pairs:
        if a not in t:
            raise SystemExit(f'{what}: {a!r} not in the old text')
        t = t.replace(a, b, 1) if b is not None else t.replace(a, '', 1)
    same_words(t, new, what)


def present(units: dict, key: str, quoted: list[str], what: str) -> None:
    text = '\n'.join(units[key])
    for q in quoted:
        if q not in text:
            raise SystemExit(f'{what}: quoted text not in {key}: {q[:60]}')
