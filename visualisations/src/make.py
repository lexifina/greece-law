"""Rebuild visualisations/to-elliniko-dikaio-se-20-grafimata.html from this repository.

    python visualisations/src/make.py [--repo PATH] [--ref REF] [--skip-extract]

Steps (all read-only on the repository; scratch output goes to visualisations/src/.build/, which git ignores):
  1. git log of REF (default origin/main), streamed once, one commit at a time:
     - every Diavgeia record (Kind: decision-record): the body that posted it, its folder, decision type, the dates it
       was issued and posted, the posting time (publishTimestamp) and its subject  -> .build/diavgeia.tsv.gz
     - every Areios Pagos decision (Kind: caselaw): number, year, chamber, publication day, folder -> .build/caselaw.tsv
     - every other commit (laws, decrees, the Constitution, amendments): its whole message  -> .build/acts.txt
  2. the Constitution: every version of every article (syntagma/), as committed           -> .build/syntagma.json
  3. the laws held as enacted with a text layer (nomos/<year>/<number>/text-layer.txt and source.json): the title
     from the head of the text and the number of Gazette pages                            -> .build/laws.jsonl
  4. the tables data/acts.json, data/versions.json, data/laws.csv, data/commits.csv, registry/data/acts.json
                                                                                         -> .build/repo/
  5. the text of every Areios Pagos decision (caselaw/.../decision.html, Windows-1253): the hearing, deliberation and
     publication dates, the operative part ("ΓΙΑ ΤΟΥΣ ΛΟΓΟΥΣ ΑΥΤΟΥΣ") and the judgment appealed against
                                                                                         -> .build/ap-text.tsv
  6. prep.py turns those into .build/data.json; build.py fills page.tpl.html with it.
In a blobless clone the missing blobs are fetched in batches: about 41,200 files (40,049 decisions, 947 law files,
some 160 versions of Constitution articles and five tables), about 280 MB of packs. No other text is read: the
Diavgeia records are read from the commit messages alone. Nothing large is held in memory.
"""
import argparse, gzip, html, json, os, re, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--repo', default=os.path.abspath(os.path.join(HERE, '..', '..')))
ap.add_argument('--ref', default=None, help='default: origin/main if present, else HEAD')
ap.add_argument('--out', default=os.path.join(HERE, '..', 'to-elliniko-dikaio-se-20-grafimata.html'))
ap.add_argument('--skip-extract', action='store_true', help='reuse .build/ from a previous run (prep and build only)')
a = ap.parse_args()
B = os.path.join(HERE, '.build')
os.makedirs(os.path.join(B, 'repo'), exist_ok=True)
NOLAZY = dict(os.environ, GIT_NO_LAZY_FETCH='1')
GIT = ['git', '-C', a.repo, '-c', 'core.quotepath=off']


def git(*args):
    return subprocess.run([*GIT, *args], check=True, capture_output=True, env=NOLAZY).stdout


def has(ref):
    return subprocess.run([*GIT, 'rev-parse', '--verify', '-q', ref], capture_output=True).returncode == 0


ref = a.ref or ('origin/main' if has('origin/main') else 'HEAD')
sha = git('rev-parse', ref).decode().strip()
print('ref', ref, sha, flush=True)


def fetch_missing(oids, batch=4000):
    """batched fetches of the blobs a partial clone does not have yet (only these blobs)"""
    oids = sorted(set(oids))
    chk = subprocess.run([*GIT, 'cat-file', '--batch-check'], input=''.join(o + '\n' for o in oids).encode(),
                         capture_output=True, env=NOLAZY).stdout.decode().split('\n')
    missing = [l.split()[0] for l in chk if l.endswith(' missing')]
    for i in range(0, len(missing), batch):
        part = missing[i:i + batch]
        print('fetching', len(part), 'blobs', f'({i + len(part)} of {len(missing)})', flush=True)
        subprocess.run([*GIT, '-c', 'fetch.negotiationAlgorithm=noop', 'fetch', 'origin', '--no-tags', '--no-write-fetch-head',
                        '--recurse-submodules=no', '--filter=blob:none', '--stdin'], input=''.join(m + '\n' for m in part).encode(),
                       check=False, capture_output=True)


def read_blobs(items):
    """yield (path, bytes) for (oid, path) pairs, one blob at a time"""
    p = subprocess.Popen([*GIT, 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=NOLAZY)
    for oid, path in items:
        p.stdin.write((oid + '\n').encode()); p.stdin.flush()
        head = p.stdout.readline().split()
        if len(head) < 3:
            sys.exit('cannot read ' + path)
        data = p.stdout.read(int(head[2])); p.stdout.read(1)
        yield path, data
    p.stdin.close(); p.wait()


def tree(r, *paths):
    """(path, oid) of every file of the tree of r under paths, streamed"""
    lt = subprocess.Popen([*GIT, 'ls-tree', '-r', '-z', r, '--', *paths], stdout=subprocess.PIPE, env=NOLAZY)
    buf = b''
    for chunk in iter(lambda: lt.stdout.read(1 << 16), b''):
        buf += chunk
        *ents, buf = buf.split(b'\0')
        for e in ents:
            meta, path = e.split(b'\t', 1)
            yield path.decode('utf-8'), meta.split()[2].decode()
    lt.wait()


def fold(s):
    """lower case without accents, final sigma as sigma (Greek titles are matched on this form)"""
    s = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').replace('ς', 'σ')


TR = re.compile(r'^([A-Z][A-Za-z-]+): (.*)$')
TS = re.compile(r'publishTimestamp (\d{12,})')
AP_SUBJ = re.compile(r'^ΑΡΕΙΟΣ ΠΑΓΟΣ - ΑΠΟΦΑΣΗ (\d+)/(\d{4})(?: \((.*)\))?')

if not a.skip_extract:
    # ---------------------------------------------------------------- 1. the history, streamed
    lg = subprocess.Popen([*GIT, 'log', ref, '--format=%x1e%H%x1f%an%x1f%ae%x1f%ad%x1f%B', '--date=short'], stdout=subprocess.PIPE, env=NOLAZY)
    dv = gzip.open(os.path.join(B, 'diavgeia.tsv.gz'), 'wt', encoding='utf-8', newline='\n', compresslevel=4)
    dv.write('\t'.join(['posted', 'folder', 'issuer', 'type', 'enacted', 'published', 'ts', 'title']) + '\n')
    cl = open(os.path.join(B, 'caselaw.tsv'), 'w', encoding='utf-8', newline='\n')
    cl.write('\t'.join(['published', 'number', 'year', 'chamber', 'path']) + '\n')
    ot = open(os.path.join(B, 'acts.txt'), 'w', encoding='utf-8', newline='\n')
    n = {'commits': 0, 'diavgeia': 0, 'caselaw': 0, 'other': 0}
    buf = b''

    def handle(rec):
        if not rec.strip():
            return
        parts = rec.decode('utf-8', 'replace').split('\x1f', 4)
        if len(parts) < 5:
            return
        h, an, ae, ad, body = parts
        lines = body.split('\n')
        tr = {}
        for l in lines[1:]:
            m = TR.match(l)
            if m:
                tr.setdefault(m.group(1), m.group(2))
        n['commits'] += 1
        kind = tr.get('Kind', '')
        if kind == 'decision-record':
            f = tr.get('Files', '').split(', ')[0]
            seg = f.split('/')
            ts = TS.search(tr.get('In-force-basis', ''))
            row = [ad, '/'.join(seg[:2]), an.split(', ΑΔΑ')[0], tr.get('Decision-type', ''), tr.get('Enacted', ''), tr.get('Published', ''),
                   ts.group(1) if ts else '', lines[0].strip()]
            dv.write('\t'.join(x.replace('\t', ' ') for x in row) + '\n'); n['diavgeia'] += 1
        elif kind == 'caselaw':
            m = AP_SUBJ.match(lines[0].strip())
            f = tr.get('Files', '').split(', ')[0]
            cl.write('\t'.join([ad, m.group(1) if m else '', m.group(2) if m else '', (m.group(3) or '') if m else '', '/'.join(f.split('/')[:-1])]) + '\n')
            n['caselaw'] += 1
        else:
            ot.write(f'=== {h}\n{an} <{ae}>\n{ad}\n{body.rstrip()}\n\n'); n['other'] += 1

    for chunk in iter(lambda: lg.stdout.read(1 << 20), b''):
        buf += chunk
        *recs, buf = buf.split(b'\x1e')
        for r in recs:
            handle(r)
    handle(buf)
    lg.wait()
    dv.close(); cl.close(); ot.close()
    print('history', n, flush=True)

    # ---------------------------------------------------------------- 2. the Constitution, every version
    # the commits that changed an article (not the README), oldest first
    V = [tuple(l.split()) for l in git('log', ref, '--reverse', '--format=%H %ad', '--date=short', '--', 'syntagma/art-*.md').decode().split('\n') if l.strip()]
    items, which = [], []
    for h, d in V:
        for path, oid in tree(h, 'syntagma'):
            if re.search(r'/art-[0-9a-z-]+\.md$', path):
                items.append((oid, path)); which.append(h)
    fetch_missing([o for o, _ in items])
    syn = {}
    for (path, data), h in zip(read_blobs(items), which):
        syn.setdefault(h, {})[path] = data.decode('utf-8')
    meta = {h: d for h, d in V}
    json.dump({'versions': [[h, meta[h]] for h in syn], 'text': syn}, open(os.path.join(B, 'syntagma.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('syntagma versions', len(syn), flush=True)

    # ---------------------------------------------------------------- 3. laws held as enacted: titles and pages
    items = [(oid, path) for path, oid in tree(ref, 'nomos') if path.endswith('/text-layer.txt') or path.endswith('/source.json')]
    fetch_missing([o for o, _ in items])
    laws = {}
    HEAD_RX = re.compile(r'ΝΟΜΟΣ\s+ΥΠ[’\'΄`]?\s*ΑΡΙΘ[^\s\d]*\.?\s*(\d+)\.?\s*\n(.*?)\n\s*(?:Ο|O)?\s*ΠΡΟΕΔΡΟΣ', re.S)
    for path, data in read_blobs(items):
        folder = path.rsplit('/', 1)[0]
        L = laws.setdefault(folder, {'folder': folder})
        if path.endswith('source.json'):
            j = json.loads(data)
            L.update({'pages': j.get('pages'), 'published': j.get('published'), 'in_force': j.get('in_force'), 'number': j.get('number'), 'year': j.get('year')})
        else:
            t = data.decode('utf-8', 'replace')
            head = t[:5000].replace('NOMOΣ', 'ΝΟΜΟΣ').replace('NΟΜΟΣ', 'ΝΟΜΟΣ')
            m = HEAD_RX.search(head)
            if m:
                L['title'] = re.sub(r'\s+', ' ', re.sub(r'[−‐-]\s*\n\s*', '', m.group(2))).strip()
            L['chars'] = len(t)
    with open(os.path.join(B, 'laws.jsonl'), 'w', encoding='utf-8', newline='\n') as out:
        for L in laws.values():
            out.write(json.dumps(L, ensure_ascii=False) + '\n')
    print('laws as enacted', len(laws), 'with a title from the text', sum(1 for L in laws.values() if L.get('title')), flush=True)

    # ---------------------------------------------------------------- 4. tables
    TABLES = ['data/acts.json', 'data/versions.json', 'data/laws.csv', 'data/commits.csv', 'registry/data/acts.json']
    oids = []
    for t in TABLES:
        oids.append(git('rev-parse', f'{ref}:{t}').decode().strip())
    fetch_missing(oids)
    for t, (path, data) in zip(TABLES, read_blobs(list(zip(oids, TABLES)))):
        dst = os.path.join(B, 'repo', t.replace('/', '__'))
        open(dst, 'wb').write(data)
    print('tables', len(TABLES), flush=True)

    # ---------------------------------------------------------------- 5. Areios Pagos decision texts
    items = [(oid, path) for path, oid in tree(ref, 'caselaw') if path.endswith('/decision.html')]
    fetch_missing([o for o, _ in items])
    MON = ['ιανουαριου', 'φεβρουαριου', 'μαρτιου', 'απριλιου', 'μαιου', 'ιουνιου', 'ιουλιου', 'αυγουστου', 'σεπτεμβριου', 'οκτωβριου', 'νοεμβριου', 'δεκεμβριου']
    DATE = r'(\d{1,2})(?:η|ησ)?\s+(' + '|'.join(MON) + r')\s+(?:του\s+)?(\d{4})'
    NUMD = r'(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2,4})'

    def date_after(low, pat):
        for rx in (DATE, NUMD):
            m = re.search('(?:' + pat + r')[^.]{0,260}?' + rx, low)
            if m:
                d, mo, y = m.group(m.lastindex - 2), m.group(m.lastindex - 1), m.group(m.lastindex)
                mo = MON.index(mo) + 1 if not mo.isdigit() else int(mo)
                y = int(y); y = y + 2000 if y < 100 else y
                if 1 <= mo <= 12 and 1 <= int(d) <= 31 and 1990 <= y <= 2030:
                    return f'{y:04d}-{mo:02d}-{int(d):02d}'
        return ''

    k = 0
    with open(os.path.join(B, 'ap-text.tsv'), 'w', encoding='utf-8', newline='\n') as out:
        out.write('\t'.join(['path', 'hearing', 'decided', 'published', 'words', 'operative', 'appealed']) + '\n')
        for path, data in read_blobs(items):
            raw = data.decode('cp1253', 'replace')
            txt = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
            low = re.sub(r'\s+', ' ', fold(txt))
            i = low.rfind('για τουσ λογουσ αυτουσ')
            op = low[i + 22:i + 422] if i >= 0 else ''
            j = low.find('για αναιρεση')
            app = low[j:j + 260] if j >= 0 else ''
            out.write('\t'.join([path.rsplit('/', 1)[0], date_after(low, r'συνεδριασε|συνηλθε|συνεδριασαν'), date_after(low, r'κριθηκε|αποφασισθηκε|αποφασιστηκε'),
                                 date_after(low, r'δημοσιευθηκε|δημοσιευτηκε'), str(len(low.split())), op.replace('\t', ' '), app.replace('\t', ' ')]) + '\n')
            k += 1
    print('decision texts', k, flush=True)

# ---------------------------------------------------------------- 6. prep + build
env = dict(os.environ, HEAD_SHA=sha)
subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, 'prep.py'), B], check=True, env=env)
subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, 'build.py'), os.path.join(B, 'data.json'), os.path.abspath(a.out)], check=True)
