"""GR-L pipeline loop (detached): for every org whose metadata harvest is complete, in the harvest's priority order:
classify (select_acts) -> fetch + read the selected documents (fetch_docs, <= 1 request/s, 6 parallel downloads) ->
build the staged parts (build_parts -> bulk/gr-l/stage/b-l-<unit>-<k>.json + gr-l/held/<unit>.json) ->
coverage.csv. Parts are NOT promoted into corpus.d here: promotion needs the 20 hand spot-checks (PROGRESS.md).

    python -X utf8 -I pipeline.py            (loops; stop file <WORK>/STOP-PIPELINE; log <WORK>/pipeline.log)

Resumable: an org is re-selected when its harvest counts.json or the classifier version changed, and rebuilt when
its selection or any of its text files is newer than its staged parts.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_parts  # noqa: E402
import fetch_docs  # noqa: E402
import harvest2  # noqa: E402
import select_acts  # noqa: E402
from classify import VERSION  # noqa: E402
from common_l import META, SEL, TEXT, WORK, unit_slug  # noqa: E402
from common import now  # noqa: E402


def log(msg: str) -> None:
    with open(WORK / 'pipeline.log', 'a', encoding='utf-8') as f:
        f.write(f'{now()} {msg}\n')


def stale_selection(uid: str) -> bool:
    st = WORK / 'select-stats' / f'{uid}.json'
    if not st.exists() or not (SEL / f'{uid}.jsonl').exists():
        return True
    s = json.loads(st.read_text(encoding='utf-8'))
    return s.get('classifier') != VERSION or st.stat().st_mtime < (META / uid / 'counts.json').stat().st_mtime


def newest_input(uid: str) -> float:
    t = (SEL / f'{uid}.jsonl').stat().st_mtime
    d = TEXT / uid
    if d.exists():
        for p in d.rglob('*.json.gz'):
            t = max(t, p.stat().st_mtime)
    return t


def main() -> None:
    log(f'pipeline start pid {os.getpid()} classifier {VERSION}')
    orgs = {o['uid']: o for o in harvest2.ordered_orgs()}
    while True:
        did = 0
        for uid, org in orgs.items():
            if (WORK / 'STOP-PIPELINE').exists():
                log('stop file')
                return
            if not (META / uid / 'counts.json').exists():
                continue
            if stale_selection(uid):
                s = select_acts.select(uid)
                log(f'select {uid}: {s["total"]} decisions, {s["selected"]} selected {s["by_category"]}')
                did += 1
            rows = [json.loads(l) for l in open(SEL / f'{uid}.jsonl', encoding='utf-8') if l.strip()]
            todo = [r for r in rows if not fetch_docs.text_path(r['org'], int(r['year']), r['ada']).exists()]
            if todo:
                c = fetch_docs.run(todo)
                log(f'fetch {uid}: {c}')
                did += 1
                if c.get('blocked'):
                    log('fetch blocked: stopping the pipeline (see STOP-FETCH)')
                    return
                if any(not fetch_docs.text_path(r['org'], int(r['year']), r['ada']).exists() for r in todo):
                    continue  # transient failures: build later
            slug = unit_slug(org)
            staged = sorted(build_parts.STAGE.glob(f'b-l-{slug}-*.json'))
            held = WORK / 'held' / f'{slug}.json'
            if rows and (not held.exists() or held.stat().st_mtime < newest_input(uid)):
                parts, rep = build_parts.build(uid)
                names = {n for n, _ in parts}
                for old in staged:
                    if old.name not in names:
                        old.unlink()
                for n, part in parts:
                    build_parts.write(build_parts.STAGE / n, build_parts.dump(part))
                build_parts.write(held, build_parts.dump(rep))
                log(f'built {slug}: {rep["selected"]} selected, {rep["published"]} published, {len(rep["held"])} held, '
                    f'{len(parts)} part(s)')
                did += 1
        build_parts.coverage()
        if not did:
            if all('worker %d/3 done' % k in (WORK / 'harvest.log').read_text(encoding='utf-8') for k in range(3)):
                log('pipeline done: every harvested org selected, fetched and built')
                return
            time.sleep(300)


if __name__ == '__main__':
    main()
