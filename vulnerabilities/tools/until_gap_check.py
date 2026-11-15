"""Greek "until <date>" phrases in the law texts of greece-law at the pinned commit, and how many textscan's LIMIT does not read.

    python -X utf8 until_gap_check.py <scripts dir>

A phrase: έως / μέχρι / ως, optionally «και», optionally an article (την, τη, τις, το, τον, της), then a full date (day, month,
year): numeric d.m.yyyy or d/m/yyyy, also with an ordinal ending (31η.12.2020, 30ή.6.2021), or the day and a Greek month name.
Matching ignores accents and case. A phrase is read when a LIMIT or LIMIT_POST match of ingest/textscan.py overlaps it.
Folders that are not law (config.json's not_law) and the repository's own notes are left out.
"""
import os, re, subprocess, sys
from collections import Counter
from pathlib import Path
S = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(S / "ingest"))
os.chdir(S)
import json
import textscan
PIN = json.load(open(S / "pins.json", encoding="utf-8"))["corpora"][0]
REPO = S / "sources" / "corpus" / f"{PIN['repo']}.git"
NOT_LAW = ("caselaw/", "data/", "registry/", "tools/")
DOCS = ("README.md", "README.en.md", "ACTS.md", "REPRODUCE.md")
TODAY = "2026-11-15"  # the day of the run
ACC = str.maketrans("άέήίόύώϊϋΐΰΆΈΉΊΌΎΏΪΫ", "αεηιουωιυιυΑΕΗΙΟΥΩΙΥ")
MONTHS = "ιανουαριου φεβρουαριου μαρτιου απριλιου μαιου ιουνιου ιουλιου αυγουστου σεπτεμβριου οκτωβριου νοεμβριου δεκεμβριου".split()
MI = {m: i for i, m in enumerate(MONTHS, 1)}
DAY = r"(\d{1,2})(?:η|ης|ην)?"
PH = re.compile(r"(?<![\w])(εως|μεχρι|ως)\s+(?:και\s+)?(?:(?:την|τη|τις|το|τον|της)\s+)?"
                rf"(?:{DAY}\s?\.?\s?[./]\s?(\d{{1,2}})\s?[./]\s?(\d{{4}})|{DAY}\.?\s+({'|'.join(MONTHS)})\s+(\d{{4}}))")
files = []
for line in subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r", PIN["sha"]], capture_output=True).stdout.decode("utf-8").splitlines():
    meta, path = line.split("\t", 1)
    if meta.split()[1] != "blob" or not textscan.is_law_file(path) or path.startswith(NOT_LAW) or path.rsplit("/", 1)[-1] in DOCS:
        continue
    files.append((meta.split()[2], path))
tot = past = miss = 0
allf, missf, kinds, ex = set(), set(), Counter(), {}
for (sha, text), (_, path) in zip(textscan.stream(REPO, [s for s, _ in files]), files):
    low = text.translate(ACC).lower()  # same length as text, so spans carry over
    spans = [m.span() for m in list(textscan.LIMIT.finditer(text)) + list(textscan.LIMIT_POST.finditer(text))]
    for m in PH.finditer(low):
        if m.group(2):
            d, mo, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
        else:
            d, mo, y = int(m.group(5)), MI[m.group(6)], int(m.group(7))
        if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
            continue
        tot += 1
        allf.add(path)
        if f"{y:04d}-{mo:02d}-{d:02d}" >= TODAY:
            continue
        past += 1
        a, b = m.span()
        if any(s < b and a < e for s, e in spans):
            continue
        miss += 1
        missf.add(path)
        orig = text[a:b]
        k = ("ordinal ending + month in figures (31η.12.2020, 30ή.6.2021)" if re.search(r"\d(?:η|ης|ή|ής|ην)\s?\.?\s?[./]", orig) else
             "ordinal ending ή/ής + month name (30ή Ιουνίου 2011)" if re.search(r"\d(?:ή|ής)\s", orig) else
             "month name in capitals or without accent" if m.group(6) else "other")
        kinds[k] += 1
        ex.setdefault(k, []).append(f"{path}: {orig}")
print(f"phrases {tot} in {len(allf)} files; with a date before {TODAY}: {past}; not read: {miss} in {len(missf)} files")
for k, n in kinds.most_common():
    print(f"  {n:4d} {k}")
    for e in ex[k][:5]:
        print("       ", e)
