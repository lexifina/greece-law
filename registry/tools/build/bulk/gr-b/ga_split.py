"""GR-A task 3: split one ΦΕΚ Α΄ issue into acts and units (gazette-only model: each act as enacted).

Entry point (works on line lists, so GR-OCR's text plugs in unchanged):

    split_issue(lines, meta) -> {'acts': [act, ...], 'skipped': [{'what', 'why', ...}], 'notes': [...]}

  lines: body lines in reading order, each {'t', 'p', 'indent', 'bold'?, 'small'?}: order.reading_order(doc) gives
         them from a text/<series>/<year>/<id>.json.gz file (text layer or OCR; for OCR 'bold' is simply absent).
  meta:  the issue's meta/<series>/<year>/<id>.json (id, year, number, issue_date MM/DD/YYYY, url, api_url,
         sha256, no_text_pages, ...) plus 'text_source'.

Each act: {'kind', 'number', 'heading', 'title', 'signed', 'published', 'from', 'from_rule', 'units' {key: [lines]},
           'pages': [first, last], 'held': None | reason}
Kinds (CONVENTIONS KINDS): nomos, pd, pnp, an, nd, bd, nbd, kanonismos. An act starts at its heading line (ΝΟΜΟΣ ΥΠ’
ΑΡΙΘΜ. N, ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ ΥΠ’ ΑΡΙΘΜ. N, ΠΡΑΞΗ ΝΟΜΟΘΕΤΙΚΟΥ ΠΕΡΙΕΧΟΜΕΝΟΥ, ΑΝΑΓΚΑΣΤΙΚΟΣ ΝΟΜΟΣ, ΝΟΜΟΘΕΤΙΚΟ(Ν)
ΔΙΑΤΑΓΜΑ, ΒΑΣΙΛΙΚΟ(Ν) ΔΙΑΤΑΓΜΑ, ΚΑΝΟΝΙΣΜΟΣ ΥΠ’ ΑΡΙΘΜ. N/YYYY) when an enacting formula follows within 12 lines (Ο
ΠΡΟΕΔΡΟΣ ΤΗΣ (ΕΛΛΗΝΙΚΗΣ) ΔΗΜΟΚΡΑΤΙΑΣ, ... ΒΑΣΙΛΕΥΣ ΤΩΝ ΕΛΛΗΝΩΝ, Έχοντας υπόψη, Η ΙΕΡΑ ΣΥΝΟΔΟΣ ...), and ends at
the next act, a section header (ΑΝΑΚΟΙΝΩΣΕΙΣ, ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ, ΑΠΟΦΑΣΕΙΣ, ...), or the publisher's back page.
Inside an act:
  title     the lines between the heading and the enacting formula;
  prooimio  (decrees, π.ν.π., regulations) the recitals from the formula to the first article; laws: the formula
            and the law's table of contents are not carried (as the hand-built parts);
  art-NNN   one per top-level article (Άρθρο N / Άρθρο πρώτο ...; 5Α -> art-005a): a heading is top-level when it is
            not inside a «quotation» and its number follows the previous one (prev+1..prev+3, or a letter suffix);
            acts whose first article is an ordinal (πρώτο) keep numbered headings inside (a ratified code);
            ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ/ΤΜΗΜΑ headings go with the article they open;
  keimeno   an act with no articles (an appointment decree): its operative text after «αποφασίζουμε:»;
  parartima-NN  each top-level ΠΑΡΑΡΤΗΜΑ heading after the articles (also after the signatures);
  signatures (Αθήνα, <date> ...), the promulgation sentence of laws and the Great Seal line are not carried.
Dates: signed = «Αθήνα, D Month YYYY»; published = the issue date; from = the commencement clause when it plainly
states publication or one fixed date for the whole act, else the publication day (from_rule says which).
Held (not emitted): text with control characters (unmapped fonts), act pages without a text layer, no units.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

GR = Path(r'C:\Users\alany\Documents\lexifina\scripts\greece-law')
if str(GR) not in sys.path:
    sys.path.insert(0, str(GR))
import parse as P  # noqa: E402
import parse_n4624 as N  # noqa: E402

# ---------------------------------------------------------------- headings

UP = r'ΥΠ[’\']?\s*ΑΡΙΘ(?:Μ|ΜΟΝ)?\.?\s*'
HEADS = [
    ('nomos', re.compile(rf'^ΝΟΜΟΣ\s+{UP}(\d+)\.?$')),
    ('pd', re.compile(rf'^ΠΡΟΕΔΡΙΚΟ\s+ΔΙΑΤΑΓΜΑ\s+{UP}(\d+)\.?$')),
    ('pnp', re.compile(r'^ΠΡΑΞΗ\s+ΝΟΜΟΘΕΤΙΚΟΥ\s+ΠΕΡΙΕΧΟΜΕΝΟΥ(?:\s+(?:ΤΗΣ\s+)?.*)?$')),
    ('an', re.compile(rf'^ΑΝΑΓΚΑΣΤΙΚΟΣ\s+ΝΟΜΟΣ\s+{UP}(\d+)\.?$')),
    ('nd', re.compile(rf'^ΝΟΜΟΘΕΤΙΚΟΝ?\s+ΔΙΑΤΑΓΜΑ\s+{UP}(\d+)\.?$')),
    ('nbd', re.compile(rf'^ΝΟΜΟΘΕΤΙΚΟΝ?\s+ΒΑΣΙΛΙΚΟΝ?\s+ΔΙΑΤΑΓΜΑ\s+{UP}(\d+)\.?$')),
    ('bd', re.compile(rf'^ΒΑΣΙΛΙΚΟΝ?\s+ΔΙΑΤΑΓΜΑ(?:\s+{UP}(\d+)\.?)?$')),
    ('kanonismos', re.compile(rf'^ΚΑΝΟΝΙΣΜΟΣ\s+{UP}(\d+)/(\d{{4}})\.?$')),
]
FORMULA = re.compile(r'^(Ο\s+ΠΡΟΕΔΡΟΣ\s+ΤΗΣ\s+(ΕΛΛΗΝΙΚΗΣ\s+)?ΔΗΜΟΚΡΑΤΙΑΣ|Ο\s+ΠΡΟΕΔΡΟΣ\s+ΤΗΣ\s+ΕΛΛΗΝΙΚΗΣ$|.*ΒΑΣΙΛΕΥΣ\s+ΤΩΝ\s+'
                     r'ΕΛΛΗΝΩΝ|Ο\s+ΑΝΤΙΒΑΣΙΛΕΥΣ|Η\s+ΙΕΡΑ\s+ΣΥΝΟΔΟΣ|Η\s+ΒΟΥΛΗ\s+ΤΩΝ\s+ΕΛΛΗΝΩΝ|Έχοντας\s+υπ)')
SECTION = re.compile(r'^(ΑΝΑΚΟΙΝΩΣΕΙΣ|ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ|ΑΠΟΦΑΣΕΙΣ|ΠΡΑΞΕΙΣ|ΕΓΚΥΚΛΙΟΙ|ΨΗΦΙΣΜΑΤΑ|ΑΝΑΚΟΙΝΩΣΗ|'
                     r'ΔΙΟΡΘΩΣΗ ΣΦΑΛΜΑΤΟΣ|ΑΠΟΦΑΣΗ|ΠΡΑΞΗ|ΨΗΦΙΣΜΑ|ΕΠΑΝΑΔΗΜΟΣΙΕΥΣΗ.*)$')
GROUP = re.compile(r'^(ΝΟΜΟΙ|ΠΡΟΕΔΡΙΚΑ ΔΙΑΤΑΓΜΑΤΑ|ΚΑΝΟΝΙΣΜΟΙ|ΠΡΑΞΕΙΣ ΝΟΜΟΘΕΤΙΚΟΥ ΠΕΡΙΕΧΟΜΕΝΟΥ|ΠΕΡΙΕΧΟΜΕΝΑ|'
                   r'ΔΙΑΤΑΓΜΑΤΑ|ΒΑΣΙΛΙΚΑ ΔΙΑΤΑΓΜΑΤΑ)$')
BACK = re.compile(r'^(Καποδιστρίου 34|Ταχυδρομική Διεύθυνση|\*\d{10,}\*$|• Τα ΦΕΚ σε έντυπη|ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ$|'
                  r'ΑΠΟ ΤΟ ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ|ΤΙΜΗ ΠΩΛΗΣΗΣ|ΗΛΕΚΤΡΟΝΙΚΗ ΔΙΕΥΘΥΝΣΗ: (http://)?www\.et\.gr)')
ARTIFACT = re.compile(r'^(\(\d{1,3}\)|Ι|I|\*\d{10,}\*)$')
STAMP = re.compile(r'^[A-Z][A-Z .\-]{3,}[A-Z]$')  # a digital-signature stamp name, set small
SIGNED = re.compile(r'^(Αθήνα|Αθήναι|Εν Αθήναις|Στην Αθήνα|Κέρκυρα|Θεσσαλονίκη)[,\s]+(?:τη[νς]?\s+)?(\d{1,2})(?:η|ης)?\s+'
                    r'([Α-Ωα-ωάέήίόύώϊΐ]+)\s+(\d{4})\.?$')
PROMULGATION = re.compile(r'^Παραγγέλλομε(ν)? τη(ν)? δημοσίευση')
SEAL = re.compile(r'^Θεωρήθηκε και τέθηκε η Μεγάλη Σφραγίδα')
DECIDE = re.compile(r'(αποφασίζουμε|αποφασίζομεν|αποφασίζει|αποφασίσαμεν|ψηφίζει)\s*:?\s*$')
STRUCT = re.compile(r'^(ΜΕΡΟΣ|ΤΜΗΜΑ|ΚΕΦΑΛΑΙΟ|ΕΝΟΤΗΤΑ|ΤΙΤΛΟΣ|ΒΙΒΛΙΟ)\b')
ANNEX = re.compile(r'^ΠΑΡΑΡΤΗΜΑ(\s+[Α-ΩA-Z0-9IVXΙΧ’]{1,6})?\.?$')
MONTHS = ['Ιανουαρίου', 'Φεβρουαρίου', 'Μαρτίου', 'Απριλίου', 'Μαΐου', 'Ιουνίου', 'Ιουλίου', 'Αυγούστου',
          'Σεπτεμβρίου', 'Οκτωβρίου', 'Νοεμβρίου', 'Δεκεμβρίου']
MONTH_ALT = {'Μαΐου': 5, 'Μαίου': 5, 'Μαϊου': 5, 'Μαΐου.': 5}
CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\ufffd]')

# ---------------------------------------------------------------- article numbers (digits or ordinal words)

UNITS = {'πρώτ': 1, 'δεύτερ': 2, 'τρίτ': 3, 'τέταρτ': 4, 'πέμπτ': 5, 'έκτ': 6, 'έβδομ': 7, 'όγδο': 8, 'ένατ': 9,
         'έννατ': 9}
TEENS = {'δέκατ': 10, 'ενδέκατ': 11, 'δωδέκατ': 12}
TENS = {'εικοστ': 20, 'τριακοστ': 30, 'τεσσαρακοστ': 40, 'πεντηκοστ': 50, 'εξηκοστ': 60, 'εβδομηκοστ': 70,
        'ογδοηκοστ': 80, 'ενενηκοστ': 90}
HUNDREDS = {'εκατοστ': 100, 'διακοσιοστ': 200, 'τριακοσιοστ': 300, 'τετρακοσιοστ': 400, 'πεντακοσιοστ': 500}
ORD_END = r'(?:ο|όν|ον|ός|ό)'
WORD = re.compile(r'[Α-Ωα-ωάέήίόύώϊΐ]+')


def ordinal(words: str) -> int | None:
    """Neuter (or katharevousa) ordinal words -> number: «πρώτο» 1, «δέκατο τρίτο» 13, «εκατοστό πρώτο» 101."""
    total = 0
    toks = words.lower().split()
    if not toks or len(toks) > 4:
        return None
    for tok in toks:
        stem = re.sub(r'(ο|όν|ον|ός|ό|ου|η|ή)$', '', tok)
        for table in (HUNDREDS, TENS, TEENS, UNITS):
            if stem in table:
                total += table[stem]
                break
        else:
            return None
    return total or None


ART_NUM = re.compile(r'^(?:Άρθρο|ΑΡΘΡΟ|Άρθρον|ΑΡΘΡΟΝ)\s+(\d{1,4})\s*([Α-Ω]{1,2})?\.?$')
ART_WORD = re.compile(r'^(?:Άρθρο|ΑΡΘΡΟ|Άρθρον|ΑΡΘΡΟΝ)\s+([Α-Ωα-ωάέήίόύώϊΐ ]{4,60}?)\.?$')
SUFFIX = {'Α': 'a', 'Β': 'b', 'Γ': 'c', 'Δ': 'd', 'Ε': 'e', 'ΣΤ': 'f', 'Ζ': 'g', 'Η': 'h', 'Θ': 'i', 'Ι': 'j',
          'ΙΑ': 'k', 'ΙΒ': 'l'}


def art_heading(t: str) -> tuple[int, str, str] | None:
    """(number, suffix, style) of an article heading line, else None."""
    m = ART_NUM.match(t)
    if m:
        suf = m.group(2) or ''
        if suf and suf not in SUFFIX:
            return None
        return int(m.group(1)), suf, 'num'
    m = ART_WORD.match(t)
    if m:
        n = ordinal(m.group(1))
        if n:
            return n, '', 'word'
    return None


def art_key(n: int, suf: str) -> str:
    return f'art-{n:03d}' + (SUFFIX[suf] if suf else '')


# ---------------------------------------------------------------- paragraphs

UPPER_START = re.compile(r'^[«"(]?[Α-ΩΆΈΉΊΌΎΏ]')
BODY_START = re.compile(r'^«?(\d+[Α-Ω]?\.\s|[α-ω]{1,3}[)’.]\s|\([α-ω]{1,3}\)\s|[ivx]+\)\s|\[)')


def paragraphs(lines: list[dict]) -> list[str]:
    """Lines of one unit -> paragraphs: a new one at an indented line (> 4 pt), a change of weight, a heading, or
    a numbered line; hyphenated line ends joined back (parse_n4624.join_lines); typesetting tidied (parse.tidy_para)."""
    out: list[str] = []
    cur: list[str] = []
    prev = None
    in_title = False  # the lines right after an article heading: its title (a wrapped title line starts lower case)
    for l in lines:
        t = l['t']
        head = bool(art_heading(t) or STRUCT.match(t) or ANNEX.match(t))
        new = (not cur or l.get('indent', 0) > 4 or head or (prev is not None and prev.get('_head'))
               or (prev is not None and bool(l.get('bold')) != bool(prev.get('bold')))
               or BODY_START.match(t) is not None
               or (in_title and len(cur) and UPPER_START.match(t) is not None
                   and not (prev is not None and prev['_head'])))
        if head and art_heading(t):
            in_title = True
        elif new and not (prev is not None and prev.get('_head')):
            in_title = False
        if new and cur:
            out.append(P.tidy_para(N.join_lines(cur)))
            cur = []
        cur.append(t)
        prev = {**l, '_head': head}
    if cur:
        out.append(P.tidy_para(N.join_lines(cur)))
    return [p for p in out if p]


def quote_delta(t: str) -> int:
    return t.count('«') - t.count('»')


# ---------------------------------------------------------------- dates

def parse_date(d: str, m: str, y: str) -> str | None:
    m = m.strip('.')
    mon = MONTHS.index(m) + 1 if m in MONTHS else MONTH_ALT.get(m)
    if not mon:
        return None
    try:
        import datetime as dt
        return dt.date(int(y), mon, int(d)).isoformat()
    except ValueError:
        return None


def issue_date(meta: dict) -> str:
    mm, dd, yy = meta['issue_date'].split(' ')[0].split('/')
    return f'{yy}-{int(mm):02d}-{int(dd):02d}'


LEAD = r'(?:^|[.:;]\s|\d\.\s)(?:(?:Με την επιφύλαξη|Τηρουμένων|Υπό την επιφύλαξη)[^\n]{0,250}?,?\s+)?'
ACT_WORD = r'(?:\s+(?:νόμου|διατάγματος|πράξης|πράξεως|κανονισμού|Κανονισμού|Κώδικα))?'
CLAUSES = [
    re.compile(LEAD + r'(?:[Ηη] ισχύς|[Ηη] έναρξη ισχύος|[Ηη] ισχύ)\s+(?:του παρόντος|της παρούσας|αυτού|αυτής)'
               + ACT_WORD + r'\s*(?:,[^,]{0,250},)?\s*(?:αρχίζει|εκκινεί|άρχεται)\s+(.{0,160})', re.M),
    re.compile(LEAD + r'(?:[Οο] παρών|[Ηη] παρούσα|[Τ]ο παρόν|[Οο]ι διατάξεις του παρόντος|[Οο]ι διατάξεις της παρούσας)'
               r'(?:\s+(?:νόμος|διάταγμα|πράξη|Κανονισμός|κανονισμός|Κώδικας))?\s+(?:ισχύει|ισχύουν|τίθεται σε ισχύ|'
               r'τίθενται σε ισχύ)\s+(από\s.{0,160})', re.M),
    re.compile(r'(?:^|[.:]\s)Κυρώνεται και έχει ισχύ νόμου\s+(.{0,160})', re.M),
]
TO_PUB = re.compile(r'^(?:από\s+)?(?:τη|την|της)\s+(?:ημερομηνία\s+(?:της\s+)?)?(?:δημοσίευσ|δημοσιεύσε)')
RETRO = re.compile(r'^αναδρομικ')
NUMW = {'ένα': 1, 'έναν': 1, 'μία': 1, 'μια': 1, 'δύο': 2, 'τρεις': 3, 'τρία': 3, 'τέσσερις': 4, 'τέσσερα': 4,
        'πέντε': 5, 'έξι': 6, 'επτά': 7, 'εφτά': 7, 'οκτώ': 8, 'εννέα': 9, 'δέκα': 10, 'έντεκα': 11, 'δώδεκα': 12,
        'δεκαπέντε': 15, 'είκοσι': 20, 'τριάντα': 30, 'εξήντα': 60, 'ενενήντα': 90}
RELATIVE = re.compile(r'^(?:από\s+)?([Α-Ωα-ωάέήίόύώ]+|\d+)\s*(?:\((\d+)\)\s*)?(ημέρ|ημερ|μήν|μην|έτ|ετ)\w*\s+(?:μετά|από)\s+'
                      r'(?:τη|την|της)\s+(?:δημοσίευσ|δημοσιεύσε)')
FIXED = re.compile(r'^(?:από\s+|στις\s+|κατά\s+)?(?:την\s+|τη\s+|τις\s+)?(\d{1,2})(?:η|ης|ην)?\s*\.?\s*'
                   r'(?:(\d{1,2})\.(\d{4})|([Α-Ωα-ωάέήίόύώϊΐ]+)\s+(\d{4}))')


def add_months(iso: str, n: int) -> str | None:
    import calendar
    import datetime as dt
    d = dt.date.fromisoformat(iso)
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def commencement(units: dict[str, list[str]], published: str) -> tuple[str, str]:
    """(from, rule) from the act's own commencement clause (looked for in its last three articles or its operative
    text): publication -> publication day; one fixed date -> that date (a date before publication, or «αναδρομικά»,
    -> publication day); «N ημέρες/μήνες μετά τη δημοσίευση» -> publication + N (computed); anything else ->
    publication day. Provisions the clause starts on other days are not applied (the rule text says so)."""
    import datetime as dt
    keys = [k for k in units if k.startswith('art-')]
    look = keys[-3:] + [k for k in ('keimeno',) if k in units]
    for k in reversed(look):
        text = '\n'.join(units[k])
        for rx in CLAUSES:
            m = rx.search(text)
            if not m:
                continue
            rest = m.group(1).strip()
            extra = (' (other provisions start as the clause states; not applied)'
                     if re.search(r'εκτός|επιφύλαξη|εξαιρ|διαφορετικά|πλην', text) else '')
            if TO_PUB.match(rest):
                return published, f'commencement clause ({k}): from publication{extra}'
            if RETRO.match(rest):
                return published, f'commencement clause ({k}) is retroactive: dated from publication{extra}'
            r = RELATIVE.match(rest)
            if r:
                n = int(r.group(2)) if r.group(2) else (int(r.group(1)) if r.group(1).isdigit()
                                                         else NUMW.get(r.group(1).lower()))
                if n:
                    unit_ = r.group(3)
                    if unit_.startswith(('ημέρ', 'ημερ')):
                        d = (dt.date.fromisoformat(published) + dt.timedelta(days=n)).isoformat()
                    elif unit_.startswith(('μήν', 'μην')):
                        d = add_months(published, n)
                    else:
                        d = add_months(published, 12 * n)
                    return d, f'commencement clause ({k}): {n} {unit_}… after publication = {d} (computed){extra}'
            f = FIXED.match(rest)
            if f:
                d = (f'{int(f.group(3)):04d}-{int(f.group(2)):02d}-{int(f.group(1)):02d}' if f.group(2)
                     else parse_date(f.group(1), f.group(4), f.group(5)))
                try:
                    d = d and dt.date.fromisoformat(d).isoformat()
                except ValueError:
                    d = None
                if d:
                    if d < published:
                        return published, (f'commencement clause ({k}) states {d}, before publication: dated from '
                                           f'publication{extra}')
                    return d, f'commencement clause ({k}): fixed date {d}{extra}'
            return published, f'commencement clause ({k}) not a plain date ({rest[:60]!r}): publication day'
    return published, 'no commencement clause found: publication day'


# ---------------------------------------------------------------- the issue

def find_starts(lines: list[dict]) -> list[tuple[int, str, re.Match]]:
    starts = []
    depth = 0
    for i, l in enumerate(lines):
        t = l['t']
        before = depth
        depth = max(0, depth + quote_delta(t))
        if before > 0:
            continue  # inside a «quotation» (an act reprinted in a ratification law)
        for kind, rx in HEADS:
            m = rx.match(t)
            if not m:
                continue
            nxt = [x['t'] for x in lines[i + 1:i + 13]]
            if any(FORMULA.match(x) for x in nxt) and not any(
                    any(r.match(x) for _, r in HEADS) for x in nxt[:next((j for j, x in enumerate(nxt)
                                                                         if FORMULA.match(x)), 0)]):
                starts.append((i, kind, m))
                depth = 0
            break
    return starts


def split_issue(lines: list[dict], meta: dict) -> dict:
    published = issue_date(meta)
    # the issue's body ends at the publisher's back page
    end = next((i for i, l in enumerate(lines) if BACK.match(l['t'])), len(lines))
    lines = lines[:end]
    starts = find_starts(lines)
    stops = sorted({i for i, l in enumerate(lines) if (SECTION.match(l['t']) or GROUP.match(l['t']))
                    and (l.get('bold') or l['t'].isupper())} | {s[0] for s in starts} | {len(lines)})
    acts, skipped = [], []
    for k, (i, kind, m) in enumerate(starts):
        j = next(s for s in stops if s > i)
        act = parse_act(lines[i:j], kind, m, meta, published, k + 1)
        acts.append(act)
    first = starts[0][0] if starts else len(lines)
    for i, l in enumerate(lines):
        if i > first and SECTION.match(l['t']) and (l.get('bold') or l['t'].isupper()):
            j = next(s for s in stops if s > i)
            skipped.append({'what': l['t'], 'lines': j - i - 1, 'why': 'not an act (section not parsed)'})
    return {'acts': acts, 'skipped': skipped}


def parse_act(lines: list[dict], kind: str, m: re.Match, meta: dict, published: str, order: int) -> dict:
    head = lines[0]['t']
    number = None
    if kind in ('nomos', 'pd', 'an', 'nd', 'nbd', 'bd') and m.groups() and m.group(1):
        number = int(m.group(1))
    if kind == 'kanonismos':
        number = int(m.group(1))
    body = [l for l in lines[1:] if not (ARTIFACT.match(l['t']) or (l.get('small') and STAMP.match(l['t'])))]
    fi = next(i for i, l in enumerate(body) if FORMULA.match(l['t']))
    title = P.tidy_para(N.join_lines([l['t'] for l in body[:fi]]))
    rest = body[fi:]
    # signatures: from the first «Αθήνα, D Month YYYY» on; annexes after them are kept
    signed = None
    sig = None
    for i, l in enumerate(rest):
        s = SIGNED.match(l['t'])
        if s:
            signed = parse_date(s.group(2), s.group(3), s.group(4))
            sig = i
            break
    tail_annex: list[dict] = []
    if sig is not None:
        after = rest[sig + 1:]
        a = next((i for i, l in enumerate(after) if ANNEX.match(l['t'])), None)
        if a is not None:
            tail_annex = after[a:]
        rest = rest[:sig]
    # drop the promulgation sentence of laws (and anything after it before the signatures) and the seal line
    pi = next((i for i, l in enumerate(rest) if PROMULGATION.match(l['t'])), None)
    if pi is not None:
        rest = rest[:pi]
    tail_annex = [l for l in tail_annex if not SEAL.match(l['t'])]
    # articles
    units: dict[str, list[dict]] = {}
    pending: list[dict] = []
    style = None
    prev_n = 0
    prev_suf = ''
    depth = 0
    key = None
    pre: list[dict] = []
    gaps = []
    for l in rest:
        t = l['t']
        h = art_heading(t)
        if h and not t.startswith('«'):
            n, suf, st = h
            ok = False
            if style is None:
                ok = n == 1 and not suf
            elif st == style:
                ok = (prev_n < n <= prev_n + 3 and not suf) or (n == prev_n and suf and suf != prev_suf) \
                     or (n == prev_n + 1 and suf)
                if ok and depth > 0 and not (n == prev_n + 1 or (n == prev_n and suf)):
                    ok = False
            if ok:
                if style is None:
                    style = st
                if n > prev_n + 1 and not suf:
                    gaps.append(f'Άρθρο {prev_n + 1}..{n - 1} not found')
                depth = 0
                key = art_key(n, suf)
                if key in units:
                    key = None
                    ok = False
                else:
                    units[key] = pending + [l]
                    pending = []
                    prev_n, prev_suf = n, suf
                    continue
        if key is None:
            pre.append(l)
            continue
        if depth == 0 and STRUCT.match(t) and l.get('bold', True):
            pending.append(l)
            continue
        if depth == 0 and ANNEX.match(t):
            key = f'parartima-{sum(1 for k in units if k.startswith("parartima")) + 1:02d}'
            units[key] = pending + [l]
            pending = []
            continue
        if pending:
            units[key].extend(pending)
            pending = []
        units[key].append(l)
        depth = max(0, depth + quote_delta(t))
    if pending and key:
        units[key].extend(pending)
    for l in tail_annex:
        if ANNEX.match(l['t']):
            key = f'parartima-{sum(1 for k in units if k.startswith("parartima")) + 1:02d}'
            units[key] = []
        units[key].append(l)
    # preamble / text before the first article
    out: dict[str, list[str]] = {}
    if pre:
        if kind == 'nomos':
            pass  # formula + table of contents: not carried (as the hand-built parts)
        elif any(k.startswith('art-') for k in units):
            out['prooimio'] = paragraphs(pre)
        else:
            d = next((i for i, l in enumerate(pre) if DECIDE.search(l['t'])), None)
            if d is None:
                out['keimeno'] = paragraphs(pre)
            else:
                out['prooimio'] = paragraphs(pre[:d + 1])
                if pre[d + 1:]:
                    out['keimeno'] = paragraphs(pre[d + 1:])
    for k, ls in units.items():
        out[k] = paragraphs(ls)
    out = {k: v for k, v in out.items() if v}
    frm, rule = commencement(out, published)
    pages = sorted({l['p'] for l in lines})
    held = None
    text = '\n'.join('\n'.join(v) for v in out.values())
    if CONTROL.search(text):
        held = 'text layer has control characters (unmapped font): needs OCR or a font map'
    no_text = set(meta.get('no_text_pages') or [])
    if no_text and any(pages[0] <= p <= pages[-1] + 1 for p in no_text):
        held = held or f'pages without a text layer inside the act ({sorted(no_text)[:5]}...): needs OCR'
    if not any(k.startswith(('art-', 'keimeno')) for k in out):
        held = held or 'no articles or operative text found'
    if kind == 'nomos' and number is None:
        held = held or 'law without a number'
    return {'kind': kind, 'number': number, 'order': order, 'heading': head, 'title': title, 'signed': signed,
            'published': published, 'from': frm, 'from_rule': rule, 'units': out, 'pages': [pages[0], pages[-1]],
            'gaps': gaps, 'held': held}
