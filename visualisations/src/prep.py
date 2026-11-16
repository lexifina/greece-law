"""Compute every number of the 20 charts and the data profile from the files make.py extracted.

    python prep.py <.build folder>          (writes <.build>/data.json)

Categories read from titles (decision topics, council resolutions, decree topics, law-title types, directives, the
operative part of a decision and the court appealed against) follow the rules in this file. Titles are matched in a
folded form: lower case, without accents, final sigma as sigma. A word rule matches at word boundaries only; what
no rule recognises is counted as "other".
"""
import collections, csv, datetime, gzip, json, math, os, re, statistics, sys, unicodedata
from zoneinfo import ZoneInfo

B = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '.build')
OUT = {}
TZ = ZoneInfo('Europe/Athens')
D = datetime.date.fromisoformat


def fold(s):
    s = unicodedata.normalize('NFD', (s or '').lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').replace('ς', 'σ')


LAT = str.maketrans({'a': 'α', 'o': 'ο', 'e': 'ε', 'i': 'ι', 'k': 'κ', 'p': 'ρ', 'x': 'χ', 'y': 'υ', 't': 'τ', 'h': 'η', 'm': 'μ', 'n': 'ν', 'b': 'β', 'z': 'ζ'})


def W(x):
    """a whole-word alternative: no letter or digit before it, none after it (stems end in \\w*)"""
    return r'(?<![α-ωa-z0-9])(?:' + x + r')(?![α-ωa-z0-9])'


def first(rules, text):
    for k, rx in rules:
        if re.search(rx, text):
            return k
    return 'other'


MON = ['ιανουαριου', 'φεβρουαριου', 'μαρτιου', 'απριλιου', 'μαιου', 'ιουνιου', 'ιουλιου', 'αυγουστου', 'σεπτεμβριου', 'οκτωβριου', 'νοεμβριου', 'δεκεμβριου']

# ====================================================================== I. the Constitution
syn = json.load(open(os.path.join(B, 'syntagma.json'), encoding='utf-8'))
VERS = syn['versions']                       # [[commit, in-force day]], oldest first
TXT = syn['text']
v_dates = [d for _, d in VERS]
print('constitution versions', v_dates)
assert len(VERS) == 5, VERS


def art_key(path):
    m = re.search(r'art-(\d+)(?:-([a-z]))?\.md$', path)
    return (int(m.group(1)), m.group(2) or '')


def split_art(t):
    """(heading lines before 'Άρθρο N', the article id, the article body)"""
    lines = t.split('\n')
    for i, l in enumerate(lines):
        m = re.match(r'^Άρθρο\s+(\d+\s*[Α-Ω]?)\s*$', l.strip())
        if m:
            return lines[:i], m.group(1).replace(' ', ''), '\n'.join(lines[i + 1:])
    raise SystemExit('no article line: ' + t[:80])


words = lambda t: re.findall(r'\w+', t)


def diff_words(a, b):
    import difflib
    wa, wb = words(a), words(b)
    ins = dele = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=wa, b=wb, autojunk=False).get_opcodes():
        if op in ('replace', 'delete'): dele += i2 - i1
        if op in ('replace', 'insert'): ins += j2 - j1
    return ins, dele


last = TXT[VERS[-1][0]]
paths = sorted(last, key=art_key)
part, part_title, arts = 0, '', []
PARTS = {'ΠΡΩΤΟ': 1, 'ΔΕΥΤΕΡΟ': 2, 'ΤΡΙΤΟ': 3, 'ΤΕΤΑΡΤΟ': 4}
for p in paths:
    head, aid, body = split_art(last[p])
    for i, l in enumerate(head):
        m = re.match(r'^ΜΕΡΟΣ\s+(\S+)', l.strip())
        if m:
            part = PARTS[m.group(1)]
            part_title = head[i + 1].strip() if i + 1 < len(head) else ''
    rec = {'id': aid, 'part': part, 'words': len(words(body)), 'decl': 'Ερμηνευτική δήλωση' in body,
           'repealed': bool(re.search(r'\(Το άρθρο \S+ καταργείται\.?\)', body)), 'ch': []}
    for k in range(1, len(VERS)):
        a0, a1 = TXT[VERS[k - 1][0]].get(p), TXT[VERS[k][0]].get(p)
        if a0 != a1:
            b0, b1 = split_art(a0)[2] if a0 else '', split_art(a1)[2]
            ins, dele = diff_words(b0, b1)
            rec['ch'].append([VERS[k][1], ins, dele, len(words(b0)), len(words(b1))])
    rec['w2001'] = len(words(split_art(TXT[VERS[0][0]][p])[2])) if p in TXT[VERS[0][0]] else 0
    arts.append(rec)
    if part and not OUT.get('parts', {}).get(str(part)):
        OUT.setdefault('parts', {})[str(part)] = part_title
REV = {'2008': v_dates[1], '2019': v_dates[3]}            # the two revision resolutions; 2008-06-27 and 2019-12-24 are republications
REP = {v_dates[2], v_dates[4]}
for r in arts:
    r['r2008'] = any(c[0] == REV['2008'] for c in r['ch'])
    r['r2019'] = any(c[0] == REV['2019'] for c in r['ch'])
    r['typo'] = any(c[0] in REP for c in r['ch']) and not (r['r2008'] or r['r2019'])
revised = [r for r in arts if r['r2008'] or r['r2019']]
print('articles', len(arts), 'revised since 2001', len(revised), 'decl', sum(r['decl'] for r in arts))
c01 = {'arts': arts, 'parts': OUT.pop('parts'), 'versions': v_dates, 'words2001': sum(r['w2001'] for r in arts), 'words': sum(r['words'] for r in arts)}
# chart 2: words in and out at each revision
c02 = {}
for y, d in REV.items():
    rows = []
    for r in arts:
        for c in r['ch']:
            if c[0] == d:
                rows.append({'id': r['id'], 'ins': c[1], 'del': c[2], 'before': c[3], 'after': c[4], 'repealed': r['repealed'] and y == '2019'})
    c02[y] = rows
c02['typo'] = {d: sum(1 for r in arts for c in r['ch'] if c[0] == d) for d in sorted(REP)}
c02['typo_words'] = {d: sum(c[1] for r in arts for c in r['ch'] if c[0] == d) for d in sorted(REP)}
OUT['c01'], OUT['c02'] = c01, c02
for y in REV:
    print('revision', y, len(c02[y]), '+', sum(x['ins'] for x in c02[y]), '-', sum(x['del'] for x in c02[y]))

# ====================================================================== II. laws and decrees
# every commit message other than Diavgeia records and decisions
ACTS = []
cur = None
for line in open(os.path.join(B, 'acts.txt'), encoding='utf-8'):
    if line.startswith('=== '):
        if cur: ACTS.append(cur)
        cur = {'h': line[4:].strip(), 'lines': []}
    elif cur is not None:
        cur['lines'].append(line.rstrip('\n'))
if cur: ACTS.append(cur)
for c in ACTS:
    L = c['lines']
    c['author'], c['date'], c['subject'] = L[0], L[1], (L[2] if len(L) > 2 else '')
    c['body'] = '\n'.join(L[2:])
    c['tr'] = {}
    for l in L[3:]:
        m = re.match(r'^([A-Z][A-Za-z-]+): (.*)$', l)
        if m: c['tr'].setdefault(m.group(1), m.group(2))
print('other commits', len(ACTS))

rd = lambda name: os.path.join(B, 'repo', name)
laws_csv = list(csv.DictReader(open(rd('data__laws.csv'), encoding='utf-8')))
acts_json = json.load(open(rd('data__acts.json'), encoding='utf-8'))['acts']
versions = {v['slug']: v for v in json.load(open(rd('data__versions.json'), encoding='utf-8'))['acts']}
reg = json.load(open(rd('registry__data__acts.json'), encoding='utf-8'))
reg = reg['acts'] if isinstance(reg, dict) else reg

# ---- chart 3: the titles of every law in the repository
LAWS = {}
for r in laws_csv:
    m = re.match(r'^ν\. (\d+)/(\d{4})$', r['label'])
    if m:
        LAWS[(int(m.group(2)), int(m.group(1)))] = {'title': r['title'], 'pub': r['published'] or r['enacted'], 'src': 'record'}
subj = {}
for c in ACTS:
    if c['tr'].get('Kind') == 'as-enacted':
        m = re.match(r'^ν\. (\d+)/(\d{4}): (.*)$', c['subject'])
        if m: subj[(int(m.group(2)), int(m.group(1)))] = (m.group(3), c['date'])
pages = {}
for line in open(os.path.join(B, 'laws.jsonl'), encoding='utf-8'):
    j = json.loads(line)
    m = re.match(r'^nomos/(\d{4})/(\d+)$', j['folder'])
    if not m:
        continue
    k = (int(m.group(1)), int(m.group(2)))
    if j.get('pages'): pages[k] = j['pages']
    if k in LAWS:
        continue
    t = j.get('title') or (subj.get(k) or ('', ''))[0]
    if t:
        LAWS[k] = {'title': t, 'pub': j.get('published') or (subj.get(k) or ('', ''))[1], 'src': 'text' if j.get('title') else 'subject'}
OMNI = W(r'(?:αλλεσ|λοιπεσ)\s+(?:επειγουσεσ\s+|συναφεισ\s+)?(?:διαταξεισ|ρυθμισεισ)')


def law_type(t):
    f = fold(t)
    if f.startswith('κυρωση') and re.search(r'πραξησ? νομοθετικου περιεχομενου|πραξεων νομοθετικου περιεχομενου', f): return 'pnp'
    if f.startswith('κυρωση') and not re.search(r'^κυρωση\s+(?:του\s+)?κωδικα|κωδικα νομοθεσιασ', f): return 'ratif'
    return 'omni' if re.search(OMNI, f) else 'single'


c03 = collections.defaultdict(lambda: collections.Counter())
for (y, n), L in LAWS.items():
    L['type'] = law_type(L['title'])
    c03[y][L['type']] += 1
# numbering coverage: laws held / the span of law numbers held that year
span = {}
for (y, n) in LAWS:
    lo, hi = span.get(y, (n, n)); span[y] = (min(lo, n), max(hi, n))
OUT['c03'] = {'years': [{'y': y, **c03[y], 'lo': span[y][0], 'hi': span[y][1]} for y in sorted(c03)],
              'examples': {t: sorted([(y, n, L['title'][:160]) for (y, n), L in LAWS.items() if L['type'] == t], key=lambda x: (-x[0], -x[1]))[:6] for t in ['omni', 'pnp']},
              'n': len(LAWS), 'from_text': sum(1 for L in LAWS.values() if L['src'] == 'text'), 'from_subject': sum(1 for L in LAWS.values() if L['src'] == 'subject')}
tot3 = collections.Counter()
for y in c03: tot3.update(c03[y])
print('laws', len(LAWS), dict(tot3), 'omni share of non-ratification %.1f%%' % (100 * tot3['omni'] / (tot3['omni'] + tot3['single'])))

# ---- chart 4: the laws followed through their amendments
tracked = {a['slug']: a for a in reg if a.get('kind') == 'nomos'}
lab2slug = {}
for s, a in tracked.items():
    lab2slug[a['short']] = s
AM = []
for c in ACTS:
    if c['tr'].get('Kind') != 'law':
        continue
    m = re.match(r'^(ν\. \d+/\d{4}|Σύνταγμα): (.*) \((.*)\)$', c['subject'])
    if not m:
        continue
    target, what, amender = m.groups()
    if target == amender or target == 'Σύνταγμα':
        continue
    body = c['body']
    title = ''
    paras = [p.strip() for p in body.split('\n\n')]
    if len(paras) > 1:
        title = re.sub(r'\s+', ' ', paras[1])
    art = None
    mm = re.search(r'(?:^|\n)(?:The [^\n]*?, )?' + re.escape(amender) + r'(?: \(ΦΕΚ[^)]*\))? arts?\. (\d+)', body)
    if mm: art = int(mm.group(1))
    AM.append({'date': c['tr'].get('In-force', c['date']), 'target': target, 'by': amender, 'art': art, 'title': title, 'omni': bool(re.search(OMNI, fold(title))),
               'what': what})
print('amendments of followed laws', len(AM), 'by', len({a['by'] for a in AM}), 'laws; article known', sum(1 for a in AM if a['art']))
REC_TO =max(c['date'] for c in ACTS if '@et.invalid' in c['author'] or '@greece.invalid' in c['author'])
first_am = {}
for a in sorted(AM, key=lambda a: a['date']):
    first_am.setdefault(a['target'], a)
rows4 = []
for s, a in tracked.items():
    v = versions.get(s)
    t0 = v['versions'][0]['from'] if v else a.get('from')
    fa = first_am.get(a['short'])
    rows4.append({'law': a['short'], 'title': a['title'][:200], 't0': t0, 'first': fa['date'] if fa else None, 'by': fa['by'] if fa else None,
                  'n': sum(1 for x in AM if x['target'] == a['short'])})
# Kaplan-Meier: months from the law's first day in force to its first amendment by another act; censored at REC_TO
ev = []
for r in rows4:
    end = r['first'] or REC_TO
    m = (D(end) - D(r['t0'])).days / 30.4375
    ev.append((max(0.0, m), r['first'] is not None))
ev.sort()
S, at, km, i = 1.0, len(ev), [[0, 1.0, len(ev)]], 0
while i < len(ev):
    t = ev[i][0]; d = c_ = 0
    while i < len(ev) and ev[i][0] == t:
        d += ev[i][1]; c_ += 1; i += 1
    if d:
        S *= (1 - d / at)
        km.append([round(t, 2), round(S, 4), at - c_])
    at -= c_
bins = [[1, 20], [21, 50], [51, 100], [101, 200], [201, 10000]]
OUT['c04'] = {'rows': sorted(rows4, key=lambda r: (-r['n'], r['law'])), 'km': km, 'record_to': REC_TO, 'n': len(rows4), 'amended': sum(1 for r in rows4 if r['first']),
              'am': [{k: x[k] for k in ['date', 'target', 'by', 'art', 'omni']} for x in AM],
              'bins': [[lo, hi, sum(1 for x in AM if x['art'] and lo <= x['art'] <= hi)] for lo, hi in bins], 'noart': sum(1 for x in AM if not x['art']),
              'amenders': len({x['by'] for x in AM}), 'amenders_omni': len({x['by'] for x in AM if x['omni']})}
km_at = lambda months: min([S_ for t_, S_, _ in km if t_ <= months], default=1.0)
print('followed laws', len(rows4), 'amended', OUT['c04']['amended'], 'KM unamended at 12/24/36 months', km_at(12), km_at(24), km_at(36))

# ---- chart 5: presidential decrees
PD = [a for a in acts_json if a['kind'] == 'diatagma']
PD_RULES = [
    ('parish', W(r'ενορι\w*|μον(?:η|ησ|ων)|μοναστηρι\w*|ιερ\w* ναου|ιερ\w* μητροπολ\w*|μητροπολεωσ|ησυχαστηρι\w*')),
    ('holiday', W(r'αργια\w*|εορτ\w*|επετει\w*')),
    ('amend', r'^\W*' + W(r'τροποποιησ\w*|συμπληρωσ\w*|αντικαταστασ\w*|καταργησ\w* (?:του|τησ|των) (?:π\.?\s?δ|προεδρικ|διαταγμ|αρθρ|παραγρ|διαταξ)\w*')),
    ('univ', W(r'πανεπιστημ\w*|τμηματ\w* (?:\w+ ){0,6}σχολησ|σχολησ|τει|πολυτεχνει\w*|ακαδημι\w*|διδακτορ\w*|φοιτητ\w*|σπουδ\w*')),
    ('staff', W(r'θεσε\w*|θεσεων|προσωπικ\w*|μεταταξ\w*|βαθμ\w*|αποδοχ\w*|υπαλληλ\w*|στελεχ\w*|αξιωματικ\w*|δικαστικ\w* λειτουργ\w*|ειρηνοδικ\w*|φρουρ\w*|αξιολογησ\w*|υπερωρι\w*|αποζημιωσ\w*')),
    ('org', W(r'οργανισμ\w*|οργανωσ\w*|διαρθρωσ\w*|αναδιαρθρωσ\w*|ιδρυσ\w*|συστασ\w*|συγχωνευσ\w*|καταργησ\w*|μετονομασι\w* (?:\w+ ){0,3}(?:γενικ|διευθυνσ|υπηρεσι|υπουργει|γραμματει)\w*|αρμοδιοτητ\w*|υπουργει\w*|προξενει\w*|πρεσβει\w*|καταστημα\w* κρατησ\w*|υπηρεσι\w*|γραμματει\w*')),
    ('municipal', W(r'δημ(?:ου|ων|οσ)|κοινοτητ\w*|νομου|νομαρχ\w*|περιφερει\w*|εδρα\w*')),
    ('eu', W(r'οδηγι\w*')),
]
c05y = collections.Counter(); c05 = collections.Counter(); ex5 = collections.defaultdict(list)
for a in PD:
    k = first(PD_RULES, fold(a['title']))
    c05[k] += 1; c05y[(a['year'], k)] += 1
    if len(ex5[k]) < 4: ex5[k].append(a['short'] + ': ' + a['title'][:140])
years5 = sorted({a['year'] for a in PD})
OUT['c05'] = {'topics': [[k, c05[k], {y: c05y[(y, k)] for y in years5 if c05y[(y, k)]}] for k, _ in c05.most_common()], 'years': years5, 'n': len(PD),
              'amending_status': sum(1 for a in PD if a['status'] == 'amending act'), 'examples': ex5}
print('decrees', len(PD), c05.most_common())

# ---- chart 6: EU directives named in titles, and how long after them the Greek act came
DIR = re.compile(r'(?:ενσωματωσ\w*|εναρμονισ\w*|προσαρμογ\w*|μεταφορ\w*)\s+(?:\w+\s+){0,8}?(?:τησ|των|στισ|στην|προσ τισ|προσ την)?\s*(?:διαταξεισ τησ |διαταξεων τησ )?(?:εκτελεστικησ\s+)?οδηγι\w*\s+(?:\((?:εε|εκ|εοκ)\)\s*)?(?:αριθ\w*\.?\s*)?(\d{2,4}/\d{1,4}(?:/(?:εε|εκ|εοκ))?)(.{0,170})')
DATE_T = re.compile(r'τησ\s+(\d{1,2})(?:ησ|ηs|ησ)?\s+(' + '|'.join(MON) + r')\s+(\d{4})')
cand = []
for r in laws_csv:
    if r['label'].startswith('ν.') or r['label'].startswith('π.δ.'):
        cand.append((r['label'], r['published'] or r['enacted'], r['title']))
for (y, n), L in LAWS.items():
    if L['src'] != 'record':
        cand.append((f'ν. {n}/{y}', L['pub'], L['title']))
c06, seen6, nodate6 = [], set(), []
for lab, pub, t in cand:
    if lab in seen6 or not pub:
        continue
    f = re.sub(r'«[^»]*»|“[^”]*”|"[^"]*"', ' ', fold(t))      # the quoted title of an act it amends is not this act's transposition
    m = DIR.search(f)
    if not m:
        continue
    seen6.add(lab)
    dm = DATE_T.search(m.group(2))
    num = m.group(1).upper().replace('ΕΕ', 'ΕΕ')
    if not dm:
        nodate6.append([lab, num]); continue
    dd = f'{int(dm.group(3)):04d}-{MON.index(dm.group(2)) + 1:02d}-{int(dm.group(1)):02d}'
    if not (dd[:4] in num or num.split('/')[0][-2:] == dd[2:4]):
        nodate6.append([lab, num]); continue
    c06.append({'act': lab, 'pub': pub, 'dir': num, 'ddate': dd, 'days': (D(pub) - D(dd)).days, 'title': t[:220]})
c06.sort(key=lambda r: r['days'])
OUT['c06'] = {'rows': c06, 'nodate': nodate6, 'median': statistics.median([r['days'] for r in c06]) if c06 else None}
print('directives with a date in the title', len(c06), 'without', len(nodate6), 'median days', OUT['c06']['median'])

# ====================================================================== III. Diavgeia
CATS = ['dimos', 'perif', 'apok', 'ypourg', 'univ', 'other']


def cat_of(issuer, folder):
    n = issuer.upper()
    if n.startswith('ΔΗΜΟΣ '): return 'dimos'
    if n.startswith('ΠΕΡΙΦΕΡΕΙΑ'): return 'perif'
    if n.startswith('ΑΠΟΚΕΝΤΡΩΜΕΝΗ ΔΙΟΙΚΗΣΗ'): return 'apok'
    if n.startswith('ΥΠΟΥΡΓΕΙΟ'): return 'ypourg'
    if re.search(r'ΠΑΝΕΠΙΣΤΗΜ|ΠΟΛΥΤΕΧΝΕΙΟ|ΤΕΧΝΟΛΟΓΙΚΟ ΕΚΠΑΙΔΕΥΤΙΚΟ|ΑΝΩΤΑΤΗ ΣΧΟΛΗ|ΕΙΔΙΚΟΣ ΛΟΓΑΡΙΑΣΜΟΣ ΚΟΝΔΥΛΙΩΝ ΕΡΕΥΝΑΣ|\bΤ\.?Ε\.?Ι\b', n): return 'univ'
    return 'other'


TOPICS = [
    ('legality', W(r'ελεγχ\w* (?:τησ )?νομιμοτητ\w*')),
    ('regulation', W(r'κανονισμ\w*')),
    ('fees', W(r'τελ(?:οσ|ουσ|η|ων)|συντελεστ\w*|τιμολογ\w*|φορ(?:οσ|ου|ων|ουσ|ολογ\w*)|αντιτιμ\w*|εισφορ\w*')),
    ('traffic', W(r'κυκλοφοριακ\w*|σταθμευσ\w*|μονοδρομ\w*|πεζοδρομ\w*')),
    ('committee', W(r'συγκροτησ\w*|επιτροπ\w*|αντιδημαρχ\w*|ορισμ\w* (?:μελ|εκπροσωπ|προεδρ|αναπληρ|γραμματ|δικηγορ|πληρεξουσ|νομικ)\w*')),
    ('staff', W(r'προσωπικ\w*|προσληψ\w*|υπαλληλ\w*|μετακινησ\w*|αποσπασ\w*|υπερωρι\w*|μισθοδοσ\w*|ωρομισθ\w*|συμβασιουχ\w*|εργαζομεν\w*|εκπαιδευτικ\w*|μελ\w* δεπ|διδακτικ\w* προσωπ\w*')),
    ('procurement', W(r'προμηθει\w*|διαγωνισμ\w*|κατακυρωσ\w*|διακηρυξ\w*|μειοδοτ\w*|αναδοχ\w*|αναθεσ\w*|ανακεφαλαιωτικ\w*|παραλαβ\w*|εργ(?:ο|ου|ων|α)|εργασι\w*|μελετ\w*|συμβασ\w*|προσφορ\w*|υπηρεσιων|παροχ\w* υπηρεσι\w*')),
    ('property', W(r'μισθωσ\w*|εκμισθωσ\w*|παραχωρησ\w*|ακινητ\w*|οικοπεδ\w*|κοινοχρηστ\w*|απαλλοτριωσ\w*|δημοπρασι\w*|ρυμοτομ\w*|πολεοδομ\w*')),
    ('budget', W(r'πιστωσ\w*|προυπολογισμ\w*|δαπαν\w*|αναμορφωσ\w*|ενταλμ\w*|απολογισμ\w*|ισολογισμ\w*|αναληψ\w* υποχρεωσ\w*|τεχνικ\w* προγραμμα\w*|δεσμευσ\w*|χρηματοδοτ\w*|πληρωμ\w*')),
    ('grants', W(r'επιχορηγησ\w*|ενισχυσ\w*|βοηθημ\w*|επιδομ\w*|χορηγι\w*|δωρε\w*|αποδοχ\w* (?:ποσ|χρηματ|δωρε)\w*')),
    ('forest', W(r'δασ\w*|αναδασωσ\w*|αλιει\w*|θηρ\w*|κυνηγ\w*|περιβαλλοντ\w*|υδατ\w*|λατομ\w*|αιγιαλ\w*|βοσκ\w*')),
    ('council', W(r'πρακτικ\w*|επικυρωσ\w*|συνεδριασ\w*|ψηφισμα\w*|ημερησι\w*')),
    ('permits', W(r'αδει\w*|βεβαιωσ\w*|πιστοποιητικ\w*')),
]
RES = [
    ('condolence', W(r'συλλυπητηρι\w*|θανατ\w*|εκλιποντ\w*|εκλιπουσ\w*|αποβιωσ\w*|μνημη\w*|αποθανοντ\w*|κηδει\w*|απωλει\w*|εκδημι\w*|μακαριστ\w*|δολοφονι\w*|πενθ\w*')),
    ('national', W(r'μακεδον\w*|σκοπι\w*|πρεσπ\w*|ονομασι\w*|κυπρ\w*|τουρκ\w*|κατοχ\w*|γερμαν\w*|ολοκαυτωμ\w*|ποντι\w*|γενοκτον\w*|βορειοηπειρ\w*|ελληνογερμαν\w*')),
    ('migration', W(r'προσφυγ\w*|μεταναστ\w*|hotspot|λαθρομεταναστ\w*|δομ\w* φιλοξεν\w*|κεντρ\w* (?:κρατησ|φιλοξεν|υποδοχ)\w*')),
    ('ert', W(r'ερτ|ε\.ρ\.τ\.?')),
    ('privatisation', W(r'υπερταμει\w*|ιδιωτικοποι\w*|ταιπεδ|ευδαπ|ευαθ|ιδιωτ\w* του νερου|νερ\w*|υδρευσ\w*')),
    ('environment', W(r'αιολικ\w*|ανεμογεννητ\w*|μεταλλ\w*|εξορυξ\w*|χυτα|χυτυ|απορριμ\w*|περιβαλλ\w*|δασικ\w*|ιχθυοκαλλιεργ\w*|κεραι\w*|ρυπανσ\w*|υδρογονανθρακ\w*|λατομ\w*|ηλεκτροπαραγ\w*|φωτοβολτα\w*|σκουπιδ\w*|κινητ\w* τηλεφων\w*|σταθμ\w* βασησ|ακτ(?:η|εσ|ων)|αιγιαλ\w*|πυρκαγι\w*|πυροπληκτ\w*|σεισμ\w*|πλημμυρ\w*')),
    ('debt', W(r'πλειστηριασμ\w*|υπερχρεωμεν\w*|κατοικι\w*|δανει\w*|δανει|κοκκιν\w* δαν\w*')),
    ('taxes', W(r'ενφια|φορ\w*|φπα|τελ(?:οσ|ουσ|η|ων)|διοδι\w*|χαρατσ\w*')),
    ('labour', W(r'απολυσ\w*|εργαζομεν\w*|διαθεσιμοτητ\w*|κινητικοτητ\w*|μισθ\w*|συνταξ\w*|συνταξιουχ\w*|αγροτ\w*|απεργ\w*|ανεργ\w*|κτηνοτροφ\w*|ελαιοπαραγωγ\w*|αλιε\w*|δασεργατ\w*|κοινωφελ\w*|σχολικ\w* φυλακ\w*|επαγγελματι\w*|συμβασιουχ\w*|προσληψ\w*')),
    ('services', W(r'κλεισιμ\w*|καταργησ\w*|υποβαθμισ\w*|συγχωνευσ\w*|λειτουργι\w*|ικα|δου|ελτα|τραπεζ\w*|νοσοκομει\w*|κεντρ\w* υγει\w*|σχολει\w*|αστυνομ\w*|αστυνομικ\w*|δικαστ\w*|ειρηνοδικ\w*|λιμεν\w*|σιδηροδρομ\w*|οσε|ακτοπλοι\w*|υποθηκοφυλακ\w*|πυροσβεστ\w*|παιδει\w*|υγει\w*|εοπυυ|σχολ\w*')),
    ('solidarity', W(r'συμπαραστασ\w*|αλληλεγγυ\w*|καταδικ\w*|καταγγελ\w*|χρυσ\w* αυγ\w*|ρατσισ\w*|φασισ\w*|βια\w*|επιθεσ\w*|ειρην\w*|παλαιστιν\w*|συρι\w*|κουρδ\w*|πολεμ\w*|στηριξ\w*|διαμαρτυρ\w*')),
]
RES_GENERIC = set('ψηφισμα ψηφισματοσ ψηφισματα ψηφισματων δημοτικου δημοτικο συμβουλιου συμβουλιο δημου δημοσ αποφαση αποφασησ αποφασεωσ αριθ αριθμ αριθμοσ '
                  'θεμα περι εκδοση εκδοσησ καταθεση καταθεσησ λημμα ληψη σχετικα σχετικο σχετικη αδσ ομοφωνο ομοφωνη του τησ την των τον στο στη στην για απο '
                  'και που αφορα κατεπειγον κατεπειγοντοσ θεματοσ συνεδριαση συνεδριασησ τακτικη τακτικησ εκτακτη εκτακτησ ημερησιασ διαταξησ προ ψηφιση '
                  'εγκριση εγκρισησ ψηφισησ'.split())
LAWRX = re.compile(r'(?<![\w/])[νΝ]\.?\s?(\d{3,4})\s?/\s?(\d{4}|\d{2})(?!\d)')
MAXDAYS = 400
yc = collections.Counter(); folders_y = collections.defaultdict(set); first_post = {}
top_c = collections.Counter(); top_cat = collections.Counter(); top_y = collections.Counter()
delay = {c: collections.Counter() for c in CATS + ['all']}; delay_y = collections.defaultdict(collections.Counter)
clock = collections.Counter(); ntype = collections.Counter()
legal = collections.Counter(); apok_tot = collections.Counter(); apok_y = collections.Counter()
lawcit = collections.Counter(); lawcit_y = collections.Counter(); lawname = collections.defaultdict(collections.Counter)
lawtop = collections.defaultdict(collections.Counter); lawcat = collections.defaultdict(collections.Counter)
res = collections.Counter(); res_y = collections.Counter(); res_ex = collections.defaultdict(list); res_n = 0
reg_kind = collections.Counter(); bad_dates = 0; N = 0; mon_y = collections.Counter()
soft = collections.Counter(); soft_y = collections.Counter(); legal_local = 0; reg_any = 0
REG_WORD = W(r'κανονισμ\w*')
QUOT = re.compile(r'«([^»]{6,120})»')
with gzip.open(os.path.join(B, 'diavgeia.tsv.gz'), 'rt', encoding='utf-8') as fh:
    next(fh)
    for line in fh:
        posted, folder, issuer, typ, en, pub, ts, title = line.rstrip('\n').split('\t', 7)
        N += 1
        y = posted[:4]; c = cat_of(issuer, folder)
        yc[(y, c)] += 1; folders_y[y].add(folder); mon_y[posted[:7]] += 1
        ntype[typ] += 1
        f = fold(title)
        k = first(TOPICS, f)
        top_c[k] += 1; top_cat[(c, k)] += 1; top_y[(y, k)] += 1
        try:
            dd = (D(pub or posted) - D(en)).days
        except ValueError:
            dd = None; bad_dates += 1
        if dd is not None:
            v = dd if dd >= 0 else -1
            v = min(v, MAXDAYS)
            delay[c][v] += 1; delay['all'][v] += 1; delay_y[y][v] += 1
        if ts:
            t = datetime.datetime.fromtimestamp(int(ts) / 1000, TZ)
            clock[(t.weekday(), t.hour)] += 1
        if k == 'legality' and re.search(W(r'δημοτικ\w*|δημου|δημων|δημαρχ\w*|περιφερειακ\w*|περιφερει\w*|κοινοτ\w*|ν\.?π\.?δ\.?δ\.?|συνδεσμ\w*'), f):
            legal_local += 1
        if c == 'apok':
            apok_tot[issuer] += 1
            if k == 'legality':
                legal[issuer] += 1; apok_y[(issuer, y)] += 1
        elif k == 'legality':
            legal['(other bodies)'] += 1
        found = set()
        for m in LAWRX.finditer(title):
            nn, yy = m.group(1), m.group(2)
            if len(yy) == 2: yy = ('19' if int(yy) > 30 else '20') + yy
            if 1900 <= int(yy) <= 2019:
                found.add(f'{nn}/{yy}')
        for lw in found:
            lawcit[lw] += 1; lawcit_y[(lw, y)] += 1; lawtop[lw][k] += 1; lawcat[lw][c] += 1
            mq = re.search(r'(?<![\w/])[νΝ]\.?\s?' + lw.split('/')[0] + r'\s?/\s?(?:' + lw.split('/')[1] + '|' + lw.split('/')[1][2:] + r')(?!\d)[^«]{0,40}«([^»]{6,160})»', title)
            if mq: lawname[lw][mq.group(1).strip().rstrip('.').strip()] += 1
        if c == 'dimos' and re.search(W(r'ψηφισμα\w*'), f):
            # a title that names no subject: only "resolution", the council, the municipality, numbers and small words
            rest = [w for w in re.findall(r'[α-ωa-z]+', f) if len(w) > 2 and w not in RES_GENERIC and w not in fold(issuer).split()]
            r_ = 'nosubject' if not rest else first(RES, f)
            res[r_] += 1; res_y[(y, r_)] += 1; res_n += 1
            if len(res_ex[r_]) < 8: res_ex[r_].append([y, issuer, title[:150]])
        if k == 'regulation':
            reg_kind[c] += 1
        if re.search(REG_WORD, f):
            reg_any += 1
        if not typ.startswith('Α.2'):
            soft[(typ[:3], issuer)] += 1; soft_y[(typ[:3], y)] += 1
print('diavgeia records', N, 'bad dates', bad_dates)
YRS = sorted({y for y, _ in yc})


def med_hist(h):
    tot = sum(h.values()); acc = 0
    for v in sorted(h):
        acc += h[v]
        if acc >= tot / 2: return v
    return None


def q_hist(h, q):
    tot = sum(h.values()); acc = 0
    for v in sorted(h):
        acc += h[v]
        if acc >= tot * q: return v


DB = [[0, 0], [1, 1], [2, 7], [8, 30], [31, MAXDAYS]]
bucket = lambda h: [sum(n for v, n in h.items() if lo <= v <= hi) for lo, hi in DB]
OUT['c07'] = {'years': [{'y': y, **{c: yc[(y, c)] for c in CATS}, 'issuers': len(folders_y[y])} for y in YRS], 'n': N,
              'first': min(mon_y), 'last': max(mon_y), 'months': sorted(mon_y.items()), 'types': ntype.most_common()}
OUT['c08'] = {'topics': top_c.most_common(), 'by_cat': {c: {k: top_cat[(c, k)] for k, _ in top_c.most_common()} for c in CATS},
              'by_year': {y: {k: top_y[(y, k)] for k, _ in top_c.most_common()} for y in YRS}, 'n': N, 'reg_any': reg_any}
OUT['c09'] = {'cats': {c: {'b': bucket(delay[c]), 'med': med_hist(delay[c]), 'q3': q_hist(delay[c], .75), 'neg': delay[c][-1], 'n': sum(delay[c].values())} for c in CATS + ['all']},
              'years': {y: {'b': bucket(delay_y[y]), 'med': med_hist(delay_y[y]), 'n': sum(delay_y[y].values())} for y in YRS}}
OUT['c10'] = {'grid': [[d, h, clock[(d, h)]] for d in range(7) for h in range(24)], 'n': sum(clock.values())}
OUT['c11'] = {'apok': [[k, legal[k], apok_tot[k], {y: apok_y[(k, y)] for y in YRS if apok_y[(k, y)]}] for k in sorted(apok_tot, key=lambda k: -legal[k])],
              'other': legal['(other bodies)'], 'n': sum(legal.values()), 'apok_all': sum(apok_tot.values()), 'local': legal_local}
toplaws = [lw for lw, _ in lawcit.most_common(16)]
OUT['c12'] = {'laws': [[lw, lawcit[lw], {y: lawcit_y[(lw, y)] for y in YRS if lawcit_y[(lw, y)]}, lawname[lw].most_common(3), lawtop[lw].most_common(3), lawcat[lw].most_common(3)] for lw in toplaws],
              'with': sum(lawcit.values()), 'distinct': len(lawcit), 'years': YRS}
OUT['c13'] = {'topics': [[k, res[k], {y: res_y[(y, k)] for y in YRS if res_y[(y, k)]}] for k, _ in res.most_common()], 'n': res_n, 'examples': res_ex}
OUT['c20'] = {t_: {'issuers': sorted([[i, n_] for (tt, i), n_ in soft.items() if tt == t_], key=lambda x: -x[1]),
                   'years': {y: soft_y[(t_, y)] for y in YRS}} for t_ in ['Α.3', 'Α.4', 'Α.5']}
print('circulars', sum(n_ for (tt, i), n_ in soft.items() if tt == 'Α.3'), 'opinions', sum(n_ for (tt, i), n_ in soft.items() if tt == 'Α.4'))
print('topics', top_c.most_common()); print('resolutions', res_n, res.most_common())
print('law citations', lawcit.most_common(16))
for lw in toplaws: print('  ', lw, lawname[lw].most_common(2))

# ====================================================================== IV. Areios Pagos
# a decision's key: (year, chamber folder, number). Commits made before the layout change name the folder without the
# number-range level (and 93 older ones without the chamber: all criminal, as the layout commit records)
def ap_key(folder):
    seg = folder.split('/')
    grp = seg[3] if len(seg) >= 5 else 'criminal'
    return (int(seg[2]), grp, int(seg[-1]))


CH = {}
for line in list(open(os.path.join(B, 'caselaw.tsv'), encoding='utf-8'))[1:]:
    pub, num, year, chamber, folder = line.rstrip('\n').split('\t')
    k = ap_key(folder)
    CH[k] = {'pub': pub, 'num': int(num) if num else k[2], 'year': int(year) if year else k[0], 'chamber': chamber, 'grp': k[1]}
TX = {}
for line in list(open(os.path.join(B, 'ap-text.tsv'), encoding='utf-8'))[1:]:
    p = line.rstrip('\n').split('\t')
    TX[ap_key(p[0])] = {'hearing': p[1], 'decided': p[2], 'published': p[3], 'words': int(p[4]), 'op': p[5], 'app': p[6]}
print('decisions', len(CH), 'texts', len(TX), 'matched', len(set(CH) & set(TX)))


def section(c):
    """('civil'|'criminal'|'civil-plenary'|'criminal-plenary', short section label)"""
    ch, grp = c['chamber'], c['grp']                  # grp: civil, criminal, civil-plenary, criminal-plenary
    m = re.match(r'^(ΠΟΛΙΤΙΚΕΣ|ΠΟΙΝΙΚΕΣ) - (.*)$', ch)
    sec = m.group(2).strip() if m else ''
    if 'ΟΛΟΜΕΛΕΙΑ' in sec or 'plenary' in grp:
        return ('criminal-plenary' if 'criminal' in grp or (m and m.group(1) == 'ΠΟΙΝΙΚΕΣ') else 'civil-plenary'), 'Ολ'
    if 'Ποιν. Διακ' in sec:
        return 'criminal', 'Διακ'
    return ('criminal' if 'criminal' in grp else 'civil'), sec or '?'


OUTC = [('quash', r'^\W*(?:κατα (?:μεροσ|ενα μεροσ) )?αναιρει'), ('dismiss', r'^\W*απορριπτει'), ('closed', r'^\W*(?:κηρυσσει|θεωρει|καταργει)'),
        ('other', r'.')]


def outcome(op):
    op = op.translate(LAT).strip()
    if not op:
        return None
    m = re.search(r'(αναιρει|απορριπτει|κηρυσσει|θεωρει|καταργει|παραπεμπει|δεχεται|διατασσει|αναβαλλει|διορθωνει|αποφαινεται|ερμηνευει|ακυρωνει|αναστελλει|επικυρωνει|εξαφανιζει)', op)
    if not m:
        return 'other'
    v = m.group(1)
    return {'αναιρει': 'quash', 'απορριπτει': 'dismiss', 'κηρυσσει': 'closed', 'θεωρει': 'closed', 'καταργει': 'closed'}.get(v, 'other')


CITY = [  # the seat named after the court in the judgment appealed against (folded genitive) -> city key
    ('αθηνων', 'athens'), ('πειραια', 'piraeus'), ('πειραιωσ', 'piraeus'), ('θεσσαλονικησ', 'thessaloniki'), ('πατρων', 'patras'), ('λαρισασ', 'larissa'),
    ('λαρισησ', 'larissa'), ('ναυπλιου', 'nafplio'), ('ιωαννινων', 'ioannina'), ('θρακησ', 'komotini'), ('κομοτηνησ', 'komotini'), ('ανατολικησ κρητησ', 'heraklion'),
    ('ηρακλειου', 'heraklion'), ('κρητησ', 'chania'), ('χανιων', 'chania'), ('κερκυρασ', 'corfu'), ('δωδεκανησου', 'rhodes'), ('ροδου', 'rhodes'),
    ('βορειου αιγαιου', 'mytilene'), ('μυτιληνησ', 'mytilene'), ('λεσβου', 'mytilene'), ('αιγαιου', 'syros'), ('συρου', 'syros'),
    ('δυτικησ μακεδονιασ', 'kozani'), ('κοζανησ', 'kozani'), ('λαμιασ', 'lamia'), ('καλαματασ', 'kalamata'), ('δυτικησ στερεασ ελλαδασ', 'agrinio'),
    ('αγρινιου', 'agrinio'), ('ευβοιασ', 'chalkida'), ('χαλκιδασ', 'chalkida'), ('βολου', 'volos'), ('σερρων', 'serres'), ('δραμασ', 'drama'), ('καβαλασ', 'kavala'),
    ('ξανθησ', 'xanthi'), ('ροδοπησ', 'komotini'), ('αλεξανδρουπολησ', 'alexandroupoli'), ('ορεστιαδασ', 'orestiada'), ('κατερινησ', 'katerini'),
    ('βεροιασ', 'veria'), ('εδεσσασ', 'edessa'), ('γιαννιτσων', 'giannitsa'), ('κιλκισ', 'kilkis'), ('χαλκιδικησ', 'polygyros'), ('πολυγυρου', 'polygyros'),
    ('τρικαλων', 'trikala'), ('καρδιτσασ', 'karditsa'), ('αμφισσασ', 'amfissa'), ('λιβαδειασ', 'livadeia'), ('θηβων', 'thebes'), ('κορινθου', 'corinth'),
    ('τριπολησ', 'tripoli'), ('σπαρτησ', 'sparta'), ('πυργου', 'pyrgos'), ('αιγιου', 'aigio'), ('μεσολογγιου', 'mesolongi'), ('αρτασ', 'arta'), ('πρεβεζασ', 'preveza'),
    ('θεσπρωτιασ', 'igoumenitsa'), ('ηγουμενιτσασ', 'igoumenitsa'), ('καστοριασ', 'kastoria'), ('φλωρινασ', 'florina'), ('γρεβενων', 'grevena'),
    ('λευκαδασ', 'lefkada'), ('ζακυνθου', 'zakynthos'), ('κεφαλληνιασ', 'argostoli'), ('κεφαλονιασ', 'argostoli'), ('ρεθυμνου', 'rethymno'), ('λασιθιου', 'lasithi'),
    ('νεαπολησ', 'lasithi'), ('σαμου', 'samos'), ('χιου', 'chios'), ('κω', 'kos'), ('ναξου', 'naxos'), ('ρεθυμνησ', 'rethymno'), ('καλαβρυτων', 'kalavryta'),
    ('ηλειασ', 'pyrgos'), ('αμαλιαδασ', 'amaliada'), ('κυπαρισσιασ', 'kyparissia'), ('γυθειου', 'gytheio'), ('αμφιλοχιασ', 'amfilochia'),
    ('πατρασ', 'patras'), ('μεσσηνιασ', 'kalamata'), ('κυκλαδων', 'syros'), ('τριμελουσ εφετειου κακουργηματων αθηνων', 'athens'),
]
CITY_RX = [(re.compile(W(k)), v) for k, v in CITY]
COURT = re.compile(r'(εφετει\w*|εφετων|πρωτοδικει\w*|πρωτοδικων|πλημμελειοδικει\w*|πλημμελειοδικων|ειρηνοδικει\w*|πταισματοδικει\w*|ορκωτ\w* δικαστηρι\w*|μικτ\w* ορκωτ\w*|δικαστηρι\w* ανηλικων|στρατοδικει\w*|αναθεωρητικ\w* δικαστηρι\w*|ναυτοδικει\w*)\s+(.{0,60})')


def appealed(app):
    """(level, city) of the judgment appealed against, from the text after "για αναίρεση" """
    if not app:
        return None, None
    m = COURT.search(app)
    if not m:
        return None, None
    lv = m.group(1)
    level = 'appeal' if lv.startswith('εφετ') else 'first' if lv.startswith(('πρωτοδικ', 'πλημμελειοδικ', 'μικτ', 'ορκωτ', 'δικαστηρι')) else 'other'
    if 'εφετ' in m.group(0) and 'ορκωτ' in m.group(0): level = 'appeal'
    rest = m.group(2)
    for rx, v in CITY_RX:
        if rx.search(rest):
            return level, v
    return level, None


rows = []
for key, c in CH.items():
    grp, sec = section(c)
    t = TX.get(key, {})
    o = outcome(t.get('op', ''))
    # the judgment appealed against, as the operative part names it (it does for every outcome), else as the text
    # after "για αναίρεση" names it
    lev, city = appealed(t.get('op', ''))
    if not city:
        lev2, city = appealed(t.get('app', ''))
        lev = lev or lev2
    lag = None
    if t.get('hearing') and c['pub']:
        try:
            lag = (D(c['pub']) - D(t['hearing'])).days
        except ValueError:
            lag = None
        if lag is not None and not (0 <= lag <= 1500):
            lag = None
    rows.append({'y': c['year'], 'pub': c['pub'], 'grp': grp, 'sec': sec, 'num': c['num'], 'o': o, 'lag': lag, 'level': lev, 'city': city,
                 'words': t.get('words'), 'text': bool(t)})
print('decisions', len(rows), 'with text', sum(r['text'] for r in rows), 'outcome', collections.Counter(r['o'] for r in rows).most_common(),
      'lag known', sum(1 for r in rows if r['lag'] is not None), 'city', sum(1 for r in rows if r['city']), 'level', collections.Counter(r['level'] for r in rows))
APY = sorted({r['y'] for r in rows})
G = lambda r: 'plenary' if 'plenary' in r['grp'] else r['grp']
# numbering per year (civil and criminal are numbered apart): the highest number held, for the coverage note
hi = collections.defaultdict(int); cnt = collections.Counter()
for r in rows:
    if r['grp'] in ('civil', 'criminal') and r['num']:
        hi[(r['y'], r['grp'])] = max(hi[(r['y'], r['grp'])], r['num']); cnt[(r['y'], r['grp'])] += 1
OUT['c14'] = {'years': [{'y': y, 'civil': sum(1 for r in rows if r['y'] == y and G(r) == 'civil'), 'criminal': sum(1 for r in rows if r['y'] == y and G(r) == 'criminal'),
                         'plenary': sum(1 for r in rows if r['y'] == y and G(r) == 'plenary'), 'hi_civil': hi[(y, 'civil')], 'hi_criminal': hi[(y, 'criminal')],
                         'secs': collections.Counter(r['sec'] for r in rows if r['y'] == y and G(r) != 'plenary')} for y in APY], 'n': len(rows)}
mon = collections.Counter((int(r['pub'][:4]), int(r['pub'][5:7])) for r in rows if r['pub'])
OUT['c15'] = {'grid': [[y, m, mon[(y, m)]] for y in APY for m in range(1, 13)], 'n': sum(mon.values()),
              'wd': collections.Counter(D(r['pub']).weekday() for r in rows if r['pub'])}
SECS = ['Α1', 'Α2', 'Β1', 'Β2', 'Γ', 'Δ', 'Ε', 'ΣΤ', 'Ζ']
sec_rows = []
for grp, sec, lab in [('civil', s, s) for s in SECS[:6]] + [('criminal', s, s) for s in SECS[6:]] + [('civil-plenary', 'Ολ', 'ΟλΠ'), ('criminal-plenary', 'Ολ', 'ΟλΠοιν')]:
    rr = [r for r in rows if r['grp'] == grp and r['sec'] == sec and r['o']]
    oc = collections.Counter(r['o'] for r in rr)
    sec_rows.append({'grp': grp, 'sec': lab, 'n': len(rr), **{k: oc[k] for k in ['quash', 'dismiss', 'closed', 'other']}})
OUT['c16'] = {'rows': sec_rows, 'all': dict(collections.Counter(r['o'] for r in rows if r['o'])),
              'by_grp': {g: dict(collections.Counter(r['o'] for r in rows if G(r) == g and r['o'])) for g in ['civil', 'criminal', 'plenary']},
              'no_op': sum(1 for r in rows if r['text'] and not r['o'])}
OUT['c17'] = {'years': [{'y': y, **{g: dict(collections.Counter(r['o'] for r in rows if r['y'] == y and G(r) == g and r['o'])) for g in ['civil', 'criminal']}} for y in APY]}


def qs(v):
    v = sorted(v)
    if not v: return None
    q = lambda p: v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]
    return [q(.25), statistics.median(v), q(.75), len(v)]


OUT['c18w'] = {'years': [{'y': y, **{g: qs([r['words'] for r in rows if r['y'] == y and G(r) == g and r['words']]) for g in ['civil', 'criminal']}} for y in APY]}
OUT['c18'] = {'years': [{'y': y, **{g: qs([r['lag'] for r in rows if r['y'] == y and G(r) == g and r['lag'] is not None]) for g in ['civil', 'criminal']}} for y in APY],
              'all': {g: qs([r['lag'] for r in rows if G(r) == g and r['lag'] is not None]) for g in ['civil', 'criminal']}}
cityc = collections.defaultdict(collections.Counter)
for r in rows:
    if r['city']:
        cityc[r['city']][G(r)] += 1
        if r['o'] == 'quash': cityc[r['city']]['q_' + G(r)] += 1
        if r['o']: cityc[r['city']]['o_' + G(r)] += 1
        cityc[r['city']]['lv_' + (r['level'] or '')] += 1
OUT['c19'] = {'cities': {k: dict(v) for k, v in cityc.items()}, 'n': sum(1 for r in rows if r['city']), 'with_app': sum(1 for r in rows if r['level']),
              'texts': sum(1 for r in rows if r['text'])}
print('city top', sorted(((k, sum(v[g] for g in ['civil', 'criminal', 'plenary'])) for k, v in cityc.items()), key=lambda x: -x[1])[:12])

# ====================================================================== profile and write
OUT['profile'] = {
    'built': datetime.date.today().isoformat(), 'head': os.environ.get('HEAD_SHA', ''), 'diavgeia': N, 'caselaw': len(rows), 'laws': len(LAWS),
    'decrees': len(PD), 'articles': len(arts), 'tracked': len(rows4), 'record_to': REC_TO, 'dv_from': OUT['c07']['first'], 'dv_to': OUT['c07']['last'],
    'ap_from': min(r['pub'] for r in rows if r['pub']), 'ap_to': max(r['pub'] for r in rows if r['pub']), 'issuers': len(set().union(*folders_y.values())),
}
with open(os.path.join(B, 'data.json'), 'w', encoding='utf-8') as fh:
    json.dump({'charts': {k: v for k, v in OUT.items() if k != 'profile'}, 'profile': OUT['profile']}, fh, ensure_ascii=False, separators=(',', ':'), default=list)
print('data.json', os.path.getsize(os.path.join(B, 'data.json')))
