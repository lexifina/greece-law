"""GR-L text reader: gr-a extract.read_pdf() plus a repair for one broken font map common in Diavgeia PDFs of 2011-2019.

Diavgeia re-renders many uploads with PDFlib using NON-embedded Type0 (Identity-H) fonts such as Arial; their ToUnicode
maps give wrong Greek letters (ΑΘΗΝΑΙΩΝ reads ΑΘΖΝΑΗΧΝ, Σ reads U+03A2), and several real letters share one wrong
letter, so no character table can undo it. The glyph ids are right, though: each Greek character of such a span is read
again from its glyph id through the cmap of the same Windows font (C:/Windows/Fonts, versions recorded in READER_FIX).
The repaired reading is kept only if it reads as Greek (function-word share >= 0.15); otherwise the document is
marked `garbled` and its act is held.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, r'C:\Users\alany\Documents\lexifina\scripts\greece-law\bulk\gr-a')
import extract  # noqa: E402
import fitz  # noqa: E402

FONTS = Path('C:/Windows/Fonts')
FAMILY = [('arial', 'arial'), ('times', 'times'), ('tahoma', 'tahoma'), ('calibri', 'calibri'),
          ('verdana', 'verdana'), ('courier', 'cour'), ('georgia', 'georgia'), ('cambria', 'cambria'),
          ('trebuchet', 'trebuc'), ('garamond', 'gara'), ('bookman', 'bookos'), ('century', 'century')]
STYLE = {'arial': ('arial', 'arialbd', 'ariali', 'arialbi'), 'times': ('times', 'timesbd', 'timesi', 'timesbi'),
         'tahoma': ('tahoma', 'tahomabd', 'tahoma', 'tahomabd'), 'calibri': ('calibri', 'calibrib', 'calibrii', 'calibriz'),
         'verdana': ('verdana', 'verdanab', 'verdanai', 'verdanaz'), 'cour': ('cour', 'courbd', 'couri', 'courbi'),
         'georgia': ('georgia', 'georgiab', 'georgiai', 'georgiaz'), 'cambria': ('cambria', 'cambriab', 'cambriai', 'cambriaz'),
         'trebuc': ('trebuc', 'trebucbd', 'trebucit', 'trebucbi'), 'gara': ('gara', 'garabd', 'garait', 'gara'),
         'bookos': ('bookos', 'bookosb', 'bookosi', 'bookosbi'), 'century': ('century', 'century', 'century', 'century')}
FW = set('και του της την των το τα τη με για στο στην από απο που ο η οι ως σε στη στον να είναι ή τον τις τους '
         'δήμου θα ότι κατά μετά'.split())
GREEK_CH = re.compile(r'[\u0370-\u03ff]')


def quality(text: str) -> tuple[int, float]:
    """(Greek words, share of them that are common function words). Normal Greek prose: 0.2-0.35."""
    words = [w for w in re.findall(r'[^\W\d_]+', text.lower()) if GREEK_CH.match(w)]
    return len(words), (sum(w in FW for w in words) / len(words) if words else 0.0)


def garbled(text: str) -> bool:
    n, q = quality(text)
    return n >= 30 and q < 0.08


def font_file(name: str) -> Path | None:
    n = name.split('+', 1)[-1].lower()
    fam = next((f for k, f in FAMILY if k in n), None)
    if fam is None:
        return None
    bold = 'bold' in n or n.endswith(',b') or '-bd' in n
    ital = 'italic' in n or 'oblique' in n
    p = FONTS / f'{STYLE[fam][bold + 2 * ital]}.ttf'
    return p if p.exists() else None


@lru_cache(maxsize=None)
def gid_map(path: str) -> dict[int, int]:
    from fontTools.ttLib import TTFont
    f = TTFont(path, lazy=True)
    out: dict[int, int] = {}
    for u, name in sorted(f.getBestCmap().items()):
        out.setdefault(f.getGlyphID(name), u)
    return out


@lru_cache(maxsize=None)
def font_version(path: str) -> str:
    from fontTools.ttLib import TTFont
    f = TTFont(path, lazy=True)
    return f'{Path(path).name} {f["head"].fontRevision:.2f}'


def repaired_lines(doc, info: list[dict]) -> tuple[list[dict], set[str]]:
    """Lines as extract.read_pdf() makes them, with each Greek char re-read from its glyph id."""
    used: set[str] = set()
    lines = []
    for pno, page in enumerate(doc):
        if not info[pno]['text']:
            continue
        fix: dict[tuple, str] = {}
        for s in page.get_texttrace():
            ff = font_file(s['font'])
            if ff is None:
                continue
            m = gid_map(str(ff))
            for c in s['chars']:
                u, gid, origin = c[0], c[1], c[2]
                if gid > 0 and GREEK_CH.match(chr(u)) and gid in m:
                    fix[(round(origin[0], 1), round(origin[1], 1), u)] = chr(m[gid])
                    used.add(font_version(str(ff)))
        for b in page.get_text('rawdict')['blocks']:
            if b['type'] != 0:
                continue
            for l in b['lines']:
                spans = [s for s in l['spans'] if ''.join(ch['c'] for ch in s['chars']).strip()]
                if not spans:
                    continue
                t = ''.join(fix.get((round(ch['origin'][0], 1), round(ch['origin'][1], 1), ord(ch['c'])), ch['c'])
                            for s in l['spans'] for ch in s['chars'])
                n = sum(len(s['chars']) for s in spans)
                x0, y0, x1, y1 = l['bbox']
                lines.append({'p': pno, 't': extract.unicodedata.normalize('NFC', t), 'x0': round(x0, 2),
                              'y0': round(y0, 2), 'x1': round(x1, 2), 'y1': round(y1, 2),
                              'size': round(max(s['size'] for s in spans), 2),
                              'bold': sum(len(s['chars']) for s in spans if s['flags'] & 16) * 2 > n})
    return lines, used


def read_pdf(path: Path, meta: dict) -> dict:
    d = extract.read_pdf(path, meta)
    for ln in d['lines']:
        ln.pop('b', None)
    text = '\n'.join(l['t'] for l in d['lines'])
    if not garbled(text) and text.count('΢') < 2:
        return d
    # U+03A2 is not a character: two or more of them mark the same broken map in a milder form (Σ, ς, Υ, ά ...)
    doc = fitz.open(stream=Path(path).read_bytes(), filetype='pdf')
    lines, used = repaired_lines(doc, d['page_info'])
    t2 = '\n'.join(l['t'] for l in lines)
    if lines and not garbled(t2) and t2.count('΢') < 2 and quality(t2)[1] >= max(0.15, quality(text)[1] - 0.02):
        d['lines'] = lines
        d['text_source'] = 'text layer (glyph ids re-read with ' + ', '.join(sorted(used)) + ')'
    else:
        d['garbled'] = True
    return d
