# Tools

The scripts behind this Greece-only run of global-law's vulnerability detectors. They run inside a copy of
[global-law/vulnerabilities/scripts](https://github.com/lexifina/global-law/tree/main/vulnerabilities/scripts) (Python 3.11+,
`pip install duckdb pyarrow`), with a bare clone of this repository at `sources/corpus/greece-law.git`, a blobless bare
clone of global-law at `sources/global-law.git`, and a `pins.json` that names only greece-law and its commit.
`build_vulns.py`, `flags_chart.py`, `late_ext_select.py` and `late_ext_rebut.py` sit two folders above the scripts, next to
`config.json`.

| Script | What it does |
| --- | --- |
| `run.sh` | Indexes the history and texts, adds this repository's history rows, and runs the detectors (`bash run.sh <shards>`) |
| `add_root.py` | Builds the history rows from this repository's own commits (global-law does not replay it yet), so the history detectors read every change |
| `run_triage.sh` | The model review: the 40 strongest flags per category, the 40 strongest lapsed time limits in law texts, and the empty periods |
| `late_ext_select.py` | Chooses the empty periods for global-law's review of that category (there were none here) |
| `late_ext_rebut.py` | Adds the second, arguing-against pass to the empty-period review, as `triage.py` does for the other categories |
| `build_vulns.py` | Builds `data/flags.csv`, `data/reviewed.csv` and `data/by_category.csv` from the findings and the model review |
| `flags_chart.py` | Draws the chart at the top of the READMEs, in Greek and English, light and dark |
| `config.json` | The repository, the Greek category names, the top-level folders that are not law, and the chart's labels |

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
