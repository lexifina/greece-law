"""Grow a published git-for-law history append-only: new acts and newer versions go on top; nothing is rewritten.

    python -X utf8 append.py <scripts/<slug>-law> --repo <clone of the published repo> --docs-date YYYY-MM-DD

The clone's main must equal origin/main. What main already holds is read from git itself: for each act, the newest
In-force day it carries, and that the text in force on that day equals the corpus version. Then:

- an act main does not hold yet is appended as one block: its first version, then one commit per law per in-force day,
  in in-force order;
- a version of an act main already holds, in force after the newest one there, is appended as a change, as the full
  build would make it;
- a version in force on or before the newest one there that main lacks (a back-filled form), or a version whose text
  differs from main (a correction), stops the run: those need a labelled correction commit, decided by hand;
- versions in force after --docs-date are left for a later run (they are appended when their day comes).

Author date: noon local time on the in-force day, as in the full build. Committer date: the published head's committer
time plus one second per appended commit, so committer dates never go backwards and the same head and corpus always
give the same hashes. Tags that already exist are never moved; new ones are added. A documentation commit is appended
last (README, REPRODUCE.md, data/), never replacing the earlier one. The result is pushed with a plain `git push`.

Readers choose versions by the In-force trailer (tools/on.py, tools/check_repo.py), so an appended block reads the same
as a full build does.
"""
import argparse
import csv
import io
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402
import check_repo as K  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return B.git(repo, *args)


def published_state(repo: Path, c: dict) -> dict[str, str]:
    """{act slug: newest In-force day on main} for every act main holds; checks that day's text equals the corpus."""
    slugs = [a['slug'] for a in c['acts']]
    rows = K.all_commits_by_act(repo, 'main', slugs)
    # A law credited for a version that changed no words gets a commit that touches no file, which the per-path walk
    # above cannot see. data/commits.csv names the acts of every commit, so those days count too; otherwise each such
    # commit would be appended again on every run.
    listed: dict[str, str] = {}
    try:
        for e in published_log(repo):
            if e['branch'] == 'main':
                for s in e['acts']:
                    listed[s] = max(listed.get(s, ''), e['day'])
    except B.CorpusError:  # no data/commits.csv on main
        pass
    cat = K.Cat(repo)
    trees: dict = {}
    state = {}
    problems = []
    try:
        for act in c['acts']:
            r = rows[act['slug']]
            if not r:
                continue
            last = max([d for _, d in r] + [listed.get(act['slug'], '')])
            state[act['slug']] = last
            # Every corpus version on or before `last` must read back from main exactly (else: correction or back-fill).
            for i, v in enumerate(act['versions']):
                if v['from'] > last:
                    break
                if i + 1 < len(act['versions']) and act['versions'][i + 1]['from'] == v['from']:
                    continue
                h = K.state_on(r, v['from'])
                files = K.tree_oids(cat, h, act['slug'], trees) if h else {}
                want = {f'{act["slug"]}/{k}.md': K.blob_oid(u['text']) for k, u in v['units'].items()}
                if files != want:
                    bad = sorted(f for f in set(files) | set(want) if files.get(f) != want.get(f))
                    problems.append(f'{act["slug"]} {v["from"]}: main differs from the corpus in {len(bad)} file(s), '
                                    f'e.g. {bad[:3]} (a correction or a back-filled form: decide by hand)')
    finally:
        cat.close()
    if problems:
        raise B.CorpusError('main does not match the corpus for versions it already holds:\n  ' + '\n  '.join(problems[:40]))
    return state


def to_append(c: dict, state: dict[str, str], docs_date: str) -> tuple[dict, set[str]]:
    """A corpus of only what is new. A held act keeps its newest held version as the base, so the first new version
    is planned as a change from it; that base's own 'start' commit is dropped (main has it)."""
    out = dict(c)
    acts, based = [], set()
    for act in c['acts']:
        vs = [v for v in act['versions'] if v['from'] <= docs_date]
        last = state.get(act['slug'])
        if last is None:
            if vs:
                acts.append({**act, 'versions': vs})
            continue
        held = [v for v in vs if v['from'] <= last]
        new = [v for v in vs if v['from'] > last]
        if new:
            acts.append({**act, 'versions': [held[-1]] + new})
            based.add(act['slug'])
    out['acts'] = acts
    return out, based


def published_log(repo: Path) -> list[dict]:
    text = git(repo, 'show', 'main:data/commits.csv')
    log = []
    for r in csv.DictReader(io.StringIO(text)):
        log.append({'day': r['day'], 'kind': r['kind'], 'law': r['law'] or None, 'acts': r['acts'].split(),
                    'units': int(r['files'] or 0), 'branch': r['branch'], 'clamped': r['day'] < '1970-01-01'})
    return log


class Appender:
    """`git fast-import` onto an existing main; separate author and committer dates."""

    def __init__(self, repo: Path, head: str, head_ct: int, head_tz: str):
        self.p = subprocess.Popen(['git', 'fast-import', '--quiet', '--done', '--date-format=raw'], cwd=repo,
                                  stdin=subprocess.PIPE)
        self.mark, self.parent, self.ct, self.tz = 0, head, head_ct, head_tz

    def _w(self, b: bytes):
        self.p.stdin.write(b)

    def _data(self, s: str):
        b = s.encode('utf-8')
        self._w(f'data {len(b)}\n'.encode() + b + b'\n')

    def commit(self, author: tuple[str, str], when: str, committer: tuple[str, str], message: str,
               files: dict[str, str | None]) -> int:
        self.mark += 1
        self.ct += 1
        self._w(f'commit refs/heads/main\nmark :{self.mark}\n'.encode())
        self._w(f'author {author[0]} <{author[1]}> {when}\n'.encode('utf-8'))
        self._w(f'committer {committer[0]} <{committer[1]}> {self.ct} {self.tz}\n'.encode('utf-8'))
        self._data(message)
        self._w((f'from {self.parent}\n' if isinstance(self.parent, str) else f'from :{self.parent}\n').encode())
        for path in sorted(files):
            if files[path] is None:
                self._w(f'D {path}\n'.encode('utf-8'))
            else:
                self._w(f'M 100644 inline {path}\n'.encode('utf-8'))
                self._data(files[path])
        self.parent = self.mark
        return self.mark

    def tag(self, name: str, mark: int):
        self._w(f'reset refs/tags/{name}\nfrom :{mark}\n\n'.encode('utf-8'))

    def finish(self):
        self._w(b'done\n')
        self.p.stdin.close()
        if self.p.wait():
            raise B.CorpusError('git fast-import failed')


def append(folder: Path, repo: Path, docs_date: str, dry_run: bool = False) -> dict:
    c, raw = B.load(folder)
    errs = B.validate(c)
    if errs:
        raise B.CorpusError('corpus has problems:\n  ' + '\n  '.join(errs[:60]))
    c['_docs_date'] = docs_date
    if git(repo, 'status', '--porcelain', '--untracked-files=no').strip():
        raise B.CorpusError(f'{repo} has uncommitted changes; refusing')
    head = git(repo, 'rev-parse', 'main').strip()
    origin = subprocess.run(['git', 'rev-parse', '--verify', '-q', 'origin/main'], cwd=repo, capture_output=True,
                            text=True).stdout.strip()
    if origin and origin != head:
        raise B.CorpusError(f'main {head[:12]} is not origin/main {origin[:12]}: fetch and reset to the published head first')
    head_ct, head_tz = git(repo, 'log', '-1', '--format=%ct %ci', 'main').split()[0::3]
    head_ct = int(head_ct)
    state = published_state(repo, c)
    sub, based = to_append(c, state, docs_date)
    commits = B.plan(sub) if sub['acts'] else []
    commits = [x for x in commits if not (x['kind'] == 'start' and x['act']['slug'] in based)]
    existing_tags = set(git(repo, 'tag', '--list').split())
    co = c['country']
    committer = ('Lexifina', f'{co["slug"]}-law@lexifina.com')
    clock = B.Clock(co['tz'])
    summary = {'head': head, 'new_acts': sorted(a['slug'] for a in sub['acts'] if a['slug'] not in based),
               'extended_acts': sorted(based), 'commits': len(commits)}
    if dry_run or not commits:
        summary['main'] = head
        return summary
    w = Appender(repo, head, head_ct, head_tz)
    tags: dict[str, int] = {}
    log = []
    for x in commits:
        if x['kind'] == 'start':
            author, msg, trailers = B.start_message(c, x)
            files = B.act_files(x['act'], x['version']['units'], None)
            touched = [x['act']['slug']]
        else:
            author, msg, trailers = B.change_message(c, x)
            files = {}
            for p in x['parts']:
                files.update(B.act_files(p['act'], p['cur']['units'], p['prev']['units'], p['keys']))
            touched = [p['act']['slug'] for p in x['parts']]
        B.check_trailers(trailers)
        text = '\n'.join(msg).rstrip('\n') + '\n\n' + '\n'.join(trailers) + '\n'
        mark = w.commit(author, clock.stamp(x['day']), committer, text, files)
        for s in touched:
            tags.setdefault(f'{s}/{x["day"]}', mark)
        if x['kind'] == 'law':
            tags.setdefault(f'law/{x["law"]}', mark)
        elif x['kind'] == 'start' and x['act'].get('first_law'):
            tags.setdefault(f'law/{x["act"]["first_law"]}', mark)
        log.append({'day': x['day'], 'kind': x['kind'],
                    'law': x.get('law') or (x['act'].get('first_law') if x['kind'] == 'start' else None),
                    'acts': touched, 'units': len(files), 'branch': 'main', 'clamped': x['day'] < '1970-01-01'})
    full_log = published_log(repo) + log
    all_tags = {t: 0 for t in existing_tags} | {t: m for t, m in tags.items()}
    docs = B.docs_files(c, folder, raw, full_log, all_tags, docs_date)
    # Ship this script beside build.py, so the repository says how its appended commits were made.
    docs['tools/append.py'] = Path(__file__).read_text(encoding='utf-8').replace('\r\n', '\n')
    w.commit(committer, clock.stamp(docs_date), committer,
             f'Documentation, tables, tools and REPRODUCE.md\n\nAppended {len(log)} commits to {head[:12]}; corpus '
             f'sha256 {B.hashlib.sha256(raw).hexdigest()}, data retrieved {docs_date}.\n', docs)
    for name, mark in sorted(tags.items()):
        if name not in existing_tags:
            w.tag(name, mark)
    w.finish()
    git(repo, '-c', 'checkout.workers=0', 'checkout', '-q', '-f', 'main')
    new_head = git(repo, 'rev-parse', 'main').strip()
    if subprocess.run(['git', 'merge-base', '--is-ancestor', head, new_head], cwd=repo).returncode:
        raise B.CorpusError('internal: the published head is not an ancestor of the new main')
    summary.update({'main': new_head, 'tags_added': sum(1 for t in tags if t not in existing_tags)})
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder')
    ap.add_argument('--repo', required=True)
    ap.add_argument('--docs-date', required=True)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    print(append(Path(a.folder), Path(a.repo), a.docs_date, a.dry_run))


if __name__ == '__main__':
    main()
