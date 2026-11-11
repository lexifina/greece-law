"""GR-OCR core: OCR one page image into lines {p, t, x0, y0, x1, y1, conf} in PDF points (GR-A's text format).

Recipe (see PROGRESS.md for the benchmark that chose it):
  1. take the page's own 300-dpi bitonal image (pageimg.page_gray);
  2. split into reading-order boxes: full-width bands and left/right columns at the gutter (pageimg.column_boxes);
  3. per box: optional upscale (cubic, which also anti-aliases the bitonal edges), 20 px white margin, tesseract
     --psm <psm> -l <model> --oem 1 with TSV output (stdin -> stdout, no temp files);
  4. TSV words -> lines (block, par, line), coordinates mapped back to PDF points; line conf = mean word conf;
  5. text cleanup: NFC; µ (micro) -> μ, ϑ -> θ, ϐ -> β; for monotonic-era pages, fold the stray polytonic marks
     the models add (breathings dropped, grave/circumflex -> acute) -- only when the page is clearly monotonic.
"""
from __future__ import annotations

import os
import subprocess
import threading
import unicodedata

import cv2
import numpy as np

import pageimg

TESS = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
TESSDATA = r'C:\Users\alany\Documents\greece-law-src\tessdata'
NOWIN = 0x08000000
BELOW_NORMAL = 0x00004000
ENV = {**os.environ, 'OMP_THREAD_LIMIT': '1'}
FITZ_LOCK = threading.RLock()  # PyMuPDF is not thread-safe: every fitz call runs under this lock


def tess_version() -> str:
    r = subprocess.run([TESS, '--version'], capture_output=True, text=True, creationflags=NOWIN)
    first = (r.stdout or r.stderr).splitlines()[0]
    return first.replace('tesseract ', '').strip()


def run_tess(img: np.ndarray, model: str, psm: int, variant: str = 'best', timeout: int = 600) -> str:
    ok, png = cv2.imencode('.png', img)
    assert ok
    cmd = [TESS, 'stdin', 'stdout', '--tessdata-dir', f'{TESSDATA}\\{variant}', '-l', model, '--oem', '1',
           '--psm', str(psm), '-c', 'tessedit_create_tsv=1']
    r = subprocess.run(cmd, input=png.tobytes(), capture_output=True, timeout=timeout,
                       creationflags=NOWIN | BELOW_NORMAL, env=ENV)
    return r.stdout.decode('utf-8', errors='replace')


FIX = str.maketrans({'µ': 'μ', 'ϑ': 'θ', 'ϐ': 'β', 'ϰ': 'κ', 'ϱ': 'ρ', 'ϕ': 'φ', 'ϖ': 'π'})
# combining marks in NFD
PSILI, DASIA, GRAVE, ACUTE, PERI, YPO, DIA = '\u0313', '\u0314', '\u0300', '\u0301', '\u0342', '\u0345', '\u0308'


def polytonic_share(text: str) -> float:
    """Share of Greek letters carrying a breathing, circumflex or grave (polytonic-only marks)."""
    d = unicodedata.normalize('NFD', text)
    letters = sum(1 for c in d if '\u0370' <= c <= '\u03ff' or '\u1f00' <= c <= '\u1fff')
    marks = sum(1 for c in d if c in (PSILI, DASIA, PERI, GRAVE))
    return marks / max(1, letters)


def monotonic(text: str) -> str:
    """Fold polytonic marks on Greek letters to monotonic: drop breathings and iota subscript; grave/circumflex ->
    acute; at most one acute. Marks on non-Greek letters (French accents etc.) are left alone."""
    out = []
    greek = False
    for ch in unicodedata.normalize('NFD', text):
        if not unicodedata.combining(ch):
            greek = 'Ͱ' <= ch <= 'Ͽ' or 'ἀ' <= ch <= '῿'
            out.append(ch)
            continue
        if not greek:
            out.append(ch)
            continue
        if ch in (PSILI, DASIA, YPO):
            continue
        if ch in (GRAVE, PERI):
            ch = ACUTE
        if ch == ACUTE and ACUTE in out[-2:]:
            continue
        out.append(ch)
    return unicodedata.normalize('NFC', ''.join(out))


def clean(t: str) -> str:
    return unicodedata.normalize('NFC', t.translate(FIX))


def prep(crop: np.ndarray, up: float, thick: int = 0) -> np.ndarray:
    if thick:  # thicken thin/broken strokes of faded bitonal scans: grow the ink by a k x k square
        crop = cv2.erode(crop, np.ones((thick, thick), np.uint8))
    if up and up != 1.0:
        crop = cv2.resize(crop, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def tsv_lines(tsv: str, ox: float, oy: float, f: float) -> list[dict]:
    """TSV -> lines; pixel (in the prepped crop) -> page pixel: (x - 20) / up + ox; then * f (pt per px)."""
    rows = tsv.splitlines()
    lines: dict[tuple, dict] = {}
    order = []
    for r in rows[1:]:
        c = r.split('\t')
        if len(c) < 12 or c[0] != '5':
            continue
        word = c[11].strip()
        if not word:
            continue
        key = (int(c[2]), int(c[3]), int(c[4]))
        x, y, w, h, conf = int(c[6]), int(c[7]), int(c[8]), int(c[9]), float(c[10])
        L = lines.get(key)
        if L is None:
            L = lines[key] = {'w': [], 'c': [], 'x0': x, 'y0': y, 'x1': x + w, 'y1': y + h}
            order.append(key)
        L['w'].append(word)
        L['c'].append(conf)
        L['x0'], L['y0'] = min(L['x0'], x), min(L['y0'], y)
        L['x1'], L['y1'] = max(L['x1'], x + w), max(L['y1'], y + h)
    out = []
    for key in order:
        L = lines[key]
        out.append({'t': ' '.join(L['w']), 'conf': round(sum(L['c']) / len(L['c']), 1), 'n': len(L['w']),
                    'x0': L['x0'], 'y0': L['y0'], 'x1': L['x1'], 'y1': L['y1']})
    return out


def composite(a: np.ndarray, boxes, up: float, gap: int = 40, thick: int = 0):
    """Stack the prepped box crops vertically (left-aligned) into one image, so one tesseract run reads a page in
    box order. Returns (image, [(y_off, height, box)])."""
    parts, offs, y = [], [], 0
    for b in boxes:
        x0, y0, x1, y1 = b
        crop = a[y0:y1, x0:x1]
        if crop.size == 0 or (crop < 128).mean() < 0.0005:
            continue
        img = prep(crop, up, thick)
        parts.append(img)
        offs.append((y, img.shape[0], b))
        y += img.shape[0] + gap
    if not parts:
        return None, []
    W = max(p.shape[1] for p in parts)
    out = np.full((y - gap, W), 255, np.uint8)
    for img, (yo, h, _) in zip(parts, offs):
        out[yo:yo + h, :img.shape[1]] = img
    return out, offs


def _read(a, boxes, sc, pno, model, psm, up, variant, thick, columns):
    img, offs = composite(a, boxes, up if columns else 1.0, thick=thick)
    lines = []
    if img is None:
        return lines
    u = (up or 1.0) if columns else 1.0
    tsv = run_tess(img, model, psm if columns else 3, variant)
    lo = min(b[0] for b in boxes)
    hi = max(b[2] for b in boxes)
    for L in tsv_lines(tsv, 0, 0, 1):
        t = clean(L['t'])
        alnum = sum(1 for c in t if c.isalnum())
        if alnum == 0 or (L['conf'] < 30 and alnum <= 2):
            continue  # specks, rules and scan edges read as stray marks
        cy = (L['y0'] + L['y1']) / 2
        yo, h, (bx0, by0, bx1, by1) = next((o for o in offs if o[0] <= cy < o[0] + o[1]), offs[-1])
        px0 = (L['x0'] - 20) / u + bx0
        px1 = (L['x1'] - 20) / u + bx0
        py0 = (L['y0'] - yo - 20) / u + by0
        py1 = (L['y1'] - yo - 20) / u + by0
        col = None if (bx1 - bx0) > 0.7 * (hi - lo) else (0 if bx0 == lo else 1)
        lines.append({'p': pno, 't': t, 'x0': round(px0 / sc, 2), 'y0': round(py0 / sc, 2),
                      'x1': round(px1 / sc, 2), 'y1': round(py1 / sc, 2), 'conf': L['conf'], 'n': L['n'],
                      'col': col})
    return lines


def mean_conf(lines) -> float | None:
    """Word-weighted mean confidence."""
    n = sum(L['n'] for L in lines if L['conf'] >= 0)
    return round(sum(L['conf'] * L['n'] for L in lines if L['conf'] >= 0) / n, 1) if n else None


def latin_share(lines) -> float:
    t = ''.join(L['t'] for L in lines)
    lat = sum(1 for c in t if 'A' <= c <= 'z' and c.isalpha())
    letters = sum(1 for c in t if c.isalpha())
    return lat / max(1, letters)


def ocr_page(doc, pno: int, model: str, psm: int = 4, up: float = 1.0, columns: bool = True,
             variant: str = 'best', fold: str = 'auto', thick: int = 0, alt: str | None = None
             ) -> tuple[list[dict], dict]:
    """Lines {p,t,x0,y0,x1,y1,conf} in PDF points for page pno, and page info.

    alt: a second model (e.g. 'ell+eng') tried when the first read is weak (word conf < 70) or Latin-heavy
    (> 25% Latin letters: treaties, French/English texts); the read with the higher word confidence (by >= 5) wins."""
    with FITZ_LOCK:
        a, sc = pageimg.page_gray(doc, pno)
        page = doc[pno]
        pw, ph = round(page.rect.width, 1), round(page.rect.height, 1)
    boxes = pageimg.column_boxes(a, sc) if columns else [(0, 0, a.shape[1], a.shape[0])]
    lines = _read(a, boxes, sc, pno, model, psm, up, variant, thick, columns)
    used = model
    c1 = mean_conf(lines)
    tried_alt = False
    if alt and lines and ((c1 is not None and c1 < 70) or latin_share(lines) > 0.25):
        tried_alt = True
        lines2 = _read(a, boxes, sc, pno, alt, psm, up, variant, thick, columns)
        c2 = mean_conf(lines2)
        if c2 is not None and (c1 is None or c2 >= c1 + 5):
            lines, used = lines2, alt
    for L in lines:
        L.pop('n', None)
    text = '\n'.join(L['t'] for L in lines)
    share = polytonic_share(text)
    folded = False
    if fold == 'yes' or (fold == 'auto' and share < 0.08):
        for L in lines:
            L['t'] = monotonic_words(L['t'])
        folded = True
    confs = [L['conf'] for L in lines if L['conf'] >= 0]
    info = {'page': pno, 'w': pw, 'h': ph, 'text': bool(lines),
            'ocr': True, 'model': used,
            'gutter': next((round(b[2] / sc, 2) for b in boxes if b[0] == min(x[0] for x in boxes)
                            and (b[2] - b[0]) <= 0.7 * (max(x[2] for x in boxes) - min(x[0] for x in boxes))), None), 'alt_tried': tried_alt, 'boxes': len(boxes),
            'polytonic_share': round(share, 4), 'monotonic_fold': folded,
            'mean_conf': round(sum(confs) / len(confs), 1) if confs else None}
    return lines, info


_DIPH = ('αι', 'ει', 'οι', 'ου', 'αυ', 'ευ', 'ηυ', 'υι')
_VOW = set('αεηιουω')


def _syllables(word: str) -> int:
    base = ''.join(c for c in unicodedata.normalize('NFD', word.lower()) if not unicodedata.combining(c))
    n, i = 0, 0
    while i < len(base):
        if base[i] in _VOW:
            n += 1
            i += 2 if base[i:i + 2] in _DIPH else 1
        else:
            i += 1
    return n


def monotonic_words(text: str) -> str:
    """monotonic(), then monosyllabic Greek words of 2+ letters lose their accent (των, και, του ... carry none in
    monotonic; the models' stray grave/circumflex on them would otherwise become a false acute)."""
    import re
    t = monotonic(text)

    def fix(m):
        w = m.group(0)
        if len(w) >= 2 and _syllables(w) == 1:
            return unicodedata.normalize('NFC', ''.join(c for c in unicodedata.normalize('NFD', w)
                                                        if c != ACUTE))
        return w
    return re.sub(r'[\u0370-\u03ff\u1f00-\u1fff]+', fix, t)
