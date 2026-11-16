"""Fetch Greek Government Gazette (ΦΕΚ) issues for the Greece git-for-law corpus.

The National Printing Office (Εθνικό Τυπογραφείο) serves every ΦΕΚ issue as a PDF with a real text layer from its
blob store, directly and without a bot wall:

    https://ia37rg02wpsa01.blob.core.windows.net/fek/<series>/<YYYY>/<YYYY><series><NNNNN>.pdf

where series 01 is issue Α΄ and NNNNN is the issue number, zero-padded to 5.

Everything is cached under .cache/ by the sha256 of the URL, fetched with curl (TLS through Python fails on this
machine), at most 3 requests a second, and logged to .cache/requests.jsonl. Resumable: cached URLs are never fetched
again.

    python -X utf8 scripts/greece-law/fetch.py                 # every issue in ISSUES below
    python -X utf8 scripts/greece-law/fetch.py 2019:187 1986:23  # extra issues (series Α΄)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / '.cache'
UA = 'lexifina-watch/1.0 (+https://lexifina.com/watch; corpus@lexifina.com)'
BLOB = 'https://ia37rg02wpsa01.blob.core.windows.net/fek'
MIN_INTERVAL = 1 / 3  # at most 3 requests a second to the Gazette host

# (year, issue number) in series Α΄. The issue numbers were checked against each PDF's own masthead (see parse.py
# and PROGRESS.md).
ISSUES = [
    (1975, 111),   # Σύνταγμα 1975 (issue number recalled): a page-image scan with no text layer, so not used (no OCR)
    (1986, 23),    # 1986 revision (issue number recalled): a page-image scan with no text layer, so not used
    (2001, 84),    # Ψήφισμα της 6ης Απριλίου 2001 (revision), masthead: Αρ. Φύλλου 84, 17 Απριλίου 2001
    (2001, 85),    # Σύνταγμα, republished whole, masthead: Αρ. Φύλλου 85, 18 Απριλίου 2001
    (2008, 102),   # Ψήφισμα της 27ης Μαΐου 2008 (revision), masthead: Αρ. Φύλλου 102, 2 Ιουνίου 2008
    (2008, 120),   # Σύνταγμα, republished whole, masthead: Αρ. Φύλλου 120, 27 Ιουνίου 2008
    (2019, 187),   # Ψήφισμα της 25ης Νοεμβρίου 2019 (revision), masthead: Αρ. Φύλλου 187, 28 Νοεμβρίου 2019
    (2019, 211),   # Σύνταγμα, republished whole, masthead: Αρ. Φύλλου 211, 24 Δεκεμβρίου 2019
]

_last = 0.0


def fek_url(year: int, num: int, series: str = '01') -> str:
    return f'{BLOB}/{series}/{year}/{year}{series}{num:05d}.pdf'


def cache_path(url: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode('utf-8')).hexdigest() + '.pdf')


def fetch(url: str) -> Path | None:
    global _last
    p = cache_path(url)
    if p.exists() and p.stat().st_size > 0:
        return p
    CACHE.mkdir(exist_ok=True)
    wait = MIN_INTERVAL - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    tmp = p.with_suffix('.part')
    r = subprocess.run(['curl', '-sS', '--compressed', '-L', '-A', UA, '-o', str(tmp), '-w', '%{http_code}', url],
                       capture_output=True, text=True)
    status = r.stdout.strip()
    size = tmp.stat().st_size if tmp.exists() else 0
    with open(CACHE / 'requests.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'url': url,
                            'status': status, 'bytes': size}) + '\n')
    if status == '200' and size > 0:
        tmp.replace(p)
        return p
    if tmp.exists():
        tmp.unlink()
    print(f'  {status} {url} {r.stderr.strip()}', file=sys.stderr)
    return None


def main(argv: list[str]) -> None:
    issues = list(ISSUES)
    for a in argv:
        y, n = a.split(':')
        issues.append((int(y), int(n)))
    for y, n in issues:
        url = fek_url(y, n)
        p = fetch(url)
        print(f'{y} Α΄ {n}: {"ok " + str(p.stat().st_size) if p else "FAILED"}')


if __name__ == '__main__':
    main(sys.argv[1:])
