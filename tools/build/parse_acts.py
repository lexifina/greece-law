"""Greece: every law (νόμος) published in series Α΄ of the Government Gazette (ΦΕΚ) since 2000, as published.

Reads only local inputs and writes corpus.d parts (SCHEMA.md in scripts/gitlaw_common). No network. Deterministic:
the same inputs give the same bytes.

    python -X utf8 parse_acts.py --src <folder> --retrieved YYYY-MM-DD [--report holds.jsonl]

<folder> holds:
- issues.jsonl: one row per ΦΕΚ Α΄ issue from the National Printing Office's search index (search.et.gr):
  {"year", "num", "id", "issue_date", "pub_date", "pages", "label"};
- fek.jsonl: one row per issue fetched: {"year", "num", "status" (200 or 404), "sha256", ...};
- dumps/<year>/<num>.json.gz: the text layer of each issue PDF, as fek_text.py writes it;
- timeline.jsonl: per issue, the index's relations (search.et.gr /timeline/<id>/0):
  {"year", "num", "id", "n", "rows": [[other issue label, relation type id, direction], ...]}.

What becomes an act: a law (ΝΟΜΟΣ ΥΠ' ΑΡΙΘΜ. N) printed in a ΦΕΚ Α΄ issue, from its title to the order to publish
("Παραγγέλλομε τη δημοσίευση ..."): its articles, the headings before them and its annexes. The President's
enacting formula, the signatures and the Gazette's own furniture are not part of the text. One version, the law as
published, from the day its own commencement clause names.

A law is held back, not published, when any of these is true (the reason goes to the report):
- a later ΦΕΚ Α΄ text cites its number in an article (or title, or erratum) that amends, replaces, repeals, adds to,
  corrects, extends, suspends or interprets something: its text today may differ from the text as published;
- the National Printing Office's index records a later ΦΕΚ Α΄ document as amending, replacing or invalidating its
  issue (or records 100 relations or more, the most it lists), or its relations have not been read;
- it is a code (its title names a Κώδικας): codes are amended under their own names;
- every later ΦΕΚ Α΄ issue has not been read (the citation scan would be incomplete), or a later issue has no text
  layer;
- its pages hold images or pages without text (part of its text would be missing), or two columns in different
  languages (the reading order would interleave them);
- its articles do not run 1, 2, 3, ... without gaps or repeats, or the enacting formula or the order to publish is
  missing;
- its commencement clause is missing or unreadable, or names a day before the law's publication day, or the masthead
  day differs from the index's issue day.

One exception to the first two rules: a law or decree that one later law or decree repeals as a whole, and that nothing
else changes, is published with a second, empty version on the repeal day, credited to the repealing act. Every
citation of it in that act's changing passages must repeal it whole ('καταργείται', the act alone in its item, no
article or part named, no exception, no day of its own; a heading 'Κατάργηση του ...' may name it too), the index may
record no other later document changing its issue, and the repeal day is the repealing act's own commencement day,
read without exceptions (a stated day only when nothing later amends the repealing act).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "corpus.d"
BLOB = "https://ia37rg02wpsa01.blob.core.windows.net/fek/01/{y}/{y}01{n:05d}.pdf"
KIND = "nomos"
PD_KIND = "diatagma"

# ---------------------------------------------------------------- text normalisation

LEGACY_EXTRA = set("–—‘’“”…€‚„†‡ˆ‰Š‹ŒŽ•˜™š›œžŸ")


def legacy_decode(s: str) -> str:
    """Issues set in the old Greek fonts hold Windows-1253 bytes in their text layer, read as Latin-1 (or Windows-1252
    for 0x80-0x9F). Map them back. Byte 0x88, undefined in Windows-1253, is those fonts' ano teleia."""
    out = []
    for ch in s:
        o = ord(ch)
        if o == 0x88:
            out.append("·")
        elif 0x80 <= o <= 0xFF:
            try:
                out.append(bytes([o]).decode("cp1253"))
            except UnicodeDecodeError:
                out.append(ch)
        elif ch in LEGACY_EXTRA:
            try:
                out.append(ch.encode("cp1252").decode("cp1253"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
LATIN1_HIGH = re.compile(r"[À-þ]")
LOOK = {"A": "Α", "B": "Β", "E": "Ε", "Z": "Ζ", "H": "Η", "I": "Ι", "K": "Κ", "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ",
        "T": "Τ", "Y": "Υ", "X": "Χ", "o": "ο", "v": "ν", "∆": "Δ", "µ": "μ", "Ω": "Ω"}
WORD = re.compile(r"[A-Za-zͰ-Ͽἀ-῿∆µΩ]+")
APOS = str.maketrans({"΄": "’", "'": "’", "ʹ": "’", "‘": "’", "´": "’", "`": "’", "ʼ": "’"})


def fix_word(m: re.Match) -> str:
    w = m.group(0)
    if GREEK.search(w) and all(c in LOOK or GREEK.match(c) for c in w):
        return "".join(LOOK.get(c, c) for c in w)
    return w


def norm_line(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\xa0", " ").replace("\t", " ").replace("−", "-").replace("‐", "-").replace("\xad", "-")
    s = s.translate(APOS)
    s = WORD.sub(fix_word, s)
    # a lone Latin capital used as a Greek numeral or issue letter: (A’ 48), Β’ τάξη
    s = re.sub(r"(?<![A-Za-z])([ABEZHIKMNOPTYX])(?=’)", lambda m: LOOK[m.group(1)], s)
    # a short all-capital look-alike word next to a Greek word: (EE) for (ΕΕ); Roman numerals (II) stay
    s = re.sub(r"(?<![A-Za-z0-9])([ABEZHKMNOPTYX][ABEZHIKMNOPTYX]{1,3})(?![A-Za-z0-9])(?=[)»,.;:]?\s+[Ͱ-Ͽ]|[)»]?\s+\d{4}/)",
               lambda m: "".join(LOOK[c] for c in m.group(1)), s)
    s = re.sub(r"(?<=[Ͱ-Ͽ]\s\()([ABEZHKMNOPTYX][ABEZHIKMNOPTYX]{1,3})(?=\))", lambda m: "".join(LOOK[c] for c in m.group(1)), s)
    # a lone look-alike letter between Greek words: O ΠΡΟΕΔΡΟΣ, o νόμος
    s = re.sub(r"(?<![A-Za-z0-9.])([ABEZHIKMNOPTYXo])(?=\s+[Ͱ-Ͽ])", lambda m: LOOK[m.group(1)], s)
    s = re.sub(r"(?<=[Ͱ-Ͽ]\s)([ABEZHIKMNOPTYXo])(?![A-Za-z0-9])", lambda m: LOOK[m.group(1)], s)
    # the old Greek fonts set an accented capital as an accent mark before the letter: ’Αρθρο, ’Εναρξη
    s = re.sub(r"(?<![^\s«(\"“])’ ?([ΑΕΗΙΟΥΩ])(?=[α-ωάέήίόύώϊϋΐΰς])", lambda m: ACCENTED[m.group(1)], s)
    return re.sub(r"\s+", " ", s).strip()


ACCENTED = {"Α": "Ά", "Ε": "Έ", "Η": "Ή", "Ι": "Ί", "Ο": "Ό", "Υ": "Ύ", "Ω": "Ώ"}


def fold(s: str) -> str:
    """Lower case without accents, for matching only."""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("ς", "σ")


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*[–—]\s*", " – ", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s+([,.;:·])(?=\s|$)", r"\1", s)
    s = re.sub(r"«\s+", "«", s)
    s = re.sub(r"\s+»", "»", s)
    return s


MONTHS = {fold(m): i for i, m in enumerate(["Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
                                             "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου",
                                             "Δεκεμβρίου"], 1)}
DAY_RE = re.compile(r"(\d{1,2})(?:η|ης)?\s+([Α-Ωα-ωάέήίόύώϊϋΐΰ]+)\s*(\d{4})")


def text_day(s: str) -> str | None:
    m = DAY_RE.search(s)
    if not m or fold(m.group(2)) not in MONTHS:
        return None
    try:
        return date(int(m.group(3)), MONTHS[fold(m.group(2))], int(m.group(1))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- PDF text layer to lines in reading order

JUNK = [re.compile(p) for p in (
    r"^ΕΦΗΜΕΡΙ(?:Σ|ΔΑ)\s+ΤΗΣ\s+ΚΥΒΕΡΝΗΣΕΩΣ", r"^ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ$", r"^ΕΦΗΜΕΡΙ(?:Σ|ΔΑ)$", r"^ΤΕΥΧΟΣ ΠΡΩΤΟ",
    r"^Τεύχος Α’ \d+/", r"^\(?ΤΕΥΧΟΣ ΠΡΩΤΟ\)?$", r"^\*[0-9]{10,}\*$")]
END_OF_ISSUE = re.compile(r"^(?:Το Εθνικό Τυπογραφείο αποτελεί δημόσια υπηρεσία|ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ$)")


class Line:
    __slots__ = ("page", "x0", "y0", "x1", "size", "bold", "t", "left", "right", "col")

    def __init__(self, page, x0, y0, x1, size, bold, t):
        self.page, self.x0, self.y0, self.x1, self.size, self.bold, self.t = page, x0, y0, x1, size, bold, t
        self.left = self.right = 0.0
        self.col = 0


def issue_lines(dump: dict) -> tuple[list[Line], dict]:
    """Body lines of one issue in reading order, and facts about the issue (masthead day, page images, ...)."""
    raw = [l[6] for p in dump["pages"] for l in p["lines"]]
    legacy = sum(len(LATIN1_HIGH.findall(t)) for t in raw) > sum(len(GREEK.findall(t)) for t in raw)
    facts = {"legacy": legacy, "pages": len(dump["pages"]), "img_pages": set(), "empty_pages": set(),
             "masthead_day": None, "masthead_num": None, "bilingual_pages": set(), "latin_pages": set()}
    out: list[Line] = []
    held: list[tuple[list[Line], float]] = []
    ended = False
    for pno, p in enumerate(dump["pages"]):
        if any(im[3] > 115 for im in p.get("img", [])):   # the signature stamp sits in the top margin
            facts["img_pages"].add(pno)
        w, h = p["w"], p["h"]
        lines = []
        for x0, y0, x1, y1, size, bold, t in p["lines"]:
            if legacy and not GREEK.search(t):
                t = legacy_decode(t)
            if legacy:
                t = t.replace("~", "’")   # those fonts' accent and numeral sign: υπ~ αριθμ., (Α~ 12), ~Αρθρο
            t = norm_line(t)
            if not t or size < 6:
                continue
            if pno == 0 and y0 < 300:
                if facts["masthead_num"] is None:
                    m = re.match(r"^Αρ\.\s*Φύλλου\s*(\d+)", t)
                    if m:
                        facts["masthead_num"] = int(m.group(1))
                        continue
                if facts["masthead_day"] is None and re.fullmatch(r"\d{1,2}\s+\S+\s+\d{4}", t) and text_day(t):
                    facts["masthead_day"] = text_day(t)
                    continue
                if size > 13 or re.match(r"^(?:ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ|Αρ\.\s*Φύλλου)", t) and size > 11.5:
                    continue
            if y1 <= 76 or any(j.search(t) for j in JUNK):
                continue
            if size < 8 and y0 > h - 80:
                continue
            if END_OF_ISSUE.match(t):
                ended = True
                break
            lines.append(Line(pno, x0, y0, x1, size, bold, t))
        if not lines and not ended:
            facts["empty_pages"].add(pno)
        pt = " ".join(l.t for l in lines)
        g, la = len(GREEK.findall(pt)), len(re.findall(r"[A-Za-z]", pt))
        if la > g and la > 100:
            facts["latin_pages"].add(pno)   # a foreign-language page, or a text layer that is not real text
        held.append((lines, w))
        if ended:
            break
    # Pages that are clearly two justified columns decide for the ambiguous ones (tables in both columns).
    verdicts = [page_columns(lines, w)[3] for lines, w in held]
    clear = [v for v, (lines, _) in zip(verdicts, held) if len(lines) >= 20]
    mostly_two = bool(clear) and sum(clear) * 2 > len(clear)
    for lines, w in held:
        out.extend(order_page(lines, w, facts, mostly_two))
    return out, facts


def mode_left(lines: list[Line]) -> float:
    if len(lines) < 3:
        return min((l.x0 for l in lines), default=0)
    c = Counter(round(l.x0) for l in lines)
    best = max(c.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    # the continuation margin is the leftmost frequent x0
    cands = [x for x, n in c.items() if n >= min(c[best], max(2, c[best] // 3))]
    return float(min(cands))


def gutter(lines: list[Line], w: float) -> float:
    """The x between two columns: most lines end left of it or start right of it (the columns need not be centred)."""
    cands = sorted({round(l.x1 + 1) for l in lines if 0.35 * w < l.x1 < 0.65 * w}
                   | {round(l.x0 - 1) for l in lines if 0.35 * w < l.x0 < 0.65 * w})
    best, best_score = w / 2, -1
    for x in cands:
        score = sum(1 for l in lines if l.x1 <= x + 3 or l.x0 >= x - 3)
        if score > best_score or (score == best_score and abs(x - w / 2) < abs(best - w / 2)):
            best, best_score = x, score
    return best


def page_columns(lines: list[Line], w: float) -> tuple[list[Line], list[Line], list[Line], bool]:
    """(left column, right column, lines across both, whether the page is set in two justified columns)."""
    if not lines:
        return [], [], [], False
    mid = gutter(lines, w)
    L = [l for l in lines if l.x1 <= mid + 3]
    R = [l for l in lines if l.x0 >= mid - 3 and l not in L]
    S = [l for l in lines if l not in L and l not in R]
    two = False
    if len(L) >= 5 and len(R) >= 5:
        # the left column's lines end at one x, the right column's start at one x
        lx = max(l.x1 for l in L)
        rx = mode_left(R)
        two = (sum(1 for l in L if lx - l.x1 < 3) >= max(4, 0.3 * len(L))
               and sum(1 for l in R if abs(l.x0 - rx) < 3) >= max(4, 0.3 * len(R)))
    return L, R, S, two


def order_page(lines: list[Line], w: float, facts: dict, mostly_two: bool = False) -> list[Line]:
    if not lines:
        return []
    L, R, S, two = page_columns(lines, w)
    if not two and mostly_two and len(L) >= 3 and len(R) >= 3 and len(S) < 0.5 * len(lines):
        two = True
    if not two:
        cols = [sorted(lines, key=lambda l: (round(l.y0), l.x0))]
        left = mode_left(lines)
        right = max(l.x1 for l in lines)
        for l in lines:
            l.left, l.right, l.col = left, right, 0
        seq = cols[0]
    else:
        ll, rl = mode_left(L), mode_left(R)
        lr, rr = max((l.x1 for l in L), default=w / 2), max((l.x1 for l in R), default=w)
        for l in L:
            l.left, l.right, l.col = ll, lr, 1
        for l in R:
            l.left, l.right, l.col = rl, rr, 2
        for l in S:
            l.left, l.right, l.col = min(ll, rl), max(lr, rr), 0
        # bands between spanning lines: left column then right column within each band
        S.sort(key=lambda l: l.y0)
        seq, cuts = [], [l.y0 for l in S] + [1e9]
        lo = -1e9
        si = 0
        for cut in cuts:
            band = [l for l in L if lo <= l.y0 < cut], [l for l in R if lo <= l.y0 < cut]
            for col in band:
                seq.extend(sorted(col, key=lambda l: (round(l.y0), l.x0)))
            if si < len(S):
                seq.append(S[si])
                si += 1
            lo = cut
        # two columns in two languages: Latin letters dominate one, Greek the other
        def share(col):
            t = " ".join(l.t for l in col)
            g, la = len(GREEK.findall(t)), len(re.findall(r"[A-Za-z]", t))
            return g, la
        (g1, a1), (g2, a2) = share(L), share(R)
        if (a1 > 3 * g1 and g2 > 3 * a2 and a1 > 200 and g2 > 200) or (a2 > 3 * g2 and g1 > 3 * a1 and a2 > 200 and g1 > 200):
            facts["bilingual_pages"].add(lines[0].page)
    # cells of one table row: same column, same baseline
    merged: list[Line] = []
    for l in seq:
        if merged and merged[-1].col == l.col and merged[-1].page == l.page and abs(merged[-1].y0 - l.y0) < 2 \
                and l.x0 > merged[-1].x1 - 1:
            m = merged[-1]
            m.t = m.t + " " + l.t
            m.x1 = l.x1
        else:
            merged.append(l)
    return merged


# ---------------------------------------------------------------- lines to paragraphs

LOWER_START = re.compile(r"^[a-zα-ωάέήίόύώϊϋΐΰς]")
UPPER_START = re.compile(r"^[A-ZΑ-ΩΆΈΉΊΌΎΏΪΫ]")


class Para:
    __slots__ = ("t", "centered", "bold", "page", "first")

    def __init__(self, t, centered, bold, page):
        self.t, self.centered, self.bold, self.page = t, centered, bold, page


def join_lines(parts: list[str], vocab: set[str]) -> str:
    s = ""
    for t in parts:
        if not s:
            s = t
            continue
        m = re.search(r"([A-Za-zΑ-Ωα-ωάέήίόύώϊϋΐΰςΆΈΉΊΌΎΏ]+)-$", s)
        if m and (LOWER_START.match(t) or (m.group(1).isupper() and UPPER_START.match(t))):
            head = m.group(1)
            tail = re.match(r"[^\s,.;:·»)]+", t).group(0) if re.match(r"[^\s,.;:·»)]+", t) else ""
            if fold(head + "-" + tail) in vocab and fold(head + tail) not in vocab:
                s = s + t  # a compound word with its own hyphen
            else:
                s = s[:-1] + t
        else:
            s = s + " " + t
    return s


def paragraphs(lines: list[Line], vocab: set[str]) -> list[Para]:
    out: list[Para] = []
    cur: list[Line] = []

    def flush():
        if cur:
            c = cur[0]
            out.append(Para(tidy(join_lines([l.t for l in cur], vocab)), is_centered(c), all(l.bold for l in cur), c.page))
            cur.clear()

    for l in lines:
        indent = l.x0 - l.left
        if not cur:
            start = True
        elif is_centered(l) and is_centered(cur[-1]) and l.bold == cur[-1].bold and l.page == cur[-1].page                 and 0 < l.y0 - cur[-1].y0 < 1.6 * max(l.size, 6) and not KEY_START.match(l.t)                 and not KEY_ALONE.match(cur[-1].t) and not KEY_ALONE.match(cur[0].t):
            start = False   # a heading or title set over several centred lines
        else:
            start = (indent > 2.5 or is_centered(cur[-1]) or is_centered(l) or KEY_START.match(l.t) is not None
                     or (l.col == 0) != (cur[-1].col == 0) or l.bold != cur[-1].bold
                     or KEY_ALONE.match(cur[-1].t) is not None or ENACT.match(cur[0].t) is not None
                     or TOC.match(cur[-1].t) is not None)
        # otherwise a paragraph runs on into the next column or page
        if start:
            flush()
        cur.append(l)
    flush()
    return out


KEY_START = re.compile(r"^(?:Παραγγέλλομε τη δημοσίευση|Εκδίδομε τον ακόλουθο|(?:Ο|Η) ΠΡΟΕΔΡΟΣ|ΝΟΜΟΣ ΥΠ|Αθήνα,|«?(?:Άρθρο|ΆΡΘΡΟ|ΑΡΘΡΟ)\s+\S+\s*$"
                       r"|(?:Άρθρο|ΆΡΘΡΟ|ΑΡΘΡΟ)\s|ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ"
                       r"|ΜΕΡΟΣ\b|ΚΕΦΑΛΑΙΟ\b|ΤΜΗΜΑ\b|ΠΑΡΑΡΤΗΜΑ\b|ΤΙΤΛΟΣ\b|ΕΝΟΤΗΤΑ\b|ΥΠΟΚΕΦΑΛΑΙΟ\b|ΒΙΒΛΙΟ\b)")
KEY_ALONE = re.compile(r"^(?:«?(?:Άρθρο|ΆΡΘΡΟ|ΑΡΘΡΟ)\s+\S+(?:\s+\S+){0,3}|(?:ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΠΑΡΑΡΤΗΜΑ|ΤΙΤΛΟΣ|ΕΝΟΤΗΤΑ|ΥΠΟΚΕΦΑΛΑΙΟ|ΒΙΒΛΙΟ)"
                       r"(?:\s+\S+){0,2}|ΝΟΜΟΣ ΥΠ.*|(?:Ο|Η) ΠΡΟΕΔΡΟΣ.*)$")


def is_centered(l: Line) -> bool:
    return (l.x0 - l.left) >= 20 and (l.right - l.x1) >= 8


def vocabulary(lines: list[Line]) -> set[str]:
    v = set()
    for l in lines:
        ws = l.t.split()
        for w in ws[:-1]:
            v.add(fold(w.strip(",.;:·«»()")))
    return v


# ---------------------------------------------------------------- documents in an issue

LAW_HEAD = re.compile(r"^ΝΟΜΟΣ\s+ΥΠ[’]?\s*ΑΡΙΘ(?:Μ)?\.?\s*(\d{1,4})\.?$")
OTHER_HEAD = re.compile(r"^(?:ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ|ΠΡΟΕΔΡΙΚΑ ΔΙΑΤΑΓΜΑΤΑ|ΠΡΑΞΗ ΝΟΜΟΘΕΤΙΚΟΥ ΠΕΡΙΕΧΟΜΕΝΟΥ|ΠΡΑΞΕΙΣ ΝΟΜΟΘΕΤΙΚΟΥ"
                        r"|ΑΠΟΦΑΣΕΙΣ|ΑΠΟΦΑΣΗ|ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ|ΔΙΟΡΘΩΣΗ ΣΦΑΛΜΑΤ|ΚΑΝΟΝΙΣΜΟΙ|ΚΑΝΟΝΙΣΜΟΣ|ΠΕΡΙΕΧΟΜΕΝΑ"
                        r"|ΨΗΦΙΣΜΑ|ΑΝΑΚΟΙΝΩΣΕΙΣ|ΑΝΑΚΟΙΝΩΣΗ|ΠΡΑΞΕΙΣ ΥΠΟΥΡΓΙΚΟΥ ΣΥΜΒΟΥΛΙΟΥ|ΠΡΑΞΗ ΥΠΟΥΡΓΙΚΟΥ ΣΥΜΒΟΥΛΙΟΥ"
                        r"|ΔΙΑΤΑΓΜΑ|ΕΓΚΥΚΛΙΟΣ|ΣΥΝΤΑΓΜΑ)\b")
ENACT = re.compile(r"^Εκδίδομε\s+τον\s+(?:ακόλουθο\s+)?νόμο")
ORDER = re.compile(r"^Παραγγέλλομε\s+τη(?:ν)?\s+δημοσίευσ")
ORDER_ANY = re.compile(r"^Παραγγέλλ?ομε\s+τη(?:ν)?\s+δημοσίευσ")   # also misprinted 'Παραγγέλομε'


def law_order(paras: list) -> re.Pattern:
    """The order to publish of a law: 'Παραγγέλλομε ...', or the misprint 'Παραγγέλομε' when the law has no other."""
    return ORDER if any(ORDER.match(p.t) for p in paras) else ORDER_ANY
PRESIDENT = re.compile(r"^(?:Ο|Η)\s+ΠΡΟΕΔΡΟΣ(?:\s+ΤΗΣ\s+ΕΛΛΗΝΙΚΗΣ\s+ΔΗΜΟΚΡΑΤΙΑΣ)?$")
ATHENS = re.compile(r"^(?:Αθήνα|Αθήναι),?\s+")
# the place and day under the President's signature: 'Αθήνα, 9 Νοεμβρίου 2011', 'Ρίο, 10 Αυγούστου 2000', 'Αθήνα,12 ...'
PLACE_DAY = re.compile(r"^[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+(?:[\s-][Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]+)?\s*,\s*\d{1,2}")
CORRECTIONS = re.compile(r"^ΔΙΟΡΘΩΣ")
# A presidential decree: its considerations end with the decision formula, its text with the order to publish.
PD_HEAD = re.compile(r"^ΠΡΟΕΔΡΙΚΟ\s+ΔΙΑΤΑΓΜΑ\s+ΥΠ[’]?\s*ΑΡΙΘ(?:Μ)?\.?\s*(\d{1,4})\.?$")
DECIDE = re.compile(r"\b(?:αποφασίζουμε|αποφασίζομε|αποφασίζομεν)\s*[:,]?\s*$", re.I)
PD_ORDER = re.compile(r"^(?:\d{1,2}\.\s*)?(?:(?:Στον|Στην|Στους|Στις|Εις τον|Εις τους)\s.{0,300}?\b(?:αναθέτουμε\s+τη(?:ν)?\s+δημοσίευ"
                      r"|ανατίθεται\s+η\s+δημοσίευση)|Η\s+δημοσίευση\s+και\s+(?:η\s+)?εκτέλεση\s+του\s+παρόντος.{0,60}?\bανατίθεται\b)")
# an order to publish printed on in the paragraph before it (no indent): '... Κυβερνήσεως. Στον Υπουργό ... αναθέτουμε ...'
ORDER_INSIDE = {"law": re.compile(r"(?<=[.·])\s+(Παραγγέλλομε\s+τη(?:ν)?\s+δημοσίευσ.*)$"),
                "pd": re.compile(r"(?<=[.·])\s+((?:Στον|Στην|Στους|Στις)\s[^.«»]{0,300}?\bαναθέτουμε\s+τη(?:ν)?\s+δημοσίευ.*)$")}


def split_order(paras: list, kind: str) -> list:
    """A document whose order to publish has no paragraph of its own: split it off the paragraph that holds it."""
    end_rx = ORDER_ANY if kind == "law" else PD_ORDER
    if any(end_rx.match(p.t) for p in paras):
        return paras
    for i in range(len(paras) - 1, -1, -1):
        m = ORDER_INSIDE[kind].search(paras[i].t)
        if m and end_rx.match(m.group(1)):
            p = paras[i]
            a, b = Para(p.t[:m.start()].rstrip(), p.centered, p.bold, p.page), Para(m.group(1), p.centered, p.bold, p.page)
            return paras[:i] + [a, b] + paras[i + 1:]
    return paras


def documents(paras: list[Para]) -> list[dict]:
    """Split an issue into its documents: {"kind": "law"|"other"|"preface", "num", "paras"}."""
    docs = [{"kind": "preface", "num": None, "head": "", "paras": []}]
    in_law_body = False
    for p in paras:
        m = LAW_HEAD.match(p.t)
        if m and not in_law_body:
            docs.append({"kind": "law", "num": int(m.group(1)), "head": p.t, "paras": []})
            in_law_body = True
            continue
        m = PD_HEAD.match(p.t)
        if m and not in_law_body:
            docs.append({"kind": "pd", "num": int(m.group(1)), "head": p.t, "paras": []})
            continue
        if OTHER_HEAD.match(p.t) and len(p.t) < 120 and not in_law_body:
            docs.append({"kind": "corrections" if CORRECTIONS.match(p.t) else "other", "num": None, "head": p.t, "paras": []})
            continue
        docs[-1]["paras"].append(p)
        if in_law_body and ORDER_ANY.match(p.t):
            in_law_body = False
    return docs


# ---------------------------------------------------------------- one law to units

ORD = {"πρωτο": 1, "δευτερο": 2, "τριτο": 3, "τεταρτο": 4, "πεμπτο": 5, "εκτο": 6, "εβδομο": 7, "ογδοο": 8, "ενατο": 9,
       "δεκατο": 10, "ενδεκατο": 11, "δωδεκατο": 12, "εικοστο": 20, "τριακοστο": 30, "τεσσαρακοστο": 40,
       "πεντηκοστο": 50, "εξηκοστο": 60, "εβδομηκοστο": 70, "ογδοηκοστο": 80, "ενενηκοστο": 90, "εκατοστο": 100,
       "διακοσιοστο": 200}
ART_HEAD = re.compile(r"^(?:Άρθρο|ΑΡΘΡΟ)\s+(.{1,40})$", re.I)
ART_ALONE = re.compile(r"^(?:Άρθρο|ΆΡΘΡΟ|ΑΡΘΡΟ)\s+(\d{1,3}[Α-Ωα-ω]?|[^\W\d]+(?:\s+[^\W\d]+){0,3})\.?$")
SQ_OPEN = re.compile(r"^[\"“]")
SQ_CLOSE = re.compile(r"[\"”][.;,]?$")
STRUCT = re.compile(r"^(?:ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΤΙΤΛΟΣ|ΕΝΟΤΗΤΑ|ΥΠΟΚΕΦΑΛΑΙΟ|ΒΙΒΛΙΟ|ΥΠΟΤΜΗΜΑ)\b")
ANNEX = re.compile(r"^ΠΑΡΑΡΤΗΜΑ\b")
TOC = re.compile(r"^ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ$")


def art_number(label: str) -> tuple[str, int, str] | None:
    """('num'|'word'|'sole', number, suffix) for an article heading's label, or None."""
    f = re.sub(r"\s*\([^()]*\)$", "", fold(label).strip(" .")).strip(" .")   # 'Άρθρο 1 (άρθρο 1 οδηγίας)'
    m = re.fullmatch(r"(\d{1,3})\s*(?:ο|ον)", f)   # 'Άρθρο 1ο': an ordinal, not a letter
    if m:
        return "num", int(m.group(1)), ""
    m = re.fullmatch(r"(\d{1,3})\s*([α-ω]?)", f)
    if m:
        return "num", int(m.group(1)), m.group(2)
    if f == "μονο":
        return "sole", 1, ""
    words = f.split()
    if words and all(w in ORD for w in words):
        n = sum(ORD[w] for w in words)
        return "word", n, ""
    return None


class Hold(Exception):
    pass


def quote_delta(t: str) -> int:
    return t.count("«") - t.count("»")


def law_units(paras: list[Para], vocab: set[str] = frozenset(), kind: str = "law") -> tuple[str, dict, list[str]]:
    """(title, units, body paragraphs outside quotations) for one law's (or decree's) paragraphs."""
    i_pres = next((i for i, p in enumerate(paras) if PRESIDENT.match(p.t)), None)
    start_rx, end_rx = (ENACT, law_order(paras)) if kind == "law" else (DECIDE, PD_ORDER)
    i_enact = [i for i, p in enumerate(paras) if (start_rx.match(p.t) if kind == "law" else start_rx.search(p.t))]
    i_order = [i for i, p in enumerate(paras) if end_rx.match(p.t)]
    if i_pres is None or len(i_enact) != 1 or len(i_order) != 1 or not (i_pres < i_enact[0] < i_order[0]):
        raise Hold("structure:formula")
    title = tidy(join_lines([p.t for p in paras[:i_pres]], vocab))
    if not title:
        raise Hold("structure:no_title")
    body = paras[i_enact[0] + 1:i_order[0]]
    units: dict[str, dict] = {}
    if kind == "pd":
        # the decree's considerations ("Έχοντας υπόψη: ... αποφασίζουμε:") are part of its text
        considered = [p.t for p in paras[i_pres + 1:i_enact[0] + 1] if not PRESIDENT.match(p.t)
                      and not re.fullmatch(r"ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ", p.t)]
        units["prooimio"] = {"label": "Προοίμιο", "kind": "preamble", "lines": considered}
    order: list[str] = ["prooimio"] if units else []
    pending: list[str] = []
    cur = None
    mode = None
    depth = 0
    numbers = []
    plain: list[str] = []   # body paragraphs with quotations cut, for the commencement clause
    expect_title = False
    in_toc = False
    annex_n = 0
    bold_heads = None
    sq = False   # inside a quotation set in straight double quotes ("...") as old issues print them
    sq_skipped = False
    for p in body:
        t = p.t
        top = depth == 0
        depth = max(0, depth + quote_delta(t))
        in_sq = sq or bool(SQ_OPEN.match(t))
        if SQ_OPEN.match(t) and not (len(t) > 1 and SQ_CLOSE.search(t)):
            sq = True
        elif sq and SQ_CLOSE.search(t):
            sq = False
        heading_like = p.centered or p.bold
        a = None
        m = ART_HEAD.match(t) if heading_like and (bold_heads is None or p.bold == bold_heads) else None
        alone = False
        if (not m and top and numbers and not in_toc and p.bold == bold_heads and ART_ALONE.match(t)
                and not (mode == "num" and re.search(r"[Κκ]υρώνεται|[Κκ]υρούται", " ".join(units[cur]["lines"])))):
            # 'Άρθρο N' alone in its paragraph but not set as a heading (an odd margin): this law's own next
            # article only when it is exactly the next number
            m, alone = ART_ALONE.match(t), True
        if m:
            a = art_number(m.group(1))
            if a and mode is not None and a[0] != mode and mode != "sole":
                a = None    # a heading of the text an article quotes or ratifies (Άρθρο 1 inside Άρθρο πρώτο)
        if a:
            sfx = ord(a[2]) - ord("α") + 1 if a[2] else 0
            prev = numbers[-1] if numbers else None
            # the next article: n+1, or n with the next letter (an article inserted during the vote: 73, 73Α, 74)
            follows = (a[1], sfx) == (1, 0) if prev is None else \
                (a[1], sfx) in ((prev[0] + 1, 0), (prev[0], prev[1] + 1))
            if alone and not follows:
                a = None
            elif not top:
                # Inside a quotation by the count of «», which a misprint can upset: take it as this law's own next
                # article only when it is bold like this law's own headings; otherwise it is quoted text.
                if not (follows and not sfx and bold_heads):
                    a = None
            elif in_sq and not follows:
                a = None    # a heading of the text an article quotes in straight quotes
                sq_skipped = sq   # ... which must close before this law's next article
            elif not follows:
                raise Hold("articles:sequence " + ",".join(f"{n}{'+' * s}" for n, s in numbers[-5:]) + " then " + t)
        if not sq:
            sq_skipped = False
        if a:
            if sq_skipped:
                raise Hold("articles:quote_unclosed " + t)
            if mode is None:
                mode = a[0]
                bold_heads = p.bold
            depth = 0   # a quotation never runs over this law's own article heading
            sq = False
            numbers.append((a[1], sfx))
            key = f"art-{a[1]:03d}" + (f"-{sfx:02d}" if sfx else "")
            if key in units:
                raise Hold("articles:repeat " + t)
            units[key] = {"label": t, "kind": "art", "lines": pending + [t]}
            pending = []
            order.append(key)
            cur = key
            expect_title = True
            in_toc = False
            continue
        if top and heading_like and ANNEX.match(t) and cur is not None:
            annex_n += 1
            key = f"parartima-{annex_n:02d}"
            units[key] = {"label": t, "kind": "annex", "lines": pending + [t]}
            pending = []
            order.append(key)
            cur = key
            expect_title = True
            continue
        if top and heading_like and STRUCT.match(t) and len(t) < 300:
            pending.append(t)
            expect_title = False
            in_toc = False
            continue
        if top and pending and heading_like and cur is None or (top and pending and heading_like and not expect_title
                                                                 and units.get(cur, {}).get("kind") != "annex"
                                                                 and t.upper() == t and len(t) < 300):
            pending.append(t)   # the title of a part or chapter heading
            continue
        if top and TOC.match(t) and cur is None:
            in_toc = True
        if expect_title and top and heading_like:
            ls = units[cur]["lines"]
            if ls[-1] == units[cur]["label"]:
                ls.append(t)
            else:
                ls[-1] = tidy(join_lines([ls[-1], t], vocab))   # a title set over several lines
            continue
        expect_title = False
        if cur is None:
            units.setdefault("prooimio", {"label": "Πίνακας περιεχομένων" if in_toc else "Προοίμιο", "kind": "preamble",
                                          "lines": []})
            if "prooimio" not in order:
                order.append("prooimio")
            units["prooimio"]["lines"].extend(pending + [t])
            pending = []
        else:
            if pending:
                units[cur]["lines"].extend(pending)
                pending = []
            units[cur]["lines"].append(t)
        if top and not in_sq:
            plain.append(re.sub(r"«[^«»]*»?", " ", t))
    if pending and cur:
        units[cur]["lines"].extend(pending)
    if sq_skipped:
        raise Hold("articles:quote_unclosed")
    if not numbers:
        raise Hold("articles:none")
    if mode == "sole" and numbers != [(1, 0)]:
        raise Hold("articles:sole_and_more")
    # The table of contents, when the law prints one, must list exactly the articles read.
    toc = []
    for m in re.finditer(r"(?:^|\s)Άρθρο\s+(\d{1,3}[Α-Ωα-ω]?|[^\W\d]+(?:\s+[^\W\d]+){0,3})(?=[\s:.]|$)",
                         "\n".join(units.get("prooimio", {}).get("lines", []))):
        words = m.group(1).split()
        for k in (4, 3, 2, 1):   # 'εκατοστό δέκατο τρίτο' before 'εκατοστό'
            a = art_number(" ".join(words[:k]))
            if a:
                break
        if a and a[0] == mode:
            toc.append((a[1], ord(a[2]) - ord("α") + 1 if a[2] else 0))
    if toc and kind == "law":
        # Every article read is listed, in order; the table may also list the articles this law inserts into others
        # (Άρθρο 109, 110, ... under Άρθρο 3), but nothing after the last article read may continue its numbering.
        j, at = 0, -1
        for i, x in enumerate(toc):
            if j < len(numbers) and x == numbers[j]:
                j, at = j + 1, i
        last = numbers[-1]
        if j < len(numbers) or any(x in ((last[0] + 1, 0), (last[0], last[1] + 1)) for x in toc[at + 1:]):
            raise Hold(f"toc_mismatch:{len(set(toc))} listed, {len(numbers)} read")
    out = {}
    for k in order:
        u = units[k]
        if u["lines"]:
            out[k] = {"label": u["label"], "kind": u["kind"], "text": "\n".join(u["lines"]) + "\n"}
    return title, out, plain


# ---------------------------------------------------------------- commencement

_REST = r"(?P<rest>[^.]{0,220}(?:\.\d[^.]{0,200})*)"
# the act itself as the subject of its commencement clause (folded text)
_PD = r"(?:προεδρικου\s+διαταγματοσ|διαταγματοσ|π\.?\s*δ\.?\s*/\s*(?:τοσ|γματοσ)|π\.\s*δ\.?|π\.\s*διαταγματοσ)"
_ANY = r"(?:νομου|κωδικα|κανονισμου|οργανισμου|" + _PD + ")"
_OWN = {"law": r"(?:νομου)", "pd": _PD}
IN_FORCE = {k: [
    re.compile(r"(?:εναρξη\s+)?ισχυ(?:οσ|σ)\s+(?:των\s+διαταξεων\s+)?(?:(?:του|το)\s+)?(?:παροντοσ(?:\s+" + _ANY + r")?|" + _ANY
               + r"\s+(?:αυτου|τουτου)|" + own + r")(?:\s*,[^,]{1,80},|\s*,)?\s+(?:αρχιζει|αρχεται|οριζεται)\s+" + _REST),
    re.compile(r"(?:ο\s+|το\s+|οι\s+)?(?:παρων(?:\s+νομοσ)?|νομοσ\s+αυτοσ|παρον(?:\s+(?:προεδρικο\s+)?διαταγμα)?"
               r"|(?:προεδρικο\s+)?διαταγμα\s+αυτο|διαταξεισ\s+του\s+παροντοσ(?:\s+" + _ANY + r")?)\s+(?:ισχυει|ισχυουν"
               r"|τιθεται\s+σε\s+ισχυ|τιθενται\s+σε\s+ισχυ|αρχιζει\s+να\s+ισχυει|αρχιζουν\s+να\s+ισχυουν)\s+"
               r"(?P<rest>(?:απο|με|στισ)\b[^.]{0,220}(?:\.\d[^.]{0,200})*)"),
] for k, own in _OWN.items()}
NUM_DAY = re.compile(r"(?:απο\s+|στισ\s+)?(?:την\s+|τη\s+)?(\d{1,2})(?:η|ησ)?\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})")
WORD_DAY = re.compile(r"(?:απο\s+|στισ\s+)?(?:την\s+|τη\s+)?(\d{1,2})(?:η|ησ)?\s+([α-ω]+)\s+(?:του\s+ετουσ\s+)?(\d{4})")
PUB = re.compile(r"^(?:απο|με)\s+(?:την?\s+|τησ\s+)?(?:ημερομηνια\s+(?:τησ\s+)?)?δημοσιευσ\w*(?:\s+του)?(?:\s+στην\s+εφημεριδα\s+"
                 r"τησ\s+κυβερνησ\w+)?")
# the first day of the month after (or after next) the publication
NEXT_MONTH = re.compile(r"^(?:απο\s+)?(?:την\s+)?πρωτη\s+(?:ημερα\s+)?(?:του\s+)?(?:(?P<w>επομενου|μεθεπομενου)\s+μην(?:α|οσ)\s+"
                        r"(?:απο|μετα)\s+(?:τη|την)|μην(?:α|οσ)\s+του\s+επομενου\s+(?:εκεινου\s+)?τησ)\s+δημοσιευσ\w*"
                        r"(?:\s+του)?(?:\s+στην\s+εφημεριδα\s+τησ\s+κυβερνησ\w+)?")
EXCEPT = re.compile(r"εκτοσ|επιφυλαξ|εξαιρεσ|διαφορετικ|ειδικοτερ|επιμερουσ")
# after the day: words that make it conditional, temporary or retroactive
NOT_PLAIN = re.compile(r"ληγ|ληξ|μεχρι|\bεωσ\b|\bπαυ|αναδρομ|εφοσον|οποτε|μεταγενεστ|προγενεστ|\bη\s+(?:απο|με|κατα|την|τη|στισ)\b")


def commencement(plain: list[str], issue_day: str, kind: str = "law", masthead_day: str | None = None) -> tuple[str, str]:
    found = []
    for para in plain:
        f = fold(para)
        for rx in IN_FORCE["pd" if kind == "pd" else "law"]:
            for m in rx.finditer(f):
                rest = m.group("rest").strip()
                exc = bool(EXCEPT.search(f))
                md = PUB.match(rest)
                if md:
                    if NOT_PLAIN.search(rest[md.end():]):
                        raise Hold("in_force:conditional " + rest[:100])
                    found.append(("publication", issue_day, exc))
                    continue
                md = NEXT_MONTH.match(rest)
                if md:
                    if NOT_PLAIN.search(rest[md.end():]):
                        raise Hold("in_force:conditional " + rest[:100])
                    if masthead_day and masthead_day[:7] != issue_day[:7]:
                        raise Hold("in_force:month_of_publication_unclear " + rest[:80])
                    step = 2 if md.group("w") == "μεθεπομενου" else 1
                    yy, mm = divmod(int(issue_day[5:7]) - 1 + step, 12)
                    found.append(("first_of_month", date(int(issue_day[:4]) + yy, mm + 1, 1).isoformat(), exc))
                    continue
                md = NUM_DAY.match(rest)
                if md:
                    try:
                        day = date(int(md.group(3)), int(md.group(2)), int(md.group(1))).isoformat()
                    except ValueError:
                        raise Hold("in_force:bad_date " + rest[:80])
                    if NOT_PLAIN.search(rest[md.end():]):
                        raise Hold("in_force:conditional " + rest[:100])
                    found.append(("date", day, exc))
                    continue
                md = WORD_DAY.match(rest)
                if md and md.group(2) in MONTHS:
                    if NOT_PLAIN.search(rest[md.end():]):
                        raise Hold("in_force:conditional " + rest[:100])
                    found.append(("date", date(int(md.group(3)), MONTHS[md.group(2)], int(md.group(1))).isoformat(), exc))
                    continue
                raise Hold("in_force:unreadable " + rest[:100])
    if not found:
        raise Hold("in_force:none")
    days = {d for _, d, _ in found}
    if len(days) != 1:
        raise Hold("in_force:conflict " + ",".join(sorted(days)))
    how = found[0][0] + ("+exceptions" if any(e for _, _, e in found) else "")
    return found[0][1], how


# ---------------------------------------------------------------- citation scan (hold rule)

STEMS = re.compile(r"τροποπ|αντικαθ|αντικατασ|καταργ|προστιθ|προστεθ|προσθηκ|συμπληρ|διαγραφ|απαλειφ|αναριθμ|παρατειν"
                   r"|παραταση|αναστελ|αναστολ|διορθ|ερμηνευ|διαμορφων|επερχον|αναδιατυπ|νεα\s+διατυπωσ")
CITE = re.compile(r"(?<![\d/])(\d{4})\s*/\s*(\d{4}|\d{2})(?![\d/])")
# a presidential decree by number (folded text): π.δ. 75/2022, πδ 75/2022, προεδρικου διαταγματοσ 75/2022
PD_CITE = re.compile(r"(?<![α-ω.])(?:π\s*\.\s*δ\s*\.?(?:/τοσ)?|πδ|προεδρικ\w*\s+διαταγματ\w*)\s*(?:υπ[’']?\s*αριθμ?\.?\s*)?"
                     r"(\d{1,4})\s*/\s*(\d{4}|\d{2})(?![\d/])")
# more numbers under the same designation: 'τα π.δ. 1/2000 (Α' 1), 2/2000 «...» και 3/2000'
PD_MORE = re.compile(r"\s*(?:\([^()]{0,60}\)\s*)?(?:«[^«»]{0,400}»\s*)?(?:\([^()]{0,60}\)\s*)?,?\s*(?:,|και|καθωσ\s+και)?\s*"
                     r"(?:το\s+|του\s+)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?![\d/])")


def pd_cites(text: str):
    """Every decree cited in folded text: (number, year as written, start of the number, end, start of its
    designation or -1 for a number listed after another one's designation)."""
    seen = set()
    for m in PD_CITE.finditer(text):
        if m.start(1) not in seen:
            seen.add(m.start(1))
            yield int(m.group(1)), m.group(2), m.start(1), m.end(), m.start()
        pos = m.end()
        while True:
            mm = PD_MORE.match(text, pos)
            if not mm or mm.start(1) == pos:
                break
            sep = text[pos:mm.start(1)]
            if not re.search(r",|και", re.sub(r"\([^()]*\)|«[^«»]*»", " ", sep)):
                break   # two numbers need a comma or 'και' between them
            if mm.start(1) not in seen:
                seen.add(mm.start(1))
                yield int(mm.group(1)), mm.group(2), mm.start(1), mm.end(), -1
            pos = mm.end()


ISSUE_CITE = re.compile(r"(?:φεκ\s*)?(?:α|a)\s*[’']?\s*(\d{1,3})\s*/\s*(?:\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*)?(\d{4})"
                        r"|(\d{1,3})\s*/\s*(?:α|a)[’']?\s*/?\s*(\d{4})")
# The official index's relations that can change a text, when a later ΦΕΚ Α΄ document points at this one.
REL = {"0": "Τροποποίηση", "3": "Ακύρωση", "5": "Αντικατάσταση"}
ART_SPLIT = re.compile(r"^«?\s*Άρθρο\s+\S+(?:\s+\S+){0,2}\s*$", re.I)


def scan_blocks(docs: list[dict]) -> list[tuple[str, str]]:
    """(kind, folded text) blocks: one per article (split at every article heading, quoted or not) of every
    document except decree preambles; a corrections notice is one block."""
    return [(k, t) for k, t, _, _ in scan_blocks_full(docs)]


def scan_blocks_full(docs: list[dict]) -> list[tuple[str, str, int, list[str]]]:
    """scan_blocks, with each block's document (index in docs) and its paragraphs (the first may be a heading)."""
    out = []
    for di, d in enumerate(docs):
        if d["kind"] == "corrections":
            ps = [d["head"]] + [p.t for p in d["paras"]]
            out.append(("corrections", fold(" ".join(ps)), di, ps))
            continue
        paras = d["paras"]
        trimmed = False
        if d["head"].startswith("ΠΡΟΕΔΡΙΚ"):
            # a decree's title is scanned, its considerations (which cite the acts it rests on) are not
            i_pres = next((i for i, p in enumerate(paras) if PRESIDENT.match(p.t)), None)
            i_dec = next((i for i, p in enumerate(paras) if DECIDE.search(p.t)), None)
            if i_pres is not None and i_dec is not None and i_pres < i_dec:
                ps = [d["head"]] + [p.t for p in paras[:i_pres]]
                out.append((d["kind"], fold(" ".join(ps)), di, ps))
                paras = paras[i_dec + 1:]
                trimmed = True
        cur = [d["head"]]
        first = True
        for p in paras:
            if ART_SPLIT.match(p.t):
                if not (first and d["head"].startswith("ΠΡΟΕΔΡΙΚ") and not trimmed):
                    out.append((d["kind"], fold(" ".join(cur)), di, cur))
                cur, first = [], False
            cur.append(p.t)
        out.append((d["kind"], fold(" ".join(cur)), di, cur))
    return out


# ---------------------------------------------------------------- whole repeals (a second, empty version)

LAW_DESIG = re.compile(r"(?:ν\.|νομου|νομοσ|νομο|ν)\s*(?:υπ[’']?\s*αριθμ?\.?\s*)?$")
ITEM_MARK = r"(?:\(?[α-ω]{1,3}[’']?\)|[α-ω]{1,3}[’']?\.|\(?\d{1,3}\)|\d{1,3}\.)"
# what may stand between the start of an item and the act's designation: a boundary, a list mark, an article
ITEM_BEFORE = re.compile(r"(?:^|[;:·,]|\bκαι\b|\bκαταργ\w*|[)»]|(?<=[)»\d])\.)\s*(?:" + ITEM_MARK + r"\s*)?"
                         r"(?:(?:ο|το|οι|τα)\s+|(?:οι\s+)?διαταξεισ\s+του\s+)?$")
ITEM_END = re.compile(r"[;:·,]|\bκαι\b|(?<=[)»\d])\s+" + ITEM_MARK + r"\s")
# what may follow the act's number inside its item (bracketed and quoted parts are masked out before)
ITEM_TAIL = re.compile(r"^\s*(?:φεκ\s*)?(?:οπωσ\s+ισχυ\w*\s*)?(?:στο\s+συνολο\s+του\s*)?(?:καταργ\w+\s*)?(?:@\s*)?\.?\s*$")
SENT_END = re.compile(r"(?:(?<=[)»\d])|(?<=[α-ω]{4}))\.(?=\s+[^\d\s]|\s*$)")
CHANGE = re.compile(r"τροποπ|αντικαθ|αντικατασ|προστιθ|προστεθ|προσθηκ|συμπληρ|αναριθμ|παρατειν|παραταση|αναστελ|αναστολ|διορθ"
                    r"|ερμηνευ|αναδιατυπ|επαναφερ|επαναφορ|αναβιω|διαγραφ|απαλειφ|διαμορφων|επερχον")
EXCEPTED = re.compile(r"εκτοσ|πλην|εξαιρ|επιφυλαξ|κατα\s+το\s+μεροσ|καθ’\s*ο\s+μεροσ|ωσ\s+προσ|οσον\s+αφορα|σε\s+ο\s*,?\s*τι"
                      r"|διατηρ|εξακολουθ|\bμονο\b|μεταβατ|αναλογ|κατα\s+τα\s+λοιπα|μερικ|εν\s+μερει|ακυρ")
# 'from the start of this act': the repealing act's own day
OWN_DAY = re.compile(r"(?:απο|με)\s+(?:την\s+εναρξη\s+(?:τησ\s+)?ισχυοσ|τησ\s+(?:εναρξεωσ\s+(?:τησ\s+)?)?ισχυοσ|την\s+ισχυ"
                     r"|τη(?:ν|σ)?\s+δημοσιευσ\w*)\s+του\s+παροντοσ(?:\s+(?:νομου|προεδρικου\s+διαταγματοσ|διαταγματοσ"
                     r"|π\.?\s*δ\.?(?:/τοσ)?))?")
TIME_WORDS = re.compile(r"\bαπο\b|\bμετα\b|\bεωσ\b|\bμεχρι\b|ληξ|ληγ|ημερομην|\bετο\w*|σχολικ|\bημερ\w*|\bμην\w*|προθεσμ"
                        r"|\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}|\b(?:19|20)\d\d\b|" + "|".join(MONTHS))


def mask_groups(t: str) -> str:
    """The text with what is inside «...» and (...) replaced by '_' (same length)."""
    out, dq, dp = [], 0, 0
    for ch in t:
        if ch == "«":
            dq += 1
        elif ch == "»" and dq:
            dq -= 1
        elif ch == "(":
            dp += 1
        elif ch == ")" and dp:
            dp -= 1
        elif dq or dp:
            out.append("_")
            continue
        out.append(ch)
    return "".join(out)


def whole_repeal(paras: list[str], pi: int, s: int, e: int, des: int) -> bool:
    """Whether the citation at [s, e) of folded paragraph pi (its designation starting at des) repeals the act as a
    whole: the act alone in its item ('ο ν. N/YYYY (Α' n)', 'το π.δ. N/YYYY «...»', nothing about an article, a
    paragraph or a part of it), in a sentence (or a list under a heading ending with ':') that repeals with
    'καταργ...', changes nothing else, makes no exception and names no day or time of its own."""
    raw = paras[pi]
    m = mask_groups(raw)
    if m[s:e] != raw[s:e]:
        return False   # inside a quotation or brackets
    if not ITEM_BEFORE.search(m[:des]):
        return False
    nxt = ITEM_END.search(m, e)
    if not ITEM_TAIL.match(OWN_DAY.sub(" @ ", re.sub(r"[«(]_*[»)]", " ", m[e:nxt.start() if nxt else len(m)]))):
        return False
    starts = [x.end() for x in SENT_END.finditer(m, 0, s)]
    a = starts[-1] if starts else 0
    z = SENT_END.search(m, e)
    sent = m[a:z.start() if z else len(m)]
    gov = [sent]
    if not re.search(r"καταργ", sent):
        # an item of a list: the paragraphs before it are items too, up to the heading that ends with ':'
        if a or not re.match(r"\s*" + ITEM_MARK + r"\s", m):
            return False
        for j in range(pi - 1, -1, -1):
            h = mask_groups(paras[j]).rstrip()
            if h.endswith(":"):
                hs = [x.end() for x in SENT_END.finditer(h)]
                gov.append(h[hs[-1] if hs else 0:])
                break
            if not re.match(r"\s*" + ITEM_MARK + r"\s", h):
                return False
        else:
            return False
        if not re.search(r"καταργ", gov[-1]):
            return False
    g = " ".join(gov)
    g = re.sub(r"(?<![\d/])\d{1,4}\s*/\s*(?:\d{4}|\d{2})(?![\d/])", " @ ", CITE.sub(" @ ", PD_CITE.sub(" @ ", g)))
    g = OWN_DAY.sub(" ", g)
    return not (CHANGE.search(g) or EXCEPTED.search(g) or TIME_WORDS.search(g))


def repeal_title(fp: str, s: int, e: int, des: int) -> bool:
    """A heading (an article's title, a line of the table of contents) that only names the repeal: 'Κατάργηση του
    ν. N/YYYY', alone or as one ' - ' segment of the heading."""
    m = mask_groups(fp)
    if len(fp) > 400 or m[s:e] != fp[s:e] or SENT_END.search(m[:max(0, len(m) - 2)]):
        return False
    a = max([x.end() for x in re.finditer(r"\s[-–]\s", m[:des])] + [0])
    z = re.compile(r"\s[-–]\s").search(m, e)
    seg = m[a:z.start() if z else len(m)]
    return re.fullmatch(r"\s*(?:\d{1,3}\.\s*)?(?:αρθρο\s+\S+\s*:?\s*)?καταργηση\s+(?:(?:του|των)\s+)?(?:διαταξεων\s+του\s+)?"
                        + re.escape(m[des:e]) + r"\s*(?:[«(]_*[»)]\s*)*\.?\s*", seg) is not None


def repeal_items(blocks, docs) -> list[list]:
    """For each act this issue cites in a passage that can change it: [kind ('law'|'pd'), number, year as written,
    position of the citing law or decree among this issue's laws and decrees (or None), whether every such citation
    repeals it as a whole from that one document (headings that only name the repeal aside), the repealing
    paragraph]."""
    pos = {}
    for di, d in enumerate(docs):
        if d["kind"] in ("law", "pd"):
            pos[di] = len(pos)
    found: dict[tuple, list] = {}
    depth, last_di = 0, None
    for kind, text, di, ps in blocks:
        if di != last_di:
            depth, last_di = 0, di
        amending = kind == "corrections" or STEMS.search(text)
        contents = docs[di]["kind"] == "preface" or re.match(r"ΠΕΡΙΕΧΟΜΕΝΑ|ΠΡΟΕΔΡΙΚΑ ΔΙΑΤΑΓΜΑΤΑ", docs[di]["head"])
        for pi, p in enumerate(ps):
            quoted = depth > 0
            depth = max(0, depth + quote_delta(p))
            if not amending or (contents and re.search(r"\.{5,}", p)):
                continue   # an entry of the issue's list of contents (a title and its page, with dot leaders)
            fp = fold(p)
            hits = []
            for mm in CITE.finditer(fp):
                md = LAW_DESIG.search(fp, 0, mm.start())
                law_like = md is not None and md.end() == mm.start() and not re.search(r"[α-ω]$", fp[:md.start()])
                hits.append(("law", int(mm.group(1)), mm.group(2), mm.start(), mm.end(), md.start() if law_like else -1))
            for n_, y_, s_, e_, des_ in pd_cites(fp):
                hits.append(("pd", n_, y_, s_, e_, des_))
            for k, n, y, s, e, des in hits:
                how = "bad"
                if kind in ("law", "pd") and des >= 0 and not quoted:
                    if repeal_title(fp, s, e, des):
                        how = "title"
                    elif whole_repeal([fold(x) for x in ps], pi, s, e, des):
                        how = "repeal"
                key = (k, n, y)
                prev = found.setdefault(key, [k, n, y, pos.get(di), True, None])
                if prev[3] != pos.get(di):
                    prev[3] = None
                if how == "bad":
                    prev[4] = False
                elif how == "repeal" and prev[5] is None:
                    prev[5] = p[:400]
    out = []
    for v in found.values():
        ok = v[4] and v[3] is not None and v[5] is not None
        out.append(v[:4] + [ok, v[5] if ok else None])
    return out


# ---------------------------------------------------------------- main


def load_jsonl(p: Path) -> list[dict]:
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def process_issue(dump: dict) -> dict:
    """Everything this parser needs from one issue, as plain JSON (cacheable): facts, the laws in it (units or the
    reason they can't be read), and the law numbers its amending passages cite."""
    lines, facts = issue_lines(dump)
    facts["sha256"] = dump.get("sha256")
    out = {"facts": {k: sorted(v) if isinstance(v, set) else v for k, v in facts.items()}, "blind": False,
           "laws": [], "cites": [], "issue_cites": []}
    if not lines or (facts["pages"] > 1 and len(facts["empty_pages"]) >= facts["pages"] - 1):
        out["blind"] = True
        return out
    vocab = vocabulary(lines)
    docs = documents(paragraphs(lines, vocab))
    cites, icites, pdcites = set(), set(), set()
    blocks = scan_blocks_full(docs)
    for kind, text, _, _ in blocks:
        if kind != "corrections" and not STEMS.search(text):
            continue
        for m in CITE.finditer(text):
            cites.add((int(m.group(1)), m.group(2)))
        for n_, y_, _, _, _ in pd_cites(text):
            pdcites.add((n_, y_))
        if kind == "corrections":
            for m in ISSUE_CITE.finditer(text):
                iss, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                icites.add((int(y), int(iss)))
    out["cites"] = sorted(cites)
    out["pd_cites"] = sorted(pdcites)
    out["issue_cites"] = sorted(icites)
    out["repeals"] = repeal_items(blocks, docs)
    for d in docs:
        if d["kind"] not in ("law", "pd"):
            continue
        paras = d["paras"] = split_order(d["paras"], d["kind"])
        end_rx = law_order(paras) if d["kind"] == "law" else PD_ORDER
        i_end = next((i for i, p in enumerate(paras) if end_rx.match(p.t)), len(paras) - 1)
        pages = [p.page for p in paras[:i_end + 1]] or [0]
        r = {"num": d["num"], "kind": d["kind"], "pages": [min(pages), max(pages)],
             "enacted": next((text_day(p.t) for p in paras[i_end:]
                              if (ATHENS.match(p.t) or PLACE_DAY.match(p.t)) and text_day(p.t)), None)}
        try:
            r["title"], r["units"], r["plain"] = law_units(paras, vocab, d["kind"])
        except Hold as h:
            r["hold"] = str(h)
            i_pres = next((i for i, p in enumerate(paras) if PRESIDENT.match(p.t)), 0)
            r["title"] = tidy(join_lines([p.t for p in paras[:i_pres]], vocab))[:300]
        out["laws"].append(r)
    return out


def _process_file(job) -> dict:
    key, path, cache_file = job
    r = process_issue(json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8")))
    if cache_file:
        # two files: the light record every run reads, and the units, read only for acts that pass every check
        cf = Path(cache_file)
        cf.parent.mkdir(parents=True, exist_ok=True)
        heavy = [{k: lr.get(k) for k in ("units", "plain")} for lr in r["laws"]]
        light = dict(r, laws=[{k: v for k, v in lr.items() if k not in ("units", "plain")} for lr in r["laws"]])
        for f, obj in ((heavy_path(cf), heavy), (cf, light)):
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(obj, ensure_ascii=False).encode("utf-8"), 6, mtime=0))
            tmp.replace(f)
    return r


def heavy_path(cf: Path) -> Path:
    return cf.with_name(cf.name.replace(".json.gz", ".units.json.gz"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--retrieved", required=True, help="the day the inputs were retrieved (YYYY-MM-DD)")
    ap.add_argument("--report")
    ap.add_argument("--jobs", type=int, default=4, help="worker processes for reading issues")
    ap.add_argument("--cache", help="folder for per-issue intermediate results (speeds up reruns)")
    ap.add_argument("--out", help="folder for the parts (default: corpus.d beside this file)")
    ap.add_argument("--repo", help="a checkout of the published repository: laws it already holds as other acts are "
                                   "skipped, and acts this parser published are carried over unchanged")
    ap.add_argument("--keep", help="JSON {slug: {year, act, law_key, law}}: published entries to carry over unchanged")
    ap.add_argument("--rejects", help="JSON {\"<num>/<year>\": reason}: laws held back by hand or by a failed check")
    a = ap.parse_args()
    src = Path(a.src)
    out_dir = Path(a.out) if a.out else PARTS
    issues = {(r["year"], r["num"]): r for r in load_jsonl(src / "issues.jsonl")}
    fetched = {}
    for r in load_jsonl(src / "fek.jsonl"):
        if r.get("status") in (200, 404):
            fetched[(r["year"], r["num"])] = r
    rejects = json.loads(Path(a.rejects).read_text(encoding="utf-8")) if a.rejects and Path(a.rejects).exists() else {}
    timeline = {(r["year"], r["num"]): r for r in load_jsonl(src / "timeline.jsonl")}
    # Laws the repository already holds under another act (built with their amendment history) are not repeated.
    elsewhere = set()
    if a.repo and (Path(a.repo) / "data" / "paths.json").exists():
        for slug in json.loads((Path(a.repo) / "data" / "paths.json").read_text(encoding="utf-8")).get("paths", {}):
            m = re.fullmatch(r"nomos-(\d{1,4})-(\d{4})", slug)
            if m:
                elsewhere.add((int(m.group(1)), int(m.group(2))))
    # acts already in other parts of this corpus (built with their history) are not repeated here
    taken = set()
    for p in sorted(PARTS.glob("*.json")):
        if p.name.startswith(("40-nomoi-", "50-diatagmata-")):
            continue   # this parser's own parts
        for act in json.loads(p.read_text(encoding="utf-8")).get("acts", []):
            m = re.search(r"/(\d{4})01(\d{5})\.pdf$", act.get("url", ""))
            if m:
                taken.add((int(m.group(1)), int(m.group(2))))

    # Years whose every indexed issue has been read, and every later year too.
    years = sorted({y for y, _ in issues})
    complete_from = None
    for y in reversed(years):
        if all(k in fetched for k in issues if k[0] == y):
            complete_from = y
        else:
            break
    blind = []      # issues with no text layer at all
    laws = []       # (issue key, law or decree result)
    cited: dict[int, set[str]] = defaultdict(set)                  # law number -> citing issues
    cited_pd: dict[tuple[int, int], set[str]] = defaultdict(set)   # (decree number, year) -> citing issues
    cited_issue: dict[tuple[int, int], set[str]] = defaultdict(set)
    law_years: dict[int, int] = {}
    pd_seen: set[tuple[int, int]] = set()
    facts_of = {}
    results = {}
    cache = Path(a.cache) if a.cache else None
    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    todo, cached, cache_of = [], {}, {}
    # one index file holds every light record of this code version, so a warm run reads one file, not thousands
    index_f = cache / f"index-{code}.json.gz" if cache else None
    index = json.loads(gzip.decompress(index_f.read_bytes()).decode("utf-8")) if index_f and index_f.exists() else {}
    index_changed = False
    fresh_index = not index
    for key in sorted(fetched):
        if fetched[key].get("status") != 200:
            continue
        name = f"{key[0]}-{key[1]}-{fetched[key].get('sha256', '')[:16]}-{code}.json.gz"
        cf = cache / name if cache else None
        if cf and name in index:
            cached[key] = index[name]
            cache_of[key] = cf
            continue
        f = src / "dumps" / str(key[0]) / f"{key[1]}.json.gz"
        if not f.exists():
            continue
        if cf and cf.exists() and heavy_path(cf).exists():
            cached[key] = index[name] = json.loads(gzip.decompress(cf.read_bytes()).decode("utf-8"))
            cache_of[key] = cf
            index_changed = True
        else:
            todo.append((key, str(f), str(cf) if cf else None))
    fresh = {}
    if todo:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max(1, min(a.jobs, len(todo)))) as ex:
            for (key, _, _), r in zip(todo, ex.map(_process_file, todo, chunksize=4)):
                fresh[key] = r
        if cache:
            for key, _, cf in todo:
                r = fresh[key]
                index[Path(cf).name] = dict(r, laws=[{k: v for k, v in lr.items() if k not in ("units", "plain")}
                                                     for lr in r["laws"]])
                cache_of[key] = Path(cf)
            index_changed = True
    if index_f and index_changed:
        for old_f in cache.glob("index-*.json.gz"):
            if old_f != index_f:
                old_f.unlink(missing_ok=True)   # an earlier code version's index
        tmp = index_f.with_name(f"{index_f.name}.{os.getpid()}.tmp")
        tmp.write_bytes(gzip.compress(json.dumps(index, ensure_ascii=False).encode("utf-8"), 1, mtime=0))
        tmp.replace(index_f)
        if fresh_index:
            for old_f in cache.glob("*.json.gz"):
                if f"-{code}." not in old_f.name and not old_f.name.startswith("index-"):
                    old_f.unlink(missing_ok=True)   # per-issue results of an earlier code version
    for key in sorted(set(cached) | set(fresh)):
        r = cached.get(key) or fresh[key]
        results[key] = r
        facts_of[key] = r["facts"]
        if r["blind"]:
            blind.append(key)
            continue
        for i, lr in enumerate(r["laws"]):
            lr["_i"] = i
            laws.append((key, lr))
            if lr.get("kind", "law") == "law":
                law_years.setdefault(lr["num"], key[0])
            else:
                pd_seen.add((lr["num"], key[0]))
    for key, r in results.items():
        label = f"Α {key[1]}/{key[0]}"
        for n, y in r["cites"]:
            ly = law_years.get(n)
            if ly and (str(ly) == y or (len(y) == 2 and str(ly)[2:] == y)):
                cited[n].add(label)
        for n, y in r.get("pd_cites", []):
            yy = int(y) if len(y) == 4 else (2000 + int(y) if int(y) < 50 else 1900 + int(y))
            if (n, yy) in pd_seen:
                cited_pd[(n, yy)].add(label)
        for y, iss in r["issue_cites"]:
            cited_issue[(y, iss)].add(label)
    # whole repeals: (kind, number, year) -> {citing issue label: [position of the repealing act, whole repeal?, text]}
    repeals: dict[tuple, dict] = defaultdict(dict)
    for key, r in results.items():
        label = f"Α {key[1]}/{key[0]}"
        for k, n, y, pos, ok, text in r.get("repeals", []):
            if k == "law":
                ly = law_years.get(n)
                if not (ly and (str(ly) == y or (len(y) == 2 and str(ly)[2:] == y))):
                    continue
                ident = ("law", n, ly)
            else:
                ident = ("pd", n, int(y) if len(y) == 4 else (2000 + int(y) if int(y) < 50 else 1900 + int(y)))
            have = repeals[ident].get(label)
            if have is None:
                repeals[ident][label] = [pos, ok, text]
            else:   # the same act cited as a law and as a decree, or with two spellings of the year: all must agree
                repeals[ident][label] = [have[0] if have[0] == pos else None, have[1] and ok, have[2] or text]

    # Acts this parser has already published stay exactly as published: their entries are carried over from the
    # parts written before (or from --keep), whatever this run would read for them.
    frozen: dict[str, dict] = {}
    published_slugs = set()
    if a.repo and (Path(a.repo) / "data" / "paths.json").exists():
        published_slugs = {s for s in json.loads((Path(a.repo) / "data" / "paths.json").read_text(encoding="utf-8"))
                           .get("paths", {}) if re.fullmatch(rf"(?:{KIND}-20[0-3]\d-\d{{4}}|{PD_KIND}-20[0-3]\d-\d{{1,4}})", s)}
    if a.keep and Path(a.keep).exists():
        for slug, e in json.loads(Path(a.keep).read_text(encoding="utf-8")).items():
            if slug in published_slugs:
                frozen[slug] = e
    prev_parts = sorted(out_dir.glob("40-nomoi-*.json")) + sorted(out_dir.glob("50-diatagmata-*.json")) \
        if out_dir.exists() else []
    for p in prev_parts:
        part = json.loads(p.read_text(encoding="utf-8"))
        for act in part.get("acts", []):
            if act["slug"] in published_slugs and act["slug"] not in frozen:
                lk = act["first_law"]
                frozen[act["slug"]] = {"year": int(act["slug"].split("-")[1]), "act": act, "law_key": lk,
                                       "law": part["laws"][lk]}
    def repeal_version(rep, day: str):
        """(law key, law entry, version) for the empty version an act gets on the day the law or decree that repeals
        it as a whole takes effect: that act's own commencement clause, read without exceptions; a stated day
        counts only when nothing later amends the repealing act (a later act could have moved it)."""
        lab, (pos, _, text) = rep
        mi = re.fullmatch(r"Α (\d+)/(\d{4})", lab)
        rkey = (int(mi.group(2)), int(mi.group(1)))
        rr = results.get(rkey)
        meta = issues.get(rkey)
        if not rr or not meta or pos >= len(rr["laws"]):
            raise Hold("repealing act not read")
        rd = rr["laws"][pos]
        rkind, rn, ry = rd.get("kind", "law"), rd["num"], rkey[0]
        if rd.get("hold"):
            raise Hold(f"repealing act unreadable ({rd['hold'][:60]})")
        facts = {k: set(v) if isinstance(v, list) else v for k, v in facts_of[rkey].items()}
        span = set(range(rd["pages"][0], rd["pages"][1] + 1))
        if span & (facts["img_pages"] | facts["empty_pages"] | facts["bilingual_pages"] | facts["latin_pages"]):
            raise Hold("repealing act has pages with images, no text or other languages")
        if facts["masthead_num"] not in (None, rkey[1]) or (facts["masthead_day"] and facts["masthead_day"] != meta["issue_date"]):
            raise Hold("repealing act's masthead differs from the index")
        enacted = rd["enacted"]
        if not enacted or enacted > meta["issue_date"]:
            raise Hold("repealing act's enactment day unreadable")
        published = meta.get("pub_date") or meta["issue_date"]
        if published < meta["issue_date"]:
            raise Hold("repealing act published before its issue day")
        if "units" not in rd:
            rd.update(json.loads(gzip.decompress(heavy_path(cache_of[rkey]).read_bytes()).decode("utf-8"))[pos])
        rday, how = commencement(rd["plain"], published, rkind, meta["issue_date"])
        if rday < published:
            raise Hold("repealing act in force before its publication")
        if "exceptions" in how:
            raise Hold("repealing act's commencement clause has exceptions")
        if how != "publication":
            later = (cited[rn] if rkind == "law" else cited_pd[(rn, ry)]) - {lab}
            if later:
                raise Hold(f"repealing act starts on a stated day and is cited later ({sorted(later)[0]})")
        if rday <= day:
            raise Hold(f"repeal day {rday} not after the act's own day {day}")
        rlabel = f"ν. {rn}/{ry}" if rkind == "law" else f"π.δ. {rn}/{ry}"
        rslug = f"{KIND}-{ry}-{rn}" if rkind == "law" else f"{PD_KIND}-{ry}-{rn}"
        rlk = f"n-{rn}-{ry}" if rkind == "law" else f"pd-{rn}-{ry}"
        rurl = BLOB.format(y=ry, n=rkey[1])
        rlaw = frozen[rslug]["law"] if rslug in frozen else {
            "label": rlabel, "title": rd["title"], "kind": "law" if rkind == "law" else "decree", "enacted": enacted,
            "published": published, "url": rurl, "temporary_until": None, "restores": None, "note": None}
        return rlk, rlaw, {"from": rday, "source_url": rurl, "sha256": facts_of[rkey]["sha256"], "units": {},
                           "note": f"Repealed as a whole by {rlabel} (ΦΕΚ Α΄ {rkey[1]}/{ry}), in force from {rday} by its "
                                   f"own commencement clause."}

    parts: dict[tuple[str, int], dict] = defaultdict(lambda: {"laws": {}, "acts": []})
    holds = []
    seen = set()
    for key, d in sorted(laws, key=lambda x: (x[0], x[1].get("kind", "law"), x[1]["num"])):
        y, iss = key
        n = d["num"]
        kind = d.get("kind", "law")
        label = f"ν. {n}/{y}" if kind == "law" else f"π.δ. {n}/{y}"
        slug = f"{KIND}-{y}-{n}" if kind == "law" else f"{PD_KIND}-{y}-{n}"
        title = ""
        if slug in frozen:
            continue
        try:
            ident = (kind, n) if kind == "law" else (kind, n, y)
            if ident in seen:
                raise Hold("duplicate_number")
            seen.add(ident)
            if kind == "law" and (key in taken or (n, y) in elsewhere):
                raise Hold("built_elsewhere")
            rkey = f"{n}/{y}" if kind == "law" else f"pd {n}/{y}"
            if rkey in rejects:
                raise Hold("rejected:" + str(rejects[rkey])[:200])
            meta = issues.get(key)
            if not meta:
                raise Hold("not_in_index")
            if d.get("hold"):
                title = d.get("title", "")
                raise Hold(d["hold"])
            title = d["title"]
            if re.search(r"κωδικ", fold(title)):
                raise Hold("code")
            own_others = (cited[n] if kind == "law" else cited_pd[(n, y)]) - {f"Α {iss}/{y}"}
            rep = None
            if own_others:
                # One later text cites it, and only to repeal it as a whole: published with a second, empty version.
                cand = repeals.get((kind, n, y), {}).get(next(iter(own_others))) if len(own_others) == 1 else None
                if not (cand and cand[0] is not None and cand[1]):
                    raise Hold("amended_or_cited:" + ",".join(sorted(own_others)[:6]))
                rep = (next(iter(own_others)), cand)
            if cited_issue.get(key):
                raise Hold("erratum:" + ",".join(sorted(cited_issue[key])[:6]))
            tl = timeline.get(key)
            if tl is None:
                raise Hold("index_relations_unread")
            if tl["n"] >= 100:
                raise Hold("index_relations_full")
            rel = sorted({f"{lab} ({REL.get(t, t)})" for lab, t, dr in tl["rows"]
                          if str(dr) == "-1" and str(t) in REL and (lab or "").startswith("Α ")})
            if rel and not (rep and all(x.split(" (")[0] == rep[0] for x in rel)):
                raise Hold("index_relation:" + ",".join(rel[:6]))
            facts = {k: set(v) if isinstance(v, list) else v for k, v in facts_of[key].items()}
            span = set(range(d["pages"][0], d["pages"][1] + 1))
            if span & facts["img_pages"]:
                raise Hold("images_on_pages")
            if span & facts["empty_pages"]:
                raise Hold("page_without_text")
            if span & facts["bilingual_pages"]:
                raise Hold("bilingual_columns")
            if span & facts["latin_pages"]:
                raise Hold("latin_text_pages")
            if facts["masthead_num"] not in (None, iss):
                raise Hold(f"masthead_number:{facts['masthead_num']}")
            if facts["masthead_day"] and facts["masthead_day"] != meta["issue_date"]:
                raise Hold(f"masthead_day:{facts['masthead_day']} vs index {meta['issue_date']}")
            enacted = d["enacted"]
            if not enacted or enacted > meta["issue_date"]:
                raise Hold(f"enacted_day:{enacted}")
            published = meta.get("pub_date") or meta["issue_date"]
            if published < meta["issue_date"]:
                raise Hold(f"publication_before_issue:{published}")
            if "units" not in d:
                d.update(json.loads(gzip.decompress(heavy_path(cache_of[key]).read_bytes()).decode("utf-8"))[d["_i"]])
            units, plain = d["units"], d["plain"]
            day, how = commencement(plain, published, kind, meta["issue_date"])
            if day < published:
                raise Hold(f"in_force_before_publication:{day}")
            if complete_from is None or y < complete_from:
                raise Hold("scan_incomplete")
            later_blind = [b for b in blind if issues.get(b, {}).get("issue_date", "") >= meta["issue_date"] and b != key]
            if later_blind:
                raise Hold("later_issue_without_text:" + ",".join(f"{b[1]}/{b[0]}" for b in later_blind[:5]))
            repeal = None
            if rep:
                try:
                    repeal = repeal_version(rep, day)
                except Hold as h:
                    raise Hold(f"amended_or_cited:{rep[0]} (repealed as a whole; no second version: {h})")
        except Hold as h:
            holds.append({"law": label, "issue": f"Α {iss}/{y}", "title": title[:160], "reason": str(h)})
            continue
        lk = f"n-{n}-{y}" if kind == "law" else f"pd-{n}-{y}"
        url = BLOB.format(y=y, n=iss)
        note = None
        if "exceptions" in how:
            note = "Its commencement clause gives some provisions a different day; the whole text is dated by its general day."
        parts[(kind, y)]["laws"][lk] = {"label": label, "title": title, "kind": "law" if kind == "law" else "decree",
                                        "enacted": enacted, "published": published, "url": url,
                                        "temporary_until": None, "restores": None, "note": None}
        versions = [{"from": day, "source_url": url, "sha256": facts_of[key]["sha256"], "units": units,
                     "credits": {}, **({"note": note} if note else {})}]
        if repeal:
            rlk, rlaw, rversion = repeal
            parts[(kind, y)]["laws"][rlk] = rlaw
            versions.append({"from": rversion["from"], "source_url": rversion["source_url"], "sha256": rversion["sha256"],
                             "units": {}, "credits": {k: [rlk] for k in units}, "note": rversion["note"]})
            parts[(kind, y)]["repealed"] = parts[(kind, y)].get("repealed", 0) + 1
        parts[(kind, y)]["acts"].append({
            "slug": slug, "short": label, "title": title, "url": url, "first_law": lk, "earlier_laws": [],
            "versions": versions})
    for slug, e in frozen.items():
        k = ("law" if slug.startswith(KIND + "-") else "pd", e["year"])
        parts[k]["laws"][e["law_key"]] = e["law"]
        parts[k]["acts"].append(e["act"])
    missing = sorted(published_slugs - set(frozen) - {x["slug"] for p in parts.values() for x in p["acts"]})
    out_dir.mkdir(exist_ok=True)
    written = []
    for kind, y in sorted(parts):
        p = parts[(kind, y)]
        what, whats = ("law", "laws") if kind == "law" else ("decree", "presidential decrees")
        p["acts"].sort(key=lambda x: int(x["slug"].rsplit("-", 1)[1]))
        p["sources"] = [{
            "name": "Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: issue PDFs of series Α΄",
            "url": "https://ia37rg02wpsa01.blob.core.windows.net/fek/", "retrieved": a.retrieved,
            "licence": "Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). "
                       "Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).",
            "notes": "Every issue of series Α΄ from 2000 on, read from its text layer (no OCR); the index of issues, "
                     "with their issue and publication days and the relations between documents, from the National "
                     "Printing Office's search (search.et.gr)."}]
        if kind == "law":
            first = ("A law is published here as printed in its ΦΕΚ Α΄ issue: its title, articles, headings and annexes; "
                     "the President's enacting formula, the order to publish, the signatures and the Gazette's page "
                     "furniture are not part of the text.")
        else:
            first = ("A presidential decree is published here as printed in its ΦΕΚ Α΄ issue: its title, its "
                     "considerations ('Έχοντας υπόψη ... αποφασίζουμε'), articles, headings and annexes; the order to "
                     "publish and execute it, the signatures and the Gazette's page furniture are not part of the text. "
                     "Decrees without numbered articles are not published.")
        if kind == "law":
            p["decisions"] = [
                first,
                "Its one version takes effect on the day its own commencement clause names. A law that starts 'από τη "
                "δημοσίευσή του' starts on its publication day: the day the issue was released, as the National Printing "
                "Office's index records it (its publication date, which recent issues also carry in their digital "
                "signature), not the issue date printed on the masthead, which can be earlier. No general rule is applied: "
                "laws without a readable clause, or starting before their publication day, are held back.",
                "A law is published only when no later ΦΕΚ Α΄ text read for this corpus cites its number in an article, "
                "title or erratum that amends, replaces, repeals, adds to, corrects, extends, suspends or interprets "
                "anything (an over-cautious test: such a citation may concern another law), and only when the National "
                "Printing Office's index records no later ΦΕΚ Α΄ document amending, replacing or invalidating its issue; "
                "codes are never published this way. Implied repeal, which changes no words, is not tracked.",
                "Text is read from the PDF text layer: two-column pages left column first; a word broken at a line end is "
                "joined back unless the issue elsewhere prints it with that hyphen; cells of one table row are joined with "
                "spaces; Latin look-alike letters inside Greek words are mapped to Greek; issues set in the old Greek fonts "
                "are decoded from Windows-1253. Laws with images, pages without text or two languages side by side are "
                "held back."]
        else:
            p["decisions"] = [
                first,
                "Its one version takes effect on the day its own commencement clause names. A decree that starts 'από τη "
                "δημοσίευσή του' starts on its publication day: the day the issue was released, as the National Printing "
                "Office's index records it (its publication date, which recent issues also carry in their digital "
                "signature), not the issue date printed on the masthead, which can be earlier. No general rule is applied: "
                "decrees without a readable clause, or starting before their publication day, are held back.",
                "A decree is published only when no later ΦΕΚ Α΄ text read for this corpus cites it by number (π.δ. N/YYYY, "
                "or N/YYYY listed after another decree under one designation: 'τα π.δ. 1/2000, 2/2000 και 3/2000') "
                "in an article, title or erratum that amends, replaces, repeals, adds to, corrects, extends, suspends or "
                "interprets anything (an over-cautious test), and only when the National Printing Office's index records "
                "no later ΦΕΚ Α΄ document amending, replacing or invalidating its issue; codifications are never "
                "published this way. Implied repeal, which changes no words, is not tracked.",
                "Text is read from the PDF text layer: two-column pages left column first; a word broken at a line end is "
                "joined back unless the issue elsewhere prints it with that hyphen; cells of one table row are joined with "
                "spaces; Latin look-alike letters inside Greek words are mapped to Greek; issues set in the old Greek fonts "
                "are decoded from Windows-1253. Decrees with images, pages without text or two languages side by side are "
                "held back."]
        n_repealed = p.pop("repealed", 0)
        if n_repealed:
            p["decisions"].append(
                f"A {what} repealed as a whole and changed by nothing else gets a second, empty version on the day the "
                f"repeal takes effect, credited to the repealing act: when the only later ΦΕΚ Α΄ text citing it in a "
                f"passage that can change it is one law or presidential decree, and every such citation repeals it as a "
                f"whole ('καταργείται', the {what} alone in its item, no article or part of it named, no exception and no "
                f"day of its own; a heading 'Κατάργηση του ...' may name it too); when the National Printing Office's index "
                f"records no other later document changing its issue; and when the repealing act's own commencement clause "
                f"gives one day without exceptions, after the {what}'s own day (its publication day, or a stated day if no "
                f"later text amends the repealing act). That day is the repeal day.")
        p["ai_use"] = ["none"]
        f = out_dir / (f"40-nomoi-{y}.json" if kind == "law" else f"50-diatagmata-{y}.json")
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        tmp.replace(f)
        pub = f.with_suffix(".PUBLISH")
        ptmp = pub.with_suffix(".PUBLISH.tmp")
        rep_note = (f" {n_repealed} of them repealed as a whole by one later act and changed by nothing else: a second, "
                    f"empty version on the repealing act's own day, credited to it." if n_repealed else "")
        if kind == "law":
            ptmp.write_text(f"{len(p['acts'])} laws of {y} as published in ΦΕΚ Α΄, each checked by parse_acts.py: article "
                            f"sequence, enacting formula and order to publish, masthead number and day against the official "
                            f"index, commencement clause, no images or textless pages, and no amending citation in any later "
                            f"ΦΕΚ Α΄ issue (all read to {a.retrieved}).{rep_note}\n", encoding="utf-8", newline="\n")
        else:
            ptmp.write_text(f"{len(p['acts'])} presidential decrees of {y} as published in ΦΕΚ Α΄, each checked by "
                            f"parse_acts.py: article sequence, decision formula and order to publish, masthead number and day "
                            f"against the official index, commencement clause, no images or textless pages, and no amending "
                            f"citation in any later ΦΕΚ Α΄ issue (all read to {a.retrieved}).{rep_note}\n", encoding="utf-8",
                            newline="\n")
        ptmp.replace(pub)
        written.append((f.name, len(p["acts"])))
    if a.report:
        Path(a.report).write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in holds), encoding="utf-8")
    reasons = Counter(h["reason"].split(":")[0] for h in holds)
    print(json.dumps({"acts_seen": len(laws), "published": sum(n for _, n in written), "held": len(holds),
                      "held_by_reason": dict(reasons.most_common()), "complete_from": complete_from,
                      "blind_issues": len(blind), "carried_over": len(frozen), "published_but_missing": missing,
                      "parts": written}, ensure_ascii=False))


if __name__ == "__main__":
    main()
