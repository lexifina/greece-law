"""GR-L shared helpers: paths, ADA transliteration, unit slugs, text normalisation for Diavgeia PDFs."""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, r'C:\Users\alany\Documents\lexifina\scripts\greece-law\bulk\gr-a')
from common import SRC  # noqa: E402,F401

WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-l')
META = SRC / 'diavgeia' / 'meta'
TEXT = SRC / 'diavgeia' / 'text'
PDF = SRC / 'diavgeia' / 'pdf'
SEL = SRC / 'diavgeia' / 'selected'
CORPUS = Path(r'C:\Users\alany\Documents\lexifina\scripts\greece-law\corpus.d')
ATH = dt.timezone(dt.timedelta(hours=2))

# ADA letters (Greek capitals) -> one ASCII letter each (a bijection, so ADA-ascii is unique).
ADA_MAP = dict(zip('ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ', 'abgdezhuiklmnjoprstyfxcw'))


def ada_ascii(ada: str) -> str | None:
    out = []
    for ch in ada:
        if ch.isdigit() or ch == '-':
            out.append(ch)
        elif ch in ADA_MAP:
            out.append(ADA_MAP[ch])
        else:
            return None
    return ''.join(out)


TRANSLIT = [('ου', 'ou'), ('αι', 'ai'), ('ει', 'ei'), ('οι', 'oi'), ('μπ', 'b'), ('ντ', 'nt'), ('γκ', 'gk'),
            ('γγ', 'ng'), ('αυ', 'av'), ('ευ', 'ev'), ('θ', 'th'), ('χ', 'ch'), ('ψ', 'ps'), ('ξ', 'x')]
SINGLE = dict(zip('αβγδεζηικλμνοπρστυφω', 'avgdeziiklmnoprstyfo'))


def translit(s: str) -> str:
    """ELOT-743-like ASCII slug of a Greek name: 'ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ' -> 'dimos-athinaion'."""
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn').replace('ς', 'σ')
    for a, b in TRANSLIT:
        s = s.replace(a, b)
    s = ''.join(SINGLE.get(c, c) for c in s)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s


UNIT_PREFIX = {'MUNICIPALITY': 'dimos', 'REGION': 'perifereia', 'ADMINISTRATIVEREGION': 'apokentromeni-dioikisi'}
UNIT_WORD = {'MUNICIPALITY': r'^\s*δημο[σς]?\s+', 'REGION': r'^\s*περιφερεια\s+',
             'ADMINISTRATIVEREGION': r'^\s*αποκεντρωμενη\s+διοικηση\s+'}


def unit_slug(org: dict) -> str:
    """dimos-athinaion, perifereia-attikis, apokentromeni-dioikisi-attikis (from the Diavgeia label)."""
    lab = unicodedata.normalize('NFD', org['label'].lower())
    lab = ''.join(c for c in lab if unicodedata.category(c) != 'Mn')
    lab = re.sub(UNIT_WORD[org['category']], '', lab)
    lab = lab.replace('δημο ', '').replace('(κρητησ)', 'kritis').replace('(κρητης)', 'kritis')
    return f'{UNIT_PREFIX[org["category"]]}-{translit(lab)}'


# Text normalisation (applied once when the corpus is written; the stored line files keep the PDF's own text).
LOOK = {'∆': 'Δ', 'µ': 'μ', 'Ω': 'Ω', '\u00a0': ' ', '\u2009': ' ', '\u202f': ' ', '\u200b': '', '\ufeff': '',
        '\u00ad': '', 'ʹ': '΄', '΄': '΄', '`': '΄'}
LAT2GR = dict(zip('ABEHIKMNOPTXYZaeoikxuv', 'ΑΒΕΗΙΚΜΝΟΡΤΧΥΖαεοικχυν'))
GREEK = re.compile(r'[\u0370-\u03ff\u1f00-\u1fff]')
WORD = re.compile(r'[^\W\d_]+')
# The broken font map seen in some municipal PDFs: capitals from Σ on come out one code point low (Σ as U+03A2 ΢,
# Τ as Σ, Υ as Τ ...). A line holding U+03A2 is read with the shift undone for U+03A2..U+03A8.
SHIFT = {chr(c): chr(c + 1) for c in range(0x03A2, 0x03A9)}


def fix_word(w: str) -> str:
    if GREEK.search(w) and all(GREEK.match(c) or c in LAT2GR for c in w):
        return ''.join(LAT2GR.get(c, c) for c in w)
    return w


def norm_line(t: str, shifted: bool = False) -> str:
    t = unicodedata.normalize('NFC', t)
    if shifted:
        t = ''.join(SHIFT.get(c, c) for c in t)
    t = ''.join(LOOK.get(c, c) for c in t)
    # control and format characters (U+0001 etc. from unmapped glyphs, C1 controls, bidi marks) carry no text
    t = ''.join(' ' if unicodedata.category(c) in ('Cc', 'Zl', 'Zp') else '' if unicodedata.category(c) == 'Cf'
                else c for c in t)
    t = WORD.sub(lambda m: fix_word(m.group(0)), t)
    t = t.replace('“', '«').replace('”', '»').replace('„', '«')
    t = re.sub(r'[ \t]+', ' ', t).strip()
    return t


def doc_shifted(lines: list[str]) -> bool:
    """The whole document uses the shifted map when U+03A2 (never a real character) appears in it at least twice."""
    return sum(t.count('\u03a2') for t in lines) >= 2
