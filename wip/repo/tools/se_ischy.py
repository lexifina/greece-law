"""Prints the Greek Constitution as it stood on a given day, read from this repository's history.

    python tools/se_ischy.py 2010-01-01 syntagma 101      # art. 101 on 1 January 2010
    python tools/se_ischy.py 2019-12-01 syntagma 101Α     # art. 101Α (the file art-101-a.md); 101A also works
    python tools/se_ischy.py 2005-01-01 syntagma          # the whole Constitution on 1 January 2005
    python tools/se_ischy.py --law 2020-01-01 syntagma 32 # also name the revision behind that wording

A thin wrapper around tools/on.py: the version is chosen by each commit's `In-force:` trailer, never by its commit
date. An article number may carry a Greek or Latin letter suffix (5Α, 9A); it is read as the file art-005-a.
Standard library only.
"""
import re
import runpy
import sys
from pathlib import Path

SUFFIX = {'Α': 'a', 'A': 'a', 'α': 'a', 'a': 'a', 'Β': 'b', 'B': 'b', 'β': 'b', 'b': 'b'}


def arg(a: str) -> str:
    m = re.fullmatch(r'(\d+)\s*([ΑΒαβABab])', a)
    return f'art-{int(m.group(1)):03d}-{SUFFIX[m.group(2)]}' if m else a


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.argv = [str(Path(__file__).with_name('on.py'))] + [arg(a) for a in sys.argv[1:]]
    runpy.run_path(sys.argv[0], run_name='__main__')
