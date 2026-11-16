"""GR-OCR: page images from ΦΕΚ scans, and the column/gutter detection used by the OCR recipe.

The pre-2000 ΦΕΚ scans are one bitonal CCITT image per page (2480x3508 or 2580x3662, i.e. 300 dpi). We take the
embedded image itself (no resampling) when a page is one full-page image; otherwise render at 300 dpi.
"""
from __future__ import annotations

import cv2
import numpy as np
import fitz  # PyMuPDF

cv2.setNumThreads(1)  # OpenCV's own thread pool fails in the detached runner ("Unknown C++ exception"); we parallelise per page


def page_gray(doc: fitz.Document, pno: int, dpi: int = 300) -> tuple[np.ndarray, float]:
    """(uint8 gray image 0=black..255=white, pixels per PDF point)."""
    page = doc[pno]
    imgs = page.get_images(full=True)
    if len(imgs) == 1:
        xref = imgs[0][0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        if rects and rects[0].width >= page.rect.width * 0.95 and rects[0].height >= page.rect.height * 0.95 \
                and page.rotation == 0:
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha != 1 or pix.alpha:
                pix = fitz.Pixmap(fitz.csGRAY, pix)
            a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
            r = rects[0]
            # Pixel scale; the image fills the page rect (rect may extend slightly past it).
            return a.copy(), pix.width / r.width
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    return a.copy(), dpi / 72


def ink_mask(a: np.ndarray) -> np.ndarray:
    """Ink without long vertical rules (column separators), as bool."""
    import cv2
    ink = (a < 128).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 70)))
    lines = cv2.dilate(lines, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1)))
    return (ink & (1 - lines)).astype(bool)


def text_box(ink: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the ink, ignoring scan-edge borders (dark bands along the edges) and specks."""
    h, w = ink.shape
    rows = ink.mean(axis=1)
    cols = ink.mean(axis=0)
    ok_r = np.where((rows > 0.003) & (rows < 0.5))[0]
    ok_c = np.where((cols > 0.003) & (cols < 0.5))[0]
    if len(ok_r) == 0 or len(ok_c) == 0:
        return 0, 0, w, h
    return int(ok_c[0]), int(ok_r[0]), int(ok_c[-1]) + 1, int(ok_r[-1]) + 1


def find_gutter(ink: np.ndarray, box: tuple[int, int, int, int], scale: float) -> int | None:
    """The body gutter: the x in the middle 30-70% of the text box whose (rule-free) ink is lowest across the body,
    accepted when the column there is clear (<0.3% ink over a 2-pt window) in at least 30% of the body strips."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    lo, hi = x0 + int(0.3 * w), x0 + int(0.7 * w)
    win = max(3, int(2 * scale))
    step = int(40 * scale)
    strips = [(sy, min(y1, sy + step)) for sy in range(y0, y1, step) if min(y1, sy + step) - sy > step // 3]
    if not strips:
        return None
    k = np.ones(win) / win
    clear = np.zeros(hi - lo)
    used = 0
    for sy, ey in strips:
        sub = ink[sy:ey, x0:x1]
        if sub.mean() < 0.01:
            continue  # nearly blank strip
        used += 1
        prof = np.convolve(sub[:, lo - x0:hi - x0].mean(axis=0), k, mode='same')
        clear += prof < 0.003
    if not used:
        return None
    best = int(np.argmax(clear))
    if clear[best] < 0.3 * used:
        return None
    # centre of the maximal plateau
    run = np.where(clear >= clear[best] - 0.5)[0]
    seg = [best]
    j = best
    while j + 1 < len(clear) and clear[j + 1] >= clear[best] - 0.5:
        j += 1
        seg.append(j)
    j = best
    while j - 1 >= 0 and clear[j - 1] >= clear[best] - 0.5:
        j -= 1
        seg.append(j)
    return lo + (min(seg) + max(seg)) // 2


def column_boxes(a: np.ndarray, scale: float) -> list[tuple[int, int, int, int]]:
    """Boxes in reading order: horizontal bands top to bottom; a band where the gutter is clear is split into left
    and right columns, a band where text crosses it (headings, full-width tables) stays whole."""
    ink = ink_mask(a)
    box = text_box(ink)
    x0, y0, x1, y1 = box
    if x1 - x0 < 50 or y1 - y0 < 50:
        return [(0, 0, a.shape[1], a.shape[0])]
    g = find_gutter(ink, box, scale)
    if g is None:
        return [box]
    reach = int(6 * scale)   # look for a white run within +-6 pt of the gutter
    minrun = max(3, int(1.2 * scale))  # >= 1.2 pt of white (text may touch a rule on one side)
    strip = int(12 * scale)
    states = []
    for sy in range(y0, y1, strip):
        ey = min(y1, sy + strip)
        if ink[sy:ey, x0:x1].mean() < 0.0005:
            states.append(None)
            continue
        col = ink[sy:ey, max(x0, g - reach):min(x1, g + reach + 1)].any(axis=0)
        run = best = 0
        for v in col:
            run = 0 if v else run + 1
            best = max(best, run)
        states.append(best >= minrun)
    last = None
    for i, s in enumerate(states):
        if s is None:
            states[i] = last
        else:
            last = s
    first = next((s for s in states if s is not None), True)
    states = [first if s is None else s for s in states]
    for i in range(1, len(states) - 1):
        if states[i - 1] == states[i + 1] != states[i]:
            states[i] = states[i - 1]
    boxes = []
    i, n = 0, len(states)
    while i < n:
        j = i
        while j < n and states[j] == states[i]:
            j += 1
        by0, by1 = y0 + i * strip, min(y1, y0 + j * strip)
        if states[i]:
            boxes += [(x0, by0, g, by1), (g, by0, x1, by1)]
        else:
            boxes.append((x0, by0, x1, by1))
        i = j
    return boxes
