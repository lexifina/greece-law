"""Greece: every law (νόμος) published in series Α΄ of the Government Gazette (ΦΕΚ) since 2000, as published.

Reads only local inputs and writes corpus.d parts (SCHEMA.md in scripts/gitlaw_common). No network. Deterministic:
the same inputs give the same bytes.

    python -X utf8 parse_acts.py --src <folder> --retrieved YYYY-MM-DD [--report holds.jsonl]

<folder> holds:
- issues.jsonl: one row per ΦΕΚ Α΄ issue from the National Printing Office's search index (search.et.gr):
  {"year", "num", "id", "issue_date", "pub_date", "pages", "label"};
- fek.jsonl: one row per issue fetched: {"year", "num", "status" (200 or 404), "sha256", ...};
- dumps/<year>/<num>.json.gz: the text layer of each issue PDF, as fek_text.py writes it.

What becomes an act: a law (ΝΟΜΟΣ ΥΠ' ΑΡΙΘΜ. N) printed in a ΦΕΚ Α΄ issue, from its title to the order to publish
("Παραγγέλλομε τη δημοσίευση ..."): its articles, the headings before them and its annexes. The President's
enacting formula, the signatures and the Gazette's own furniture are not part of the text. One version, the law as
published, from the day its own commencement clause names.

A law is held back, not published, when any of these is true (the reason goes to the report):
- a later ΦΕΚ Α΄ text cites its number in an article (or title, or erratum) that amends, replaces, repeals, adds to,
  corrects, extends, suspends or interprets something: its text today may differ from the text as published;
- it is a code (its title names a Κώδικας): codes are amended under their own names;
- every later ΦΕΚ Α΄ issue has not been read (the citation scan would be incomplete), or a later issue has no text
  layer;
- its pages hold images or pages without text (part of its text would be missing), or two columns in different
  languages (the reading order would interleave them);
- its articles do not run 1, 2, 3, ... without gaps or repeats, or the enacting formula or the order to publish is
  missing;
- its commencement clause is missing or unreadable, or names a day before the law's publication day, or the masthead
  day differs from the index's issue day.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "corpus.d"
BLOB = "https://ia37rg02wpsa01.blob.core.windows.net/fek/01/{y}/{y}01{n:05d}.pdf"
KIND = "nomos"

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
    return re.sub(r"\s+", " ", s).strip()


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
DAY_RE = re.compile(r"(\d{1,2})(?:η|ης)?\s+([Α-Ωα-ωάέήίόύώϊϋΐΰ]+)\s+(\d{4})")


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
    r"^Τεύχος Α’ \d+/", r"^\(?ΤΕΥΧΟΣ ΠΡΩΤΟ\)?$", r"^\*[0-9]{10,}\*$", r"^[EF]$", r"^\d{1,5}$")]
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
    ended = False
    for pno, p in enumerate(dump["pages"]):
        if any(im[3] > 115 for im in p.get("img", [])):   # the signature stamp sits in the top margin
            facts["img_pages"].add(pno)
        w, h = p["w"], p["h"]
        lines = []
        for x0, y0, x1, y1, size, bold, t in p["lines"]:
            if legacy and not GREEK.search(t):
                t = legacy_decode(t)
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
        out.extend(order_page(lines, w, facts))
        if ended:
            break
    return out, facts


def mode_left(lines: list[Line]) -> float:
    if len(lines) < 3:
        return min((l.x0 for l in lines), default=0)
    c = Counter(round(l.x0) for l in lines)
    best = max(c.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    # the continuation margin is the leftmost frequent x0
    cands = [x for x, n in c.items() if n >= min(c[best], max(2, c[best] // 3))]
    return float(min(cands))


def order_page(lines: list[Line], w: float, facts: dict) -> list[Line]:
    if not lines:
        return []
    mid = w / 2
    L = [l for l in lines if l.x1 <= mid + 10]
    R = [l for l in lines if l.x0 >= mid - 10 and l not in L]
    S = [l for l in lines if l not in L and l not in R]
    if len(S) >= max(3, 0.3 * len(lines)) or not R:
        cols = [sorted(lines, key=lambda l: (round(l.y0), l.x0))]
        left = mode_left(lines)
        right = max(l.x1 for l in lines)
        for l in lines:
            l.left, l.right, l.col = left, right, 0
        seq = cols[0]
    else:
        ll, rl = mode_left(L), mode_left(R)
        lr, rr = max((l.x1 for l in L), default=mid), max((l.x1 for l in R), default=w)
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
            start = indent > 2.5 or is_centered(cur[-1]) or is_centered(l) or KEY_START.match(l.t) is not None                 or ((l.col == 0) != (cur[-1].col == 0)) or l.bold != cur[-1].bold or KEY_ALONE.match(cur[-1].t) is not None
        # otherwise a paragraph runs on into the next column or page
        if start:
            flush()
        cur.append(l)
    flush()
    return out


KEY_START = re.compile(r"^(?:Παραγγέλλομε τη δημοσίευση|Εκδίδομε τον ακόλουθο|(?:Ο|Η) ΠΡΟΕΔΡΟΣ|ΝΟΜΟΣ ΥΠ|Αθήνα,|«?Άρθρο\s+\S+\s*$"
                       r"|ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΠΑΡΑΡΤΗΜΑ|ΤΙΤΛΟΣ|ΕΝΟΤΗΤΑ|ΥΠΟΚΕΦΑΛΑΙΟ|ΒΙΒΛΙΟ)")
KEY_ALONE = re.compile(r"^(?:«?Άρθρο\s+\S+(?:\s+\S+)?|(?:ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΠΑΡΑΡΤΗΜΑ|ΤΙΤΛΟΣ|ΕΝΟΤΗΤΑ|ΥΠΟΚΕΦΑΛΑΙΟ|ΒΙΒΛΙΟ)"
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
ENACT = re.compile(r"^Εκδίδομε τον ακόλουθο νόμο")
ORDER = re.compile(r"^Παραγγέλλομε τη δημοσίευση")
PRESIDENT = re.compile(r"^(?:Ο|Η)\s+ΠΡΟΕΔΡΟΣ(?:\s+ΤΗΣ\s+ΕΛΛΗΝΙΚΗΣ\s+ΔΗΜΟΚΡΑΤΙΑΣ)?$")
ATHENS = re.compile(r"^(?:Αθήνα|Αθήναι),?\s+")
CORRECTIONS = re.compile(r"^ΔΙΟΡΘΩΣ")


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
        if OTHER_HEAD.match(p.t) and len(p.t) < 120 and not in_law_body:
            docs.append({"kind": "corrections" if CORRECTIONS.match(p.t) else "other", "num": None, "head": p.t, "paras": []})
            continue
        docs[-1]["paras"].append(p)
        if in_law_body and ORDER.match(p.t):
            in_law_body = False
    return docs


# ---------------------------------------------------------------- one law to units

ORD = {"πρωτο": 1, "δευτερο": 2, "τριτο": 3, "τεταρτο": 4, "πεμπτο": 5, "εκτο": 6, "εβδομο": 7, "ογδοο": 8, "ενατο": 9,
       "δεκατο": 10, "ενδεκατο": 11, "δωδεκατο": 12, "εικοστο": 20, "τριακοστο": 30, "τεσσαρακοστο": 40,
       "πεντηκοστο": 50, "εξηκοστο": 60, "εβδομηκοστο": 70, "ογδοηκοστο": 80, "ενενηκοστο": 90, "εκατοστο": 100,
       "διακοσιοστο": 200}
ART_HEAD = re.compile(r"^Άρθρο\s+(.{1,40})$", re.I)
STRUCT = re.compile(r"^(?:ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΤΙΤΛΟΣ|ΕΝΟΤΗΤΑ|ΥΠΟΚΕΦΑΛΑΙΟ|ΒΙΒΛΙΟ|ΥΠΟΤΜΗΜΑ)\b")
ANNEX = re.compile(r"^ΠΑΡΑΡΤΗΜΑ\b")
TOC = re.compile(r"^ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ$")


def art_number(label: str) -> tuple[str, int, str] | None:
    """('num'|'word'|'sole', number, suffix) for an article heading's label, or None."""
    f = fold(label).strip(" .")
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


def law_units(paras: list[Para], vocab: set[str] = frozenset()) -> tuple[str, dict, list[str]]:
    """(title, units, body paragraphs outside quotations) for one law document's paragraphs."""
    i_pres = next((i for i, p in enumerate(paras) if PRESIDENT.match(p.t)), None)
    i_enact = [i for i, p in enumerate(paras) if ENACT.match(p.t)]
    i_order = [i for i, p in enumerate(paras) if ORDER.match(p.t)]
    if i_pres is None or len(i_enact) != 1 or len(i_order) != 1 or not (i_pres < i_enact[0] < i_order[0]):
        raise Hold("structure:formula")
    title = tidy(join_lines([p.t for p in paras[:i_pres]], vocab))
    if not title:
        raise Hold("structure:no_title")
    body = paras[i_enact[0] + 1:i_order[0]]
    units: dict[str, dict] = {}
    order: list[str] = []
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
    for p in body:
        t = p.t
        top = depth == 0
        depth = max(0, depth + quote_delta(t))
        heading_like = p.centered or p.bold
        a = None
        m = ART_HEAD.match(t) if heading_like and (bold_heads is None or p.bold == bold_heads) else None
        if m:
            a = art_number(m.group(1))
            if a and mode is not None and a[0] != mode and mode != "sole":
                a = None    # a heading of the text an article quotes or ratifies (Άρθρο 1 inside Άρθρο πρώτο)
        if a:
            expected = len(numbers) + 1
            if not top:
                # Inside a quotation by the count of «», which a misprint can upset: take it as this law's own next
                # article only when it is bold like this law's own headings; otherwise it is quoted text.
                if a[1] == expected and not a[2] and bold_heads:
                    pass
                else:
                    a = None
            elif a[1] != expected or a[2]:
                raise Hold("articles:sequence " + ",".join(map(str, numbers[-5:])) + " then " + t)
        if a:
            if mode is None:
                mode = a[0]
                bold_heads = p.bold
            depth = 0   # a quotation never runs over this law's own article heading
            numbers.append(a[1])
            key = f"art-{a[1]:03d}"
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
        if top:
            plain.append(re.sub(r"«[^«»]*»?", " ", t))
    if pending and cur:
        units[cur]["lines"].extend(pending)
    if not numbers:
        raise Hold("articles:none")
    if mode == "sole":
        if numbers != [1]:
            raise Hold("articles:sole_and_more")
    elif numbers != list(range(1, len(numbers) + 1)):
        raise Hold("articles:sequence " + ",".join(map(str, numbers[:40])))
    out = {}
    for k in order:
        u = units[k]
        if u["lines"]:
            out[k] = {"label": u["label"], "kind": u["kind"], "text": "\n".join(u["lines"]) + "\n"}
    return title, out, plain


# ---------------------------------------------------------------- commencement

IN_FORCE = [
    re.compile(r"(?:εναρξη\s+)?ισχυ(?:οσ|σ)\s+(?:του\s+)?(?:παροντοσ|νομου\s+αυτου)(?:\s+νομου|\s+κωδικα)?(?:\s*,[^,]{1,80},)?\s+(?:αρχιζει|αρχεται|οριζεται)\s+(?P<rest>[^.]{0,220}(?:\.\d[^.]{0,200})*)"),
    re.compile(r"(?:ο\s+)?(?:παρων(?:\s+νομοσ)?|νομοσ\s+αυτοσ)\s+(?:ισχυει|τιθεται\s+σε\s+ισχυ)\s+(?P<rest>απο[^.]{0,220}(?:\.\d[^.]{0,200})*)"),
]
NUM_DAY = re.compile(r"(?:απο\s+)?(?:την\s+|τη\s+)?(\d{1,2})(?:η|ησ)?\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})")
WORD_DAY = re.compile(r"(?:απο\s+)?(?:την\s+|τη\s+)?(\d{1,2})(?:η|ησ)?\s+([α-ω]+)\s+(\d{4})")
PUB = re.compile(r"^απο\s+(?:τη|την)\s+δημοσιευσ")
EXCEPT = re.compile(r"εκτοσ|επιφυλαξ|εξαιρεσ|διαφορετικ|ειδικοτερ|επιμερουσ")


def commencement(plain: list[str], issue_day: str) -> tuple[str, str]:
    found = []
    for para in plain:
        f = fold(para)
        for rx in IN_FORCE:
            for m in rx.finditer(f):
                rest = m.group("rest").strip()
                exc = bool(EXCEPT.search(f))
                if PUB.match(rest):
                    found.append(("publication", issue_day, exc))
                    continue
                md = NUM_DAY.match(rest)
                if md:
                    try:
                        found.append(("date", date(int(md.group(3)), int(md.group(2)), int(md.group(1))).isoformat(), exc))
                    except ValueError:
                        raise Hold("in_force:bad_date " + rest[:80])
                    continue
                md = WORD_DAY.match(rest)
                if md and md.group(2) in MONTHS:
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
CITE = re.compile(r"(?<![\d/.])(\d{4})\s*/\s*(\d{4}|\d{2})(?![\d/])")
ISSUE_CITE = re.compile(r"(?:φεκ\s*)?(?:α|a)\s*[’']?\s*(\d{1,3})\s*/\s*(?:\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*)?(\d{4})"
                        r"|(\d{1,3})\s*/\s*(?:α|a)[’']?\s*/?\s*(\d{4})")
ART_SPLIT = re.compile(r"^«?\s*Άρθρο\s+\S+(?:\s+\S+){0,2}\s*$", re.I)


def scan_blocks(docs: list[dict]) -> list[tuple[str, str]]:
    """(kind, folded text) blocks: one per article (split at every article heading, quoted or not) of every
    document except decree preambles; a corrections notice is one block."""
    out = []
    for d in docs:
        if d["kind"] == "corrections":
            out.append(("corrections", fold(d["head"] + " " + " ".join(p.t for p in d["paras"]))))
            continue
        cur = [d["head"]]
        first = True
        for p in d["paras"]:
            if ART_SPLIT.match(p.t):
                if not (first and d["kind"] == "other" and d["head"].startswith("ΠΡΟΕΔΡΙΚ")):
                    out.append((d["kind"], fold(" ".join(cur))))
                cur, first = [], False
            cur.append(p.t)
        out.append((d["kind"], fold(" ".join(cur))))
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
    cites, icites = set(), set()
    for kind, text in scan_blocks(docs):
        if kind != "corrections" and not STEMS.search(text):
            continue
        for m in CITE.finditer(text):
            cites.add((int(m.group(1)), m.group(2)))
        if kind == "corrections":
            for m in ISSUE_CITE.finditer(text):
                iss, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                icites.add((int(y), int(iss)))
    out["cites"] = sorted(cites)
    out["issue_cites"] = sorted(icites)
    for d in docs:
        if d["kind"] != "law":
            continue
        paras = d["paras"]
        i_end = next((i for i, p in enumerate(paras) if ORDER.match(p.t)), len(paras) - 1)
        pages = [p.page for p in paras[:i_end + 1]] or [0]
        r = {"num": d["num"], "pages": [min(pages), max(pages)],
             "enacted": next((text_day(p.t) for p in paras[i_end:] if ATHENS.match(p.t) and text_day(p.t)), None)}
        try:
            r["title"], r["units"], r["plain"] = law_units(paras, vocab)
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
        cf = Path(cache_file)
        cf.parent.mkdir(parents=True, exist_ok=True)
        tmp = cf.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(json.dumps(r, ensure_ascii=False).encode("utf-8"), 6, mtime=0))
        tmp.replace(cf)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--retrieved", required=True, help="the day the inputs were retrieved (YYYY-MM-DD)")
    ap.add_argument("--report")
    ap.add_argument("--jobs", type=int, default=4, help="worker processes for reading issues")
    ap.add_argument("--cache", help="folder for per-issue intermediate results (speeds up reruns)")
    ap.add_argument("--out", help="folder for the parts (default: corpus.d beside this file)")
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
    # acts already in other parts of this corpus (built with their history) are not repeated here
    taken = set()
    for p in sorted(PARTS.glob("*.json")):
        if p.name.startswith("40-nomoi-"):
            continue
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
    laws = []       # (issue key, law result)
    cited: dict[int, set[str]] = defaultdict(set)
    cited_issue: dict[tuple[int, int], set[str]] = defaultdict(set)
    law_years: dict[int, int] = {}
    facts_of = {}
    results = {}
    cache = Path(a.cache) if a.cache else None
    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    todo, cached = [], {}
    for key in sorted(fetched):
        if fetched[key].get("status") != 200:
            continue
        f = src / "dumps" / str(key[0]) / f"{key[1]}.json.gz"
        if not f.exists():
            continue
        cf = cache / f"{key[0]}-{key[1]}-{fetched[key].get('sha256', '')[:16]}-{code}.json.gz" if cache else None
        if cf and cf.exists():
            cached[key] = json.loads(gzip.decompress(cf.read_bytes()).decode("utf-8"))
        else:
            todo.append((key, str(f), str(cf) if cf else None))
    fresh = {}
    if todo:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max(1, min(a.jobs, len(todo)))) as ex:
            for (key, _, _), r in zip(todo, ex.map(_process_file, todo, chunksize=4)):
                fresh[key] = r
    for key in sorted(set(cached) | set(fresh)):
        r = cached.get(key) or fresh[key]
        results[key] = r
        facts_of[key] = r["facts"]
        if r["blind"]:
            blind.append(key)
            continue
        for lr in r["laws"]:
            laws.append((key, lr))
            law_years.setdefault(lr["num"], key[0])
    for key, r in results.items():
        label = f"Α {key[1]}/{key[0]}"
        for n, y in r["cites"]:
            ly = law_years.get(n)
            if ly and (str(ly) == y or (len(y) == 2 and str(ly)[2:] == y)):
                cited[n].add(label)
        for y, iss in r["issue_cites"]:
            cited_issue[(y, iss)].add(label)

    parts: dict[int, dict] = defaultdict(lambda: {"laws": {}, "acts": []})
    holds = []
    seen_nums = set()
    for key, d in sorted(laws, key=lambda x: (x[0], x[1]["num"])):
        y, iss = key
        n = d["num"]
        label = f"ν. {n}/{y}"
        title = ""
        try:
            if n in seen_nums:
                raise Hold("duplicate_law_number")
            seen_nums.add(n)
            if key in taken:
                raise Hold("built_elsewhere")
            if f"{n}/{y}" in rejects:
                raise Hold("rejected:" + str(rejects[f"{n}/{y}"])[:200])
            meta = issues.get(key)
            if not meta:
                raise Hold("not_in_index")
            if d.get("hold"):
                title = d.get("title", "")
                raise Hold(d["hold"])
            title, units, plain = d["title"], d["units"], d["plain"]
            if re.search(r"κωδικ", fold(title)):
                raise Hold("code")
            own_others = cited[n] - {f"Α {iss}/{y}"}
            if own_others:
                raise Hold("amended_or_cited:" + ",".join(sorted(own_others)[:6]))
            if cited_issue.get(key):
                raise Hold("erratum:" + ",".join(sorted(cited_issue[key])[:6]))
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
            day, how = commencement(plain, published)
            if day < published:
                raise Hold(f"in_force_before_publication:{day}")
            if complete_from is None or y < complete_from:
                raise Hold("scan_incomplete")
            later_blind = [b for b in blind if issues.get(b, {}).get("issue_date", "") >= meta["issue_date"] and b != key]
            if later_blind:
                raise Hold("later_issue_without_text:" + ",".join(f"{b[1]}/{b[0]}" for b in later_blind[:5]))
        except Hold as h:
            holds.append({"law": label, "issue": f"Α {iss}/{y}", "title": title[:160], "reason": str(h)})
            continue
        slug = f"{KIND}-{y}-{n}"
        lk = f"n-{n}-{y}"
        url = BLOB.format(y=y, n=iss)
        note = None
        if "exceptions" in how:
            note = "Its commencement clause gives some provisions a different day; the whole text is dated by its general day."
        parts[y]["laws"][lk] = {"label": label, "title": title, "kind": "law", "enacted": enacted,
                                "published": published, "url": url, "temporary_until": None, "restores": None,
                                "note": None}
        parts[y]["acts"].append({
            "slug": slug, "short": label, "title": title, "url": url, "first_law": lk, "earlier_laws": [],
            "versions": [{"from": day, "source_url": url, "sha256": facts_of[key]["sha256"], "units": units,
                          "credits": {}, **({"note": note} if note else {})}]})
    out_dir.mkdir(exist_ok=True)
    written = []
    for y in sorted(parts):
        p = parts[y]
        p["acts"].sort(key=lambda x: int(x["slug"].rsplit("-", 1)[1]))
        p["sources"] = [{
            "name": "Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: issue PDFs of series Α΄",
            "url": "https://ia37rg02wpsa01.blob.core.windows.net/fek/", "retrieved": a.retrieved,
            "licence": "Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). "
                       "Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).",
            "notes": "Every issue of series Α΄ from 2000 on, read from its text layer (no OCR); the index of issues, "
                     "with their issue and publication days, from the National Printing Office's search (search.et.gr)."}]
        p["decisions"] = [
            "A law is published here as printed in its ΦΕΚ Α΄ issue: its title, articles, headings and annexes; the "
            "President's enacting formula, the order to publish, the signatures and the Gazette's page furniture are "
            "not part of the text.",
            "Its one version takes effect on the day its own commencement clause names. A law that starts 'από τη "
            "δημοσίευσή του' starts on its publication day: the day the issue was released, as the National Printing "
            "Office's index records it (its publication date, which recent issues also carry in their digital "
            "signature), not the issue date printed on the masthead, which can be earlier. No general rule is applied: "
            "laws without a readable clause, or starting before their publication day, are held back.",
            "A law is published only when no later ΦΕΚ Α΄ text read for this corpus cites its number in an article, "
            "title or erratum that amends, replaces, repeals, adds to, corrects, extends, suspends or interprets "
            "anything (an over-cautious test: such a citation may concern another law); codes are never published "
            "this way. Implied repeal, which changes no words, is not tracked.",
            "Text is read from the PDF text layer: two-column pages left column first; a word broken at a line end is "
            "joined back unless the issue elsewhere prints it with that hyphen; cells of one table row are joined with "
            "spaces; Latin look-alike letters inside Greek words are mapped to Greek; issues set in the old Greek fonts "
            "are decoded from Windows-1253. Laws with images, pages without text or two languages side by side are "
            "held back."]
        p["ai_use"] = ["none"]
        f = out_dir / f"40-nomoi-{y}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        tmp.replace(f)
        pub = f.with_suffix(".PUBLISH")
        ptmp = pub.with_suffix(".PUBLISH.tmp")
        ptmp.write_text(f"{len(p['acts'])} laws of {y} as published in ΦΕΚ Α΄, each checked by parse_acts.py: article "
                        f"sequence, enacting formula and order to publish, masthead number and day against the official "
                        f"index, commencement clause, no images or textless pages, and no amending citation in any later "
                        f"ΦΕΚ Α΄ issue (all read to {a.retrieved}).\n", encoding="utf-8", newline="\n")
        ptmp.replace(pub)
        written.append((f.name, len(p["acts"])))
    if a.report:
        Path(a.report).write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in holds), encoding="utf-8")
    reasons = Counter(h["reason"].split(":")[0] for h in holds)
    print(json.dumps({"laws_seen": len(laws), "published": sum(n for _, n in written), "held": len(holds),
                      "held_by_reason": dict(reasons.most_common()), "complete_from": complete_from,
                      "blind_issues": len(blind), "parts": written}, ensure_ascii=False))


if __name__ == "__main__":
    main()
