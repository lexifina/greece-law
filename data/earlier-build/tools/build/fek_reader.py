"""Gazette page reader with full-width bands (used by parse_n5160.py, parse_single.py and parse_n3471.py).

parse_n4624.read_lines reads each page as two columns and drops any line that spans both, such as the full-width
commencement article on a law's last page or a table set across the page. Here a page is cut into horizontal bands
at every full-width line: inside a band the left column is read before the right one, and each full-width line is
read in its place between bands. Lines of a table (smaller type, set across the page) are kept when KEEP_SMALL is on.
The rest is parse_n4624.read_lines unchanged (same filters, same fields), so pages with two clean columns read the
same.
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

import parse as P  # noqa: E402  (is_junk)
import parse_n4624 as N  # noqa: E402

KEEP_SMALL = False
# Ruled tables (GR-13; GR-12 tried row midlines): a table whose rules the page draws and which holds a cell with only
# a number (dropped as a "page number" before) is read row by row from its rules (ruled_rows, table_rows), so the
# serial numbers and numbers of posts of the staff tables of ν. 5179/2025 and ν. 5218/2025 are kept. Every other
# part reads byte for byte as before (checked by re-parsing all of them); see PROGRESS.md GR-13.
TABLE_NUMBERS = True
CONTROL = re.compile(r'[\x00-\x1f]')
# GR-18: per issue (cache file name -> {page index: the first words of the lines}): on that page, left-column lines set
# below the end of the right column, starting with those words, follow the right column (ν. 4680/2020's commencement
# article, set under both columns just above the promulgation formula). Filled by parse_single.py for its laws only.
TAIL_PAGES: dict[str, dict[int, str]] = {}


def read_lines(path: Path) -> list[dict]:
    out = []
    doc = fitz.open(path)
    sizes: dict[float, int] = {}
    for page in doc:
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        k = round(s['size'] * 2) / 2
                        sizes[k] = sizes.get(k, 0) + len(s['text'])
    body = max(sizes, key=lambda k: (sizes[k], -k))
    for pno, page in enumerate(doc):
        lines = []
        blocks = [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]
        cells = ruled_rows(page, blocks) if TABLE_NUMBERS else {}
        for b in blocks:
            for l in b['lines']:
                spans = [s for s in l['spans'] if s['text'].strip()]
                if not spans:
                    continue
                t = N.norm_line(''.join(s['text'] for s in l['spans']))
                size = max(s['size'] for s in spans)
                x0, y0, x1, _ = l['bbox']
                small = size < body - 0.6
                cell = NUMBER.match(t) is not None and id(l) in cells
                if (P.is_junk(t) and not cell) or size > body + 1.5 or (small and not KEEP_SMALL and id(l) not in cells) \
                        or y0 < 75:
                    continue
                bold_chars = sum(len(s['text']) for s in spans if s['flags'] & 16)
                lines.append({'x0': x0, 'y0': y0, 'x1': x1, 't': t, 'page': pno, 'small': small,
                              'bold': bold_chars * 2 > sum(len(s['text']) for s in spans), '_blk': b['number'],
                              '_row': cells[id(l)][0] if id(l) in cells else None,
                              '_key': cells[id(l)][1] if id(l) in cells else None, '_y1': l['bbox'][3]})
        lines = table_rows(lines)
        if not lines:
            continue
        start = len(out)
        lo = min(l['x0'] for l in lines)
        hi = max(l['x1'] for l in lines)
        mid = (lo + hi) / 2
        wide = sorted((l for l in lines if l['x0'] < mid - 6 and l['x1'] > mid + 6), key=lambda l: l['y0'])
        cols = [l for l in lines if not (l['x0'] < mid - 6 and l['x1'] > mid + 6)]
        cuts = [w['y0'] for w in wide] + [10 ** 9]
        tab = any(l.get('_tab') for l in lines)
        # on a page with a ruled table (TABLE_NUMBERS), each column's left edge is taken from the whole page, not
        # from the band: a band between two tables may hold only a caption
        page_edge = {}
        if tab:
            for side, col in (('L', [l for l in cols if l['x1'] <= mid + 6 and not l.get('_tab')]),
                              ('R', [l for l in cols if l['x0'] >= mid - 6 and not l.get('_tab')])):
                if col:
                    page_edge[side] = _edge(col)
        prev = -1.0
        wi = 0
        for cut in cuts:
            band = [l for l in cols if prev <= l['y0'] < cut]
            left = [l for l in band if l['x1'] <= mid + 6]
            right = [l for l in band if l['x0'] >= mid - 6]
            tail_first = TAIL_PAGES.get(Path(path).name, {}).get(pno)
            tail_edge = None
            if tail_first and left and right:
                bottom = max(l['_y1'] for l in right)
                tail = sorted((l for l in left if l['y0'] > bottom + 2), key=lambda l: l['y0'])
                if tail and tail[0]['t'].startswith(tail_first) and \
                        all(l['y0'] > max((m['y0'] for m in left if m not in tail), default=-1) for l in tail):
                    tail_edge = _edge(left)
                    left = [l for l in left if l not in tail]
                    right = right + [{**l, '_after': True} for l in tail]
            if tab and wi < len(wide) and wide[wi].get('_tab') and left and right:
                # left-column lines set below the end of the right column, just above a table set across the page
                # (a table's caption), are read after the right column
                bottom = max(l['_y1'] for l in right)
                tail = [l for l in left if l['y0'] > bottom + 2]
                if tail and all(l['y0'] > max((m['y0'] for m in left if m not in tail), default=-1) for l in tail):
                    left = [l for l in left if l not in tail]
                    right = right + [{**l, '_after': True} for l in tail]
            first = []
            if tab and wi > 0 and wide[wi - 1].get('_tab') and left and right:
                # right-column lines set wholly above the left column, just below a table set across the page (the
                # closing » of a restated table), are read before the left column
                top = min(l['y0'] for l in left)
                first = [l for l in right if l['_y1'] <= top + 1]
                right = [l for l in right if l not in first]
                for l in first:
                    l['indent'] = l['x0'] - (page_edge.get('R') or _edge(first))
                    out.append(l)
            for side, col in (('L', left), ('R', right)):
                if not col:
                    continue
                after = [l for l in col if l.pop('_after', False)]
                col = [l for l in col if l not in after]
                # the column's left edge: the most common line start (a stray fragment set a little to the left
                # must not shift every indent)
                edge = page_edge.get(side) or _edge(col)
                if tab and len(col) == 1 and not after and wi < len(wide) and wide[wi].get('_tab'):
                    # a lone line just above a table (its caption): indented from the page's left edge, not its own
                    edge = lo
                for l in justified_runs(sorted(col, key=cell_order(col)), edge, max(l['x1'] for l in col)):
                    l['indent'] = l['x0'] - edge
                    out.append(l)
                for l in after:
                    l['indent'] = l['x0'] - page_edge.get('L', tail_edge if tail_edge is not None else _edge([l]))
                    out.append(l)
            if wi < len(wide):
                w = wide[wi]
                w['indent'] = w['x0'] - lo
                out.append(w)
                wi += 1
            prev = cut
        if tab:
            # each table row is its own paragraph, and so is the line after a table (a caption or new text)
            for i in range(start, len(out)):
                if out[i].get('_tab') or i > start and out[i - 1].get('_tab'):
                    out[i]['indent'] = max(out[i]['indent'], 10.0)
    for l in out:
        l.pop('_blk', None)
        l.pop('_y1', None)
        l.pop('_tab', None)
    return out


def _edge(col: list[dict]) -> float:
    """A column's left edge: the most common line start (a stray fragment set a little to the left must not shift
    every indent)."""
    lo_x = min(l['x0'] for l in col)
    xs = [round(l['x0']) for l in col if l['x0'] <= lo_x + 12]
    edge = min(xs, key=lambda x: (-xs.count(x), x))
    return min(l['x0'] for l in col if l['x0'] >= edge - 1.5)


NUMBER = re.compile(r'^\d{1,5}$')


def table_rows(lines: list[dict]) -> list[dict]:
    """Each row found by ruled_rows read as one line, its cells in reading order (the key ruled_rows gives each
    line), in place of its first line."""
    rows: dict = {}
    for l in lines:
        if l['_row'] is not None:
            rows.setdefault(l['_row'], []).append(l)
    out = []
    for l in lines:
        r = l.pop('_row')
        if r is None:
            out.append(l)
        elif l is rows[r][0]:
            cells = sorted(rows[r], key=lambda c: c['_key'])
            out.append({**cells[0], 'x0': min(c['x0'] for c in cells), 'x1': max(c['x1'] for c in cells),
                        'y0': min(c['y0'] for c in cells), '_y1': max(c['_y1'] for c in cells),
                        't': ' '.join(c['t'] for c in cells), '_tab': True})
    for l in out:
        l.pop('_key', None)
    return out


def _merge(segs: list[tuple], tol: float = 1.5) -> dict[float, list[list[float]]]:
    """Segments (pos, a, b) grouped by position (within tol), each group's extents merged (gaps up to tol)."""
    out: dict[float, list[list[float]]] = {}
    for pos, a, b in sorted(segs):
        key = next((k for k in out if abs(k - pos) <= tol), pos)
        out.setdefault(key, []).append([a, b])
    for k, iv in out.items():
        iv.sort()
        m = [iv[0][:]]
        for a, b in iv[1:]:
            if a <= m[-1][1] + tol:
                m[-1][1] = max(m[-1][1], b)
            else:
                m.append([a, b])
        out[k] = m
    return out


def _covers(iv: list[list[float]], a: float, b: float, tol: float = 2.0) -> bool:
    return any(x <= a + tol and y >= b - tol for x, y in iv)


def ruled_rows(page, blocks: list[dict]) -> dict[int, tuple]:
    """Rows of the ruled tables of a page that hold a cell with only a number (the page-number pattern of
    parse.is_junk, so such cells were dropped). A table is a set of ruling segments (drawn lines and the edges of
    drawn cell boxes) that touch one another; its columns are cut at its vertical rules and its rows at the
    horizontal rules that run across its whole width. A row's cells are read column by column, left to right; where
    the columns from some column on are split again by rules across all of them (one cell beside several, e.g. a
    branch with two specialities, each with its own number of posts), each such sub-row is read in turn, its cells
    left to right; a cell of several lines is read top to bottom. Returns {id(line): ((table, row), key)} for every
    line of such a table (GR-13: ν. 5179/2025 arts. 19-20 and ν. 5218/2025 art. 77, serial numbers and numbers of
    posts in staff tables; the page number sits above y0 75, in no table)."""
    hs, vs = [], []
    for g in page.get_drawings():
        for it in g['items']:
            if it[0] == 'l':
                p, q = it[1], it[2]
                if abs(p.y - q.y) < 1 and abs(p.x - q.x) >= 1:
                    hs.append(((p.y + q.y) / 2, min(p.x, q.x), max(p.x, q.x)))
                elif abs(p.x - q.x) < 1 and abs(p.y - q.y) >= 1:
                    vs.append(((p.x + q.x) / 2, min(p.y, q.y), max(p.y, q.y)))
            elif it[0] == 're':
                r = it[1]
                if r.width >= 1:
                    hs += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                if r.height >= 1:
                    vs += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    if not hs or not vs:
        return {}
    lines = []
    for b in blocks:
        for l in b['lines']:
            t = ''.join(s['text'] for s in l['spans']).strip()
            if t:
                lines.append((l, t, l['bbox']))
    nums = [bb for l, t, bb in lines if NUMBER.match(t) and bb[1] >= 75]
    if not nums:
        return {}
    # tables: connected sets of segments (touching within 2 pt)
    segs = [('h',) + s for s in hs] + [('v',) + s for s in vs]
    boxes = [(s[2], s[1], s[3], s[1]) if s[0] == 'h' else (s[1], s[2], s[1], s[3]) for s in segs]
    parent = list(range(len(segs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    order = sorted(range(len(segs)), key=lambda i: boxes[i][1])
    for n, i in enumerate(order):
        a = boxes[i]
        for j in order[n + 1:]:
            b = boxes[j]
            if b[1] > a[3] + 2:
                break
            if a[0] <= b[2] + 2 and b[0] <= a[2] + 2:
                parent[root(j)] = root(i)
    comps: dict[int, list[int]] = {}
    for i in range(len(segs)):
        comps.setdefault(root(i), []).append(i)
    out: dict[int, tuple] = {}
    for c, members in comps.items():
        th = [segs[i][1:] for i in members if segs[i][0] == 'h']
        tv = [segs[i][1:] for i in members if segs[i][0] == 'v']
        if len(th) < 3 or len(tv) < 3:
            continue
        x0 = min(min(a for _, a, _ in th), min(p for p, _, _ in tv))
        x1 = max(max(b for _, _, b in th), max(p for p, _, _ in tv))
        y0 = min(min(p for p, _, _ in th), min(a for _, a, _ in tv))
        y1 = max(max(p for p, _, _ in th), max(b for _, _, b in tv))
        if not any(x0 <= (bb[0] + bb[2]) / 2 <= x1 and y0 <= (bb[1] + bb[3]) / 2 <= y1 for bb in nums):
            continue
        H = _merge(th)
        cols = sorted(_merge(tv))
        if len(cols) < 3:
            continue
        mine = [(l, bb) for l, t, bb in lines if x0 - 1 <= (bb[0] + bb[2]) / 2 <= x1 + 1
                and y0 - 1 <= (bb[1] + bb[3]) / 2 <= y1 + 1]
        if any(CONTROL.search(''.join(s['text'] for s in l['spans'])) for l, _ in mine):
            continue  # a table without a usable text layer (ΦΕΚ Α΄ 195/2024, Annexes I and II) is left as it is

        def col_of(bb) -> int:
            k = 0
            while k + 1 < len(cols) - 1 and cols[k + 1] <= bb[0] + 1:
                k += 1
            return k

        def emit(lo: float, hi: float, k: int, here: list, key: tuple, row: tuple) -> None:
            if k >= len(cols) - 1 or not here:
                return
            # rules inside the band that run across columns k.. to the table's right edge
            cut = sorted(y for y, iv in H.items() if lo + 2 < y < hi - 2 and _covers(iv, cols[k], cols[-1]))
            if cut:
                edges = [lo] + cut + [hi]
                for n2, (a, b) in enumerate(zip(edges, edges[1:])):
                    emit(a, b, k, [x for x in here if a <= (x[1][1] + x[1][3]) / 2 < b], key + (n2,), row)
                return
            for x in sorted((x for x in here if col_of(x[1]) == k), key=lambda x: (x[1][1], x[1][0])):
                out[id(x[0])] = (row, key + (0, x[1][1], x[1][0]))
            emit(lo, hi, k + 1, [x for x in here if col_of(x[1]) > k], key + (1,), row)
        ys = sorted(y for y, iv in H.items() if _covers(iv, x0, x1))
        for r, (a, b) in enumerate(zip(ys, ys[1:])):
            emit(a, b, 0, [x for x in mine if a <= (x[1][1] + x[1][3]) / 2 < b], (), (c, r))
    return out


def cell_order(col: list[dict]):
    """Sort key for a column's lines: by height, except table cells set side by side. A text block of 2+ lines
    whose lines are all in this column, beside another such block (vertical extents overlap, horizontal extents
    disjoint), is a table cell: the cells of such a group are read whole, left to right, at the group's top line
    (GR-11: ν. 5188/2025 art. 35, Tables 1 and 2, whose two header cells otherwise interleave line by line)."""
    blocks: dict[int, list[dict]] = {}
    for l in col:
        blocks.setdefault(l['_blk'], []).append(l)
    box = {k: (min(l['x0'] for l in v), min(l['y0'] for l in v), max(l['x1'] for l in v), max(l['y0'] for l in v))
           for k, v in blocks.items() if len(v) >= 2}
    group = {k: k for k in box}

    def root(k: int) -> int:
        while group[k] != k:
            k = group[k]
        return k
    ks = sorted(box)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = box[a], box[b]
            if (ax1 < bx0 or bx1 < ax0) and ay0 < by1 and by0 < ay1:
                group[root(b)] = root(a)
    members: dict[int, list[int]] = {}
    for k in ks:
        members.setdefault(root(k), []).append(k)
    key: dict[int, tuple] = {}
    for g in members.values():
        if len(g) < 2:
            continue
        top = min(box[k][1] for k in g)
        for rank, k in enumerate(sorted(g, key=lambda k: box[k][0])):
            key[k] = (top, rank)
    return lambda l: (key[l['_blk']][0], key[l['_blk']][1], l['y0']) if l['_blk'] in key else (l['y0'], -1, 0.0)


def justified_runs(col: list[dict], edge: float, right: float) -> list[dict]:
    """One justified line that the text layer splits into fragments on the same baseline (wide word spaces): the
    fragments run from the column's left edge to its right edge, 3-25 pt apart, so they are read as one line
    (GR-11: ν. 5128/2024 art. 82, «2020-12-10, 20SYMV007819894 2020-12-10,»). Table rows, whose cells do not fill
    the column or stand further apart, are left as they are, and so are columns whose text layer holds control
    characters or whose right edge is not a real column edge (fewer than 4 lines reach it), as on the pages
    without a usable text layer of ΦΕΚ Α΄ 195/2024."""
    out: list[dict] = []
    full = sum(1 for l in col if l['x1'] >= right - 1.5)  # lines that reach the right edge
    if any(CONTROL.search(l['t']) for l in col):  # a column without a usable text layer is left as it is
        return col
    i = 0
    while i < len(col):
        j = i + 1
        while j < len(col) and abs(col[j]['y0'] - col[i]['y0']) < 0.5 and col[j]['page'] == col[i]['page']:
            j += 1
        frags = sorted(col[i:j], key=lambda l: l['x0'])
        gaps = [b['x0'] - a['x1'] for a, b in zip(frags, frags[1:])]
        if len(frags) > 1 and frags[0]['x0'] <= edge + 1.5 and frags[-1]['x1'] >= right - 1.5 and \
                all(3 <= g <= 25 for g in gaps) and full >= 4:
            out.append({**frags[0], 'x1': frags[-1]['x1'], 't': ' '.join(f['t'] for f in frags)})
        else:
            out.extend(col[i:j])
        i = j
    return out
