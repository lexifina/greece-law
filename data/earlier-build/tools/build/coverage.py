"""Text checks of a part file against the Gazette text layer (standard checks; reads only the local cache).

usage: python -X utf8 coverage.py [corpus.d/PART.json ...]   (no args: every part in PUBLISH order of corpus.d)
       options: --pdf URL=PATH (a cached PDF stored elsewhere), --pdf-dir DIR (PDFs stored by file name), --quiet

For each part:
 1. BAG (the earlier cov.py, with the GR-9 anchor fixes): words of version 0 against the issue's segment from the first
    heading (ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ Α, else art. 1; «Άρθρο\\xa01» accepted) to «Παραγγέλλομε τη δημοσίευση».
 2. ORDER: a word-sequence diff of version 0 against the whole issue (page headers and page numbers taken out per page
    first, so no number is ever filtered as a "page number"). Every raw token that the corpus drops between the first and
    the last matched word is reported, numbers included. Runs that only differ by joining (e.g. a kept hyphen) are
    counted as joins, not losses. Text before the first match (title, preamble) and after the last match (signatures,
    printer's notice) is reported as a count with its first words, to be read by eye.
 3. AMEND (versions 1..n): each run of words a version adds (word diff against the previous version) of 4+ words is
    located in its source issue; raw tokens inside the located span that the run lacks are reported (a restated table
    losing cells shows here). Shorter runs are reported only if a word is absent from the issue.
A part passes when ORDER and AMEND report no dropped token except those listed in coverage_ok.json
({"PART": {"order": ["token", ...], "amend": [...], "order_runs": ["first words of a run", ...], "amend_runs": [...]},
"_why": {...}}: explained readings and by-design exclusions, each with its reason under "_why" and in PROGRESS.md).
"""
from __future__ import annotations

import collections
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_laws as FL  # noqa: E402
import fitz  # noqa: E402

LAT = str.maketrans('ABEHIKMNOPTXYZabekmnopvxyz', 'ΑΒΕΗΙΚΜΝΟΡΤΧΥΖαβεκμνορνχυζ')
LOOKALIKE = set('ABEHIKMNOPTXYZabekmnopvxyz')
# Greek letters without U+0387 (ano teleia), which sits inside the block Ά-Ώ
WORD = re.compile(r'[Α-Ωα-ωΆΈ-Ώά-ώϊϋΐΰΪΫA-Za-zµμ0-9]+')
HDR_LINE = re.compile(r'^\s*(ΕΦΗΜΕΡΙ[ΣΔ]Α?\s+T?Τ?ΗΣ\s+ΚΥΒΕΡΝΗΣΕΩΣ.*|Τεύχος\s+[AΑ][’΄\']?\s*\d+/[\d.]+\s*|\d{1,5}\s*)$')
RUN_HDR = re.compile(r'^\s*(ΕΦΗΜΕΡΙ[ΣΔ]?Α?\s*T?Τ?ΗΣ\s+ΚΥΒΕΡΝΗΣΕΩΣ.*|Τεύχος\s+[AΑ][’΄\']?\s*\d+/[\d.]+|\(?ΤΕΥΧΟΣ\s+ΠΡΩΤΟ\)?)\s*$')
SIG_TAIL = re.compile(r'^\s*(Date:|Reason:|Location:|\(embedded\)|E?E[ΕE]?S?T\s*$|ΕΕΤ|Signature Not Verified|Typograf|Ethniko)')
INSTR = re.compile(r'αντικαθίστα|προστίθε|αναριθμ|καταργ|τροποποιε|διαγράφ|ως εξής|ως ακολούθως|απαλείφ|συμπληρών')
OVERRIDE: dict[str, Path] = {}
PDF_DIRS: list[Path] = []


def norm(w: str) -> str:
    w = w.replace('µ', 'μ')
    if (len(w) <= 3 or w.isupper()) and set(w) <= LOOKALIKE:
        return w.translate(LAT)
    return w.translate(LAT) if re.search(r'[Α-Ωα-ωά-ώ]', w) or (len(w) <= 3 and w.isupper()) else w


def words(t: str) -> list[str]:
    t = re.sub(r'\xa0?[-−‐]\s*\n\s*(?=[α-ωά-ώ])', '', t.replace('₂', '2'))
    return [norm(w) for w in WORD.findall(t)]


def pdf_path(url: str) -> Path:
    if url in OVERRIDE:
        return OVERRIDE[url]
    m = re.search(r'/fek/(\d\d)/(\d{4})/\d{4}\d\d(\d{5})\.pdf$', url)
    p = FL._key(FL.fek_url(int(m.group(2)), int(m.group(3)), m.group(1)), None)
    if not p.exists():
        p = FL._key(url, None)
    for d in PDF_DIRS:
        if not p.exists() and (d / url.rsplit('/', 1)[1]).exists():
            p = d / url.rsplit('/', 1)[1]
    return p


MASTHEAD_CUT: dict[str, int] = {}


def legacy(text: str) -> str:
    """The 2001 legacy font: PyMuPDF on this machine returns its Windows-1253 bytes as code page 437 glyphs. Map each
    back to its byte and decode it as Windows-1253 (byte 0x88, undefined there, is the font's ano teleia, as in
    parse.legacy_decode)."""
    out = []
    for ch in text:
        if ord(ch) < 0x80:
            out.append(ch)
            continue
        try:
            b = ch.encode('cp437')[0]
        except UnicodeEncodeError:
            out.append(ch)
            continue
        out.append('·' if b == 0x88 else bytes([b]).decode('cp1253', errors='replace'))
    return ''.join(out)


def page_texts(path: Path) -> list[str]:
    """Each page's text without its running header (masthead, page number, issue line: the first lines only) and,
    on the first page, without the front masthead block (from «ΕΦΗΜΕΡΙΔΑ» / «ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ» through «Αρ. Φύλλου»,
    the page number and the signature stamp, which the text layer puts after the page's text)."""
    out = []
    for pno, page in enumerate(fitz.open(path)):
        text = page.get_text()
        if sum(text.count(c) for c in '≡⌠▄▀ß≤≥') > 0.03 * max(1, len(text)):
            text = legacy(text)
        lines = text.replace('∆', 'Δ').split('\n')
        k = 0
        while k < min(4, len(lines)) and HDR_LINE.match(lines[k]):
            k += 1
        lines = lines[k:]
        # running headers set inside the page's text layer (2006-2012 and 2026 issues) and signature stamps
        drop = set()
        for i, l in enumerate(lines):
            if RUN_HDR.match(l):
                drop.add(i)
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    if re.fullmatch(r'\s*(\d{1,5}|[ΕE])\s*', lines[j]):
                        drop.add(j)
            if l.strip() == 'Signature Not Verified':
                drop.add(i)
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    if re.fullmatch(r'\s*\d{1,5}\s*', lines[j]):
                        drop.add(j)
            if l.strip().startswith('Digitally signed by'):
                drop.update((i, i + 1))
                j = i + 2
                while j < len(lines) and j < i + 10 and SIG_TAIL.match(lines[j]):
                    drop.add(j)
                    j += 1
        lines = [l for i, l in enumerate(lines) if i not in drop]
        if pno == 0:
            for i in range(len(lines) - 2):
                if lines[i].strip() == 'ΕΦΗΜΕΡΙΔΑ' and lines[i + 1].strip() == 'ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ' and any(
                        l.startswith('Αρ. Φύλλου') for l in lines[i:i + 12]):
                    MASTHEAD_CUT[str(path)] = len(words('\n'.join(lines[i:])))
                    lines = lines[:i]
                    break
        out.append('\n'.join(lines))
    return out


def apply_changes(units: dict, v: dict) -> dict:
    """A version's full unit map: its own `units`, or the previous map with its `changes` (None removes a unit)."""
    if 'units' in v:
        return v['units']
    out = dict(units)
    for k, u in v.get('changes', {}).items():
        if u is None:
            out.pop(k, None)
        else:
            out[k] = u
    def order(k: str) -> tuple:
        m = re.fullmatch(r'art-(\d+)(.*)', k)
        return (1, int(m.group(1)), m.group(2)) if m else ((0,) if k == 'prooimio' else (2, 0, k))
    return {k: out[k] for k in sorted(out, key=order)}


def units_text(units: dict) -> str:
    return '\n'.join(v['text'] for v in units.values())


def bag(units: dict, raw: str) -> tuple[int, collections.Counter, int]:
    a1 = units.get('art-001', {}).get('text', '').split('\n')
    title = a1[a1.index('Άρθρο 1') + 1][:15] if 'Άρθρο 1' in a1 else ''
    ms = [m for m in re.finditer(r'Άρθρο[ \xa0]1\s*\n', raw)
          if re.sub(r'\s+', ' ', raw[m.end():m.end() + 60]).strip().startswith(title)]
    if not ms:
        return -1, collections.Counter(), -1
    # GR-10: the art. 1 whose following words are the corpus's own art. 1 (a quoted statute's art. 1 later in the
    # issue can have the same title: Α΄ 206/2023); the last one if none matches word for word
    own = words(' '.join(a1[a1.index('Άρθρο 1'):] if 'Άρθρο 1' in a1 else a1))[:40]
    i = max(m.start() for m in ms)
    for m in ms:
        if words(raw[m.start():m.start() + 2000])[:len(own)] == own:
            i = m.start()
            break
    j = raw.rfind('Παραγγέλλομε τη δημοσίευση')
    j = j if j > i else raw.rfind('Αθήνα,')
    j = j if j > i else len(raw)
    # the opening headings stand right before art. 1, with no article between (not a table of contents): the
    # earliest of them (a ΜΕΡΟΣ before its ΚΕΦΑΛΑΙΟ)
    cands = [raw.rfind(h, 0, i) for h in ('ΜΕΡΟΣ Α', 'ΜΕΡΟΣ A', 'ΚΕΦΑΛΑΙΟ Α', 'ΚΕΦΑΛΑΙΟ A', 'ΜΕΡΟΣ ΠΡΩΤΟ',
                                          'ΚΕΦΑΛΑΙΟ ΠΡΩΤΟ')]
    cands = [c for c in cands if c >= 0 and i - c < 3000 and not re.search(r'Άρθρο[  ]\d', raw[c:i])]
    i0 = min(cands) if cands else i
    seg = raw[i0 if i0 >= 0 else i:j]
    theirs, mine = collections.Counter(words(seg)), collections.Counter(words(units_text(units)))
    miss = theirs - mine
    extra = mine - theirs
    for w in list(extra.elements()):  # a word the corpus joins whose two pieces the issue splits
        for k in range(2, len(w) - 1):
            a, b = w[:k], w[k:]
            if miss[a] and miss[b]:
                miss[a] -= 1; miss[b] -= 1; break
    return sum(theirs.values()), +miss, (i0 if i0 >= 0 else i)


def seq_losses(theirs: list[str], mine: list[str]) -> tuple:
    """Ordered diff. Returns (dropped runs [(context, tokens, replaced-by)], extra runs, joins, head, tail)."""
    sm = difflib.SequenceMatcher(a=theirs, b=mine, autojunk=False)
    ops = sm.get_opcodes()
    eq = [o for o in ops if o[0] == 'equal']
    if not eq:
        return [('', theirs[:20], [])], [], 0, [], [], 0
    first, last = eq[0][1], eq[-1][2]
    head, tail = theirs[:first], theirs[last:]
    dropped, extra, joins = [], [], 0
    for op, i1, i2, j1, j2 in ops:
        if op == 'equal' or i2 <= first or i1 >= last:
            if op == 'insert' and first <= i1 <= last:
                extra.append((' '.join(theirs[max(0, i1 - 5):i1]), mine[j1:j2]))
            continue
        a, b = theirs[max(i1, first):min(i2, last)], mine[j1:j2]
        if ''.join(a) == ''.join(b):
            joins += 1
            continue
        if a:
            dropped.append((' '.join(theirs[max(0, i1 - 6):i1]), a, b))
        elif b:
            extra.append((' '.join(theirs[max(0, i1 - 5):i1]), b))
    # a dropped run whose words the corpus has elsewhere (an extra run) is a move (table cells read in another
    # order), not a loss: report it apart
    pool = collections.Counter(w for _, b in extra for w in b)
    kept, moved = [], 0
    for ctx, a, b in dropped:
        rest = []
        for w in a:
            if w in b:
                b = list(b); b.remove(w)  # replaced in place by itself (a split/merge), not lost
            elif pool[w] > 0:
                pool[w] -= 1; moved += 1
            else:
                rest.append(w)
        if rest:
            kept.append((ctx, rest, b))
    return kept, extra, joins, head, tail, moved


def amend_losses(prev: dict, cur: dict, raw_words: list[str]) -> list:
    """Runs a version adds, located in its source issue; raw tokens inside each located span missing from the run."""
    out = []
    rawset = set(raw_words)
    index: dict[tuple, list[int]] = collections.defaultdict(list)
    for i in range(len(raw_words) - 3):
        index[tuple(raw_words[i:i + 4])].append(i)
    for key, u in cur.items():
        new = words(u['text'])
        old = words(prev[key]['text']) if key in prev else []
        if new == old:
            continue
        sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op not in ('insert', 'replace'):
                continue
            run = new[j1:j2]
            if len(run) < 4:
                absent = [w for w in run if w not in rawset]
                if absent:
                    out.append((key, 'absent', absent, run))
                continue
            # anchor: the first and the last 4-gram of the run that occur in the issue
            starts = [(k, index[tuple(run[k:k + 4])]) for k in range(len(run) - 3) if tuple(run[k:k + 4]) in index]
            if not starts:
                out.append((key, 'not found', run[:12], run))
                continue
            best = None
            h = len(starts) // 2
            tried = set()
            for k0, pos0 in starts[:3] + starts[max(0, h - 1):h + 2] + starts[-3:]:
                for p0 in pos0:
                    lo = p0 - k0
                    if lo in tried:
                        continue
                    tried.add(lo)
                    hi = lo + len(run) + max(10, len(run) // 4)
                    win = raw_words[max(0, lo):hi]
                    m = difflib.SequenceMatcher(a=win, b=run, autojunk=False)
                    r = m.ratio()
                    if best is None or r > best[0]:
                        best = (r, win, m)
            r, win, m = best
            blocks = [b for b in m.get_matching_blocks() if b.size]
            a_lo, a_hi = blocks[0].a, blocks[-1].a + blocks[-1].size
            lost = []
            for op2, x1, x2, y1, y2 in m.get_opcodes():
                if op2 in ('delete', 'replace') and x1 >= a_lo and x2 <= a_hi:
                    a, b = win[x1:x2], run[y1:y2]
                    if ''.join(a) != ''.join(b):
                        lost.append((' '.join(win[max(0, x1 - 5):x1]), a, b))
            missing_from_issue = [w for w in run if w not in rawset]
            if lost or missing_from_issue:
                out.append((key, f'span ratio {r:.3f}', lost, missing_from_issue))
    return out


def check_part(path: Path, ok: dict, quiet: bool) -> bool:
    name = path.stem
    d = json.loads(path.read_text(encoding='utf-8'))
    allowed = ok.get(name, {})
    good = True
    for act in d['acts']:
        vs = act['versions']
        p0 = pdf_path(vs[0]['source_url'])
        if not p0.exists():
            print(f'{name} {act["slug"]}: NO LOCAL PDF for version 0 ({vs[0]["source_url"][-28:]}): not checked')
            good = False
            continue
        pages = page_texts(p0)
        raw = ''.join(pages)
        # the base text: version 0 plus later versions from the same issue (parts that take effect later)
        units0, nb = vs[0]['units'], 1
        while nb < len(vs) and vs[nb]['source_url'] == vs[0]['source_url']:
            units0 = apply_changes(units0, vs[nb]); nb += 1
        # GR-16: a later start of the same issue that comes after another law's version (ν. 4955/2022: Part Α on
        # 13.2.2023, after ν. 4972/2022) belongs to the base text too, if it touches no unit a version in between did
        touched, late = set(), []
        for j in range(nb, len(vs)):
            ch = set(vs[j].get('changes', {}))
            if vs[j]['source_url'] == vs[0]['source_url'] and 'units' not in vs[j] and not ch & touched:
                units0 = apply_changes(units0, vs[j]); late.append(j)
            touched |= ch
        n_raw, miss, i0 = bag(units0, raw)
        before = words(raw[:i0]) if i0 > 0 else []
        dropped, extra, joins, head, tail, moved = seq_losses(words(raw[max(i0, 0):]), words(units_text(units0)))
        head = before + head
        ok_order = collections.Counter(allowed.get('order', []))
        flagged = []
        runs_ok = allowed.get('order_runs', [])
        for ctx, a, b in dropped:
            if any(' '.join(a).startswith(r) for r in runs_ok):
                continue
            left = [w for w in a if not (ok_order[w] > 0 and not ok_order.subtract([w]))]
            if left:
                flagged.append((ctx, left, b))
        nums = [w for _, a, _ in flagged for w in a if any(c.isdigit() for c in w)]
        long_extra = [(c, b) for c, b in extra if len(b) > 25 and not any(' '.join(b).startswith(r) for r in allowed.get('extra_runs', []))]
        status = 'PASS' if not flagged and not long_extra else ('LOSS' if flagged else 'EXTRA')
        print(f'{name} v0..{nb - 1}{"".join(f"+v{j}" for j in late)} [{act["slug"]}] pages {len(pages)} BAG raw {n_raw} residual {sum(miss.values())} '
              f'{miss.most_common(10)} | ORDER {status}: dropped runs {len(flagged)} (tokens '
              f'{sum(len(a) for _, a, _ in flagged)}, numbers {nums[:20]}), allowed {len(dropped) - len(flagged)}, '
              f'moved {moved}, joins {joins}, extra runs {len(extra)} | head {len(head)}w tail {len(tail)}w '
              f'masthead {MASTHEAD_CUT.get(str(p0))}w', flush=True)
        if not quiet:
            for ctx, a, b in flagged:
                print(f'    DROP ...{ctx} [ {" ".join(a)} ] -> [ {" ".join(b)} ]')
            for ctx, b in extra[:15]:
                print(f'    EXTRA ...{ctx} + [ {" ".join(b[:40])} ]')
            print(f'    head: {" ".join(head[:12])} ... {" ".join(head[-12:])}')
            print(f'    tail: {" ".join(tail[:40])}')
        good &= not flagged and not long_extra
        ok_am = collections.Counter(allowed.get('amend', []))
        cur = units0
        for k in range(nb, len(vs)):
            prev, cur = cur, apply_changes(cur, vs[k])
            pk = pdf_path(vs[k]['source_url'])
            if not pk.exists():
                print(f'{name} v{k}: NO LOCAL PDF ({vs[k]["source_url"][-28:]}): not checked')
                good = False
                continue
            rw = words(''.join(page_texts(pk)))
            res = amend_losses(prev, cur, rw)
            bad, instr = [], []
            for key, kind, lost, extra2 in res:
                if kind.startswith('span'):
                    lost2 = []
                    for c, a, b in lost:
                        if any(' '.join(a).startswith(r) for r in allowed.get('amend_runs', [])):
                            continue
                        if INSTR.search(' '.join(a)):
                            instr.append((key, c, a))  # the amending law's own instruction between two quotations
                        elif any(not (ok_am[w] > 0 and not ok_am.subtract([w])) for w in a):
                            lost2.append((c, a, b))
                    ex2 = [w for w in extra2 if not (ok_am[w] > 0 and not ok_am.subtract([w]))]
                    if lost2 or ex2:
                        bad.append((key, kind, lost2, ex2))
                elif any(' '.join(lost).startswith(r) for r in allowed.get('amend_runs', [])):
                    continue
                else:
                    left = [w for w in lost if not (ok_am[w] > 0 and not ok_am.subtract([w]))]
                    if left:
                        bad.append((key, kind, left, []))
            print(f'{name} v{k} {vs[k]["from"]} AMEND {"PASS" if not bad else "CHECK"}: {len(bad)} unit runs flagged, '
                  f'{len(instr)} instruction runs skipped', flush=True)
            if not quiet:
                for key, c, a in instr:
                    print(f'    {key} instruction ...{c} [ {" ".join(a)} ]')
                for key, kind, lost, ex2 in bad:
                    if kind.startswith('span'):
                        for c, a, b in lost:
                            print(f'    {key} {kind} DROP ...{c} [ {" ".join(a)} ] -> [ {" ".join(b)} ]')
                        if ex2:
                            print(f'    {key} {kind} not in issue: {ex2[:15]}')
                    else:
                        print(f'    {key} {kind}: {" ".join(lost[:15])}')
            good &= not bad
    return good


def main() -> int:
    args = [a for a in sys.argv[1:]]
    quiet = '--quiet' in args
    while '--pdf' in args:
        i = args.index('--pdf')
        u, p = args[i + 1].split('=', 1)
        OVERRIDE[u] = Path(p)
        del args[i:i + 2]
    while '--pdf-dir' in args:
        i = args.index('--pdf-dir')
        PDF_DIRS.append(Path(args[i + 1]))
        del args[i:i + 2]
    args = [a for a in args if not a.startswith('--')]
    paths = [Path(a) for a in args] or sorted((HERE / 'corpus.d').glob('*.json'))
    okf = HERE / 'coverage_ok.json'
    ok = json.loads(okf.read_text(encoding='utf-8')) if okf.exists() else {}
    res = {p.stem: check_part(p, ok, quiet) for p in paths}
    print('SUMMARY', 'pass' if all(res.values()) else 'FAIL', [k for k, v in res.items() if not v])
    return 0 if all(res.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
