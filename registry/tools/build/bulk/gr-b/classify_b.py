"""GR-B: classify a split Β΄ item: kind, issuer, protocol id, and whether it is an individual act naming private persons.

kind(item)      -> 'ya' | 'kya' | 'apofasi' | 'kanonismos' | 'diorthosi' | 'pd'
  diorthosi   the item stands under ΔΙΟΡΘΩΣΕΙΣ ΣΦΑΛΜΑΤΩΝ;
  pd          under ΠΡΟΕΔΡΙΚΑ ΔΙΑΤΑΓΜΑΤΑ / ΔΙΑΤΑΓΜΑΤΑ (decrees approving foundations etc. are printed in Β΄);
  kanonismos  the title is a regulation: «Κανονισμός ...», «Έγκριση/Κύρωση (του) Κανονισμού ...»;
  kya         issued by two or more ministers: «ΟΙ ΥΠΟΥΡΓΟΙ ...», «ΟΙ ΑΝΑΠΛΗΡΩΤΕΣ ΥΠΟΥΡΓΟΙ», «Ο ΥΠΟΥΡΓΟΣ ... ΚΑΙ Η
              ΥΦΥΠΟΥΡΓΟΣ ...», «Ο ΠΡΩΘΥΠΟΥΡΓΟΣ ΚΑΙ ...»;
  ya          issued by one minister / deputy / alternate minister / the Prime Minister;
  apofasi     everything else (independent and other authorities, boards, secretaries-general, regions,
              decentralised administrations, municipalities, universities, extracts with no issuer line).

privacy(item, kind) -> None | reason: an individual act that names private persons. Such items are not emitted as
  acts; a metadata row without the title or any name is kept in the held file. Signals (any one):
  - the title is an individual-act subject that by its nature names a person: citizenship/naturalisation, loss of
    citizenship, fines for smuggling, honours/awards to persons, appointments/transfers/secondments/placements of
    named staff, disciplinary decisions, recognition of qualifications, permits/licences to a named person;
  - the operative text carries personal identifiers: «(επώνυμο)», «(κύριο όνομα)», «του πατρός», «πατρώνυμο»,
    ID-card / tax / social-security numbers, «ονοματεπώνυμο» headed lists, dates/places of birth;
  - the title or operative text names a person: a Greek given name next to a capitalised surname (given-name list
    below), outside street / foundation / school names and outside the title of a public office holder.
  The recitals (Έχοντας υπόψη) are not scanned: they cite appointment decisions of the signing officials (public
  office holders), and the signature block is not carried at all.
"""
from __future__ import annotations

import re
import unicodedata

from split_b import fold

# ---------------------------------------------------------------- kind

KANON_TITLE = re.compile(r'^(κανονισμος|κανονισμοι|(εγκριση|κυρωση|εκδοση|εγκριση και κυρωση)\s+(του\s+|των\s+)?'
                         r'(νεου\s+|εσωτερικου\s+)?κανονισμ)')
MIN = r'(αναπληρωτ\w*\s+)?(υπουργ\w*|υφυπουργ\w*|πρωθυπουργ\w*)'
JOINT = re.compile(rf'^(οι\s+{MIN}|οι\s+αναπληρωτες|.*\bκαι\s+(ο|η|οι)\s+{MIN})')
SINGLE = re.compile(rf'^(ο|η)\s+{MIN}')


def kind(it: dict) -> str:
    sec = fold(it['section'])
    if 'διορθωσ' in sec:
        return 'diorthosi'
    if 'διαταγμ' in sec:
        return 'pd'
    if KANON_TITLE.match(fold(it['title'])):
        return 'kanonismos'
    iss = fold(' '.join(it['issuer_lines']))
    if JOINT.match(iss):
        return 'kya'
    if SINGLE.match(iss):
        return 'ya'
    return 'apofasi'


# ---------------------------------------------------------------- ASCII folding (ids, issuer slugs)

TR = {'α': 'a', 'β': 'v', 'γ': 'g', 'δ': 'd', 'ε': 'e', 'ζ': 'z', 'η': 'i', 'θ': 'th', 'ι': 'i', 'κ': 'k', 'λ': 'l',
      'μ': 'm', 'ν': 'n', 'ξ': 'x', 'ο': 'o', 'π': 'p', 'ρ': 'r', 'σ': 's', 'ς': 's', 'τ': 't', 'υ': 'y', 'φ': 'f',
      'χ': 'ch', 'ψ': 'ps', 'ω': 'o'}


def ascii_fold(t: str) -> str:
    t = fold(t).replace('ου', 'ou')
    t = ''.join(TR.get(c, c) for c in t)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', t)).strip('-')


STOP = {'o', 'i', 'oi', 'to', 'ta', 'tou', 'tis', 'ton', 'tin', 'kai', 'stin', 'ston'}
ROLE = re.compile(r'^(o|i|oi|to)-(anaplirot\w*-|genik\w*-)?(ypourg\w*|yfypourg\w*|prothypourg\w*)(-(kai|ston)-.*?)?-?')


def issuer_slug(it: dict, k: str) -> str:
    """The issuer, ASCII: for ministers the ministry («ergasias-koinonikis-asfalisis»; joint decisions: the first
    ministry named), otherwise the issuing body without articles, cut at 60 characters on a word boundary."""
    text = ' '.join(it['issuer_lines'])
    if not text:
        return 'unknown'
    s = ascii_fold(text)
    if k in ('ya', 'kya'):
        s = re.sub(r'^(o|i|oi)-(anaplirot\w*-)?(ypourg\w*|yfypourg\w*)-(kai-(o|i)-(anaplirot\w*-)?(ypourg\w*|yfypourg\w*)-)?',
                   '', s)
        s = re.sub(r'^(o|i)-prothypourgos.*', 'prothypourgos', s)
        s = s.split('--')[0]
        # joint: «ethnikis-oikonomias-kai-oikonomikon - esoterikon»: the dash between ministries was a separator
        parts = re.split(r'\s+[-–]\s+', fold(text))
        if k == 'kya' and len(parts) > 1:
            s = ascii_fold(re.sub(rf'^(οι|ο|η)\s+{MIN}(\s+και\s+(ο|η)\s+{MIN})?\s*', '', parts[0])) or s
    words = [w for w in s.split('-') if w and w not in STOP]
    out = ''
    for w in words:
        if len(out) + len(w) + 1 > 60:
            break
        out = f'{out}-{w}' if out else w
    return out or 'unknown'


PROTO_LEAD = re.compile(r'^(απόφ\.|αποφ\.|απόφασης|πράξης|πρωτ\.|Πρωτ\.)\s*', re.I)


def protocol(it: dict) -> str:
    """The protocol number as printed after «Αριθμ.» (leading «απόφ.»/«πράξης» dropped), tidied."""
    p = it['protocol_raw'].strip().rstrip('.')
    p = PROTO_LEAD.sub('', p)
    return re.sub(r'\s+', ' ', p).strip()


def protocol_id(p: str) -> str:
    return ascii_fold(p)[:60].strip('-')


# ---------------------------------------------------------------- privacy

INDIVIDUAL_TITLE = re.compile(
    r'^(πολιτογραφηση|αποκτηση\s+(της\s+)?(ελληνικης\s+)?ιθαγενειας|αποβολη\s+(της\s+)?(ελληνικης\s+)?ιθαγενειας|'
    r'αποδοχη\s+αιτησης\s+(για\s+)?αποβολη|ανακληση\s+(της\s+)?(αποφασης\s+)?(πολιτογραφησης|κτησης|απονομης)|'
    r'απωλεια\s+(της\s+)?ιθαγενειας|επιβολη\s+πολλαπλ|επιβολη\s+προστιμου\s+(στ|σε)|απονομη\s+(ηθικης|τιμητικ|'
    r'μεταλλ|του\s+μεταλλ|παρασημ|πολεμικ)|διορισμος|μεταταξη|αποσπαση|μετακινηση\s+υπαλλ|ενταξη\s+(του|της)\s|'
    r'μεταβολη\s+γνωστικου\s+αντικειμενου|εξελιξη\s+(του|της)\s|μονιμοποιηση|ανακηρυξη|εκλογη\s+(του|της)\s|'
    r'ονομασια\s+(του|της)\s+(ομοτιμ|επιτιμ)|απολυση|αργια|πειθαρχ|αναγνωριση\s+(της\s+)?(ισοτιμιας|επαγγελματ|'
    r'τιτλου)|χορηγηση\s+(αδειας|της\s+αδειας)\s+(ασκησης\s+)?(επαγγελματος|ιατρ|φαρμακ)|συνταξιοδοτηση|'
    r'αναγνωριση\s+(ως\s+)?(πολιτικου\s+)?προσφυγ|επιβολη\s+(διοικητικ\w+\s+)?(κυρωσ|ποιν)|ανακληση\s+διορισμου|'
    r'αποδοχη\s+(της\s+)?παραιτησης|παραιτηση|ορισμος\s+(του|της)\s+[α-ω]+\s+[α-ω]+(ου|η)?\s+ως)')
ID_MARKS = re.compile(r'(\(επωνυμο\)\s*\S|\(κυριο ονομα\)\s*\S|\bτου πατρος\s+[α-ω]|\bα\.?δ\.?τ\.?\s*[:.]?\s*[α-ω]{0,2}[\s-]?'
                      r'\d{5,}|αριθμ\w*\s+δελτ\w*\s+ταυτοτ\w*\s*[:.]?\s*[α-ω]{0,2}[\s-]?\d{5,}|'
                      r'α\.?μ\.?κ\.?α\.?\s*[:.]?\s*\d{11}|γεννηθεις|γεννηθεισα|γεννηθηκε\s+(στ|το|την))')
# field labels of a blank form (Ονοματεπώνυμο, Πατρώνυμο, ΑΦΜ ...) do not count on their own: normative decisions
# print application forms. A name list does: the label together with names.
LIST_LABEL = re.compile(r'ονοματεπωνυμ|ονομ/μο|επωνυμο\s+ονομα|ονομα\s+επωνυμο')

# common Greek given names (nominative); inflected forms are generated below
MALE = '''αγγελος αθανασιος αιμιλιος αλεξανδρος αλεξιος αλκιβιαδης αναστασιος ανδρεας αντωνιος αποστολος
αργυρης αριστειδης αριστοτελης αρης αχιλλεας βαγγελης βασιλης βικτωρας βλασης γαβριηλ γερασιμος γεωργιος
γιαννης γιωργος γρηγοριος δαμιανος δανιηλ δημητριος δημητρης διαμαντης διονυσιος δημοσθενης ελευθεριος εμμανουηλ
ευαγγελος ευθυμιος ευσταθιος ευστρατιος ζαχαριας ζησης ηλιας ηρακλης θανασης θεμιστοκλης θεοδωρος θεοφανης θεοχαρης
θωμας ιακωβος ιασονας ιγνατιος ιορδανης ιωαννης ιωσηφ καλλιοπης κλεαρχος κομνηνος κοσμας κυπριανος κυριακος κωνσταντινος
κωστας λαζαρος λαμπρος λεωνιδας λουκας μαργαριτης μαριος ματθαιος μενελαος μιλτιαδης μιχαηλ μιχαλης
νεκταριος νεοφυτος νικηφορος νικητας νικολαος νικος ξενοφων οδυσσεας ορεστης παναγιωτης παντελεημων παντελης
παρασκευας πασχαλης παυλος περικλης πετρος πλατων πολυχρονης προδρομος προκοπης ραφαηλ σεραφειμ σπυριδων
σπυρος σταματιος σταυρος στεφανος στελιος στυλιανος σωκρατης σωτηριος σωτηρης ταξιαρχης τιμοθεος τριανταφυλλος
τρυφων φιλιππος φωτιος φωτης χαραλαμπος χαρης χρηστος χριστοδουλος χριστοφορος χρυσοστομος'''.split()
FEMALE = '''αγγελικη αγλαια αθανασια αικατερινη αλεξανδρα αλεξια αλικη αμαλια ανασταια αναστασια ανδρομαχη
αντιγονη αντωνια αργυρω αριαδνη αρτεμις ασπασια αφροδιτη βαρβαρα βασιλικη βικτωρια γαρυφαλλια
δαναη δεσποινα διονυσια ελενη ελισαβετ εμμανουελα ερασμια ευαγγελια ευανθια
ευγενια ευδοκια ευθυμια ευφροσυνη ηλιανα θεανω θεοδωρα θεοπιστη θεοφανεια θεοδοσια ιουλια ιφιγενεια
ιωαννα καλλιοπη καλλιρροη κατερινα κλεοπατρα κωνσταντινα λαμπρινη λευκοθεα λιλιαν λυδια μαγδαληνη
μαργαριτα μαρια μαριανθη μαρινα μαρθα ματινα μελπομενη μυρτω ναταλια ναυσικα νεκταρια νικολετα ντινα
ουρανια παναγιωτα παντελια πηνελοπη πολυξενη ραλλου ροδανθη σμαραγδα σταματια σταυρουλα στελλα
στυλιανη σωτηρια ταξιαρχουλα τριανταφυλλια φιλιω φωτεινη χαρικλεια χαρουλα χρυσανθη χρυσουλα
χριστινα'''.split()


def _forms() -> set[str]:
    out = set()
    for n in MALE:
        out.add(n)
        if n.endswith('ος'):
            out |= {n[:-2] + 'ου', n[:-2] + 'ο'}
        elif n.endswith(('ης', 'ας')):
            out.add(n[:-1])
        elif n.endswith('ων'):
            out |= {n[:-2] + 'ωνα', n[:-2] + 'ωνος'}
    for n in FEMALE:
        out.add(n)
        if n.endswith(('α', 'η')):
            out.add(n + 'ς')
        if n.endswith('ω'):
            out.add(n + 'ς')
    return out


NAMES = _forms()
TOKEN = re.compile(r'[Α-ΩΆΈΉΊΌΎΏΪΫα-ωάέήίόύώϊϋΐΰς]+')
CAP = re.compile(r'^[Α-ΩΆΈΉΊΌΎΏΪΫ]')
# a name inside an institution, street or place name, or the title of a public office holder, is not a private
# person: such a word right before the pair, or as the «surname», drops the pair
NOT_PERSON = re.compile(r'^(οδ(ος|ου|ο|ων)|λεωφ\w*|πλατει\w*|ιδρυμα\w*|κληροδοτημ\w*|σχολ\w*|νοσοκομ\w*|γυμνασ\w*|'
                        r'λυκει\w*|δημοτ\w*|δημο[υςι]?|δημων|εκκλησ\w*|ναο[υςν]?|μονη[ςν]?|ιερα[ςν]?|αγι\w*|υπουργ\w*|'
                        r'υφυπουργ\w*|πρωθυπουργ\w*|γραμματ\w*|προεδρ\w*|δημαρχ\w*|περιφερ\w*|αντιπεριφερ\w*|'
                        r'διοικητ\w*|πρυτανη\w*|συντονιστ\w*|κοσμητορ\w*|στρατοπεδ\w*|αεροδρομ\w*|σταδι\w*|γηπεδ\w*|'
                        r'μουσει\w*|πανεπιστημ\w*|βραβει\w*|υποτροφι\w*|αιθουσ\w*|κεντρ\w*|ακαδημ\w*|ιδρυτ\w*|πολη\w*|'
                        r'χωρι\w*|συνοικισμ\w*|διευθ\w*|προισταμ\w*|τμημα\w*|ενοτητ\w*|νομο[υςν]?|ηνωμεν\w*|'
                        r'βασιλει\w*|αστυνομ\w*|υπαλλ\w*|καθηγητ\w*|αναπληρωτ\w*|γενικ\w*|ειδικ\w*|εντολη|ακριβες|'
                        r'θεωρηθηκε|κοινοτητ\w*|τοπικ\w*|κοιμητηρ\w*|ακτη[ςν]?|νησ\w*|ορο[υςν]?|ορεινο\w*|λιμεν\w*|'
                        r'φαρο[υςν]?|ποταμ\w*|λιμν\w*|κολπ\w*|ακρωτηρ\w*|σταθμ\w*|γεφυρ\w*|πυλη\w*|στοα[ςν]?|'
                        r'μεγαρ\w*|πυργ\w*|κτιρι\w*|κληρονομ\w*|πρυτανει\w*|σωματει\w*|συλλογ\w*|εταιρ\w*|'
                        r'ιατρει\w*|κλινικ\w*|ινστιτουτ\w*|εργαστηρ\w*|ενορι\w*|μητροπολ\w*|επισκοπ\w*|αγιου|'
                        r'αθην\w*|θεσσαλον\w*|ιωανν\w*|πειραι\w*|πατρ\w*|ηρακλει\w*|μηνα\w*|μηνες|μηνων|προφητ\w*|'
                        r'μεγαλ\w*|μεγα|οσιο[υςν]?|οσια[ςν]?|βενιζελ\w*|σηραγγ\w*|αλσο[υςν]?|παρκο[υν]?)$')
TITLE_WORDS = re.compile(r'(υπουργ|υφυπουργ|γραμματ|προεδρ|δημαρχ|περιφερειαρχ|διοικητ|πρυτανη|συντονιστ|κοσμητορ|'
                         r'διευθυντ|προισταμεν|καθηγητ|εισηγητ)\w*\s*,?\s*$')
ROLE_AFTER = re.compile(r'^\s*[,(–-]?\s*(προεδρ|αντιπροεδρ|εισηγητ|γραμματε|αναπληρωτ|μελο[ςυ]|μελη|τακτικ|'
                        r'υποδιοικητ|διοικητ|γενικ\w*\s+διευθ|διευθυντ|προισταμεν|ομοτιμ|καθηγητ|επικ\w*\s+καθηγ|'
                        r'βουλευτ|υπουργ|υφυπουργ|δημαρχ|αντιδημαρχ|περιφερειαρχ|αντιπεριφερειαρχ|συντονιστ|πρυτανη|'
                        r'αντιπρυτανη|κοσμητορ)')
ARTICLE_BEFORE = re.compile(r'(\b(του|της|τον|την|στον|στην|ο|η|κ\.|κου|κας|κ\.κ\.)|\(\s*επ\.?\)|\(\s*επωνυμο\s*\))\s*$')


def name_pairs(text: str) -> list[tuple[str, bool]]:
    """(span, strong) for each «given name + surname» / «SURNAME given name» pair inside one line of text.
    strong: followed by a patronymic («του Ιωάννη») or preceded by an article/«κ.» (a person named in a sentence)."""
    out = []
    for line in text.split('\n'):
        toks = list(TOKEN.finditer(line))
        for i, m in enumerate(toks):
            w = fold(m.group(0))
            if w not in NAMES or not CAP.match(m.group(0)):
                continue
            for j in (i + 1, i - 1):
                if not 0 <= j < len(toks):
                    continue
                t = toks[j]
                sw = fold(t.group(0))
                gap = line[min(m.end(), t.end()):max(m.start(), t.start())]
                if (not CAP.match(t.group(0)) or len(sw) < 4 or sw in NAMES or NOT_PERSON.match(sw)
                        or gap.strip() not in ('', ',')):
                    continue
                first, last = (m, t) if j > i else (t, m)
                k0 = i if j > i else j
                prev = fold(toks[k0 - 1].group(0)) if k0 >= 1 else ''
                if prev and NOT_PERSON.match(prev):
                    continue
                before = fold(line[max(0, first.start() - 40):first.start()])
                if TITLE_WORDS.search(before):
                    continue  # «Ο Υπουργός Γεώργιος ...»: a public office holder
                after = line[last.end():last.end() + 30]
                if ROLE_AFTER.match(fold(after)):
                    continue  # «Ιωάννης Στεφάτος, Αντιπρόεδρος»: a member named in their official role
                strong = bool(re.match(r'^\s*,?\s*(του|της)\s+[Α-ΩΆΈΉΊΌΎΏ]', after) or ARTICLE_BEFORE.search(before))
                out.append((line[first.start():last.end()], strong))
                break
    return out


def person_names(text: str) -> list[str]:
    return [s for s, _ in name_pairs(text)]


COMMITTEE_TITLE = re.compile(r'(συγκροτηση|ορισμος\s+(των\s+)?μελων|ορισμος\s+(προεδρ|γραμματ|εκπροσωπ|αναπληρ|'
                             r'μελ|υπαλλ|διευθυντ|υποδιευθυντ|προισταμεν|υπευθυν)|αντικατασταση\s+μελ|ανασυγκροτηση|'
                             r'συνθεση\s+(της|του)|ορισμος\s+(οργανων|στελεχων)|ανανεωση\s+θητειας|παραταση\s+θητειας)')


def privacy(it: dict, k: str, body_text: str) -> str | None:
    t = fold(it['title'])
    if k != 'diorthosi' and INDIVIDUAL_TITLE.match(t):
        return 'individual act naming a person (subject: ' + ' '.join(it['title'].split()[:4]) + ' ...)'
    fb = fold(body_text)
    if ID_MARKS.search(fb):
        return 'operative text carries personal identifiers (name / ID / birth details)'
    tp = name_pairs(it['title'])
    bp = name_pairs(body_text)
    if tp:
        return 'the title names a person'
    distinct = {fold(s) for s, _ in bp}
    if distinct and COMMITTEE_TITLE.search(t):
        return f'composes a body / designates members by name ({len(distinct)} name(s))'
    if any(st for _, st in bp) or len(distinct) >= 3 or (distinct and LIST_LABEL.search(fb)):
        return f'names a person ({len(distinct)} name(s) in the operative text)'
    return None
