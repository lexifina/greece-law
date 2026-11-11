"""Start a GR-L job hidden and detached at BelowNormal priority; record its PID in gr-l/pids.txt.

    python -X utf8 launch.py <name> <script.py> [args...]     (stdout/stderr -> gr-l/<name>.err)
"""
import datetime as dt
import subprocess
import sys
from pathlib import Path

WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-l')
HERE = Path(__file__).resolve().parent
FLAGS = 0x08000000 | 0x00004000 | 0x00000200  # CREATE_NO_WINDOW | BELOW_NORMAL | CREATE_NEW_PROCESS_GROUP

name, script, *args = sys.argv[1:]
err = open(WORK / f'{name}.err', 'a', encoding='utf-8')
p = subprocess.Popen([sys.executable, '-X', 'utf8', '-I', str(HERE / script), *args], cwd=str(HERE),
                     stdout=err, stderr=err, stdin=subprocess.DEVNULL, creationflags=FLAGS, close_fds=True)
with open(WORK / 'pids.txt', 'a', encoding='utf-8') as f:
    f.write(f'{p.pid} {script} {" ".join(args)} {dt.datetime.now(dt.timezone.utc).isoformat()}\n')
print(p.pid)
