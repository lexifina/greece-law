"""Fetch the sources behind the single-law parts of the Greece corpus (corpus.d/30-nomoi.json).

For each law in LAWS (series Α΄ issue of the Government Gazette):
- the ΦΕΚ PDF from the National Printing Office's blob store (the same store fetch.py reads), through the shared
  client gitlaw_common/wayback.host_get: 2 threads and long timeouts, since the store is slow;
- the official search's (search.et.gr) record of the issue and its relation timeline (amended by / amends), from the
  search service the site itself calls. parse_laws.py uses the timeline only to list candidate amending laws; each
  candidate is read in its own ΦΕΚ before anything is concluded.

Cached under .cache/laws/ by the sha256 of the URL (and, for a POST, the request body), logged to
.cache/laws/requests.jsonl.

    python -X utf8 scripts/greece-law/fetch_laws.py [discover YEAR FROM TO]   # discover: list issues' titles
    python -X utf8 scripts/greece-law/fetch_laws.py gap YEAR N...              # issues for the amendment scan
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'gitlaw_common'))
import wayback  # noqa: E402

CACHE = HERE / '.cache' / 'laws'
BLOB = 'https://ia37rg02wpsa01.blob.core.windows.net/fek'
API = 'https://searchetv99.azurewebsites.net/api'
UA = wayback.UA

# (year, issue number in series Α΄); filled in as laws are chosen (see PROGRESS.md for the reasons).
LAWS: list[tuple[int, int]] = [
    (2024, 195),   # ν. 5160/2024 (NIS2 transposition), the act as enacted
    (2025, 223),   # the only candidate amending law found by the full-text scan (legalize-gr amended_by agrees)
    (2025, 175),   # listed by the official relation index as "Ακύρωση" of Α 195/2024: read to check
    # ν. 3471/2006 (e-privacy) and the laws the full-text scan finds amending it
    (2006, 133),   # ν. 3471/2006 as enacted
    (2009, 136),   # ν. 3783/2009 art. 8
    (2011, 22),    # ν. 3917/2011 art. 16
    (2012, 82),    # ν. 4070/2012 arts. 168-175
    (2019, 137),   # ν. 4624/2019 art. 84 (repeals)
    (2024, 202),   # art. 56: a candidate from the scan (consumer-law references)
    (2015, 34),    # listed by the official index against Α΄ 133/2006 (Τροποποίηση/Αντικατάσταση/Ακύρωση): read to check
    (2007, 152),   # listed by the official index (Αντικατάσταση): read to check
    (2020, 184),   # ν. 4727/2020, listed by the official index (Ακύρωση): read to check
    # single-version laws (no amending law found; see PROGRESS.md)
    (2025, 49),    # ν. 5188/2025, Data Governance Act measures
    (2025, 84),    # ν. 5202/2025, foreign direct investment screening
    (2025, 22),    # ν. 5178/2025, gender balance among directors of listed companies
    (2025, 163),   # ν. 5232/2025, offences for breaching EU restrictive measures
    (2025, 109),   # ν. 5214/2025, resilience: civil protection and the Fire Service
    (2025, 131),   # ν. 5220/2025, railway safety
    (2025, 219),   # ν. 5255/2025, Independent Authority for Market Control and Consumer Protection
    (2025, 231),   # ν. 5261/2025, carbon dioxide capture and storage (Directive 2009/31/EC)
    # single-version candidates, round 4 (multiscan: 0 amending issues each)
    (2025, 17),    # ν. 5176/2025, amateur and professional sport
    (2025, 154),   # ν. 5226/2025, returns of third-country nationals
    (2025, 158),   # ν. 5229/2025, social housing exchange and social rent
    (2025, 175),   # ν. 5236/2025, critical entities (already fetched above)
    (2025, 176),   # ν. 5237/2025, vocational training academies
    (2025, 227),   # ν. 5258/2025, port and ship security supervision unit
    (2025, 238),   # ν. 5263/2025, Greek AI factory
    (2025, 212),   # ν. 5253/2025, ERT S.A.
    (2025, 11),    # ν. 5173/2025, national trauma system
    (2023, 170),   # ν. 5058/2023, hired vehicles without drivers (Directive 2006/1/EC)
    (2023, 188),   # ν. 5066/2023, income tax information disclosure (Directive (EU) 2021/2101)
    (2024, 57),    # ν. 5103/2024, intangible cultural heritage
    (2024, 105),   # ν. 5120/2024, Academy of Athens
    (2024, 148),   # ν. 5136/2024, controls on PDO/PGI products
    # multi-version laws with one amending issue each (multiscan)
    (2023, 189),   # ν. 5067/2023, Regulation (EU) 2021/784 (terrorist content online)
    (2026, 30),    # ν. 5282/2026 art. 64: amends ν. 5067/2023 art. 22 par. 1
    (2025, 66),    # ν. 5194/2025, legal person of public law (hospitals)
    (2025, 167),   # ν. 5234/2025 art. δεύτερο: adds art. 34Α to ν. 5194/2025
]


def fek_url(year: int, num: int, series: str = '01') -> str:
    return f'{BLOB}/{series}/{year}/{year}{series}{num:05d}.pdf'


def _key(url: str, body: str | None) -> Path:
    return CACHE / hashlib.sha256((url + ('\n' + body if body else '')).encode('utf-8')).hexdigest()


def _log(url: str, body: str | None, code: int, size: int) -> None:
    with open(CACHE / 'requests.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'url': url, 'body': body, 'status': code, 'bytes': size,
                            'at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'via': 'fetch_laws.py'}, ensure_ascii=False) + '\n')


def api(path: str, body: dict | None = None) -> object | None:
    """GET (or POST with a JSON body) to the official search's service, cached."""
    url = f'{API}/{path}'
    b = json.dumps(body, ensure_ascii=False, sort_keys=True) if body is not None else None
    p = _key(url, b)
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    cmd = ['curl', '-gsS', '--compressed', '--max-time', '120', '-A', UA, '-H', 'Origin: https://search.et.gr',
           '-H', 'Referer: https://search.et.gr/', '-w', '\n%{http_code}']
    if b is not None:
        cmd += ['-H', 'Content-Type: application/json', '--data-binary', b]
    time.sleep(3)  # at most 1 request per 3 s to the search service (plain curl, not host_get)
    out = subprocess.run(cmd + [url], capture_output=True)
    text, _, code = out.stdout.decode('utf-8', 'replace').rpartition('\n')
    code = int(code) if code.isdigit() else 0
    _log(url, b, code, len(text))
    if code != 200:
        return None
    data = json.loads(text)
    tmp = p.with_suffix('.part')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(p)
    return data


def issue_record(year: int, num: int) -> dict | None:
    got = api('simplesearch', {'selectYear': [str(year)], 'selectIssue': ['1'], 'documentNumber': str(num),
                               'searchText': '', 'datePublished': '', 'dateReleased': '', 'tags': [],
                               'categoryIds': []})
    rows = (got or {}).get('data') if isinstance(got, dict) else got
    if isinstance(rows, str):
        rows = json.loads(rows)
    return rows


def timeline(search_id: int) -> object | None:
    return api(f'timeline/{search_id}/0')


def fek(year: int, num: int) -> bytes | None:
    return wayback.host_get(fek_url(year, num), CACHE, tries=4, timeout=600)


def main(argv: list[str]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    if argv[:1] == ['gap']:
        # the ΦΕΚ Α΄ issues legalize-gr lacks (2026: 58-127, 143, 144, 147, 148, 174, 175), read for the amendment scan
        year = int(argv[1])
        nums = [int(x) for x in argv[2:]]
        with ThreadPoolExecutor(2) as ex:
            for num, body in zip(nums, ex.map(lambda n: fek(year, n), nums)):
                print(fek_url(year, num), 'missing' if body is None else len(body), flush=True)
        return
    if argv[:1] == ['discover']:
        year, lo, hi = int(argv[1]), int(argv[2]), int(argv[3])
        for n in range(lo, hi + 1):
            print(n, json.dumps(issue_record(year, n), ensure_ascii=False)[:600], flush=True)
        return
    for year, num in LAWS:
        rec = issue_record(year, num)
        print(year, num, json.dumps(rec, ensure_ascii=False)[:300], flush=True)
        if rec:
            timeline(int(rec[0]['search_ID']))
    with ThreadPoolExecutor(2) as ex:
        for (year, num), body in zip(LAWS, ex.map(lambda yn: fek(*yn), LAWS)):
            print(fek_url(year, num), 'missing' if body is None else len(body), flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
