"""GR-B: split one ΦΕΚ Β΄ issue into its items (decisions, regulations, corrections), and each item into its parts.

    split_issue(lines, meta) -> {'items': [item, ...], 'contents': [str] | None, 'problems': [str]}

lines: body lines in reading order from ga_order.reading_order(doc) (a frozen copy of GR-A's order.py, so GR-A's live
edits never change this worker's output); each {'t', 'p', 'indent', 'bold', 'small', 'wide'}.

How an issue is laid out (Β΄ 2026 text layer; checked by hand on the first issues of 2026):
  page 0 head (stamp, ΕΦΗΜΕΡΙΔΑ, ΤΕΥΧΟΣ ΔΕΥΤΕΡΟ), then, when the issue holds more than one item, ΠΕΡΙΕΧΟΜΕΝΑ: centred
  group headers (ΑΠΟΦΑΣΕΙΣ, ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ, ...) and each item's title; then the body: a left-set group header,
  and the items, each
      Αριθμ. <protocol>          (heading; one or two lines; absent for corrections and some extracts)
      (N)                       (the item's number in the issue; absent when the issue holds one item)
      <title>                   (bold)
      <issuing authority>       (Ο ΥΠΟΥΡΓΟΣ ..., ΟΙ ΥΠΟΥΡΓΟΙ ..., ΤΟ ΔΙΟΙΚΗΤΙΚΟ ΣΥΜΒΟΥΛΙΟ ..., Ο ΔΗΜΑΡΧΟΣ ...)
      Έχοντας υπόψη: ... αποφασίζουμε:   (preamble)
      <operative text>          (Άρθρο N headings, or numbered paragraphs, or plain text)
      <place>, <date>           (signature block: signatory titles and names; not carried)
      ΠΑΡΑΡΤΗΜΑ ...             (annexes printed after the signatures are kept)
      Ι                         (a separator glyph between items)
  and the publisher's back page.

Each item: {'n', 'section', 'heading', 'protocol_raw', 'title', 'issuer_lines', 'preamble', 'body', 'annexes',
            'signed', 'place', 'pages', 'lines': n}
  preamble/body/annexes are line-dict lists (body = operative text; annexes = list of line lists).
"""
from __future__ import annotations

import re
import unicodedata

import ga_split as GA

SECTION_WORDS = (r'ΠΡΟΕΔΡΙΚΑ ΔΙΑΤΑΓΜΑΤΑ|ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ|ΔΙΑΤΑΓΜΑΤΑ|ΔΙΑΤΑΓΜΑ|ΑΠΟΦΑΣΕΙΣ|ΑΠΟΦΑΣΗ|ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ|ΔΙΟΡΘΩΣΗ ΣΦΑΛΜΑΤΟΣ|ΚΑΝΟΝΙΣΜΟΙ|ΚΑΝΟΝΙΣΜΟΣ|ΠΡΑΞΕΙΣ|ΠΡΑΞΗ|'
                 r'ΕΓΚΥΚΛΙΟΙ|ΕΓΚΥΚΛΙΟΣ|ΑΝΑΚΟΙΝΩΣΕΙΣ|ΑΝΑΚΟΙΝΩΣΗ|ΑΠΟΣΠΑΣΜΑΤΑ|ΑΠΟΣΠΑΣΜΑ|ΠΕΡΙΛΗΨΕΙΣ|ΠΕΡΙΛΗΨΗ|'
                 r'ΑΝΑΚΛΗΣΕΙΣ|ΤΡΟΠΟΠΟΙΗΣΕΙΣ|ΕΠΑΝΑΔΗΜΟΣΙΕΥΣΕΙΣ|ΕΠΑΝΑΔΗΜΟΣΙΕΥΣΗ|ΓΝΩΜΟΔΟΤΗΣΕΙΣ|ΓΝΩΜΟΔΟΤΗΣΗ|'
                 r'ΨΗΦΙΣΜΑΤΑ|ΑΠΟΦΑΣΕΙΣ ΔΗΜΟΤΙΚΩΝ ΣΥΜΒΟΥΛΙΩΝ|ΠΡΟΚΗΡΥΞΕΙΣ|ΣΥΜΒΑΣΕΙΣ|ΠΡΑΞΕΙΣ ΥΠΟΥΡΓΙΚΟΥ ΣΥΜΒΟΥΛΙΟΥ|'
                 r'ΔΙΑΤΑΓΕΣ|ΑΠΟΦΑΣΕΙΣ ΥΠΟΥΡΓΩΝ|ΠΡΑΞΕΙΣ ΤΟΥ ΥΠΟΥΡΓΙΚΟΥ ΣΥΜΒΟΥΛΙΟΥ|ΟΔΗΓΙΕΣ|ΣΥΜΠΛΗΡΩΜΑΤΙΚΑ')
SECTION = re.compile(rf'^({SECTION_WORDS})\.?$')
CONTENTS = re.compile(r'^ΠΕΡΙΕΧΟΜΕΝΑ$')
MARK = re.compile(r'^\((\d{1,3})\)$')
SEP = re.compile(r'^[ΙI]$')
HEAD = re.compile(r'^(Αρ[ιί]θμ\.?|Αρ[ιί]θ\.|Αρ\.|Αρ[ιί]θμός|ΑΡΙΘΜ\.?|Υπ[’\']?\s*αρ[ιί]θμ\.?)\s*(.*)$')
BACK = re.compile(r'^(Το Εθνικό Τυπογραφείο αποτελεί δημόσια υπηρεσία|Καποδιστρίου 34|Ταχυδρομική Διεύθυνση|'
                  r'ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ$|ΑΠΟ ΤΟ ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ|ΤΙΜΗ ΠΩΛΗΣΗΣ|\*\d{10,}\*$)')
HEADJUNK = re.compile(r'^(ΕΦΗΜΕΡΙΔΑ|ΤΕΥΧΟΣ ΔΕΥΤΕΡΟ|ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ|ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ|'
                      r'\(Το παρόν ΦΕΚ επανεκτυπώθηκε.*\))$')
PREAMBLE = re.compile(r'^(Έχοντας|Έχοντες|Έχουσα|Έχοντα|Αφού έλαβε|Λαμβάνοντας)\s+υπ')
DECIDE_F = re.compile(r'(αποφασιζ\w*|αποφασισ\w*|αποφαινεται|ψηφιζει)\s*(,?\s*(ομοφωνα|ομοφωνως|κατα '
                      r'πλειοψηφια|ως εξης|τα εξης|τα ακολουθα))?\s*[:·.]?\s*$|(διαπιστωνουμε|διαπιστωνει|εγκρινουμε|'
                      r'εγκρινει|κηρυσσουμε|ανακοινωνουμε)\s*[:·]\s*$')


def fold(t: str) -> str:
    """Lower case without accents (a deciding word is sometimes typed without its accent: «αποφασιζουμε»)."""
    return ''.join(c for c in unicodedata.normalize('NFD', t.lower()) if not unicodedata.combining(c))


class _Decide:
    @staticmethod
    def search(t: str):
        return DECIDE_F.search(fold(t))


def decide_at(ls: list[dict]) -> int | None:
    """Index of the line that closes the recitals («..., αποφασίζουμε:»), also when the word is hyphenated across
    two lines («αποφα-» / «σίζουμε:»): then the second line's index."""
    for k, l in enumerate(ls):
        t = l['t']
        if DECIDE.search(t):
            return k
        if t.endswith('-') and k + 1 < len(ls) and DECIDE.search(t[:-1] + ls[k + 1]['t']):
            return k + 1
    return None


DECIDE = _Decide
MONTHS = GA.MONTHS
MON = '|'.join(MONTHS + ['Μαίου', 'Μαϊου', 'Μαΐου'])
PLACE_DATE = re.compile(rf'^(?:Εν\s+|Στην?\s+|Στο\s+)?([Α-ΩΆΈΉΊΌΎΏ][^\d,;:«»()]{{1,45}}?)\s*,\s*(?:τη[νς]?\s+|την\s+)?'
                        rf'(\d{{1,2}})(?:η|ης|ην)?\s+({MON})\s+(\d{{4}})\.?$')
PLACE_DATE_NUM = re.compile(r'^(?:Εν\s+|Στην?\s+)?([Α-ΩΆΈΉΊΌΎΏ][^\d,;:«»()]{1,45}?)\s*,\s*(\d{1,2})[./-](\d{1,2})[./-]'
                            r'(\d{4})\.?$')
SIG_ROLE = re.compile(r'^(Με εντολή|Κατ[’\']\s*εντολή|Με εξουσιοδότηση|Ακριβές αντίγραφο|Για τον|Για την|Ο/Η|Οι\s|Ο\s|Η\s|'
                      r'Τα\s+[Μμ]έλη|Τα\s+[Μμ]έλη|Ο\s+Αναπληρωτής|Η\s+Αναπληρώτρια|Ο\s+Πρόεδρος|Η\s+Πρόεδρος)')
NAME_LINE = re.compile(r'^[Α-ΩΆΈΉΊΌΎΏΪΫA-Z][Α-ΩΆΈΉΊΌΎΏΪΫA-Z.’\'\- ]{2,60}$')


def trim_signatures(rest: list[dict]) -> list[dict]:
    """Drop a trailing signature block that has no «<place>, <date>» line: signatories' roles («Ο Δήμαρχος», «Με
    εντολή Προϊσταμένης ...») and names in capitals. Only a short block (<= 12 lines) that holds at least one
    capitalised name line and one role line, and ends the item, is dropped (a table ending in capitals is not)."""
    k = len(rest)
    names = roles = 0
    while k > 0 and len(rest) - k < 12:
        t = rest[k - 1]['t']
        if NAME_LINE.match(t) and len(t.split()) <= 6 and not re.search(r'\d', t):
            names += 1
        elif SIG_ROLE.match(t) and len(t) < 100 and not t.rstrip().endswith(('.', ':', ';', ',')):
            roles += 1
        else:
            break
        k -= 1
    if names and roles:
        return rest[:k]
    return rest


FROM_LINE = re.compile(r'^\((Από|Εκ)\s+(τ[οηνα]ν?|τους|της|του)\s+.{3,120}\)\.?$')
ANNEX = re.compile(r'^(ΠΑΡΑΡΤΗΜΑ|Παράρτημα)(\s+[Α-ΩA-Z0-9IVXΙΧ’΄\'.-]{1,8})?\s*[:.]?$')
ISSUER_START = re.compile(r'^(Ο|Η|ΟΙ|ΤΟ|ΤΑ|ΤΗΣ|Η\s+ΟΛΟΜΕΛΕΙΑ|Το|Οι)\s+[Α-ΩΆΈΉΊΌΎΏ]')


def is_section(l: dict) -> bool:
    return bool(SECTION.match(l['t'])) and (l.get('bold') or l['t'].isupper())


def signed_at(t: str) -> tuple[str, str] | None:
    m = PLACE_DATE.match(t)
    if m:
        d = GA.parse_date(m.group(2), m.group(3), m.group(4))
        if d:
            return m.group(1).strip(), d
    m = PLACE_DATE_NUM.match(t)
    if m:
        try:
            import datetime as dt
            return m.group(1).strip(), dt.date(int(m.group(4)), int(m.group(3)), int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def split_issue(lines: list[dict], meta: dict) -> dict:
    problems: list[str] = []
    end = next((i for i, l in enumerate(lines) if BACK.match(l['t']) and i > 0), len(lines))
    lines = lines[:end]
    # page-0 head: drop the stamp and the masthead lines before the first section / contents header
    # page-0 masthead: the signature stamp (small type) and the title lines of the Gazette
    first = 0
    while first < len(lines) and lines[first]['p'] == 0 and (lines[first].get('small') or
                                                             HEADJUNK.match(lines[first]['t'])):
        first += 1
    if first >= len(lines):
        return {'items': [], 'contents': None, 'problems': ['no text after the masthead']}
    contents = None
    body_start = first
    if CONTENTS.match(lines[first]['t']):
        # contents: centred group headers and titles, up to the body: the first left-set header line, «Αριθμ. ...»
        # line or right-set item number
        j = next((i for i in range(first + 1, len(lines)) if not lines[i].get('wide') and (
            (lines[i].get('bold') and lines[i]['t'].isupper() and lines[i].get('indent', 0) < 60)
            or HEAD.match(lines[i]['t']) or MARK.match(lines[i]['t']))), None)
        if j is None:
            return {'items': [], 'contents': None, 'problems': ['contents without a body start']}
        contents = [l['t'] for l in lines[first + 1:j] if not is_section(l)]
        body_start = j
    body = lines[body_start:]
    right: dict[int, float] = {}
    for l in lines:
        right[l['p']] = max(right.get(l['p'], 0.0), l.get('x1', 0.0))
    # an item number «(N)» is set in body type, not bold (table footnote numbers are small and bold), flush right
    # (its right end at the page's text edge) or right under a separator / section header / Αριθμ. heading (opens_item)
    marks = [i for i, l in enumerate(body) if MARK.match(l['t']) and not l.get('small') and not l.get('bold')
             and (opens_item(body, i) or l.get('x1', 0) >= right.get(l['p'], 1e9) - 15)]
    # keep the run 1, 2, 3 ... (a stray «(N)» that survives the filter breaks the run and is ignored)
    run, want = [], 1
    for i in marks:
        if int(MARK.match(body[i]['t']).group(1)) == want:
            run.append(i)
            want += 1
    if len(run) != len(marks):
        problems.append(f'markers outside the 1..n run ignored: {len(marks) - len(run)}')
    marks = run
    nums = [int(MARK.match(body[i]['t']).group(1)) for i in marks]
    if marks and nums != list(range(1, len(nums) + 1)):
        problems.append(f'item numbers not 1..n: {nums[:20]}')
    items = []
    if not marks:
        items.append(parse_item(body, 1, meta, problems))
    else:
        starts = []
        for k, m in enumerate(marks):
            lo = marks[k - 1] + 1 if k else 0
            s = m
            # heading lines above the marker: back to the last separator / section header / signature line
            while s - 1 >= lo and not (SEP.match(body[s - 1]['t']) or is_section(body[s - 1])) and m - (s - 1) <= 4:
                s -= 1
            if s < m and not HEAD.match(body[s]['t']):
                # only lines that open with Αριθμ. (and their wrap) belong to the heading
                h = next((i for i in range(s, m) if HEAD.match(body[i]['t'])), m)
                s = h
            starts.append(s)
        for k, s in enumerate(starts):
            e = starts[k + 1] if k + 1 < len(starts) else len(body)
            chunk = body[s:e]
            # trailing separators and section headers belong to no item
            while chunk and (SEP.match(chunk[-1]['t']) or is_section(chunk[-1])):
                chunk = chunk[:-1]
            sec = section_of(body, s)
            items.append(parse_item(chunk, k + 1, meta, problems, section=sec, numbered=True))
    if contents is not None:
        problems.extend(check_contents(contents, items))
    return {'items': items, 'contents': contents, 'problems': problems}


def squash(t: str) -> str:
    """Folded letters and digits only: titles in the contents and over the item compare whatever the line breaks,
    hyphenation, quotes or spacing."""
    return re.sub(r'[^0-9a-zα-ω]', '', fold(t))


def check_contents(contents: list[str], items: list[dict]) -> list[str]:
    """The ΠΕΡΙΕΧΟΜΕΝΑ list each item's title, in order. Each item title (corrections: their first line) must be
    found in the contents text, after the previous one, and no long stretch of the contents may be left over (an
    item the splitter missed)."""
    text = squash(' '.join(contents))
    pos, missing, spans = 0, [], []
    for it in items:
        key = squash(it['title'] or (it['body'][0]['t'] if it['body'] else ''))[:60]
        if not key:
            missing.append(it['n'])
            continue
        k = text.find(key, pos)
        if k < 0:
            # a correction is listed by its own title («Διόρθωση σφάλματος στην ...»), not its first line
            missing.append(it['n'])
            continue
        spans.append((k, k + len(squash(it['title'])) if it['title'] else k + len(key)))
        pos = k + len(key)
    out = []
    covered = sum(e - b for b, e in spans)
    left = len(text) - covered
    n_corr = sum(1 for it in items if it['section'].startswith('ΔΙΟΡΘΩΣ'))
    if [m for m in missing if not items[m - 1]['section'].startswith('ΔΙΟΡΘΩΣ')]:
        out.append(f'contents: titles not found for items {missing}')
    if left > 40 + 130 * n_corr:
        out.append(f'contents: {left} characters not matched to an item (an item missed?)')
    return out


def opens_item(body: list[dict], m: int) -> bool:
    """An item number «(N)» opens an item: above it are at most three heading lines (Αριθμ. ... and its wrap),
    and above those a separator glyph, a section header, or the start of the body."""
    if any(HEAD.match(body[k]['t']) for k in range(max(0, m - 2), m)):
        return True  # «Αριθμ. ...» right above (the separator glyph may be lost at a page break)
    k, seen_head = m - 1, False
    while k >= 0 and m - k <= 4:
        t = body[k]['t']
        if SEP.match(t) or is_section(body[k]):
            return True
        if HEAD.match(t):
            seen_head = True
        elif not seen_head and m - k > 1 and not HEAD.match(body[k + 1]['t']):
            return False
        k -= 1
    return k < 0


def section_of(body: list[dict], s: int) -> str:
    for i in range(s, -1, -1):
        if is_section(body[i]):
            return body[i]['t'].rstrip('.')
    return ''


def parse_item(chunk: list[dict], n: int, meta: dict, problems: list[str], section: str | None = None,
               numbered: bool = False) -> dict:
    if section is None:
        # leading header lines (ΑΠΟΦΑΣΕΙΣ, or a ministry name set as a header) before the «Αριθμ.» heading / title
        k = 0
        while k < len(chunk) and k < 3 and (is_section(chunk[k]) or (
                chunk[k].get('bold') and chunk[k]['t'].isupper() and len(chunk[k]['t']) < 80
                and k + 1 < len(chunk) and (HEAD.match(chunk[k + 1]['t']) or is_section(chunk[k + 1])))):
            k += 1
        section = ' / '.join(l['t'].rstrip('.') for l in chunk[:k])
        chunk = chunk[k:]
    # drop separators / stray page artefacts inside
    chunk = [l for l in chunk if not SEP.match(l['t']) and not (l.get('small') and GA.STAMP.match(l['t']))]
    i = 0
    heading: list[str] = []
    while i < len(chunk) and not MARK.match(chunk[i]['t']) and (HEAD.match(chunk[i]['t']) if not heading else
                                                                 (not chunk[i].get('bold') and i < 3
                                                                  and not ISSUER_START.match(chunk[i]['t'])
                                                                  and not PREAMBLE.match(chunk[i]['t'])
                                                                  and len(chunk[i]['t']) < 60
                                                                  and not chunk[i].get('wide'))):
        heading.append(chunk[i]['t'])
        i += 1
    if i < len(chunk) and MARK.match(chunk[i]['t']):
        i += 1
    rest = chunk[i:]
    # title: the bold lines that follow (text layer); without weights: up to the issuer line / preamble
    title_l: list[dict] = []
    has_bold = any(l.get('bold') for l in rest[:12])
    j = 0
    if has_bold:
        while j < len(rest) and rest[j].get('bold') and not PREAMBLE.match(rest[j]['t']):
            if title_l and ISSUER_START.match(rest[j]['t']) and rest[j]['t'].isupper():
                break
            title_l.append(rest[j])
            j += 1
    else:
        while j < len(rest) and j < 12 and not PREAMBLE.match(rest[j]['t']) and not (
                ISSUER_START.match(rest[j]['t']) and rest[j]['t'].split(' ', 1)[-1][:6].isupper()):
            title_l.append(rest[j])
            j += 1
        if j >= len(rest) or j >= 12:
            title_l, j = [], 0
    rest = rest[j:]
    # issuer lines: up to the preamble opening (only when one follows within 6 lines)
    issuer: list[str] = []
    p = next((k for k, l in enumerate(rest[:8]) if PREAMBLE.match(l['t'])), None)
    if p is not None:
        issuer = [l['t'] for l in rest[:p]]
        rest = rest[p:]
    elif rest and ISSUER_START.match(rest[0]['t']) and rest[0]['t'][:12].isupper():
        k = 0
        while k < len(rest) and k < 4 and rest[k]['t'].isupper() and not DECIDE.search(rest[k]['t']):
            issuer.append(rest[k]['t'])
            k += 1
        rest = rest[k:]
    # signature block: the last «<place>, <date>» line (or «(Από τον ...)» of a correction) ends the text;
    # annexes after it are kept
    sig = None
    signed = place = None
    for k in range(len(rest) - 1, -1, -1):
        s = signed_at(rest[k]['t'])
        if s and k >= len(rest) * 0.3 - 1:
            sig = k
            place, signed = s
            # an annex printed after the signatures has its own heading; anything before it stays text
            break
    if sig is None:
        for k in range(len(rest) - 1, -1, -1):
            if FROM_LINE.match(rest[k]['t']):
                sig = k
                break
    annexes: list[list[dict]] = []
    if sig is not None:
        after = rest[sig + 1:]
        a = next((k for k, l in enumerate(after) if ANNEX.match(l['t'])), None)
        if a is not None:
            cur: list[dict] = []
            for l in after[a:]:
                if ANNEX.match(l['t']) and cur:
                    annexes.append(cur)
                    cur = []
                cur.append(l)
            if cur:
                annexes.append(cur)
        rest = rest[:sig]
    rest = trim_signatures(rest)
    # preamble: from «Έχοντας υπόψη» to the deciding line
    preamble: list[dict] = []
    if rest and PREAMBLE.match(rest[0]['t']):
        d = decide_at(rest)
        if d is None:
            problems.append(f'item {n}: preamble without a deciding line')
            d = -1
        preamble = rest[:d + 1] if d >= 0 else []
        rest = rest[d + 1:] if d >= 0 else rest
    else:
        # a deciding line may come right after the issuer (no recitals)
        if rest and DECIDE.search(rest[0]['t']) and len(rest[0]['t']) < 40:
            preamble, rest = rest[:1], rest[1:]
    pages = sorted({l['p'] for l in chunk}) or [0]
    head = ' '.join(heading)
    m = HEAD.match(head) if head else None
    return {'n': n, 'section': section or '', 'heading': head, 'protocol_raw': (m.group(2).strip() if m else ''),
            'title': GA.P.tidy_para(GA.N.join_lines([l['t'] for l in title_l])), 'issuer_lines': issuer,
            'preamble': preamble, 'body': rest, 'annexes': annexes, 'signed': signed, 'place': place,
            'pages': [pages[0], pages[-1]], 'nlines': len(chunk)}
