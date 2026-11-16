#!/bin/bash
# Greece bulk publisher (gitlaw-greece-serbia-deep, 2026-11-11): append verified bulk parts (corpus.d/b-*.json with a
# .PUBLISH marker) to lexifina/greece-law main, append-only, in batches; each batch: check_repo gate 0, fast-forward,
# push main + tags, remote == local. Foreign-repo mode (main was built by gitlaw_common): docs under registry/.
# Log: $SRC/publish.log. Stop: touch $SRC/STOP-PUBLISH. DRY=1 for a dry run only.
set -u
SRC=/c/Users/alany/Documents/greece-law-src
F=/c/Users/alany/Documents/lexifina/scripts/greece-law
G=/c/Users/alany/Documents/lexifina/scripts/world-law/balkan-builder
R=/c/Users/alany/Documents/greece-law-pub
export GITLAW_DOCS_PREFIX=registry/
export GITLAW_LAYOUT_KINDS=syntagma,nomos,pd,pnp,an,nd,bd,nbd,en,npd,kanonismos,ya,kya,apofasi,psifisma,diorthosi
export GITLAW_VERIFIED_PARTS_ONLY=1
export GITLAW_MAX_NEW_ACTS=${BATCH:-300}
export GITLAW_PART_CACHE=$SRC/part-cache.base
log() { echo "$(date -u +%FT%TZ) $*" >> $SRC/publish.log; }
freegb() { df -BG --output=avail /c | tail -1 | tr -dc 0-9; }
echo $$ > $SRC/publish.pid
[ "$(freegb)" -ge 50 ] || { log "FAILED: C: below 50 GB"; exit 1; }
DOCS=${DOCS:-$(date -u +%F)}
cd $R && git fetch -q origin && git merge -q --ff-only origin/main || { log "FAILED: clone not FF with origin"; exit 1; }
cd $G
python -X utf8 append.py $F --repo $R --docs-date $DOCS --dry-run > $SRC/dry.out 2>&1 || { log "FAILED dry run: $(tail -3 $SRC/dry.out | tr '\n' ' ' | cut -c1-500)"; exit 1; }
log "dry run ok: $(tail -2 $SRC/dry.out | tr '\n' ' ' | cut -c1-300)"
[ "${DRY:-0}" = "1" ] && exit 0
n=0
while true; do
  [ -f $SRC/STOP-PUBLISH ] && { log "stop file between batches"; exit 0; }
  # committer times: wait until head committer time + 330 s is past (kit.md pitfall)
  ht=$(git -C $R log -1 --format=%ct main); now=$(date +%s); [ $((ht + 330)) -gt $now ] && sleep $((ht + 330 - now))
  before=$(git -C $R rev-parse main)
  python -X utf8 append.py $F --repo $R --docs-date $DOCS > $SRC/append.out 2>&1 || { log "FAILED append: $(tail -3 $SRC/append.out | tr '\n' ' ' | cut -c1-500)"; git -C $R reset -q --hard $before; exit 1; }
  after=$(git -C $R rev-parse main)
  [ "$before" = "$after" ] && break
  python -X utf8 $G/check_repo.py $R --corpus $F/corpus.json > $SRC/check.out 2>&1
  bad=$(python -X utf8 -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));print(sum(d[k] for k in ('trailer_errors','missing_in_force','merges','backwards','future_dated')))" $SRC/check.out)
  [ "$bad" = "0" ] || { log "FAILED check (see check.out); reset to $before, not pushed"; git -C $R reset -q --hard $before; exit 1; }
  git -C $R merge-base --is-ancestor origin/main main || { log "FAILED: not a fast-forward"; exit 1; }
  git -C $R push -q origin main 2>> $SRC/publish.log || { log "FAILED push main"; exit 1; }
  git -C $R push -q origin --tags 2>> $SRC/publish.log || { log "FAILED push tags"; exit 1; }
  [ "$(git -C $R ls-remote origin refs/heads/main | cut -f1)" = "$after" ] || { log "FAILED: remote main != local after push"; exit 1; }
  git -C $R fetch -q origin
  n=$((n + 1))
  log "batch pushed: $before -> $after ($(git -C $R rev-list --count $before..$after) commits)"
done
log "DONE: $n batches pushed"
