"""GR-B: start a detached, hidden, BelowNormal job and record its PID in gr-b/pids.txt.

    python launch.py <name> <args...>      (runs: python -X utf8 -I <args...> with cwd = this folder)
stdout/stderr -> gr-b/logs/<name>.out / .err
"""
import datetime as dt
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-b')
name, args = sys.argv[1], sys.argv[2:]
(WORK / 'logs').mkdir(parents=True, exist_ok=True)
out = open(WORK / 'logs' / f'{name}.out', 'w', encoding='utf-8')
err = open(WORK / 'logs' / f'{name}.err', 'w', encoding='utf-8')
p = subprocess.Popen([sys.executable, '-X', 'utf8', '-I', *args], cwd=HERE, stdout=out, stderr=err,
                     stdin=subprocess.DEVNULL,
                     creationflags=0x08000000 | 0x00004000 | 0x00000008)  # NO_WINDOW | BELOW_NORMAL | DETACHED
with open(WORK / 'pids.txt', 'a', encoding='utf-8') as f:
    f.write(f'{p.pid} {name} {" ".join(args)} started {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n')
print(p.pid)
