"""GR-L: turn one Diavgeia decision's stored text (text/<org>/<year>/<ADA-ascii>.json.gz) into act units.

parse(doc) -> {'units': {key: [paragraphs]}, 'operative': bool, 'hold': reason or None, 'checks': {...}}

Deterministic rules (one general rule each; see PROGRESS.md for the spot-checks):
- Noise lines dropped: the ΑΔΑ page header, "Α.Δ.Σ. N/date" running heads, page numbers, the Diavgeia digital-signature
  stamp, "-/-" and "-Ο-" separators.
- Paragraphs: lines are joined unless the line starts an enumerated item or heading, the previous line ends a sentence
  and this one starts with a capital, or the vertical gap is > 1.6 line heights; end-of-line hyphens inside a word are
  removed.
- The operative part starts at the decision formula (ΑΠΟΦΑΣΙΖΕΙ / ΑΠΟΦΑΣΙΖΟΥΜΕ / Αποφασίζει ..., also letter-spaced).
- Units: `prooimio` (everything before the first article, or before the formula when there are no articles);
  `art-NNN` for articles numbered 1, 2, 3 ... in order (Άρθρο 5Α -> art-005a); without articles, the operative part is
  split into `para-NNN` at its top-level enumeration (para-001 = the text before the first item); annexes after the
  signatures -> `parartima-NN`.
- The signature block (Ο ΠΡΟΕΔΡΟΣ / Ο ΔΗΜΑΡΧΟΣ ... after the formula), "Ακριβές απόσπασμα", the members' signatures
  and distribution lists (Κοινοποίηση, Πίνακας Αποδεκτών, Εσωτερική διανομή) are not act text.
- Hold (metadata only) when: no text layer; garbled text; under 150 letters; the text names private persons (see
  PRIVATE); the decision formula shows a preparatory act (εισηγείται / γνωμοδοτεί / παραπέμπει) or a rejection.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common_l import norm_line  # noqa: E402

NOISE = re.compile(r'^(ΑΔΑ\s*:?\s*[0-9Α-ΩA-Z]{4,}[-–][0-9Α-ΩA-Z]{2,}|Α\.?\s?Δ\.?\s?Σ\.?\s*:?\s*\d+\s*/\s*[\d.\-/]+|'
                   r'σελ(ίδα|\.)\s*\d+(\s*(από|/)\s*\d+)?|-\s*/\s*-|-\s*[ΟO0]\s*-|'
                   r'Digitally signed by.*|Date\s*:.*|Reason\s*:.*|Location\s*:.*|Ψηφιακά υπογεγραμμένο.*|'
                   r'Ημερομηνία\s*:\s*\d{4}\.\d\d\.\d\d.*|[-_=.…]{5,})$')
PAGENO = re.compile(r'^-?\s*\d{1,3}\s*-?$|^\d{1,3}\s*/\s*\d{1,3}$')
SIGSTAMP = re.compile(r'^(Digitally signed by|Ψηφιακά υπογεγραμμένο)')
ENUM = re.compile(r'^(\(?\d{1,3}(\.\d{1,3}){0,3}[.)]\s|\(?[α-ωά-ώ]{1,2}[.)]\s|\(?[Α-Ω]{1,2}[.)]\s|\(?[ivxIVX]{1,4}[.)]\s|'
                  r'[-–•►▪●]\s|(Άρθρο|ΑΡΘΡΟ|Αρθρο)\s)')
# The decision formula: at a paragraph start (ΑΠΟΦΑΣΙΖΕΙ, Αποφασίζει ομόφωνα, Το Δημοτικό Συμβούλιο αποφασίζει ...)
FORMULA = re.compile(r'^(?:(?:Το|Η|Ο)\s+\S+(?:\s+\S+){0,6}\s+)?(?:ΟΜΟΦΩΝΑ\s+|ΚΑΤΑ\s+ΠΛΕΙΟΨΗΦΙΑ\s+)?'
                     r'(ΑΠΟΦΑΣΙ[ΖΣ](?:ΕΙ|Ε|ΟΥΜΕ|ΕΤΑΙ|ΟΥΝ)|ΑΠΟΦΑΣΊ[ΖΣ]\w*|[Αα]ποφασίζ(?:ει|ουμε|εται)|[Αα]ποφάσισε)\b')
# ... or inside a paragraph (Patras: "..., το Σώμα, ΟΜΟΦΩΝΑ ΑΠΟΦΑΣΙΖΕΙ:" followed by the operative text)
INLINE = re.compile(r'(?:ΟΜΟΦΩΝΑ\s+|ΚΑΤΑ\s+ΠΛΕΙΟΨΗΦΙΑ\s+)?ΑΠΟΦΑΣΙ[ΖΣ](?:ΕΙ|Ε|ΟΥΜΕ|ΕΤΑΙ)\b(?:\s+(?:ΟΜΟΦΩΝΑ|ΚΑΤΑ\s+ΠΛΕΙΟΨΗΦΙΑ))?'
                    r'\s*:?|(?:ομόφωνα\s+|κατά\s+πλειοψηφία\s+)[Αα]ποφασίζει\s*:?|[Αα]ποφασίζει\s+(?:ομόφωνα|κατά\s+πλειοψηφία)\s*:?')
SPACED = re.compile(r'(?<!\S)(?:[Α-ΩΆ-Ώα-ωά-ώ] ){3,}[Α-ΩΆ-Ώα-ωά-ώ](?!\S)')
STAMP_BITS = re.compile(r'\s*(Ministry\s+of(\s+Digital(\s+Governance)?)?|(of\s+)?Digital\s+Governance|Hellenic\s+Republic|'
                        r'Digitally signed by|Signature Not Verified|'
                        r'\d{4}[.-]\d\d[.-]\d\d\s+\d\d:\d\d:\d\d(\s*[+-]\d\d:?\d\d)?|'
                        r'\d\d:\d\d:\d\d\s*(EEST|EET)|\bEEST\b)\s*')
PREP_ANY = re.compile(r'\b(εισηγείτ?αι|εισηγούμαστε|γνωμοδοτεί|προτείνει)\s+(στο|προς|θετικά|αρνητικά|όπως)', re.I)
PREP_OPER = re.compile(r'^\W*(?:\d+[.)]\s*|[α-ωΑ-Ω][.)]\s*)?(εισηγ(είτ?αι|ούμαστε|ούνται)|γνωμοδοτ(εί|ούμε)|'
                       r'παραπέμπ(ει|ουμε)|προτείνει|δεν\s+εγκρίνει|απορρίπτει|δεν\s+αποδέχεται|'
                       r'(την\s+)?αναβολή|(την\s+)?επαναφορά\s+του\s+θέματος|(εγκρίνει\s+)?το\s+κατεπείγον)', re.I)
COMMUNITY = re.compile(r'(ΣΥΜΒΟΥΛΙΟ|Συμβούλιο)\s+(ΤΗΣ\s+|της\s+)?(\d+ης\s+)?(ΔΗΜΟΤΙΚΗΣ|ΤΟΠΙΚΗΣ|Δημοτικής|Τοπικής)\s+(ΚΟΙΝΟΤΗΤΑΣ|Κοινότητας)')
TOC = re.compile(r'(\.{4,}|…{2,}|_{4,})\s*\d*\s*$|\.{6,}')
ART = re.compile(r'^(?:Άρθρο|ΑΡΘΡΟ|Αρθρο|ΆΡΘΡΟ)\s*(\d{1,3})([ΑΒΓΔΕΖABCDEF](?![^\W\d_]))?(?:ο|ον|o|º|°|Ο)?(?![^\W\d_])\.?\s*[:\-–.]?\s*(.*)$')
ORD = {'ΠΡΩΤΟ': 1, 'ΔΕΥΤΕΡΟ': 2, 'ΤΡΙΤΟ': 3, 'ΤΕΤΑΡΤΟ': 4, 'ΠΕΜΠΤΟ': 5, 'ΕΚΤΟ': 6, 'ΕΒΔΟΜΟ': 7, 'ΟΓΔΟΟ': 8,
       'ΕΝΑΤΟ': 9, 'ΔΕΚΑΤΟ': 10}
ART_WORD = re.compile(r'^(?:Άρθρο|ΑΡΘΡΟ|Αρθρο)\s+(' + '|'.join(ORD) + r')\b\s*[:\-–.]?\s*(.*)$', re.I)
SIGN = re.compile(r'^(?:(?:Ο|Η|O)\s+(?:ΠΡΟΕΔΡΟΣ|ΠΡΟΕΔΡΕΥΩΝ|ΠΡΟΕΔΡΕΥΟΥΣΑ|ΔΗΜΑΡΧΟΣ|ΑΝΤΙΔΗΜΑΡΧΟΣ|ΠΕΡΙΦΕΡΕΙΑΡΧΗΣ|'
                  r'ΑΝΤΙΠΕΡΙΦΕΡΕΙΑΡΧΗΣ|ΓΕΝΙΚΟΣ\s+ΓΡΑΜΜΑΤΕΑΣ|ΣΥΝΤΑΚΤΗΣ|ΓΡΑΜΜΑΤΕΑΣ|ΣΥΝΤΟΝΙΣΤΗΣ)|'
                  r'Ο\s+Πρόεδρος|Η\s+Πρόεδρος|Ο\s+Δήμαρχος|Ο\s+Αντιδήμαρχος|Ακριβές\s+[Αα]πόσπασμα|ΑΚΡΙΒΕΣ\s+ΑΠΟΣΠΑΣΜΑ|'
                  r'ΤΑ\s+ΜΕΛΗ|Τα\s+[Μμ]έλη|ΠΡΟΕΔΡΟΣ|Ο ΠΡΟΕΔΡΟΣ ΤΟΥ|Π Ρ Ο Ε Δ Ρ Ο Σ|Μ\.Ε\.Π\.|Μ\.Ε\.Δ\.)\b')
DISTRIB = re.compile(r'^(Κοινοποίηση|ΚΟΙΝΟΠΟΙΗΣΗ|Πίνακας\s+[Αα]ποδεκτών|ΠΙΝΑΚΑΣ\s+ΑΠΟΔΕΚΤΩΝ|Πίνακας\s+[Δδ]ιανομής|'
                     r'ΠΙΝΑΚΑΣ\s+ΔΙΑΝΟΜΗΣ|Εσωτερική\s+[Δδ]ιανομή|ΕΣΩΤΕΡΙΚΗ\s+ΔΙΑΝΟΜΗ|Αποδέκτες|ΑΠΟΔΕΚΤΕΣ|Κοιν\.\s*:)\b')
ANNEX = re.compile(r'^(ΠΑΡΑΡΤΗΜΑ|Παράρτημα)\b')
# Private persons: identity numbers, or a private role (applicant, owner, resident, citizen ...) followed by a name.
PRIVATE = re.compile(
    r'\bΑ\.?\s?Φ\.?\s?Μ\.?\s*:?\s*\d{9}\b|\bΑ\.?\s?Δ\.?\s?Τ\.?\s*:?\s*[Α-ΩA-Z]{1,2}[\s-]?\d{5,6}\b|'
    r'\bΑ\.?Μ\.?Κ\.?Α\.?\s*:?\s*\d{11}\b|'
    r'(αίτηση|αίτημα|αιτήματος|αιτήσεως|ιδιοκτησίας|ιδιοκτήτ\w+|δημότ\w+|κατοίκ\w+|πολίτ\w+|ενδιαφερόμεν\w+|μισθωτ\w+|'
    r'αιτ(ούσα|ών|ούντος|ούσης|ούντα)|δικαιούχ\w+|κληρονόμ\w+|οφειλέτ\w+|παραβάτ\w+)\s+'
    r'(του|της|τον|την|των|στον|στην|από\s+τον|από\s+την)?\s*(κ\.|κου\b|κας\b|κυρ[ίι]\w*|κ\s)\s*[Α-Ω](\.|[α-ωά-ώΑ-Ω]+)|'
    r'(του|της)\s+(κ\.|κου\b|κας\b)\s*[Α-Ω][α-ωά-ώ]+\s+[Α-Ω][α-ωά-ώ]+\s+(του|της)\s+[Α-Ω][α-ωά-ώ]+|'
    r'(αριθμ\w*\s+κυκλοφορίας|αρ\.\s*κυκλ\.?|πινακίδ\w+|όχημα|οχήματος|Ι\.?Χ\.?)\s*:?\s*[ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ]{3}[\s-]?\d{4}\b')


def lines_of(doc: dict) -> list[dict]:
    out, skip = [], 0
    for l in doc['lines']:
        t = norm_line(l['t'])
        if not t:
            continue
        if SIGSTAMP.match(t):
            # the stamp: drop it and the signer name fragments (short Latin caps lines) just before it
            while out and re.fullmatch(r'[A-Z][A-Z .]{0,30}', out[-1]['t']):
                out.pop()
            skip = 8
            continue
        if skip and re.match(r'^(Date\s*:|Reason\s*:|Location\s*:|[A-Z][A-Z .]*$|EET|EEST|\d{4}\.\d\d\.\d\d)', t):
            skip -= 1
            continue
        skip = 0
        t = STAMP_BITS.sub(' ', t).strip()
        if not t:
            continue
        t = SPACED.sub(lambda m: m.group(0).replace(' ', ''), t)
        t = re.sub(r'^(ΑΠΟΦΑΣΙ[ΖΣ](?:ΕΙ|Ε|ΟΥΜΕ|ΕΤΑΙ))(ΟΜΟΦΩΝΑ|ΚΑΤΑ)', r'\1 \2', t)
        t = t.replace('ΚΑΤΑΠΛΕΙΟΨΗΦΙΑ', 'ΚΑΤΑ ΠΛΕΙΟΨΗΦΙΑ')
        if NOISE.match(t):
            continue
        if PAGENO.match(t):
            h = (doc.get('page_info') or [{}] * (l['p'] + 1))[l['p']].get('h') or 842
            if l['y0'] < 0.09 * h or l['y1'] > 0.91 * h:
                continue  # a page number in the top or bottom margin (a number inside the page is text: a table cell)
        out.append({**l, 't': t})
    return out


def paragraphs(ls: list[dict]) -> list[str]:
    paras: list[str] = []
    prev = None
    for l in ls:
        t = l['t']
        h = max(1.0, l['y1'] - l['y0'])
        new = prev is None
        if not new:
            gap = l['y0'] - prev['y1'] if l['p'] == prev['p'] else 0
            pt = paras[-1]
            if ENUM.match(t) or ART.match(t) or ART_WORD.match(t) or FORMULA.match(t) or SIGN.match(t) \
                    or DISTRIB.match(t) or ANNEX.match(t):
                new = True
            elif gap > 1.6 * h:
                new = True
            elif re.search(r'[.:;·»)]$', pt) and re.match(r'^[«"(Α-ΩΆ-ΏA-Z0-9]', t):
                new = True
            elif FORMULA.match(pt) or (pt.isupper() and len(pt) < 80 and t[:1].isupper() and not t.isupper()):
                new = True
        if new:
            paras.append(t)
        else:
            pt = paras[-1]
            if re.search(r'[α-ωά-ώ]-$', pt) and re.match(r'^[α-ωά-ώ]', t):
                paras[-1] = pt[:-1] + t
            else:
                paras[-1] = pt + ' ' + t
        prev = l
    return [re.sub(r'\s+', ' ', p).strip() for p in paras if p.strip()]


def art_num(p: str) -> tuple[int, str] | None:
    if TOC.search(p[:200]):
        return None  # a table-of-contents entry ("ΑΡΘΡΟ 1. ΔΙΑΡΘΡΩΣΗ ...... 14"), not the article
    m = ART.match(p)
    if m:
        return int(m.group(1)), (m.group(2) or '').lower()
    m = ART_WORD.match(p)
    if m:
        return ORD[m.group(1).upper()], ''
    return None


SUFFIX = dict(zip('αβγδεζabcdef', 'abcdefabcdef'))


def enum_style(p: str) -> str | None:
    if re.match(r'^\(?\d{1,3}[.)]\s', p):
        return 'num'
    if re.match(r'^\(?[α-ω][.)]\s', p):
        return 'lower'
    if re.match(r'^\(?[Α-Ω][.)]\s', p):
        return 'upper'
    return None


def split_items(paras: list[str]) -> list[list[str]]:
    """Operative part -> items at its top-level enumeration (first style seen); text before item 1 is its own item."""
    style = next((enum_style(p) for p in paras if enum_style(p)), None)
    items: list[list[str]] = [[]]
    for p in paras:
        if style and enum_style(p) == style:
            items.append([p])
        else:
            items[-1].append(p)
    return [it for it in items if it]


def parse(doc: dict) -> dict:
    if doc.get('garbled'):
        return {'hold': 'text layer unreadable (broken font map, not repairable)'}
    if not doc.get('lines'):
        return {'hold': 'no text layer (scanned document)' if not doc.get('error') else f'unreadable PDF ({doc["error"]})'}
    ls = lines_of(doc)
    paras = paragraphs(ls)
    letters = sum(len(re.findall(r'[^\W\d_]', p)) for p in paras)
    if letters < 150:
        return {'hold': f'too little text ({letters} letters; probably a scan with a stamp only)'}
    head = ' '.join(paras[:3])[:400]
    if COMMUNITY.search(head) and not re.search(r'ΔΗΜΟΤΙΚΟ ΣΥΜΒΟΥΛΙΟ|Δημοτικό Συμβούλιο|ΔΗΜΟΤΙΚΗ ΕΠΙΤΡΟΠΗ', head):
        return {'hold': 'decision of a community council (an opinion to the municipal council)'}
    fi = max((i for i, p in enumerate(paras) if FORMULA.match(p) or INLINE.search(p)), default=None)
    if fi is not None and not FORMULA.match(paras[fi]):
        m = list(INLINE.finditer(paras[fi]))[-1]
        before, after = paras[fi][:m.end()].strip(), paras[fi][m.end():].strip()
        paras[fi:fi + 1] = [before] + ([after] if after else [])
    if fi is None and any(PREP_ANY.search(p) for p in paras[len(paras) // 2:]):
        return {'hold': 'the decision is preparatory (εισηγείται/γνωμοδοτεί, no decision formula)'}
    # signature block / distribution list after the formula (or after the middle of a formula-less text)
    start_tail = fi if fi is not None else len(paras) // 2
    si = next((i for i in range(start_tail + 1, len(paras)) if SIGN.match(paras[i]) or DISTRIB.match(paras[i])), None)
    annex: list[str] = []
    if si is not None:
        ai = next((i for i in range(si, len(paras)) if ANNEX.match(paras[i]) or art_num(paras[i]) == (1, '')), None)
        if ai is not None:
            annex = paras[ai:]
        paras = paras[:si]
    if fi is not None:
        op_first = paras[fi + 1] if fi + 1 < len(paras) else ''
        hit = next((p for p in paras[fi + 1:fi + 4] if PREP_OPER.match(p)), None)
        if hit or PREP_OPER.match(re.sub(r'^\S+\s+(ΟΜΟΦΩΝΑ|ΚΑΤΑ ΠΛΕΙΟΨΗΦΙΑ)\s*', '', paras[fi])):
            return {'hold': 'the decision is preparatory, a postponement or a rejection (operative: '
                            + (hit or op_first)[:60] + ')'}
    # articles: numbered 1, 2, 3 ... in order, anywhere in the text (or in an annex)
    units: dict[str, list[str]] = {}
    body = paras + annex
    heads = []
    want = 1
    for i, p in enumerate(body):
        n = art_num(p)
        if n and (n[0] == want or (n[0] == want - 1 and n[1] and heads and heads[-1][1][0] == n[0])):
            heads.append((i, n))
            want = n[0] + 1
    if len(heads) >= 2:
        first = heads[0][0]
        units['prooimio'] = body[:first]
        for k, (i, n) in enumerate(heads):
            end = heads[k + 1][0] if k + 1 < len(heads) else len(body)
            key = f'art-{n[0]:03d}' + (SUFFIX.get(n[1], n[1]) if n[1] else '')
            if key in units:
                return {'hold': f'article numbering repeats ({key})'}
            units[key] = body[i:end]
        if fi is not None and fi > heads[-1][0]:
            # formula after the articles: the last article ends at the formula; operative paragraphs follow
            last = list(units)[-1]
            cut = fi - heads[-1][0]
            tail = units[last][cut:]
            units[last] = units[last][:cut]
            for k, it in enumerate(split_items(tail), 1):
                units[f'para-{k:03d}'] = it
    else:
        if fi is not None:
            units['prooimio'] = paras[:fi + 1]
            op = paras[fi + 1:]
        else:
            op = paras
        for k, it in enumerate(split_items(op), 1):
            units[f'para-{k:03d}'] = it
        for k, it in enumerate(split_items(annex), 1) if annex else []:
            units[f'parartima-{k:02d}'] = it
    units = {k: v for k, v in units.items() if v}
    bad = [k for k in units if not re.fullmatch(r'[a-z0-9-]+', k)]
    if bad:
        return {'hold': f'unit key not ASCII ({bad[0]})'}
    if not any(k != 'prooimio' for k in units):
        return {'hold': 'no operative text after the decision formula'}
    text = '\n'.join(p for v in units.values() for p in v)
    m = PRIVATE.search(text)
    if m:
        return {'hold': f'names a private person or identity data ("{m.group(0)[:40]}")', 'units': units}
    return {'units': units, 'formula': fi is not None, 'articles': len(heads) if len(heads) >= 2 else 0,
            'hold': None}
