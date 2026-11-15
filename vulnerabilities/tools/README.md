# Tools

The scripts behind this Greece-only run of global-law's vulnerability detectors. They run inside a copy of
[global-law/vulnerabilities/scripts](https://github.com/lexifina/global-law/tree/main/vulnerabilities/scripts) (Python 3.11+,
`pip install duckdb pyarrow`), with a bare clone of this repository at `sources/corpus/greece-law.git`, a blobless bare
clone of global-law at `sources/global-law.git`, and a `pins.json` that names only greece-law and its commit.
`build_vulns.py`, `flags_chart.py`, `late_ext_select.py` and `late_ext_rebut.py` sit two folders above the scripts, next to
`config.json`; `redo.py` takes that folder.

| Script | What it does |
| --- | --- |
| `run.sh` | Indexes the history and texts, adds this repository's history rows, and runs the detectors (`bash run.sh <shards>`) |
| `add_root.py` | Builds the history rows from this repository's own commits (global-law does not replay it yet), so the history detectors read every change |
| `run_triage.sh` | The model review: the 40 strongest flags per category, the 40 strongest lapsed time limits in law texts, and the empty periods |
| `late_ext_select.py` | Chooses the empty periods for global-law's review of that category (all 4 here) |
| `late_ext_rebut.py` | Adds the second, arguing-against pass to the empty-period review, as `triage.py` does for the other categories |
| `build_vulns.py` | Builds `data/flags.csv`, `data/reviewed.csv` and `data/by_category.csv` from the findings and the model review |
| `flags_chart.py` | Draws the chart at the top of the READMEs, in Greek and English, light and dark |
| `config.json` | The repository, the Greek category names, the top-level folders that are not law, and the chart's labels |
| `patch_detectors.py` | Fixes blind spots found in runs on several country repositories in the copy of global-law's scripts (`python -X utf8 patch_detectors.py <scripts dir>`; a fix already in place is skipped) |
| `redo.py` | Runs `patch_detectors.py`, then again only the scans and detectors the fixes change, the model review of lapsed time limits, references to deleted provisions and empty periods, and the build (`python -X utf8 redo.py <run folder>`; `--keep-reviews` keeps every review already made and reviews only new strong flags; `EMBED_FONTS` names the script that embeds the chart's fonts) |
| `until_gap_check.py` | Counts the Greek "until <date>" phrases in law texts and those the lapsed-time-limit search does not read (`python -X utf8 until_gap_check.py <scripts dir>`) |

The model review needs `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` and `LLM_AUTH` set for an OpenAI-compatible Responses API.
It was run as `bash run_triage.sh '^(caselaw|data|registry|tools)/'`.

Changes made for this repository:

- `add_root.py` counts as law not only `Kind: law` but also `decree` (presidential decrees and the regulatory acts of
  ministries, municipalities and regions), `as-enacted` (the Penal Code and the Code of Criminal Procedure) and `publisher`
  (the 2001 text of the Constitution and its 2008 and 2019 republications). Without them, the history detectors, which read
  only rows of kind `law`, would read 208 of the 920 commits that change law here.
- `build_vulns.py` counts as `other`, beside the folders in `config.json`, the repository's own notes: `README.md`,
  `README.en.md`, `ACTS.md` and `REPRODUCE.md`, at the root and in each act's folder.
- `run.sh` takes `LE_WORKERS` and `LE_GREP_THREADS` from the environment, and was run as
  `LE_WORKERS=3 LE_GREP_THREADS=3 bash run.sh 3` on a machine shared with other runs.
- The run was then repeated with `redo.py`, four times (the later three with `--keep-reviews`). Of `patch_detectors.py`'s fixes,
  these change this repository's flags: lapsed time limits now read «έως» and «μέχρι» with «και» and an article before the
  date («έως την 31.12.2020», «μέχρι και τις 30 Ιουνίου 2021») and an ordinal day before a month name («31η Δεκεμβρίου 2020»),
  and «το αργότερο» ranks a limit as a deadline (49 flags became 385, every earlier flag among them; the detector for empty
  periods, which reads the same dates, now finds 4). `until_gap_check.py` then found 774 such phrases with a past date in law
  texts, of which 390 were not read: an ordinal day before a month in figures («31η.12.2020», 323) and the ending «-ή»
  before a month name («30ή Ιουνίου 2011», 67). The fifth round of fixes reads both, and with it all 774 are read
  (775 flags). The reference and currency fixes change nothing here.
- `refscan.py --shards` gives each act to a shard by Python's `hash()` of its folder name, which differs between worker
  processes unless `PYTHONHASHSEED` is set: shards then overlap and some acts are read by none. The first run read all acts
  but ν. 4735/2020 (71 references to deleted provisions where there are 82); a later run missed most of them. The fifth round of
  `patch_detectors.py` splits acts by a CRC32 checksum instead, sorts the text scan's rows before splitting them, and the
  final run used it; the copy of `redo.py` here also sets `PYTHONHASHSEED=0`.
