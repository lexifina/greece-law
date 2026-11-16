"""GR-A task 2: fetch ΦΕΚ PDFs and turn text-layer issues into text/<series>/<year>/<id>.json.gz. Hidden, detached,
resumable. Two modes (coordinator 11-11: decoupled so the host budget is used):

    python -X utf8 -I fetch_job.py --mode download [--series 01] [--host blob|api] [--from 2026] [--to 1833]
    python -X utf8 -I fetch_job.py --mode extract  [--series 01]          (run ~8 of these per series)

download: walks <SRC>/index/<series>/<year>.json newest year first and downloads each issue not yet done to
  pdf/<series>/<year>/<id>.pdf (id = YYYYSSNNNNN) with a sidecar <id>.row.json (the index row); blob <= 2 req/s,
  api <= 1.4 req/s (403 x3 -> stop). Waits while PDFs waiting for extraction exceed WAIT_CAP_GB (3), while C: free
  < MIN_FREE_GB (50.5; file <WORK>/MIN_FREE_GB overrides), and in years before 2000 (scans) while kept scans exceed
  SCANNED_CAP_GB (2). A 404 writes meta status "missing".
extract: claims a waiting PDF (<id>.pdf.lock, O_EXCL; stale after 1 h), reads it (extract.read_pdf), writes
  meta/<series>/<year>/<id>.json {id, series, year, number, search_ID, issue_date, publication_date, label, url,
  api_url, blob_url, status, sha256, bytes, pages, fetched, reader, text_layer: all|partial|none, no_text_pages,
  legacy_font_pages, ocr_needed, ocr_done, pdf_kept, pdf_fate} and, unless no page has text, the text file.
  Text-layer issues: PDF deleted (url + sha256 kept; the official API re-serves every issue; archive_files.py skips
  files < 3 days old). Partial/scanned: PDF kept for GR-OCR while kept scans <= 2 GB, else deleted (OCR fetches on
  demand from url). A PDF in pdf/ WITH a meta file is a kept scan for GR-OCR; WITHOUT one it waits for extraction.
Files per series SS: log <WORK>/fetch.log (01) or fetch-SS.log, state fetch-state[-SS].json, stop file STOP-FETCH
(01) or STOP-FETCH-SS (stops the downloader and the extractors of that series), downloader-done marker
<WORK>/DL-DONE-SS.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import SRC, WORK, api_url, free_gb, http_get as curl, now, pdf_url, write_json_atomic  # noqa: E402
import extract  # noqa: E402

SCANNED_CAP_GB = 2.0  # coordinator 11-11: at most ~2 GB of scans waiting for OCR
WAIT_CAP_GB = 3.0  # PDFs downloaded, waiting for extraction
STOP = WORK / 'STOP-FETCH'
LOG = WORK / 'fetch.log'
STATE = WORK / 'fetch-state.json'
HOST = 'blob'
INTERVAL = {'blob': 0.75, 'api': 1 / 1.4 + 0.02}  # blob 0.75: GR-OCR shares the host at 1 per 5 s (BLOB-SHARE)


def log(msg: str) -> None:
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{now()} [{os.getpid()}] {msg}\n')


def min_free() -> float:
    try:
        return float((WORK / 'MIN_FREE_GB').read_text().strip())
    except (OSError, ValueError):
        return 50.5


def keep_scanned(series: str = '01') -> bool:
    """File <WORK>/NO-KEEP-SCANNED (all series) or NO-KEEP-SCANNED-<series>: record scanned issues in meta and delete
    them at once (OCR fetches on demand from url)."""
    return not ((WORK / 'NO-KEEP-SCANNED').exists() or (WORK / f'NO-KEEP-SCANNED-{series}').exists())


def pdf_sizes(series: str) -> tuple[float, float, list[Path]]:
    """(GB of kept scans, GB of PDFs waiting for extraction, waiting paths newest first)."""
    root = SRC / 'pdf' / series
    kept = wait = 0
    waiting = []
    if root.exists():
        for yd in root.iterdir():
            if not yd.is_dir():
                continue
            for e in os.scandir(yd):
                if not e.name.endswith('.pdf'):
                    continue
                try:
                    size = e.stat().st_size
                except OSError:
                    continue
                if (SRC / 'meta' / series / yd.name / f'{e.name[:-4]}.json').exists():
                    kept += size
                else:
                    wait += size
                    waiting.append(Path(e.path))
    waiting.sort(key=lambda p: p.name, reverse=True)
    return kept / 1e9, wait / 1e9, waiting


def wait_ok(series: str, scanned_era: bool) -> bool:
    """Block while disk is short or a cap is reached. False if the stop file appears."""
    said = None
    while True:
        if STOP.exists():
            return False
        f = free_gb()
        kept, wait, _ = pdf_sizes(series)
        why = None
        if f < min_free():
            why = f'C: free {f:.2f} GB < {min_free()}'
        elif wait > WAIT_CAP_GB:
            why = f'PDFs waiting for extraction {wait:.2f} GB > {WAIT_CAP_GB}'
        elif scanned_era and keep_scanned(series) and kept > SCANNED_CAP_GB:
            why = f'kept scans {kept:.2f} GB > {SCANNED_CAP_GB} GB (waiting for GR-OCR)'
        if not why:
            if said:
                log(f'resume ({said})')
            return True
        if why != said:
            log(f'PAUSE: {why}')
            said = why
        write_json_atomic(STATE, {'state': 'paused', 'why': why, 'at': now()})
        time.sleep(30)


def base_meta(series: str, year: int, row: dict, url: str) -> dict:
    num = int(row['search_DocumentNumber'])
    return {'id': f'{year}{series}{num:05d}', 'series': series, 'year': year, 'number': num,
            'search_ID': row['search_ID'], 'issue_date': row['search_IssueDate'],
            'publication_date': row['search_PublicationDate'], 'index_pages': row.get('search_Pages'),
            'label': row.get('search_PrimaryLabel'), 'url': url, 'api_url': api_url(series, year, num),
            'blob_url': pdf_url(series, year, num)}


def download_one(series: str, year: int, row: dict, bad: list) -> str:
    num = int(row['search_DocumentNumber'])
    iid = f'{year}{series}{num:05d}'
    mpath = SRC / 'meta' / series / str(year) / f'{iid}.json'
    pdf = SRC / 'pdf' / series / str(year) / f'{iid}.pdf'
    if mpath.exists() or pdf.exists():
        return 'skip'
    url = api_url(series, year, num) if HOST == 'api' else pdf_url(series, year, num)
    meta = base_meta(series, year, row, url)
    side = pdf.with_name(f'{iid}.row.json')
    write_json_atomic(side, meta)
    for attempt in range(6):
        st = curl(url, pdf, INTERVAL[HOST])
        if st == '200':
            with open(pdf, 'rb') as fh:
                head = fh.read(5)
            if head != b'%PDF-':
                pdf.unlink()
                st = 'not-pdf'
        if st == '200':
            return 'got'
        if st == '404':
            write_json_atomic(mpath, {**meta, 'status': f'missing ({HOST} 404)', 'fetched': now()}, indent=1)
            side.unlink(missing_ok=True)
            return 'missing'
        if st == '403' and HOST == 'api' and attempt >= 2:
            raise SystemExit(f'{iid}: API host keeps answering 403 (rate limit); stopped')
        bad.append(st)
        log(f'{iid}: HTTP {st}, backoff {attempt}')
        time.sleep([10, 30, 90, 300, 900, 1800][attempt])
    raise SystemExit(f'{iid}: host keeps failing ({bad[-6:]}); stopped')


def mtime_iso(p: Path) -> str:
    return dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def extract_one(series: str, pdf: Path) -> str | None:
    iid = pdf.name[:-4]
    year = int(iid[:4])
    lock = pdf.with_name(pdf.name + '.lock')
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > 3600:
            lock.unlink()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except OSError:
        return None
    try:
        mpath = SRC / 'meta' / series / str(year) / f'{iid}.json'
        if mpath.exists() or not pdf.exists():
            return None
        side = pdf.with_name(f'{iid}.row.json')
        if side.exists():
            meta = json.loads(side.read_text(encoding='utf-8'))
        else:  # left by an earlier run: rebuild from the index row
            num = int(iid[6:])
            rows = json.loads((SRC / 'index' / series / f'{year}.json').read_text(encoding='utf-8'))['rows']
            row = next(r for r in rows if int(r['search_DocumentNumber']) == num)
            meta = base_meta(series, year, row, pdf_url(series, year, num) if series == '01' else
                             api_url(series, year, num))
        try:
            doc = extract.read_pdf(pdf, {'id': iid, 'series': series, 'year': year, 'number': meta['number']})
        except Exception as e:  # a damaged PDF: keep it, flag it
            write_json_atomic(mpath, {**meta, 'status': f'unreadable: {type(e).__name__}: {e}',
                                      'fetched': mtime_iso(pdf), 'bytes': pdf.stat().st_size, 'pdf_kept': True},
                              indent=1)
            return 'unreadable'
        no_text = [p['page'] for p in doc['page_info'] if not p['text']]
        layer = 'none' if len(no_text) == doc['pages'] else ('partial' if no_text else 'all')
        meta.update({'status': 'ok', 'sha256': doc['sha256'], 'bytes': pdf.stat().st_size, 'pages': doc['pages'],
                     'fetched': mtime_iso(pdf), 'reader': doc['reader'], 'text_layer': layer,
                     'no_text_pages': no_text,
                     'legacy_font_pages': [p['page'] for p in doc['page_info'] if p['legacy']],
                     'ocr_needed': layer != 'all', 'ocr_done': False if layer != 'all' else None})
        if layer != 'none':
            write_json_atomic(SRC / 'text' / series / str(year) / f'{iid}.json.gz', doc, gz=True)
        if layer == 'all':
            pdf.unlink()
            meta.update({'pdf_kept': False, 'pdf_fate': 'deleted after extraction; url + sha256 kept (the official '
                                                        'API re-serves every issue; archive_files.py skips files < 3 '
                                                        'days old)'})
        elif keep_scanned(series) and pdf_sizes(series)[0] <= SCANNED_CAP_GB:
            meta.update({'pdf_kept': True, 'pdf_fate': 'kept for GR-OCR'})
        else:
            pdf.unlink()
            meta.update({'pdf_kept': False, 'pdf_fate': 'scanned; deleted at once (scan cap reached or '
                                                        'NO-KEEP-SCANNED): GR-OCR fetches it on demand from url'})
        write_json_atomic(mpath, meta, indent=1)
        side.unlink(missing_ok=True)
        return layer
    finally:
        lock.unlink(missing_ok=True)


def run_download(series: str, y_from: int, y_to: int) -> None:
    bad: list = []
    (WORK / f'DL-DONE-{series}').unlink(missing_ok=True)
    for year in range(y_from, y_to - 1, -1):
        idx = SRC / 'index' / series / f'{year}.json'
        while not idx.exists():
            if STOP.exists():
                log('stop file')
                return
            time.sleep(60)
        rows = json.loads(idx.read_text(encoding='utf-8'))['rows']
        seen = set()
        counts: dict[str, int] = {}
        for k, row in enumerate(rows):
            num = int(row['search_DocumentNumber'])
            if num in seen:
                continue
            seen.add(num)
            if STOP.exists() or (k % 10 == 0 and not wait_ok(series, year < 2000)):
                log('stop file')
                write_json_atomic(STATE, {'state': 'stopped', 'at': now()})
                return
            r = download_one(series, year, row, bad)
            counts[r] = counts.get(r, 0) + 1
            if r != 'skip':
                write_json_atomic(STATE, {'state': 'running', 'at': now(), 'year': year, 'last': f'{year}/{num}',
                                          'pid': os.getpid()})
        log(f'download {series}/{year} done: {counts}')
    (WORK / f'DL-DONE-{series}').write_text(now() + '\n')
    write_json_atomic(STATE, {'state': 'done', 'at': now()})
    log('download DONE')


def run_extract(series: str) -> None:
    n = 0
    while not STOP.exists():
        waiting = pdf_sizes(series)[2]
        did = False
        for pdf in waiting[:40]:
            if STOP.exists():
                break
            if extract_one(series, pdf):
                did = True
                n += 1
        if not did:
            if (WORK / f'DL-DONE-{series}').exists() and not waiting:
                log(f'extract: nothing left ({n} done)')
                return
            time.sleep(5)
    log(f'extract: stop file ({n} done)')


def main(argv: list[str]) -> None:
    global STOP, LOG, STATE, HOST
    series, y_from, y_to, mode = '01', 2026, 1833, 'download'
    for i, a in enumerate(argv):
        if a == '--series':
            series = argv[i + 1]
        elif a == '--host':
            HOST = argv[i + 1]
            assert HOST in INTERVAL
        elif a == '--from':
            y_from = int(argv[i + 1])
        elif a == '--to':
            y_to = int(argv[i + 1])
        elif a == '--mode':
            mode = argv[i + 1]
    if series != '01':
        STOP, LOG, STATE = (WORK / f'STOP-FETCH-{series}', WORK / f'fetch-{series}.log',
                            WORK / f'fetch-state-{series}.json')
    log(f'start {mode} series {series} host {HOST} {y_from}->{y_to}')
    if mode == 'download':
        run_download(series, y_from, y_to)
    else:
        run_extract(series)


if __name__ == '__main__':
    main(sys.argv[1:])
