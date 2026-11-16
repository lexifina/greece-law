"""Debug: print the reading order of one text file (t with page, indent, bold flags)."""
import sys
from pathlib import Path
sys.path.insert(0, r'C:\Users\alany\Documents\lexifina\scripts\greece-law\bulk\gr-a')
import order
doc = order.load(Path(sys.argv[1]))
for l in order.reading_order(doc):
    print(f"{l['p']:>2} {l['indent']:6.1f} {'B' if l['bold'] else ' '}{'s' if l['small'] else ' '}{'W' if l['wide'] else ' '} {l['t']}")
