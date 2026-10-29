"""Parse the Greek Constitution from cached ΦΕΚ PDFs into corpus.d/10-syntagma.json (gitlaw_common SCHEMA.md).

Reads only .cache/ (fetch.py fills it); no network. Deterministic: the same cache gives the same bytes.

Sources: the three whole-text republications of the Constitution that have a text layer, each ordered by the
revision resolution before it:
  Α΄ 85/18.4.2001  (after the 2001 revision, Α΄ 84/17.4.2001)
  Α΄ 120/27.6.2008 (after the 2008 revision, Α΄ 102/2.6.2008)
  Α΄ 211/24.12.2019 (after the 2019 revision, Α΄ 187/28.11.2019)
The 1975 text and the 1986 issues are page-image scans with no text layer, so they are not used (no OCR).

Text extraction (PyMuPDF, no OCR):
- two columns per page, read left column then right, top to bottom; lines that span both columns (mastheads, the
  President of Parliament's order, footnotes) and running headers and page numbers are dropped;
- the 2001 issue is set in a legacy Greek font whose text layer holds Windows-1253 bytes read as Windows-1252; they
  are mapped back byte for byte;
- all three issues set some Greek capitals and omicrons with look-alike Latin letters (A for Α, o for ο); these are
  mapped to the Greek letters;
- a paragraph starts at an indented line or a heading; lines are joined, and a word broken at a line end with a
  hyphen is joined back;
- the publisher's asterisks (marking which revision wrote each provision) are removed from the text and kept only to
  cross-check the credits.

    python -X utf8 scripts/greece-law/parse.py [--dump DIR]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
CACHE = HERE / '.cache'
OUT = HERE / 'corpus.d' / '10-syntagma.json'
BLOB = 'https://ia37rg02wpsa01.blob.core.windows.net/fek'


def fek_url(year: int, num: int) -> str:
    return f'{BLOB}/01/{year}/{year}01{num:05d}.pdf'


def cached(url: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode('utf-8')).hexdigest() + '.pdf')


# ---------------------------------------------------------------- text normalisation

LEGACY_EXTRA = set('–—‘’“”…€‚„†‡ˆ‰Š‹ŒŽ•˜™š›œžŸ')


def legacy_decode(s: str) -> str:
    """The 2001 font's text layer holds Windows-1253 bytes (read as Latin-1 code points, or as Windows-1252
    characters for 0x80-0x9F); map them back to Greek. Byte 0x88, undefined in Windows-1253, is that font's ano
    teleia (·): it stands exactly where the 2008 and 2019 republications print one."""
    out = []
    for ch in s:
        o = ord(ch)
        if o == 0x88:
            out.append('·')
        elif 0x80 <= o <= 0xFF:
            out.append(bytes([o]).decode('cp1253'))  # raises on a byte Windows-1253 leaves undefined
        elif ch in LEGACY_EXTRA:
            out.append(ch.encode('cp1252').decode('cp1253'))
        else:
            out.append(ch)
    return ''.join(out)


LOOKALIKE = str.maketrans({'A': 'Α', 'B': 'Β', 'E': 'Ε', 'Z': 'Ζ', 'H': 'Η', 'I': 'Ι', 'K': 'Κ', 'M': 'Μ',
                           'N': 'Ν', 'O': 'Ο', 'P': 'Ρ', 'T': 'Τ', 'Y': 'Υ', 'X': 'Χ', 'o': 'ο', 'v': 'ν',
                           '∆': 'Δ', 'µ': 'μ', 'Ω': 'Ω'})
# numeral signs, apostrophes and the elision mark all become ’ (the form the 2019 republication uses)
APOS = str.maketrans({'΄': '’', "'": '’', 'ʹ': '’', '‘': '’', '´': '’', '`': '’', 'ʹ': '’'})


def norm_line(s: str) -> str:
    s = unicodedata.normalize('NFC', s)
    s = s.replace('\xa0', ' ').replace('−', '-').replace('‐', '-').replace('\xad', '-')
    s = s.translate(LOOKALIKE).translate(APOS)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def tidy_para(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s*[–—]\s*', ' – ', s)              # spaced dashes: one form
    s = re.sub(r'(?<=\w) - (?=\w)', ' – ', s)
    s = re.sub(r'\(\s+', '(', s)
    s = re.sub(r'\s+\)', ')', s)
    s = re.sub(r'\s+([,.;:·])', r'\1', s)
    s = re.sub(r'«\s+', '«', s)
    s = re.sub(r'\s+»', '»', s)
    s = s.replace('’ ’', '’')
    s = re.sub(r'"([^"]*)"', r'«\1»', s)                # straight double quotes: one form («»)
    return s


# ---------------------------------------------------------------- PDF to lines

JUNK = [
    re.compile(r'^ΕΦΗΜΕΡΙ[ΣΔ] ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ'), re.compile(r'^ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ$'),
    re.compile(r'^ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ$'), re.compile(r'^ΤΕΥΧΟΣ ΠΡΩΤΟ'), re.compile(r'^Αρ\. Φύλλου'),
    re.compile(r'^Τεύχος Α’ \d+/'), re.compile(r'^\d{1,5}$'), re.compile(r'^[ΕF]$'),
    re.compile(r'^\d{1,2} \w+ \d{4}$'),
]


def is_junk(t: str) -> bool:
    return not t or any(p.search(t) for p in JUNK)


def pdf_lines(path: Path, legacy: bool) -> list[dict]:
    """Body lines in reading order: per page, left column then right column, each top to bottom."""
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
    body = max(sizes, key=lambda k: (sizes[k], -k))  # the body text size; footnotes are set smaller
    for pno, page in enumerate(doc):
        lines = []
        for b in page.get_text('dict')['blocks']:
            if b['type'] != 0:
                continue
            for l in b['lines']:
                raw = ''.join(s['text'] for s in l['spans'])
                if legacy:
                    raw = legacy_decode(raw)
                t = norm_line(raw)
                size = max(s['size'] for s in l['spans'])
                x0, y0, x1, _ = l['bbox']
                if is_junk(t) or size > body + 1.5 or size < body - 0.6 or y0 < 75:
                    continue
                lines.append({'x0': x0, 'y0': y0, 'x1': x1, 't': t, 'page': pno})
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


# ---------------------------------------------------------------- lines to units

ART = re.compile(r'^\**\s*Άρθρο\s+(\d+)\s*([Α-Ω])?$')
STRUCT = re.compile(r'^\**\s*(ΜΕΡΟΣ|ΤΜΗΜΑ|ΚΕΦΑΛΑΙΟ)\b')
START = re.compile(r'^\**\s*ΜΕΡΟΣ ΠΡΩΤΟ$')
END = re.compile(r'^Αθήνα, ')
PREAMBLE = 'Εις το όνομα της Αγίας και Ομοουσίου και Αδιαιρέτου Τριάδος'
MARK = re.compile(r'\*+')
GREEK_LOWER = re.compile(r'^[α-ωάέήίόύώϊϋΐΰς]')


def join_lines(lines: list[str]) -> str:
    s = ''
    for t in lines:
        if not s:
            s = t
        elif re.search(r'[Α-Ωα-ωά-ώϊϋΐΰς]-$', s) and GREEK_LOWER.match(t):
            s = s[:-1] + t
        else:
            s = s + ' ' + t
    return s


def paragraphs(lines: list[dict]) -> list[dict]:
    """Group body lines into paragraphs: a new one at an indented line, a heading, or after a heading."""
    paras: list[dict] = []
    cur: list[str] = []
    cur_kind = None

    def flush():
        nonlocal cur, cur_kind
        if cur:
            paras.append({'kind': cur_kind, 'text': join_lines(cur)})
        cur, cur_kind = [], None

    in_struct = False
    for l in lines:
        t = l['t']
        if ART.match(t):
            flush()
            paras.append({'kind': 'art', 'text': t})
            in_struct = False
            continue
        if STRUCT.match(t):
            flush()
            paras.append({'kind': 'struct', 'text': t})
            in_struct = True
            continue
        if in_struct:
            # a part/section/chapter title, possibly wrapped over lines: one title per heading line
            if cur_kind == 'title':
                cur.append(t)
            else:
                flush()
                cur, cur_kind = [t], 'title'
            continue
        if l['indent'] > 4 or not cur:
            flush()
            cur, cur_kind = [t], 'p'
        else:
            cur.append(t)
    flush()
    return paras


def article_key(num: str, suffix: str | None) -> str:
    k = f'art-{int(num):03d}'
    if suffix:
        k += '-' + {'Α': 'a', 'Β': 'b', 'Γ': 'c', 'Δ': 'd'}[suffix]
    return k


def units_from(path: Path, legacy: bool) -> tuple[dict, dict]:
    """Units {key: {label, kind, text}} and the publisher's asterisk marks {key: set of mark lengths}."""
    lines = pdf_lines(path, legacy)
    i0 = next(i for i, l in enumerate(lines) if START.match(l['t']))
    i1 = next(i for i, l in enumerate(lines) if i > i0 and END.match(l['t']))
    paras = paragraphs(lines[i0:i1])
    units: dict[str, dict] = {}
    marks: dict[str, list] = {}
    pending: list[str] = []  # structural headings waiting for the article they open
    key = None
    for p in paras:
        raw = p['text']
        stars = [len(m) for m in MARK.findall(raw)]
        text = tidy_para(MARK.sub('', raw))
        if text.endswith('»') and p is paras[-1]:
            text = text[:-1].rstrip()  # the closing quote of the President's order
        if not text:
            continue
        if p['kind'] in ('struct', 'title'):
            pending.append(text)
            if stars:
                pending_marks = stars  # noqa: F841 (heading marks are not used for credits)
            continue
        if p['kind'] == 'art':
            m = ART.match(text)
            key = article_key(m.group(1), m.group(2))
            label = f'Άρθρο {int(m.group(1))}{m.group(2) or ""}'
            if key in units:
                raise SystemExit(f'{path.name}: {label} twice')
            units[key] = {'label': label, 'kind': 'art', 'lines': pending + [label]}
            marks[key] = [(0, s) for s in stars]
            pending = []
            continue
        if key is None:
            raise SystemExit(f'{path.name}: text before the first article: {text[:60]}')
        units[key]['lines'].append(text)
        marks[key] += [(len(units[key]['lines']) - 1, s) for s in stars]
    if pending:
        raise SystemExit(f'{path.name}: headings after the last article: {pending}')
    out = {}
    for k, u in units.items():
        out[k] = {'label': u['label'], 'kind': u['kind'], 'text': '\n'.join(u['lines']) + '\n'}
    out['prooimio'] = {'label': 'Προοίμιο', 'kind': 'preamble', 'text': PREAMBLE + '\n'}
    return dict(sorted(out.items())), marks


def check_preamble(path: Path, legacy: bool) -> None:
    doc = fitz.open(path)
    t = norm_line(''.join(legacy_decode(p.get_text()) if legacy else p.get_text() for p in doc[:1]))
    if PREAMBLE not in t:
        raise SystemExit(f'{path.name}: the preamble line was not found on the first page')


def latin_left(units: dict) -> list[str]:
    return [f'{k}: {w}' for k, u in units.items() for w in re.findall(r'\S*[A-Za-z]\S*', u['text'])]


def main(argv: list[str]) -> None:
    dump = Path(argv[argv.index('--dump') + 1]) if '--dump' in argv else None
    texts = {}
    for (y, n), legacy in [((2001, 85), True), ((2008, 120), False), ((2019, 211), False)]:
        p = cached(fek_url(y, n))
        check_preamble(p, legacy)
        u, m = units_from(p, legacy)
        texts[(y, n)] = (u, m, p)
        bad = latin_left(u)
        print(f'{y} Α΄ {n}: {len(u)} units; Latin left: {bad[:10]}')
        if dump:
            d = dump / f'{y}-{n}'
            d.mkdir(parents=True, exist_ok=True)
            for k, x in u.items():
                (d / f'{k}.md').write_text(x['text'], encoding='utf-8', newline='\n')
            (d / 'marks.json').write_text(json.dumps(m, ensure_ascii=False, indent=0), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1:])
