"""Fetch the sources behind the ν. 4624/2019 part (corpus.d/20-n4624.json).

- Government Gazette (ΦΕΚ) issues from the National Printing Office's blob store (series 01 = issue Α΄), the same
  store fetch.py reads for the Constitution.
- The Hellenic Data Protection Authority's consolidated text of ν. 4624/2019 ("με ενσωματωμένες όλες τις
  τροποποιήσεις", uploaded 2023-06), used only to check the 2022 version.
- legalize-gr's file for ΦΕΚ Α΄ 137/2019 at a pinned commit, used only for the cross-check parse_n4624.py reports.

Everything goes through the shared client gitlaw_common/wayback.host_get (one adaptive request rate per host for the
whole machine), is cached by the sha256 of the URL under .cache/n4624/ (kept apart from the Constitution's cache so
fetch.py/parse.py output is unchanged) and logged to .cache/n4624/requests.jsonl.

    python -X utf8 scripts/greece-law/fetch_n4624.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'gitlaw_common'))
import wayback  # noqa: E402

CACHE = HERE / '.cache' / 'n4624'
BLOB = 'https://ia37rg02wpsa01.blob.core.windows.net/fek'

# (year, issue number) in series Α΄; each masthead is checked in parse_n4624.py.
ISSUES = [
    (2019, 137),   # ν. 4624/2019, the act as enacted
    (2021, 166),   # ν. 4829/2021, art. 20 par. 1 περ. λβ: repeals art. 18 par. 6
    (2022, 228),   # ν. 5002/2022, arts. 34-45
    (2023, 91),    # ν. 5043/2023, art. 123 par. 2 περ. γ: repeals art. 11 par. 6
    (2025, 76),    # ν. 5197/2025, art. 56
    (2025, 133),   # ν. 5221/2025, art. 154
    (2025, 223),   # ν. 5256/2025: a candidate from the full-text scan; read, it amends no provision of ν. 4624/2019
]
DPA_CONSOLIDATED = ('https://www.dpa.gr/sites/default/files/2023-06/'
                    '4624_2019%20%CE%BC%CE%B5%20%CF%84%CF%81%CE%BF%CF%80%CE%BF%CF%80%CE%BF%CE%B9%CE%AE%CF%83%CE%B5%CE%B9%CF%82.pdf')
LEGALIZE_COMMIT = '36cb88a374cd2413cf8b128b7561d1b2bd0129cd'
LEGALIZE_FILE = f'https://raw.githubusercontent.com/legalize-dev/legalize-gr/{LEGALIZE_COMMIT}/gr/FEK-A-137-2019.md'


def fek_url(year: int, num: int, series: str = '01') -> str:
    return f'{BLOB}/{series}/{year}/{year}{series}{num:05d}.pdf'


def all_urls() -> list[str]:
    return [fek_url(y, n) for y, n in ISSUES] + [DPA_CONSOLIDATED, LEGALIZE_FILE]


def main() -> None:
    urls = all_urls()
    with ThreadPoolExecutor(8) as ex:
        for url, body in zip(urls, ex.map(lambda u: wayback.host_get(u, CACHE), urls)):
            print(url, 'missing' if body is None else len(body))


if __name__ == '__main__':
    main()
