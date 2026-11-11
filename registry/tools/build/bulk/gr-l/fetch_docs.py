"""GR-L: fetch the PDFs of selected decisions, read their text layer into the shared line format, delete the PDF.

    python -X utf8 -I fetch_docs.py <selected.jsonl> [...]      (rows: {ada, org, year, ...})
    python -X utf8 -I fetch_docs.py --queue                      (every <SRC>/diavgeia/selected/<org>.jsonl, in the
                                                                  harvest's priority order; loops until all done)

Source: https://diavgeia.gov.gr/opendata/decisions/<ADA>/document (the official API; /doc/ is robots-disallowed).
Out: <SRC>/diavgeia/text/<org>/<year>/<ADA-ascii>.json.gz = gr-a extract.read_pdf() shape + {ada, org, url, bytes,
fetched}; lines keep p, t, x0, y0, x1, y1, size, bold. The PDF is deleted after reading (url + sha256 kept).
Rate <= 1 request start/s across THREADS parallel downloads (the server often takes 20-60 s per document; the harvest
takes <= 0.5/s). Stop file <WORK>/STOP-FETCH. Disk floor 50.5 GB.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common_l import PDF, SEL, TEXT, WORK, ada_ascii  # noqa: E402
from common import curl, free_gb, now  # noqa: E402
import extract_l as extract  # noqa: E402  (gr-a reader + glyph-id repair)

INTERVAL = 1.0
THREADS = 6
_lock = threading.Lock()
_mupdf = threading.Lock()  # PyMuPDF is not thread-safe: one reader at a time
_last = [0.0]


def pace() -> None:
    with _lock:
        wait = INTERVAL - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def log(msg: str) -> None:
    with open(WORK / 'fetch.log', 'a', encoding='utf-8') as f:
        f.write(f'{now()} {msg}\n')


def text_path(org: str, year: int, ada: str) -> Path:
    return TEXT / org / str(year) / f'{ada_ascii(ada)}.json.gz'


def fetch_one(r: dict) -> str:
    ada, org, year = r['ada'], r['org'], int(r['year'])
    if ada_ascii(ada) is None:
        return 'bad-ada'
    out = text_path(org, year, ada)
    if out.exists():
        return 'have'
    url = f'https://diavgeia.gov.gr/opendata/decisions/{urllib.parse.quote(ada)}/document'
    pdf = PDF / f'{ada_ascii(ada)}.pdf'
    fails = 0
    while True:
        pace()
        st = curl(url, pdf, 0, timeout=300)
        if st == '200':
            break
        fails += 1
        log(f'HTTP {st} {ada} (fail {fails})')
        if st in ('403', '429'):
            log('FAILED: blocked; stopping (no evasion): wrote STOP-FETCH')
            (WORK / 'STOP-FETCH').write_text(f'{now()} HTTP {st} on {url}\n', encoding='utf-8')
            return 'blocked'
        if st in ('404', '410', '302', '301') or fails >= 4:
            # permanent (old 2010-2011 documents redirect to the retired static.old.diavgeia.gov.gr): keep a stub so
            # the act is held with the reason and the document is not asked for again
            stub = {'ada': ada, 'org': org, 'year': year, 'url': url, 'bytes': 0, 'fetched': now(),
                    'error': f'HTTP {st}' + (' (redirect to the retired static.old.diavgeia.gov.gr archive)'
                                             if st == '302' else ''), 'lines': [], 'page_info': []}
            if st in ('404', '410', '302', '301'):
                out.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(out, 'wt', encoding='utf-8') as f:
                    json.dump(stub, f, ensure_ascii=False)
            return f'http-{st}'
        time.sleep(20 * 2 ** fails)
    size = pdf.stat().st_size
    try:
        if pdf.read_bytes()[:5] != b'%PDF-':
            raise ValueError('not a PDF')
        with _mupdf:
            doc = extract.read_pdf(pdf, {'ada': ada, 'org': org, 'year': year, 'url': url, 'bytes': size,
                                         'fetched': now()})
    except Exception as e:  # noqa: BLE001
        doc = {'ada': ada, 'org': org, 'year': year, 'url': url, 'bytes': size, 'fetched': now(),
               'error': f'{type(e).__name__}: {e}'[:300], 'lines': [], 'page_info': []}
    for ln in doc['lines']:
        ln.pop('b', None)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.tmp')
    with open(tmp, 'wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as f:
            f.write(json.dumps(doc, ensure_ascii=False).encode('utf-8'))
    os.replace(tmp, out)
    pdf.unlink()
    return 'ok' if doc['lines'] else ('error' if doc.get('error') else 'no-text')


def guarded(r: dict) -> str:
    if (WORK / 'STOP-FETCH').exists():
        return 'stopped'
    while free_gb() < 50.5:
        log('disk below 50.5 GB, waiting')
        time.sleep(300)
    return fetch_one(r)


def run(rows: list[dict]) -> dict:
    PDF.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(THREADS) as ex:
        for st in ex.map(guarded, rows):
            counts[st] = counts.get(st, 0) + 1
    if counts.get('stopped'):
        log('stop file')
        sys.exit(0)
    return counts


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]


def queue() -> None:
    import harvest2
    log(f'queue start pid {os.getpid()}')
    while True:
        order = [o['uid'] for o in harvest2.ordered_orgs()]
        did = 0
        for uid in order:
            p = SEL / f'{uid}.jsonl'
            if not p.exists():
                continue
            rows = [r for r in load(p) if not text_path(r['org'], int(r['year']), r['ada']).exists()]
            if rows:
                c = run(rows)
                did += sum(c.values())
                log(f'org {uid}: {c}')
        if not did:
            if all((Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-l') / 'harvest.log').read_text(
                    encoding='utf-8').count(f'worker {k}/3 done') for k in range(3)):
                log('queue done: every selected document read')
                return
            time.sleep(600)


def main(argv: list[str]) -> None:
    if '--queue' in argv:
        queue()
        return
    rows = [r for a in argv for r in load(Path(a))]
    print(run(rows))


if __name__ == '__main__':
    main(sys.argv[1:])
