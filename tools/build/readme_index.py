"""Folder READMEs and year indexes for greece-law, generated from the tree (tools/build/readme_index.py).

    python -X utf8 tools/build/readme_index.py [<tree-ish>] [--write <dir>]

Reads the tree only (git ls-tree / cat-file; no checkout, no network) and returns, or writes under <dir>, every
generated file: README.md in each top-level law folder (constitution/, codes/, laws/, decrees/, norm/, local/,
caselaw/, data/, tools/), README.md in each laws/<year>/ and decrees/<year>/ (number, title, in-force date, folder),
and the "Where to find the law" block of README.md (Greek) and README.en.md, between the markers
<!-- where:start --> and <!-- where:end -->. Rerun after new acts land; files that come out the same are not changed.
Standard library only.
"""
import collections
import json
import re
import subprocess
import sys

NOWIN = 0x08000000 if sys.platform == 'win32' else 0
START, END = '<!-- where:start -->', '<!-- where:end -->'
CODE_NAMES = {  # slug -> (Greek, English); codes/<slug>/README.md's first heading is used when a slug is not here
    'civil-code': ('Αστικός Κώδικας', 'Civil Code'),
    'civil-procedure-code': ('Κώδικας Πολιτικής Δικονομίας', 'Code of Civil Procedure'),
    'penal-code': ('Ποινικός Κώδικας', 'Penal Code'),
    'criminal-procedure-code': ('Κώδικας Ποινικής Δικονομίας', 'Code of Criminal Procedure'),
    'administrative-procedure-code': ('Κώδικας Διοικητικής Διαδικασίας', 'Code of Administrative Procedure'),
    'code-of-administrative-procedure-courts': ('Κώδικας Διοικητικής Δικονομίας', 'Code of Procedure of the Administrative Courts'),
    'commercial-code': ('Εμπορικός Νόμος', 'Commercial Code'),
    'tax-procedure-code': ('Κώδικας Φορολογικής Διαδικασίας', 'Tax Procedure Code'),
    'income-tax-code': ('Κώδικας Φορολογίας Εισοδήματος', 'Income Tax Code'),
    'vat-code': ('Κώδικας Φόρου Προστιθέμενης Αξίας', 'VAT Code'),
    'labour-code': ('Κώδικας Ατομικού Εργατικού Δικαίου', 'Individual Labour Law Code'),
    'local-government-code': ('Κώδικας Τοπικής Αυτοδιοίκησης', 'Local Government Code'),
    'civil-servants-code': ('Υπαλληλικός Κώδικας', 'Civil Servants Code'),
}


def git(repo, *a, binary=False):
    p = subprocess.run(['git', '-C', str(repo), *a], capture_output=True, creationflags=NOWIN)
    if p.returncode:
        raise RuntimeError(f'git {" ".join(a[:3])}: {p.stderr.decode("utf-8", "replace")[-300:]}')
    return p.stdout if binary else p.stdout.decode('utf-8', 'replace')


class Blobs:
    """Blob text by id: the local object store, else GitHub's blob API (a mirror may hold an object it cannot stream)."""

    def __init__(self, repo, slug='greece-law'):
        self.repo, self.slug, self.cache, self.remote = repo, slug, {}, 0

    def prefetch(self, shas):
        """Read many blobs through one `cat-file --batch`; an object the store cannot stream ends the batch, and the
        rest are read in a new one (that object is left to get())."""
        todo = [s for s in dict.fromkeys(shas) if s not in self.cache]
        while todo:
            p = subprocess.run(['git', '-C', str(self.repo), 'cat-file', '--batch'], input=('\n'.join(todo) + '\n').encode(),
                               capture_output=True, creationflags=NOWIN, env=_env())
            out, pos, done = p.stdout, 0, 0
            for sha in todo:
                nl = out.find(b'\n', pos)
                if nl < 0:
                    break
                hdr = out[pos:nl].split()
                if len(hdr) < 3:  # "<sha> missing"
                    pos, done = nl + 1, done + 1
                    continue
                size = int(hdr[2])
                if nl + 1 + size > len(out):
                    break
                self.cache[sha] = out[nl + 1:nl + 1 + size].decode('utf-8', 'replace')
                pos, done = nl + 1 + size + 1, done + 1
            todo = todo[done + 1:]  # skip the object the batch died on

    def get(self, sha):
        if sha in self.cache:
            return self.cache[sha]
        p = subprocess.run(['git', '-C', str(self.repo), 'cat-file', 'blob', sha], capture_output=True,
                           creationflags=NOWIN, env=_env())
        if p.returncode == 0:
            text = p.stdout.decode('utf-8', 'replace')
        else:
            import base64
            q = subprocess.run(['gh', 'api', f'repos/lexifina/{self.slug}/git/blobs/{sha}', '--jq', '.content'],
                               capture_output=True, creationflags=NOWIN)
            if q.returncode:
                raise RuntimeError(f'blob {sha} unreadable locally and from GitHub')
            text = base64.b64decode(q.stdout).decode('utf-8', 'replace')
            self.remote += 1
        self.cache[sha] = text
        return text


def _env():
    import os
    e = dict(os.environ)
    e['GIT_NO_LAZY_FETCH'] = '1'
    return e


def ls(repo, ref, *paths):
    """[(mode, type, sha, path)] for every file under the paths."""
    out = git(repo, 'ls-tree', '-r', '-z', ref, '--', *paths)
    rows = []
    for ent in out.split('\x00'):
        if '\t' in ent:
            meta, path = ent.split('\t', 1)
            m, t, s = meta.split()
            rows.append((m, t, s, path))
    return rows


def first_heading(text):
    for ln in text.splitlines():
        if ln.startswith('# '):
            return ln[2:].strip()
    return ''


def in_force_of(readme):
    m = re.search(r'In force: (\d{4}-\d\d-\d\d)', readme) or re.search(r'from (\d{4}-\d\d-\d\d)', readme)
    return m.group(1) if m else ''


def title_from_text_layer(text):
    lines = [x.strip() for x in text.splitlines()]
    out = []
    for ln in lines[1:12]:
        if not ln:
            continue
        if ln.startswith(('Ο ΠΡΟΕΔΡΟΣ', 'ΤΗΣ ΕΛΛΗΝΙΚΗΣ', 'Εκδίδομε')):
            break
        if out and out[-1].endswith(('−', '-')):
            out[-1] = out[-1][:-1] + ln
        else:
            out.append(ln)
    t = ' '.join(out).strip()
    return t[:300] + ('…' if len(t) > 300 else '')


def cell(s):
    return (s or '').replace('|', '\\|').replace('\n', ' ').strip()


def acts(repo, ref, kind_dir, blobs):
    """{year: [(number, folder, title, in_force, note)]} for laws/ or decrees/."""
    by = collections.defaultdict(lambda: collections.defaultdict(dict))
    for _m, _t, sha, path in ls(repo, ref, kind_dir):
        parts = path.split('/')
        if len(parts) < 4:
            continue
        year, folder, name = parts[1], parts[2], parts[3]
        if len(parts) == 4 and name in ('README.md', 'source.json', 'text-layer.txt'):
            by[year][folder][name] = sha
        else:
            by[year][folder].setdefault('#files', 0)
            by[year][folder]['#files'] += 1
    blobs.prefetch([sha for folders in by.values() for f in folders.values()
                    for k, sha in f.items() if k in ('README.md', 'source.json')
                    or (k == 'text-layer.txt' and 'README.md' not in f)])
    res = {}
    for year, folders in by.items():
        rows = []
        for folder, f in folders.items():
            title = inf = ''
            if 'README.md' in f:
                r = blobs.get(f['README.md'])
                title, inf = first_heading(r), in_force_of(r)
                if re.fullmatch(r'(ν\.|π\.δ\.)\s*\d+/\d{4}', title):  # a link stub to codes/<slug>/
                    body = [x.strip() for x in r.split('\n')[1:] if x.strip()]
                    if body:
                        title = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', body[0])
            if 'source.json' in f and (not title or not inf):
                try:
                    sj = json.loads(blobs.get(f['source.json']))
                except ValueError:
                    sj = {}
                title = title or sj.get('title', '')
                inf = inf or sj.get('in_force') or sj.get('published') or ''
            if 'text-layer.txt' in f and not title:
                title = title_from_text_layer(blobs.get(f['text-layer.txt']))
            m = re.match(r'(\d+)(.*)', folder)
            num = int(m.group(1)) if m else 0
            note = 'με τροποποιήσεις · with amendments' if folder.endswith('-me-tropopoiiseis') else ''
            rows.append((num, folder, title, inf, note))
        res[year] = sorted(rows, key=lambda r: (r[0], r[1]))
    return res


def year_readme(kind_dir, year, rows):
    el, en, abbr = ({'laws': ('Νόμοι', 'Laws', 'ν.'), 'decrees': ('Προεδρικά Διατάγματα', 'Presidential decrees', 'π.δ.')}
                    [kind_dir])
    out = [f'# {el} του {year} · {en} of {year}', '',
           f'{len(rows)} {"πράξεις" if len(rows) != 1 else "πράξη"} σε αυτόν τον φάκελο · {len(rows)} '
           f'{"acts" if len(rows) != 1 else "act"} in this folder. '
           f'Ημερομηνία = έναρξη ισχύος (In-force) · Date = the day it took effect. '
           f'[Όλα τα έτη · All years](../README.md)', '',
           '| Αριθμός · No. | Τίτλος · Title | Σε ισχύ από · In force | Φάκελος · Folder |',
           '| ---: | --- | --- | --- |']
    for num, folder, title, inf, note in rows:
        label = f'{abbr} {num}/{year}' if num else folder
        t = cell(title) + (f' ({note})' if note else '')
        out.append(f'| {label} | {t} | {inf} | [`{folder}/`]({folder}/) |')
    return '\n'.join(out) + '\n'


def kind_readme(kind_dir, data):
    el, en = {'laws': ('Νόμοι (ν.)', 'Laws'), 'decrees': ('Προεδρικά Διατάγματα (π.δ.)', 'Presidential decrees')}[kind_dir]
    total = sum(len(v) for v in data.values())
    src = ('Εφημερίδα της Κυβερνήσεως (ΦΕΚ), τεύχος Α΄ · Government Gazette (FEK), series A')
    out = [f'# {el} · {en}', '',
           f'{total} πράξεις, ένας φάκελος ανά πράξη: `{kind_dir}/<έτος>/<αριθμός>/` · {total} acts, one folder per act: '
           f'`{kind_dir}/<year>/<number>/`, one file per article (`art-001.md`). Πηγή · Source: {src}.', '',
           'Ημερομηνίες · Dates: κάθε έκδοση είναι ένα commit με trailer `In-force:` (η ημέρα έναρξης ισχύος) · each '
           'version is one commit with an `In-force:` trailer (the day it took effect).', '',
           '| Έτος · Year | Πράξεις · Acts |', '| --- | ---: |']
    for y in sorted(data):
        out.append(f'| [{y}]({y}/README.md) | {len(data[y])} |')
    return '\n'.join(out) + '\n'


def diavgeia_counts(repo, ref, top):
    """{folder: [records, first year, last year, metadata sha]} for norm/ or local/, streamed from ls-tree."""
    p = subprocess.Popen(['git', '-C', str(repo), 'ls-tree', '-r', ref, '--', top + '/'], stdout=subprocess.PIPE,
                         creationflags=NOWIN, env=_env())
    res, last = {}, None
    for raw in p.stdout:
        meta, _, path = raw.decode('utf-8', 'replace').rstrip('\n').partition('\t')
        parts = path.split('/')
        if len(parts) < 4:
            continue
        rec = '/'.join(parts[:-1])
        org = parts[1]
        r = res.setdefault(org, [0, '9999', '0000', None])
        if rec != last:
            r[0] += 1
            last = rec
        y = parts[2]
        if y.isdigit():
            r[1], r[2] = min(r[1], y), max(r[2], y)
        if r[3] is None and parts[-1] == 'metadata.json':
            r[3] = meta.split()[2]
    p.wait()
    return res


def diavgeia_readme(top, counts, blobs):
    el, en = {'norm': ('Κανονιστικές αποφάσεις φορέων του Δημοσίου (Διαύγεια)',
                       'Regulatory decisions of national public bodies (Diavgeia)'),
              'local': ('Αποφάσεις Περιφερειών, Αποκεντρωμένων Διοικήσεων και Δήμων (Διαύγεια)',
                        'Decisions of regions, decentralised administrations and municipalities (Diavgeia)')}[top]
    total = sum(v[0] for v in counts.values())
    blobs.prefetch([v[3] for v in counts.values() if v[3]])
    out = [f'# {el}', '', f'**{en}.**', '',
           f'{total:,} αποφάσεις σε {len(counts)} φορείς · {total:,} decisions from {len(counts)} bodies. Μία απόφαση = ένας '
           f'φάκελος `{top}/<φορέας>/<έτος>/<μήνας>/<ΑΔΑ>/` · one decision = one folder '
           f'`{top}/<body>/<year>/<month>/<ΑΔΑ>/` (ΑΔΑ: the Diavgeia posting number). Ημερομηνία = ανάρτηση στη Διαύγεια '
           f'· Date = the day it was posted on Diavgeia, when it takes effect (ν. 4727/2020 άρθρο 78 παρ. 2).', '',
           'Ο φάκελος του φορέα είναι λατινική μεταγραφή του ονόματός του · each body\'s folder is its name in Latin '
           'letters.', '',
           '| Φορέας · Body | Φάκελος · Folder | Αποφάσεις · Decisions | Έτη · Years |', '| --- | --- | ---: | --- |']
    for org in sorted(counts):
        n, y0, y1, sha = counts[org]
        label = ''
        if sha:
            try:
                label = json.loads(blobs.get(sha)).get('organization', {}).get('label', '')
            except (ValueError, RuntimeError):
                label = ''
        yrs = f'{y0}–{y1}' if y0 != '9999' else ''
        out.append(f'| {cell(label) or org} | [`{org}/`]({org}/) | {n:,} | {yrs} |')
    return '\n'.join(out) + '\n', total


def caselaw_counts(repo, ref):
    c = collections.Counter()
    for _m, _t, _s, path in ls(repo, ref, 'caselaw'):
        parts = path.split('/')
        if parts[-1] == 'source.json' and len(parts) >= 4:
            c[(parts[1], parts[2])] += 1
    return c


def caselaw_readme(c):
    courts = sorted({k[0] for k in c})
    out = ['# Νομολογία · Case law', '',
           'Αποφάσεις δικαστηρίων, ένας φάκελος ανά απόφαση · Court decisions, one folder per decision: '
           '`caselaw/<court>/<year>/<chamber>/<number range>/<number>/` (`decision.html`, `source.json`). Ημερομηνία = '
           'δημοσίευση της απόφασης · Date = the day the decision was published.', '']
    names = {'areios-pagos': 'Άρειος Πάγος · Supreme Civil and Criminal Court'}
    for court in courts:
        n = sum(v for k, v in c.items() if k[0] == court)
        out += [f'## [{names.get(court, court)}]({court}/)', '', f'{n:,} αποφάσεις · decisions.', '',
                '| Έτος · Year | Αποφάσεις · Decisions |', '| --- | ---: |']
        for (ct, y), v in sorted(c.items()):
            if ct == court:
                out.append(f'| [{y}]({court}/{y}/) | {v:,} |')
        out.append('')
    return '\n'.join(out), sum(c.values())


def codes_list(repo, ref, blobs):
    rows, src = [], {}
    for m, t, sha, path in ls(repo, ref, 'codes'):
        parts = path.split('/')
        if len(parts) == 3 and parts[2] == 'README.md':
            rows.append((parts[1], blobs.get(sha)))
        if len(parts) == 3 and parts[2] == 'source.json':
            try:
                src[parts[1]] = json.loads(blobs.get(sha))
            except ValueError:
                pass
    seen = {r[0] for r in rows}
    for _m, _t, _s, path in ls(repo, ref, 'codes'):
        parts = path.split('/')
        if len(parts) >= 3 and parts[1] not in seen:
            seen.add(parts[1])
            rows.append((parts[1], ''))
    out = []
    for slug, readme in sorted(rows):
        sj = src.get(slug, {})
        el, en = CODE_NAMES.get(slug, (sj.get('code') or first_heading(readme) or slug,
                                       sj.get('code_en') or slug.replace('-', ' ').capitalize()))
        m = re.search(r'(ν\.|π\.δ\.)\s*\d+/\d{4}', readme)
        act = sj.get('act') or (m.group(0) if m else '')
        out.append((slug, el, en, act, sj.get('in_force') or in_force_of(readme)))
    return out


def codes_readme(codes):
    out = ['# Κώδικες · Codes', '',
           'Οι βασικοί κώδικες του ελληνικού δικαίου, ένας φάκελος ανά κώδικα, ένα αρχείο ανά άρθρο · The core Greek '
           'codes, one folder per code, one file per article. Ο νόμος που κύρωσε κάθε κώδικα αναφέρεται στο README του · '
           'Each code\'s README names the act that enacted it.', '',
           '| Κώδικας · Code | Πράξη · Act | Σε ισχύ από · In force | Φάκελος · Folder |', '| --- | --- | --- | --- |']
    for slug, el, en, act, inf in codes:
        out.append(f'| {el} · {en} | {act} | {inf} | [`{slug}/`]({slug}/) |')
    if not codes:
        out.append('| (κανένας ακόμη · none yet) | | | |')
    return '\n'.join(out) + '\n'


STATIC = {
    'data/README.md': """# Δεδομένα · Data

Πίνακες για προγράμματα, όχι για ανάγνωση · Machine-readable tables about the record (not law text):

| Αρχείο · File | Περιεχόμενο · What it holds |
| --- | --- |
| [`paths.json`](paths.json) | κάθε id πράξης -> φάκελος, και οι παλαιότεροι φάκελοι (`previous`) · every act id -> its folder, and the folders it had before each layout move |
| [`acts.json`](acts.json) | πράξεις με τίτλο, κατάσταση, εκδόσεις · acts with title, status, versions (the earlier build's 624 acts) |
| [`versions.json`](versions.json) | κάθε έκδοση με πηγή και sha256 · every version with its source and sha256 |
| [`laws.csv`](laws.csv) | οι πράξεις που επέφεραν μεταβολές · the acts credited with changes |
| [`commits.csv`](commits.csv), [`appends.csv`](appends.csv) | πώς χτίστηκε η ιστορία · how the history was built |
| [`repo.json`](repo.json), [`corpus.sha256`](corpus.sha256) | ρυθμίσεις και άθροισμα ελέγχου · settings and checksum |
| `effort-*.svg`, `el/` | το διάγραμμα του README · the README chart |
| [`earlier-build/`](earlier-build/README.md) | αρχείο της προηγούμενης έκδοσης του αποθετηρίου · archive of an earlier build of this repository |
""",
    'tools/README.md': """# Εργαλεία · Tools

- [`on.py`](on.py): το κείμενο όπως ίσχυε μια ημέρα · the text as it stood on a day: `python tools/on.py 2020-01-01 syntagma art-101`
- [`se_ischy.py`](se_ischy.py): ό,τι ίσχυε μια ημέρα · what was in force on a day
- [`build/`](build/): τα σκριπτ που έχτισαν το αποθετήριο · the scripts that built this repository;
  [`build/readme_index.py`](build/readme_index.py) γράφει τα README των φακέλων και τους πίνακες ανά έτος · writes the
  folder READMEs and the per-year indexes.
""",
    'data/earlier-build/README.md': """# Προηγούμενη έκδοση · Earlier build (archive)

Αρχείο: η πρώτη έκδοση αυτού του αποθετηρίου, πριν από τη σημερινή διάταξη · Archive: the first build of this
repository, from before the current layout. Βρισκόταν στο `registry/` μέχρι τις 16 Νοεμβρίου 2026 · It sat at
`registry/` until 16 November 2026.

Περιέχει το τότε README ([`README.old.md`](README.old.md)), `ACTS.md`, `REPRODUCE.md`, `data/`, τα σκριπτ του
(`tools/build/bulk/`) και 88 README νόμων (`nomos/<year>/<number>/README.md`). Οι διαδρομές μέσα του είναι οι τότε
διαδρομές (`nomos/`, `syntagma/`) · Paths inside it are the paths of that time; today the same acts are in `laws/` and
`constitution/` ([`data/paths.json`](../paths.json)). Το κείμενο του δικαίου δεν βρίσκεται εδώ · No law text is kept
here; nothing in it is read by the tools.
""",
}


def where_block(lang, n_const, codes, laws, decrees, norm, local, caselaw_n, olds=()):
    nl, nd = sum(len(v) for v in laws.values()), sum(len(v) for v in decrees.values())
    ly = ' · '.join(f'[{y}](laws/{y}/README.md)' for y in sorted(laws))
    dy = ' · '.join(f'[{y}](decrees/{y}/README.md)' for y in sorted(decrees))
    (nn, no), (ln_, lo) = norm, local
    if lang == 'el':
        cl = '; '.join(f'[{el}](codes/{s}/) ({a})' if a else f'[{el}](codes/{s}/)' for s, el, en, a, i in codes) or 'κανένας ακόμη'
        rows = [
            ('Σύνταγμα', f'[`constitution/`](constitution/)', f'{n_const} άρθρα, εκδόσεις από το 2001'
             + (''.join(f'; το κείμενο του {y}: [`constitution/{y}/`](constitution/{y}/)' for y in olds))),
            ('Κώδικες', f'[`codes/`](codes/README.md)', cl),
            ('Νόμοι (ν.)', f'[`laws/`](laws/README.md)', f'{nl:,} νόμοι, ανά έτος: {ly}'),
            ('Προεδρικά Διατάγματα (π.δ.)', f'[`decrees/`](decrees/README.md)', f'{nd:,} διατάγματα, ανά έτος: {dy}'),
            ('Αποφάσεις φορέων (Διαύγεια)', f'[`norm/`](norm/README.md)', f'{nn:,} κανονιστικές αποφάσεις {no} φορέων'),
            ('Αποφάσεις τοπικής αυτοδιοίκησης (Διαύγεια)', f'[`local/`](local/README.md)', f'{ln_:,} αποφάσεις {lo} Περιφερειών, Αποκεντρωμένων Διοικήσεων και Δήμων'),
            ('Νομολογία', f'[`caselaw/`](caselaw/README.md)', f'{caselaw_n:,} αποφάσεις του Αρείου Πάγου'),
        ]
        head = ['## Πού βρίσκεται το δίκαιο', '', '| Τι | Φάκελος | Περιεχόμενο |', '| --- | --- | --- |']
        tail = ['', 'Κάθε πράξη έχει δικό της φάκελο (`laws/2019/4624/` είναι ο ν. 4624/2019) με ένα αρχείο ανά άρθρο '
                '(`art-001.md`) και README με τον τίτλο και τις εκδόσεις. [`ACTS.md`](ACTS.md) απαριθμεί τις πράξεις '
                'της πρώτης έκδοσης· [`data/paths.json`](data/paths.json) δίνει τον φάκελο κάθε πράξης.', '',
                '**Ημερομηνίες:** κάθε commit χρονολογείται την ημέρα που η έκδοση τέθηκε σε ισχύ (trailer `In-force:`)· '
                'βλ. [Ημερομηνίες](#ημερομηνίες). **Όρια:** δεν περιέχεται όλο το ελληνικό δίκαιο, και οι περισσότερες '
                'πράξεις είναι όπως δημοσιεύθηκαν, χωρίς μεταγενέστερες τροποποιήσεις· βλ. [Τι δεν δείχνει](#τι-δεν-δείχνει).']
    else:
        cl = '; '.join(f'[{en}](codes/{s}/) ({a})' if a else f'[{en}](codes/{s}/)' for s, el, en, a, i in codes) or 'none yet'
        rows = [
            ('Constitution (Σύνταγμα)', f'[`constitution/`](constitution/)', f'{n_const} articles, versions since 2001'
             + (''.join(f'; the {y} text: [`constitution/{y}/`](constitution/{y}/)' for y in olds))),
            ('Codes (Κώδικες)', f'[`codes/`](codes/README.md)', cl),
            ('Laws (Νόμοι, ν.)', f'[`laws/`](laws/README.md)', f'{nl:,} laws, by year: {ly}'),
            ('Presidential decrees (π.δ.)', f'[`decrees/`](decrees/README.md)', f'{nd:,} decrees, by year: {dy}'),
            ('Decisions of national bodies (Diavgeia)', f'[`norm/`](norm/README.md)', f'{nn:,} regulatory decisions of {no} bodies'),
            ('Decisions of local government (Diavgeia)', f'[`local/`](local/README.md)', f'{ln_:,} decisions of {lo} regions, decentralised administrations and municipalities'),
            ('Case law', f'[`caselaw/`](caselaw/README.md)', f'{caselaw_n:,} decisions of the Areios Pagos (Supreme Court)'),
        ]
        head = ['## Where to find the law', '', '| What | Folder | Holds |', '| --- | --- | --- |']
        tail = ['', 'Each act has its own folder (`laws/2019/4624/` is ν. 4624/2019, Law 4624/2019) with one file per '
                'article (`art-001.md`) and a README giving its title and versions. [`ACTS.md`](ACTS.md) lists the acts '
                'of the first build; [`data/paths.json`](data/paths.json) gives every act\'s folder.', '',
                '**Dates:** each commit is dated on the day its version took effect (the `In-force:` trailer); see '
                '[Dates](#dates). **Limits:** this is not all of Greek law, and most acts are held as enacted, without '
                'later amendments; see [What it does not show](#what-it-does-not-show).']
    body = head + [f'| {a} | {b} | {c} |' for a, b, c in rows] + tail
    return START + '\n' + '\n'.join(body) + '\n' + END


VSTART, VEND = '<!-- versions:start -->', '<!-- versions:end -->'


def versions_block(olds):
    links = ' · '.join(f'[{y}]({y}/)' for y in olds)
    return (VSTART + '\n' + f'Το ισχύον κείμενο είναι τα άρθρα αυτού του φακέλου (`art-NNN.md`, εκδόσεις από το 2001)· '
            f'παλαιότερα κείμενα: {links} · The current text is the articles in this folder (`art-NNN.md`, versions '
            f'since 2001); earlier texts: {links}.\n' + VEND)


def put_block(readme, block, start, end):
    if start in readme and end in readme:
        a, b = readme.index(start), readme.index(end) + len(end)
        return readme[:a] + block + readme[b:]
    lines = readme.split('\n')
    at = next((i + 1 for i, ln in enumerate(lines[:3]) if ln.startswith('# ')), 0)
    return '\n'.join(lines[:at] + ['', block] + lines[at:])


def put_where(readme, block):
    if START in readme and END in readme:
        a, b = readme.index(START), readme.index(END) + len(END)
        return readme[:a] + block + readme[b:]
    lines = readme.split('\n')
    # after the title and the language line (the first line starting with **)
    at = next((i + 1 for i, ln in enumerate(lines[:6]) if ln.startswith('**')), 1)
    return '\n'.join(lines[:at] + ['', block] + lines[at:])


def generate(repo, ref, blobs=None, readmes=None):
    """{path: text} of every generated file for the tree `ref`. `readmes` = {'README.md': text, 'README.en.md': text}
    to insert the where-block into (default: the tree's own)."""
    blobs = blobs or Blobs(repo)
    out = dict(STATIC)
    laws, decrees = acts(repo, ref, 'laws', blobs), acts(repo, ref, 'decrees', blobs)
    for kd, data in (('laws', laws), ('decrees', decrees)):
        out[f'{kd}/README.md'] = kind_readme(kd, data)
        for y, rows in data.items():
            out[f'{kd}/{y}/README.md'] = year_readme(kd, y, rows)
    codes = codes_list(repo, ref, blobs)
    out['codes/README.md'] = codes_readme(codes)
    nc, nl = diavgeia_counts(repo, ref, 'norm'), diavgeia_counts(repo, ref, 'local')
    out['norm/README.md'], n_norm = diavgeia_readme('norm', nc, blobs)
    out['local/README.md'], n_local = diavgeia_readme('local', nl, blobs)
    cc = caselaw_counts(repo, ref)
    out['caselaw/README.md'], n_case = caselaw_readme(cc)
    crows = ls(repo, ref, 'constitution')
    n_const = sum(1 for r in crows if r[3].count('/') == 1 and r[3].rsplit('/', 1)[-1].startswith('art-'))
    olds = sorted({r[3].split('/')[1] for r in crows if r[3].count('/') >= 2})
    cur = next((r[2] for r in crows if r[3] == 'constitution/README.md'), None)
    if cur and olds:
        out['constitution/README.md'] = put_block(blobs.get(cur), versions_block(olds), VSTART, VEND)
    for name, lang in (('README.md', 'el'), ('README.en.md', 'en')):
        cur = (readmes or {}).get(name)
        if cur is None:
            cur = blobs.get(git(repo, 'rev-parse', f'{ref}:{name}').strip())
        out[name] = put_where(cur, where_block(lang, n_const, codes, laws, decrees, (n_norm, len(nc)),
                                               (n_local, len(nl)), n_case, olds))
    return out


if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    ref = args[0] if args and not args[0].startswith('--') else 'HEAD'
    files = generate('.', ref)
    if '--write' in args:
        import pathlib
        root = pathlib.Path(args[args.index('--write') + 1])
        for p, t in files.items():
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_text(t, encoding='utf-8', newline='\n')
    else:
        for p in sorted(files):
            print(p, len(files[p]))
