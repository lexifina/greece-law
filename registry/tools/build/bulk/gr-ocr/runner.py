"""GR-OCR runner: OCR every ΦΕΚ issue GR-A marked ocr_needed. Hidden, detached, resumable, polling.

    python -X utf8 -I runner.py [--workers 14]

Queue (rebuilt every POLL seconds from meta/<series>/<year>/<id>.json, only files whose mtime changed are re-read):
  issues with ocr_needed and not ocr_done (and not ocr_held), series 01 (Α΄) first, then 04 (Δ΄), then 02 (Β΄);
  within a series newest year first, and issues whose PDF GR-A kept on disk (pdf/<series>/<year>/<id>.pdf) before
  those it deleted (fetched again on demand from meta url into <SRC>/ocr-tmp/, at most one request per
  FETCH_INTERVAL s (file <WORK>/FETCH-INTERVAL overrides; default 5 s, inside GR-A's host budget), logged to
  <SRC>/requests-<host>.jsonl, sha256 checked against meta).
Per issue: pages OCRed in parallel by a pool of threads (each runs one BelowNormal tesseract process); page results
are cached in <WORK>/work/<id>/p<NNNN>.json so a restart resumes inside a big issue. When all pages are done:
  text/<series>/<year>/<id>.json.gz (GR-A's format: page_info + lines {p,t,x0,y0,x1,y1,conf}; for a partial text
  layer the text-layer pages are kept from GR-A's file and only the image pages are OCRed);
  then meta: re-read, set only ocr_done, ocr_* fields and pdf_fate, write atomically; then delete the PDF.
Recipe per year: recipe() below (PROGRESS.md has the benchmark).
QA: every QA_EVERY issues, QA_PAGES random OCRed pages are exported to <WORK>/qa/batch-NNNN/ (page crop PNG + the
OCR text of that crop region) for hand spot-checks; per-year mean confidence is kept in <WORK>/years.json.
Stop file: <WORK>/STOP-OCR (finishes the pages in flight, then exits). Log <WORK>/ocr.log, state <WORK>/ocr-state.json.
Pauses while C: free < 50.5 GB (file <WORK>/MIN_FREE_GB overrides).
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import random
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fitz  # noqa: E402
import cv2  # noqa: E402
import ocr  # noqa: E402
import pageimg  # noqa: E402

SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-ocr')
STOP = WORK / 'STOP-OCR'
LOG = WORK / 'ocr.log'
STATE = WORK / 'ocr-state.json'
YEARS = WORK / 'years.json'
TMP = SRC / 'ocr-tmp'
SERIES = ['01', '04', '02']
POLL = 300
QA_EVERY = 1000
QA_PAGES = 20
ISSUES_IN_FLIGHT = 4
_stats_lock = threading.Lock()
_fetch_lock = threading.Lock()
UA = 'lexifina-watch/1.0 (+https://lexifina.com/watch; corpus@lexifina.com)'
TESS_VER = ocr.tess_version()
_loglock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def log(msg: str) -> None:
    with _loglock, open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{now()} [{os.getpid()}] {msg}\n')


def write_atomic(path: Path, obj, gz: bool = False, indent=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.ocr{os.getpid()}.tmp')
    data = json.dumps(obj, ensure_ascii=False, indent=indent).encode('utf-8')
    if gz:
        with open(tmp, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as f:
            f.write(data)
    else:
        tmp.write_bytes(data + b'\n')
    for i in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # a reader has it open (Windows)
            time.sleep(0.5 + i * 0.5)
    os.replace(tmp, path)


def min_free() -> float:
    try:
        return float((WORK / 'MIN_FREE_GB').read_text().strip())
    except (OSError, ValueError):
        return 50.5


def fetch_interval() -> float:
    try:
        return float((WORK / 'FETCH-INTERVAL').read_text().strip())
    except (OSError, ValueError):
        return 5.0


def recipe(year: int) -> dict:
    """OCR settings by era (benchmark in PROGRESS.md, 2026-11-11)."""
    if year >= 1982:  # monotonic reform: ell, columns psm 4; fold the models' stray polytonic marks on monotonic pages
        return {'model': 'ell', 'psm': 4, 'up': 1.0, 'thick': 0, 'fold': 'auto', 'alt': 'ell+eng'}
    # polytonic katharevousa, thin/broken strokes in the old bitonal scans: grow the ink 2 px, psm 6 per column
    return {'model': 'ell', 'psm': 6, 'up': 1.0, 'thick': 2, 'fold': 'no', 'alt': 'ell+eng'}


def recipe_label(r: dict) -> str:
    fold = ', monotonic fold' if r['fold'] != 'no' else ''
    alt = f", {r['alt']} for weak/Latin pages" if r.get('alt') else ''
    up = f", x{r['up']} cubic" if r['up'] != 1.0 else ''
    thick = f", ink +{r['thick']} px" if r.get('thick') else ''
    return (f"OCR (tesseract {TESS_VER}, {r['model']} best, columns split at the gutter, psm {r['psm']}{up}{thick}"
            f"{fold}{alt})")


# ---------------------------------------------------------------- queue
_meta_cache: dict[str, tuple[float, dict | None]] = {}


def scan() -> list[tuple]:
    """[(priority key, meta path, compact meta + '_pages')] of issues with pages still to OCR."""
    out = []
    req = requests()
    for si, s in enumerate(SERIES):
        root = SRC / 'meta' / s
        if not root.exists():
            continue
        for yd in root.iterdir():
            if not yd.is_dir() or not yd.name.isdigit():
                continue
            for e in os.scandir(yd):
                if not e.name.endswith('.json'):
                    continue
                try:
                    mt = e.stat().st_mtime
                except OSError:
                    continue
                c = _meta_cache.get(e.path)
                if c is None or c[0] != mt:
                    try:
                        m = json.loads(Path(e.path).read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        continue
                    c = _meta_cache[e.path] = (mt, {k: m.get(k) for k in COMPACT})
                m = c[1]
                if not m.get('id') or m.get('ocr_held') or not m.get('pages'):
                    continue
                want = pages_wanted(m, req.get(m['id']))
                if not want:
                    continue
                pdf = SRC / 'pdf' / s / yd.name / f"{m['id']}.pdf"
                kept = pdf.exists()
                # kept PDFs first (frees GR-A's scan cap); then whole scanned issues and GR-A's OCR-REQUESTS
                # (coordinator: same priority as the 1990s scans); then image pages of other partial text layers;
                # newest year first inside each
                rank = 0 if kept else (1 if (m.get('text_layer') == 'none' or m['id'] in req) else 2)
                out.append(((si, rank, -int(m['year']), m['id']), Path(e.path), {**m, '_pages': want}))
    out.sort(key=lambda x: x[0])
    return out


COMPACT = ('id', 'series', 'year', 'number', 'pages', 'sha256', 'url', 'blob_url', 'text_layer', 'no_text_pages',
           'ocr_needed', 'ocr_done', 'ocr_held', 'ocr_pages_done')
_BD = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia')
# (file, page-number base): GR-A writes 0-based pages ('0-111' of 112), GR-B 1-based ('7' = the last of 8 pages)
REQUESTS = [(_BD / 'gr-a' / 'OCR-REQUESTS.tsv', 0), (_BD / 'gr-b' / 'OCR-REQUESTS.tsv', 1)]
_req_cache: list = [None, {}]


def requests() -> dict[str, set[int]]:
    """GR-A's and GR-B's OCR-REQUESTS.tsv (id, url, pages '0-111' / '3,5-7', reason, slugs) -> {id: 0-based pages}."""
    key = []
    for f, _ in REQUESTS:
        try:
            key.append(f.stat().st_mtime)
        except OSError:
            key.append(None)
    if _req_cache[0] == key:
        return _req_cache[1]
    out: dict[str, set[int]] = {}
    for f, base in REQUESTS:
        try:
            text = f.read_text(encoding='utf-8')
        except OSError:
            continue
        for i, line in enumerate(text.splitlines()):
            c = line.split('\t')
            if i == 0 or len(c) < 3 or not c[0].strip():
                continue
            pages = set()
            for part in c[2].split(','):
                part = part.strip()
                if '-' in part:
                    lo, hi = part.split('-', 1)
                    pages.update(range(int(lo) - base, int(hi) - base + 1))
                elif part.isdigit():
                    pages.add(int(part) - base)
            out.setdefault(c[0].strip(), set()).update(p for p in pages if p >= 0)
    _req_cache[0], _req_cache[1] = key, out
    return out


def pages_wanted(m: dict, req_pages: set[int] | None) -> list[int]:
    """0-based pages still to OCR: all pages of a scanned issue, no_text_pages of a partial one (when ocr_needed),
    plus GR-A's requested pages; minus ocr_pages_done."""
    want: set[int] = set()
    if m.get('ocr_needed') and not m.get('ocr_done'):
        want |= set(range(int(m['pages']))) if m.get('text_layer') == 'none' else set(m.get('no_text_pages') or [])
    if req_pages:
        want |= {p for p in req_pages if p < int(m['pages'])}
    return sorted(want - set(m.get('ocr_pages_done') or []))


# ---------------------------------------------------------------- fetch
_last_fetch = [0.0]


GRA = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-a')


def blob_busy() -> bool:
    """True while a GR-A blob downloader (fetch-state.json = Α΄, fetch-state-04.json = Δ΄) reports state running,
    updated in the last 10 min. fetch-state-02.json is Β΄ over api.et.gr, not the blob host.
    File <WORK>/BLOB-SHARE (written when GR-A/the coordinator lowers GR-A's own rate to leave GR-OCR a share):
    fetch anyway, at FETCH-INTERVAL."""
    if (WORK / 'BLOB-SHARE').exists():
        return False
    for name in ('fetch-state.json', 'fetch-state-04.json'):
        try:
            st = json.loads((GRA / name).read_text(encoding='utf-8'))
            at = dt.datetime.strptime(st['at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        except (OSError, ValueError, KeyError):
            continue
        if st.get('state') == 'running' and (dt.datetime.now(dt.timezone.utc) - at).total_seconds() < 600:
            return True
    return False


def fetch(m: dict) -> Path | None:
    with _fetch_lock:
        return _fetch(m)


def _fetch(m: dict) -> Path | None:
    import subprocess
    from urllib.parse import urlparse
    url = m.get('blob_url') or m.get('url')  # the blob store serves every series (api.et.gr is GR-B's budget)
    if not url:
        return None
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / f"{m['id']}.pdf"
    if out.exists():
        return out
    if blob_busy():
        return None  # GR-A's downloader is using the blob host's whole 2 req/s budget: try again later
    wait = fetch_interval() - (time.monotonic() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    _last_fetch[0] = time.monotonic()
    part = out.with_name(out.name + '.part')
    r = subprocess.run(['curl', '-sS', '-L', '--max-time', '300', '-A', UA, '-o', str(part), '-w', '%{http_code}',
                        url], capture_output=True, text=True, creationflags=ocr.NOWIN)
    st = (r.stdout.strip() or '000')[-3:]
    size = part.stat().st_size if part.exists() else 0
    digest = hashlib.sha256(part.read_bytes()).hexdigest() if size else None
    with open(SRC / f'requests-{urlparse(url).hostname}.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': now(), 'url': url, 'status': st, 'bytes': size, 'sha256': digest,
                            'by': 'GR-OCR'}) + '\n')
    if st == '200' and size and (not m.get('sha256') or digest == m['sha256']):
        os.replace(part, out)
        return out
    part.unlink(missing_ok=True)
    log(f"{m['id']}: fetch {url} -> HTTP {st}, sha256 {'ok' if digest == m.get('sha256') else 'MISMATCH'}")
    return None


# ---------------------------------------------------------------- OCR
_tls = threading.local()


def ocr_one(pdf: Path, pno: int, rec: dict, cache: Path) -> dict:
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except ValueError:
            pass
    with ocr.FITZ_LOCK:
        doc = fitz.open(pdf)
    try:
        lines, info = ocr.ocr_page(doc, pno, model=rec['model'], psm=rec['psm'], up=rec['up'], fold=rec['fold'],
                                   thick=rec.get('thick', 0), alt=rec.get('alt'))
    finally:
        with ocr.FITZ_LOCK:
            doc.close()
    res = {'lines': lines, 'info': info}
    write_atomic(cache, res)
    return res


def load_text(m: dict) -> dict | None:
    p = SRC / 'text' / m['series'] / str(m['year']) / f"{m['id']}.json.gz"
    if not p.exists():
        return None
    with gzip.open(p, 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def qa_export(batch: int, picks: list[tuple]) -> None:
    """picks: [(meta, pdf path, page, lines)] -> qa/batch-NNNN/<id>-p<k>.png (top of the first body column) + .txt"""
    d = WORK / 'qa' / f'batch-{batch:04d}'
    d.mkdir(parents=True, exist_ok=True)
    for m, pdf, pno, lines in picks:
        try:
            with ocr.FITZ_LOCK:
                doc = fitz.open(pdf)
                a, sc = pageimg.page_gray(doc, pno)
                doc.close()
            boxes = pageimg.column_boxes(a, sc)
            body = max(boxes, key=lambda b: (b[3] - b[1]) * (b[2] - b[0]))
            x0, y0, x1, y1 = body
            y1 = min(y1, y0 + 520)
            cv2.imwrite(str(d / f"{m['id']}-p{pno}.png"), a[y0:y1, x0:x1])
            sel = [L['t'] for L in lines if L['y0'] * sc >= y0 - 5 and L['y1'] * sc <= y1 + 5
                   and L['x0'] * sc >= x0 - 5 and L['x1'] * sc <= x1 + 5]
            (d / f"{m['id']}-p{pno}.txt").write_text('\n'.join(sel), encoding='utf-8')
        except Exception as e:  # QA export must never stop the run
            log(f'qa export {m["id"]} p{pno}: {e}')
    log(f'QA batch {batch}: {len(picks)} page(s) exported to {d}')


def process(m: dict, mpath: Path, pool: ThreadPoolExecutor, stats: dict) -> str:
    s, year, iid = m['series'], int(m['year']), m['id']
    kept = SRC / 'pdf' / s / str(year) / f'{iid}.pdf'
    if (kept.with_name(kept.name + '.lock')).exists():
        return 'locked'
    if not kept.exists() and blob_busy():
        return 'busy'
    pdf = kept if kept.exists() else fetch(m)
    if pdf is None:
        return 'nofetch'
    rec = recipe(year)
    if not m.get('_pages'):
        return 'nothing'
    with ocr.FITZ_LOCK:
        doc = fitz.open(pdf)
        npages = doc.page_count
        doc.close()
    if npages == 0:  # PyMuPDF reads no page: keep the issue out of the queue, record why, keep the PDF
        cur = json.loads(mpath.read_text(encoding='utf-8'))
        cur.update({'ocr_done': False, 'ocr_held': True, 'ocr_at': now(),
                    'ocr_status': 'not OCRed: PyMuPDF reads 0 pages in this PDF'})
        write_atomic(mpath, cur, indent=1)
        log(f'{iid}: PDF has 0 readable pages; held (ocr_held) for a manual look')
        return 'held'
    layer = m.get('text_layer')
    todo = [p for p in m['_pages'] if p < npages]
    whole = layer == 'none'  # a scanned issue: GR-OCR writes <id>.json.gz; else only <id>.ocr.json.gz
    wdir = WORK / 'work' / iid
    wdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    futs = {pool.submit(ocr_one, pdf, p, rec, wdir / f'p{p:04d}.json'): p for p in todo}
    res = {}
    for f in as_completed(futs):
        res[futs[f]] = f.result()
    if STOP.exists() and len(res) < len(todo):
        return 'stopped'
    label = recipe_label(rec)
    tdir = SRC / 'text' / s / str(year)
    out_path = tdir / (f'{iid}.json.gz' if whole else f'{iid}.ocr.json.gz')
    prev = None
    if out_path.exists():  # earlier OCR pages of this issue (e.g. a later GR-A request): keep the ones not redone
        with gzip.open(out_path, 'rb') as f:
            prev = json.loads(f.read().decode('utf-8'))
    infos = {p: {**res[p]['info'], 'text_source': label} for p in res}
    by_page = {p: res[p]['lines'] for p in res}
    if prev and str(prev.get('text_source', '')).startswith('OCR'):
        for pi in prev.get('page_info', []):
            if pi['page'] not in infos:
                infos[pi['page']] = pi
                by_page[pi['page']] = [L for L in prev['lines'] if L['p'] == pi['page']]
    confs = [res[p]['info']['mean_conf'] for p in res if res[p]['info'].get('mean_conf') is not None]
    mean_conf = round(sum(confs) / len(confs), 1) if confs else None
    doc_out = {'id': iid, 'series': s, 'year': year, 'number': m.get('number'), 'text_source': label,
               'reader': None, 'sha256': m.get('sha256'), 'pages': npages, 'ocr_pages': sorted(infos),
               'page_info': [infos[p] for p in sorted(infos)],
               'lines': [L for p in sorted(by_page) for L in by_page[p]],
               'ocr_engine': f'tesseract {TESS_VER}', 'ocr_recipe': rec,
               'note': 'Text read by OCR from the official scan; not proof-read. Check the official PDF.',
               'ocr_line_order': 'OCR lines of a page are stored in reading order (full-width bands top to bottom, '
                                 'left column then right column inside a band); line field col = 0 left, 1 right, '
                                 'null full width; page_info gutter = the column split x (pt)'}
    write_atomic(out_path, doc_out, gz=True)
    # meta: re-read right before writing, touch only ocr_* and pdf_fate
    cur = json.loads(mpath.read_text(encoding='utf-8'))
    done = sorted(set(cur.get('ocr_pages_done') or []) | set(res))
    need = set(range(npages)) if whole else set(cur.get('no_text_pages') or [])
    upd = {'ocr_at': now(), 'ocr_text_source': label, 'ocr_pages_done': done,
           'ocr_text_file': f'text/{s}/{year}/{out_path.name}',
           'ocr_mean_conf': mean_conf,
           'ocr_low_conf_pages': sorted(set(cur.get('ocr_low_conf_pages') or []) - set(res) |
                                        {p for p in res if (res[p]['info'].get('mean_conf') or 100) < 75}),
           'pdf_fate': 'deleted after OCR (GR-OCR); url + sha256 kept (the official API re-serves every issue)'}
    if cur.get('ocr_needed'):
        upd['ocr_done'] = need <= set(done)
    req = requests().get(iid)
    if req:
        upd['ocr_request_done'] = {p for p in req if p < npages} <= set(done)
    cur.update(upd)
    cur['pdf_kept'] = False
    write_atomic(mpath, cur, indent=1)
    if res and random.random() < QA_PAGES / QA_EVERY:  # ~20 random pages per 1000 issues, cut before the PDF goes
        p = random.choice(sorted(res))
        qa_export(stats.get('qa_batch', 0), [(m, pdf, p, res[p]['lines'])])
    try:
        pdf.unlink()
    except OSError as e:
        log(f'{iid}: could not delete {pdf}: {e}')
    shutil.rmtree(wdir, ignore_errors=True)
    # stats
    _stats_lock.acquire()
    ys = stats['years'].setdefault(f'{s}/{year}', {'issues': 0, 'pages': 0, 'conf_sum': 0.0, 'conf_n': 0})
    ys['issues'] += 1
    ys['pages'] += len(res)
    for c in confs:
        ys['conf_sum'] += c
        ys['conf_n'] += 1
    stats['issues'] += 1
    stats['pages'] += len(res)
    stats['recent'].append((time.time(), len(res)))
    _stats_lock.release()
    dt_s = time.time() - t0
    log(f'{iid}: {len(res)} pages OCRed ({"whole issue" if whole else "-> " + out_path.name}) in {dt_s:.0f} s (mean conf {mean_conf}), '
        f'{"kept PDF" if pdf == kept else "fetched"} deleted')
    return 'done'


def main(argv: list[str]) -> None:
    workers = 14
    if '--workers' in argv:
        workers = int(argv[argv.index('--workers') + 1])
    only = set(argv[argv.index('--only') + 1].split(',')) if '--only' in argv else None
    log(f'start runner pid {os.getpid()} workers {workers} tesseract {TESS_VER}')
    stats = {'issues': 0, 'pages': 0, 'recent': [], 'years': {}}
    if YEARS.exists():
        try:
            stats['years'] = json.loads(YEARS.read_text(encoding='utf-8'))
        except ValueError:
            pass
    try:
        qa_state = json.loads((WORK / 'qa-state.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        qa_state = {'batch': 0, 'since': 0}
    stats['qa_batch'] = qa_state['batch']
    pool = ThreadPoolExecutor(workers)
    issue_pool = ThreadPoolExecutor(ISSUES_IN_FLIGHT)
    idle_said = False
    failures: dict[str, int] = {}
    while not STOP.exists():
        low = shutil.disk_usage('C:\\').free / 1e9 < min_free()
        q = [x for x in scan() if failures.get(x[2]['id'], 0) < 3 and (only is None or x[2]['id'] in only)]
        if low:
            # short of disk: OCR only PDFs already on disk (each one done frees its PDF); no on-demand fetches
            q = [x for x in q if x[0][1] == 0]  # kept only
            if not q:
                log(f'PAUSE: C: free < {min_free()} GB and no kept PDF to OCR')
                time.sleep(120)
                continue
        if only is not None and not q:
            log('--only: done')
            break
        if not q:
            if not idle_said:
                log('idle: no scanned issue waiting; polling')
                idle_said = True
            write_atomic(STATE, {'state': 'idle', 'at': now(), 'pid': os.getpid(), 'issues': stats['issues'],
                                 'pages': stats['pages']})
            for _ in range(POLL // 5):
                if STOP.exists():
                    break
                time.sleep(5)
            continue
        idle_said = False
        # one pass over (a slice of) the queue, re-scanned afterwards so new kept PDFs jump ahead
        t_pass = time.time()
        did = 0
        # several issues in flight (their pages share the page pool), so small issues do not leave workers idle
        inflight: dict = {}
        it = iter(q)
        exhausted = False
        while True:
            while not exhausted and len(inflight) < ISSUES_IN_FLIGHT:
                if STOP.exists() or time.time() - t_pass > POLL:
                    exhausted = True
                    break
                nxt = next(it, None)
                if nxt is None:
                    exhausted = True
                    break
                key, mpath, m = nxt
                if key[1] >= 1 and shutil.disk_usage('C:\\').free / 1e9 < min_free():
                    exhausted = True  # no on-demand fetch while short of disk
                    break
                inflight[issue_pool.submit(process, m, mpath, pool, stats)] = m
            if not inflight:
                break
            fut = next(as_completed(list(inflight)))
            m = inflight.pop(fut)
            try:
                r = fut.result()
            except Exception as e:
                failures[m['id']] = failures.get(m['id'], 0) + 1
                import traceback
                tb = traceback.format_exception(e)
                tb = ''.join(tb).strip().splitlines()
                log(f"{m['id']}: ERROR {type(e).__name__}: {e} (attempt {failures[m['id']]}) at "
                    f"{' | '.join(x.strip() for x in tb[-6:-1])}")
                continue
            if r == 'nofetch':
                failures[m['id']] = failures.get(m['id'], 0) + 1
            if r != 'done':
                continue
            did += 1
            cut = time.time() - 600
            with _stats_lock:
                stats['recent'] = [x for x in stats['recent'] if x[0] > cut]
                ppm = sum(n for _, n in stats['recent']) / 10.0
                years_copy = json.loads(json.dumps(stats['years']))
            write_atomic(STATE, {'state': 'running', 'at': now(), 'pid': os.getpid(), 'last': m['id'],
                                 'issues': stats['issues'], 'pages': stats['pages'],
                                 'pages_per_min_10min': round(ppm, 1), 'queue': len(q)})
            write_atomic(YEARS, years_copy, indent=1)
            qa_state['since'] += 1
            if qa_state['since'] >= QA_EVERY:
                log(f"QA batch {qa_state['batch']} complete ({QA_EVERY} issues): spot-check {WORK / 'qa'}")
                qa_state['batch'] += 1
                qa_state['since'] = 0
            stats['qa_batch'] = qa_state['batch']
            write_atomic(WORK / 'qa-state.json', qa_state)
        if not did:  # nothing could be done this pass (host busy, fetch failures): wait before re-scanning
            write_atomic(STATE, {'state': 'waiting', 'at': now(), 'pid': os.getpid(), 'queue': len(q),
                                 'why': 'queued issues need an on-demand fetch while GR-A uses the blob host, '
                                        'or fetches failed'})
            for _ in range(12):
                if STOP.exists():
                    break
                time.sleep(5)
    log('stop file: exiting')
    issue_pool.shutdown(wait=True)
    pool.shutdown(wait=True)
    write_atomic(STATE, {'state': 'stopped', 'at': now(), 'issues': stats['issues'], 'pages': stats['pages']})


if __name__ == '__main__':
    main(sys.argv[1:])
