"""Start the GR-OCR runner hidden + detached at BelowNormal priority and record its PID.

    python -X utf8 start.py [--workers 14]

Refuses to start a second runner while the recorded one is alive. Stop: create
C:\\Users\\alany\\Documents\\balkan-deep\\greece-serbia\\gr-ocr\\STOP-OCR (delete it before starting again).
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-ocr')
PIDS = WORK / 'pids.txt'
FLAGS = 0x08000000 | 0x00000200 | 0x00004000 | 0x01000000  # NO_WINDOW | NEW_PROCESS_GROUP | BELOW_NORMAL | BREAKAWAY


def alive(pid: int) -> bool:
    r = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                       creationflags=0x08000000)
    return f'"{pid}"' in r.stdout and 'python' in r.stdout.lower()


def main() -> None:
    if PIDS.exists():
        for line in PIDS.read_text(encoding='utf-8').splitlines():
            if 'runner.py' in line and 'stopped' not in line:
                pid = int(line.split()[0])
                if alive(pid):
                    raise SystemExit(f'runner already running: PID {pid}')
    if (WORK / 'STOP-OCR').exists():
        raise SystemExit('STOP-OCR exists: delete it first')
    WORK.mkdir(parents=True, exist_ok=True)
    out = open(WORK / 'runner.out', 'ab')
    args = [sys.executable, '-X', 'utf8', '-W', 'ignore', '-I', str(HERE / 'runner.py')] + sys.argv[1:]
    try:
        p = subprocess.Popen(args, cwd=str(HERE), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=FLAGS, close_fds=True)
    except OSError:  # breakaway not allowed by the job: start without it
        p = subprocess.Popen(args, cwd=str(HERE), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=FLAGS & ~0x01000000, close_fds=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(PIDS, 'a', encoding='utf-8') as f:
        f.write(f'{p.pid} runner.py {" ".join(sys.argv[1:])} started {stamp} (hidden, BelowNormal; tesseract '
                f'children are BelowNormal too)\n')
    print(p.pid)


if __name__ == '__main__':
    main()
