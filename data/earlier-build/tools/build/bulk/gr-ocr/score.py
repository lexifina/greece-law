"""GR-OCR: character accuracy of OCR text against a hand transcription of an excerpt of the same page.

The excerpt is located in the OCR text by semi-global alignment (free start/end in the OCR text), then
accuracy = 1 - edits / len(excerpt). Two measures:
  strict: NFC text as is (diacritics count);
  base:   diacritics stripped, final sigma folded, case kept (letters, digits, punctuation).
Both collapse whitespace and join end-of-line hyphenation ("-\\n").

    python -X utf8 -I score.py <gt.txt> <ocr.txt> [...]   (pairs)
"""
from __future__ import annotations

import re
import sys
import unicodedata

import numpy as np


def norm(t: str, base: bool) -> str:
    t = unicodedata.normalize('NFC', t)
    t = re.sub(r'-\s*\n\s*', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = t.replace('’', "'").replace('ʼ', "'").replace('΄', "'").replace('`', "'").replace('᾽', "'")
    if base:
        t = ''.join(c for c in unicodedata.normalize('NFD', t) if not unicodedata.combining(c))
        t = t.replace('ς', 'σ')
        t = unicodedata.normalize('NFC', t)
    return t


def semiglobal(gt: str, ocr: str) -> int:
    """Min edit distance of gt to any substring of ocr."""
    m = len(gt)
    if m == 0:
        return 0
    o = np.frombuffer(ocr.encode('utf-32-le'), dtype=np.uint32)
    prev = np.zeros(len(o) + 1, dtype=np.int32)  # row 0: free start
    for i in range(1, m + 1):
        g = ord(gt[i - 1])
        cur = np.empty_like(prev)
        cur[0] = i
        sub = prev[:-1] + (o != g)
        dele = prev[1:] + 1
        best = np.minimum(sub, dele)
        # insertion (cur[j-1] + 1) needs a running min: cur[j] = min(best[j-1], cur[j-1]+1)
        # solve with cumulative trick: cur[j] = min_k<=j (best_k + (j - k)) ; include cur[0]
        arr = np.concatenate(([i], best)).astype(np.int64)
        idx = np.arange(len(arr))
        cur = (np.minimum.accumulate(arr - idx) + idx).astype(np.int32)
        prev = cur
    return int(prev.min())


def accuracy(gt_text: str, ocr_text: str) -> dict:
    out = {}
    for name, base in (('strict', False), ('base', True)):
        g, o = norm(gt_text, base), norm(ocr_text, base)
        d = semiglobal(g, o)
        out[name] = round(1 - d / max(1, len(g)), 4)
    out['chars'] = len(norm(gt_text, True))
    return out


if __name__ == '__main__':
    args = sys.argv[1:]
    for gt, oc in zip(args[::2], args[1::2]):
        r = accuracy(open(gt, encoding='utf-8').read(), open(oc, encoding='utf-8').read())
        print(oc, r)
