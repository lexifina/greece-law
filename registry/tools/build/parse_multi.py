"""Multi-version parts of the Greece corpus: a law as published, then each later amendment from its own Gazette issue.

The first version of each part is exactly the single-version part parse_single.single_part() gives (the law as
published, with its annexes). Each later version applies one amending law, read in its own ΦΕΚ Α΄ issue:

- An amending article that lists word changes and then restates the article ("... και το άρθρο N διαμορφώνεται ως
  εξής:") gives the new text in the law's own words: the restatement. The parse applies every described change to the
  old text (ops below: each quoted word or phrase must appear in the instruction) and stops unless the result has the
  same words as the restatement, apart from differences listed in the part's decisions.
- Sentences, paragraphs or items the instruction adds or replaces without quoting them are taken from the
  restatement at the place the instruction names (op `take`); everything around them is still checked.
- An added article («Άρθρο NΑ ...») is a new unit; a repeal or a provision that changes no words is noted.

Each version is dated by the amending law's own commencement article (checked in its text).

    python -X utf8 scripts/greece-law/parse_multi.py [PART ...]
"""
from __future__ import annotations

import difflib
import functools
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_laws as FL  # noqa: E402
import parse_n4624 as N  # noqa: E402  (amendment helpers)
import parse_n5160 as P5  # noqa: E402  (full-width column reader, article lines)
import parse_single as PS  # noqa: E402  (the law as published)

N.CACHE = FL.CACHE
N.fek_paras = functools.lru_cache(maxsize=None)(N.fek_paras)  # each issue is read once per run

LOG: list[str] = []
DIFFS: list[str] = []
QFIX = None          # per part (build's qfix): a function applied to every quotation line read from an amending issue
ITEM_SPLIT = False   # per part (build's item_split): split_run_on also splits items run on after ':' or ', και'


# ---------------------------------------------------------------- reading an amending article

def amending(y: int, n: int, art: str, must: str) -> tuple[str, list[list[str]]]:
    """(the article's own instruction text, its whole-paragraph «…» quotations as lists of lines)."""
    body = N.amending_article(y, n, art, must)
    instr = ' '.join(p['text'] for p in body)
    qs = [[p['text'] for p in q] for q in N.quotes(body)]
    if QFIX:
        qs = [[QFIX(l) for l in q] for q in qs]
    return instr, qs


LETTERS = ['α', 'β', 'γ', 'δ', 'ε', 'στ', 'ζ', 'η', 'θ', 'ι', 'ια', 'ιβ', 'ιγ', 'ιδ', 'ιε', 'ιστ', 'ιζ', 'ιη', 'ιθ', 'κ']
SPLITS: list[str] = []
LAYOUT: list[str] = []


def _glyphs(t: str) -> str:
    return re.sub(r'C[OΟ][2₂]', 'CO2', t)


def keep_layout(old: list[str], new: list[str], what: str) -> list[str]:
    """(the 5261 part, with ITEM_SPLIT) Where restated lines are the old lines in other line breaks or with the other
    form of CO2 (CO₂, CO2, CΟ2: one word, see words()), the old lines are kept, so the history shows only the changes
    the amending law makes. Only whole lines are matched: one new line = one old line, one new line = two consecutive
    old lines, or two consecutive new lines = one old line; any other line is the restatement's. Logged."""
    if not ITEM_SPLIT:
        return new
    g = [_glyphs(l) for l in old]
    out, i, kept = [], 0, 0
    while i < len(new):
        a = _glyphs(new[i])
        b = _glyphs(new[i] + ' ' + new[i + 1]) if i + 1 < len(new) else None
        if a in g:
            k = g.index(a)
            out.append(old[k])
            kept += old[k] != new[i]
            i += 1
        elif b is not None and b in g:
            out.append(old[g.index(b)])
            kept += 1
            i += 2
        else:
            pair = next((k for k in range(len(g) - 1) if g[k] + ' ' + g[k + 1] == a), None)
            if pair is None:
                out.append(new[i])
            else:
                out += old[pair:pair + 2]
                kept += 1
            i += 1
    if kept:
        LAYOUT.append(f'{what}: {kept} restated line(s) kept in the published layout (same words; line breaks or the '
                      'form of CO2 only)')
    return out


def split_run_on(q: list[str], what: str) -> list[str]:
    """The column reader sometimes runs a paragraph or item into the line before it (a quotation's first lines
    across a column or page break). Split a line where the next paragraph number (N+1. ) or the next item letter of the
    paragraph (after β) comes γ) ) follows the end of a sentence; each split is logged."""
    out: list[str] = []
    par, item = 0, None
    for line in q:
        rest = line
        while True:
            m0 = re.match(r'^(\d+)[Α-Ω]?\. ', rest)
            if m0:
                par, item = int(m0.group(1)), None
            m1 = re.match(r'^(στ|[α-ω]{1,3})\) ', rest)
            if m1 and m1.group(1) in LETTERS:
                item = m1.group(1)
            cut = None
            for m in re.finditer(r'(?<=[.:;,»]) (?=(\d+)\. [Α-ΩΆ-Ώ«])', rest):
                if int(m.group(1)) == par + 1:
                    cut = m.start()
                    break
            nxt = LETTERS[LETTERS.index(item) + 1] if item in LETTERS[:-1] else None
            if nxt:
                for m in re.finditer(rf'(?<=[.:;,])(?<!περ\.)(?<!παρ\.) (?={nxt}\) [Α-ΩΆ-Ώα-ωά-ώ«])', rest):
                    if cut is None or m.start() < cut:
                        cut = m.start()
                    break
                if ITEM_SPLIT:
                    # an item run on after ", και" / "καθώς και" (the item before it ends there)
                    for m in re.finditer(rf'(?:(?<=, και)|(?<=καθώς και)) (?={nxt}\) [Α-ΩΆ-Ώα-ωά-ώ«])', rest):
                        if cut is None or m.start() < cut:
                            cut = m.start()
                        break
            elif ITEM_SPLIT and item is None:
                # the first item α) run on after the colon that opens the list (only when β) follows as an item)
                for m in re.finditer(r'(?<=:) (?=α\) [Α-ΩΆ-Ώα-ωά-ώ«])', rest):
                    if not re.search(r'(?:[.:;,]|, και) β\) [Α-ΩΆ-Ώα-ωά-ώ«]', rest[m.end():]):
                        break
                    if cut is None or m.start() < cut:
                        cut = m.start()
                    break
            if cut is None:
                out.append(rest)
                break
            SPLITS.append(f'{what}: line split before «{rest[cut + 1:cut + 30]}…» (run into the line before it)')
            out.append(rest[:cut])
            rest = rest[cut + 1:]
    return out


def quoted_unit(q: list[str], label: str, what: str = '') -> list[str]:
    """A quotation that is a whole article: 'Άρθρο N', title, paragraphs."""
    if q[0] != label:
        raise SystemExit(f'quotation opens with {q[0][:30]!r}, not {label!r}')
    return q[:2] + split_run_on(q[2:], what)


def words(t: str) -> list[str]:
    ws = [w for w in (N.sq(x) for x in re.split(r'[\s\-–—’]+', t)) if w]
    if ITEM_SPLIT:  # (the 5261 part) CO2 with a subscript ₂, a plain 2 or a Greek Ο: one word
        ws = ['co2' if re.fullmatch(r'c[oο][2₂]', w) else w for w in ws]
    return ws


# ---------------------------------------------------------------- applying described changes

def apply_ops(old: str, new: str, instr: str, ops: list[tuple], what: str) -> str:
    """The old text with every described change applied. ops:
    ('sub', a, b[, (s, e)])   quoted words «a» become «b» (both quoted in the instruction), once in the old text
                              (or once inside the old span from s up to e); b may be '' (deleted words)
    ('add_at', at, cited, b)  quoted words «b» added after the old words `at`, which the instruction quotes as «cited»
    ('add', after, b)         quoted words «b» added after the old words `after` (which must be quoted too)
    ('take', o1, o2, n1, n2)  the old span from o1 up to o2 replaced by the restatement's span from n1 up to n2
                              (words the instruction adds or replaces without quoting); o1 None: insert before o2;
                              o2/n2 None: to the end; o1 == o2 == '' never used
    """
    def span(t: str, a: str | None, b: str | None, tag: str) -> tuple[int, int]:
        i = t.find(a) if a is not None else (t.find(b) if b is not None else len(t))
        if a is None:
            if b is not None and t.count(b) != 1:
                raise SystemExit(f'{what}: {tag} insertion point {b!r} found {t.count(b)} times')
            return i, i
        if t.count(a) != 1:
            raise SystemExit(f'{what}: {tag} start {a!r} found {t.count(a)} times')
        if b is None:
            return i, len(t)
        j = t.find(b, i + len(a))
        if j < 0:
            raise SystemExit(f'{what}: {tag} end {b!r} not after {a!r}')
        return i, j

    def quoted(w: str) -> None:
        if w and f'«{w}»' not in instr:
            raise SystemExit(f'{what}: «{w}» is not quoted in the instruction')

    t = old
    for op in ops:
        if op[0] == 'sub':
            a, b = op[1], op[2]
            quoted(a)
            quoted(b)
            lo, hi = (span(t, op[3][0], op[3][1], 'scope') if len(op) > 3 else (0, len(t)))
            seg = t[lo:hi]
            if seg.count(a) != 1:
                raise SystemExit(f'{what}: «{a}» found {seg.count(a)} times in the old text')
            t = t[:lo] + seg.replace(a, b) + t[hi:]
        elif op[0] == 'add':
            after, b = op[1], op[2]
            quoted(after)
            quoted(b)
            lo, hi = (span(t, op[3][0], op[3][1], 'scope') if len(op) > 3 else (0, len(t)))
            seg = t[lo:hi]
            if seg.count(after) != 1:
                raise SystemExit(f'{what}: «{after}» found {seg.count(after)} times in the old text')
            t = t[:lo] + seg.replace(after, after + ' ' + b) + t[hi:]
        elif op[0] == 'del':
            # the quoted word «w» deleted after the quoted words «after»
            after, w = op[1], op[2]
            quoted(after)
            quoted(w)
            if t.count(f'{after} {w}') != 1:
                raise SystemExit(f'{what}: «{after} {w}» found {t.count(after + " " + w)} times in the old text')
            t = t.replace(f'{after} {w}', after)
        elif op[0] == 'punct':
            # after the quoted words «after» the quoted punctuation «a» is replaced by the quoted word «b»
            after, a, b = op[1], op[2], op[3]
            quoted(after)
            quoted(a)
            quoted(b)
            if t.count(after + a) != 1:
                raise SystemExit(f'{what}: «{after}{a}» found {t.count(after + a)} times in the old text')
            t = t.replace(after + a, f'{after} {b}')
        elif op[0] == 'add_at':
            # the instruction quotes the anchor in words a little different from the text (`cited`): words «b»
            # added after the text's own words `at`; the difference is logged
            at, cited, b = op[1], op[2], op[3]
            quoted(cited)
            quoted(b)
            if t.count(at) != 1:
                raise SystemExit(f'{what}: {at!r} found {t.count(at)} times in the old text')
            t = t.replace(at, at + ' ' + b)
            LOG.append(f'{what}: the instruction places its addition after «{cited}»; the text reads «{at}»')
        elif op[0] == 'sub_at':
            # quoted words «cited» become «b»; the text prints the cited words a little differently (`at`)
            at, cited, b = op[1], op[2], op[3]
            quoted(cited)
            quoted(b)
            if t.count(at) != 1:
                raise SystemExit(f'{what}: {at!r} found {t.count(at)} times in the old text')
            t = t.replace(at, b)
            LOG.append(f'{what}: the instruction quotes the replaced words as «{cited}»; the text reads «{at}»')
        elif op[0] == 'append':
            # quoted words «b» added at the end of a sentence the instruction names by its ordinal (not quoted):
            # after the old words `at` (found once in the old text); logged
            at, b = op[1], op[2]
            quoted(b)
            if t.count(at) != 1:
                raise SystemExit(f'{what}: {at!r} found {t.count(at)} times in the old text')
            t = t.replace(at, at + ' ' + b)
            LOG.append(f'{what}: «{b[:40]}…» added at the end of the sentence ending «…{at[-40:]}»')
        elif op[0] == 'take':
            o1, o2, n1, n2 = op[1:]
            i, j = span(t, o1, o2, 'old')
            k, l = span(new, n1, n2, 'new')
            t = t[:i] + new[k:l] + t[j:]
        else:
            raise SystemExit(f'unknown op {op[0]}')
    return t


def compare(expected: str, new: str, what: str, allowed: dict[tuple[str, str], str]) -> None:
    """Same words, or each difference listed in `allowed` ((old words, new words) -> the decision that accepts it)."""
    a, b = words(expected), words(new)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    diffs = [(' '.join(a[i1:i2]), ' '.join(b[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal']
    bad = [d for d in diffs if d not in allowed]
    if bad and os.environ.get('GR_DEBUG'):
        for d in bad:
            print(f'DIFF {what}: «{d[0]}» -> «{d[1]}»')
    if bad:
        raise SystemExit(f'{what}: {len(bad)} difference(s) beyond the described change: {bad[:6]}')
    for d in diffs:
        DIFFS.append(f'{what}: the restatement reads «{d[1]}» where the described change gives «{d[0]}». {allowed[d]}')


def restate(u: dict, key: str, y: int, n: int, art: str, must: str, ops: list[tuple], what: str,
            q_index: int = 0, allowed: dict | None = None, src: tuple | None = None) -> dict:
    """Article `key` replaced by the restatement in quotation `q_index` of art. `art` of Α΄ n/y, after checking it
    against the described changes `ops`."""
    if src:
        instr, qs = src[0], [src[1]]
    else:
        instr, qs = amending(y, n, art, must)
    pre = instr.split('«', 1)[0]
    old_lines = u[key]
    heads, body = N.head_split(old_lines)
    q = quoted_unit(qs[q_index], body[0], what)
    old_t, new_t = '\n'.join(body), '\n'.join(q)
    exp = apply_ops(old_t, new_t, instr, ops, what)
    compare(exp, new_t, what, allowed or {})
    u = dict(u)
    u[key] = heads + keep_layout(body, q, what)
    LOG.append(f'{what}: {key} restated ({len(body)} lines -> {len(q)}); {len(ops)} described change(s) checked; '
               f'instruction: {pre[:120]}')
    return u


def sub_quote(y: int, n: int, art: str, must: str, sub: int, what: str) -> tuple[str, list[str]]:
    """(instruction, quotation lines) of paragraph `sub` of an amending article whose paragraphs each amend."""
    body = N.amending_article(y, n, art, must)
    texts = [p['text'] for p in body]
    starts = [i for i, t in enumerate(texts) if re.match(r'^\d+\. Στ', t)]
    nums = [int(texts[i].split('.')[0]) for i in starts]
    if nums != list(range(1, len(nums) + 1)) or sub not in nums:
        raise SystemExit(f'{what}: the article\'s own paragraphs are {nums}')
    a = starts[sub - 1]
    b = starts[sub] if sub < len(starts) else len(texts)
    blk = texts[a:b]
    head, sep, rest = blk[0].partition('ως εξής:')
    if not sep:
        raise SystemExit(f'{what}: no "ως εξής:" in the instruction')
    q = ([rest.strip()] if rest.strip() else []) + blk[1:]
    if not q or not q[0].startswith('«') or not re.search(r'»\.?$', q[-1]):
        raise SystemExit(f'{what}: the restatement is not one quotation')
    q = [q[0][1:]] + q[1:]
    q[-1] = re.sub(r'»\.?$', '', q[-1])
    return head + sep, q


def restate_par(u: dict, key: str, y: int, n: int, art: str, must: str, par: str, ops: list[tuple], what: str,
                q_index: int = 0, allowed: dict | None = None, sub: int | None = None, src: tuple | None = None) -> dict:
    """Paragraph `par` of article `key` (with its items) replaced by the restated paragraph in quotation `q_index`,
    after checking it against the described changes `ops`. With `sub`, the instruction and its quotation are those
    of the amending article's own paragraph `sub` ("N. Στ…"), the quotation inline after "ως εξής:" or in the
    paragraphs that follow."""
    if src:
        instr, q = src
    elif sub:
        instr, q = sub_quote(y, n, art, must, sub, what)
    else:
        instr, qs = amending(y, n, art, must)
        q = qs[q_index]
    q = split_run_on(q, what)
    if not q[0].startswith(f'{par}. '):
        raise SystemExit(f'{what}: quotation {q_index} is not par. {par}: {q[0][:30]}')
    lines = u[key]
    i = N.find_one(lines, f'{par}. ', f'{what}: {key} par. {par}')
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
        j += 1
    old_t, new_t = '\n'.join(lines[i:j]), '\n'.join(q)
    exp = apply_ops(old_t, new_t, instr, ops, what)
    compare(exp, new_t, what, allowed or {})
    u = dict(u)
    u[key] = lines[:i] + keep_layout(lines[i:j], q, what) + lines[j:]
    LOG.append(f'{what}: {key} par. {par} restated ({j - i} line(s) -> {len(q)}); {len(ops)} described change(s) '
               'checked')
    return u


def in_part(y: int, n: int, art: str, part_head: str, next_head: str | None, what: str) -> None:
    """Article `art` of the law in Α΄ n/y lies inside the Part (ΜΕΡΟΣ) `part_head` (its body, not the contents)."""
    paras = N.fek_paras(y, n)
    pos = [i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == f'Άρθρο {art}']
    heads = [i for i, p in enumerate(paras) if p['kind'] == 'struct' and p['text'].startswith(part_head)]
    nxt = [i for i, p in enumerate(paras) if next_head and p['kind'] == 'struct' and p['text'].startswith(next_head)]
    if len(pos) != 1 or not heads or not (heads[-1] < pos[0] and (not nxt or pos[0] < nxt[-1])):
        raise SystemExit(f'{what}: art. {art} is not in {part_head}')
    LOG.append(f'{what}: art. {art} lies in {part_head}')


def add_unit(u: dict, label: str, y: int, n: int, art: str, must: str, what: str, q_index: int = 0) -> dict:
    """A new article (the quotation «Άρθρο NΑ ...») added as its own unit."""
    instr, qs = amending(y, n, art, must)
    q = quoted_unit(qs[q_index], label, what)
    m = N.ART.match(label)
    key = N.art_key(m.group(2), m.group(3))
    if key in u:
        raise SystemExit(f'{what}: {key} already exists')
    u = dict(u)
    u[key] = q
    LOG.append(f'{what}: {key} added ({len(q)} lines)')
    return u


def sub_block(y: int, n: int, art: str, must: str, sub: int, what: str,
              start_re: str = r'^\d+\. Στ') -> tuple[str, list[str]]:
    """(instruction, quotation lines) of paragraph `sub` of an amending article whose paragraphs each amend. Like
    sub_quote, but a paragraph opens only outside quotations (a restated article may itself hold "N. Στ…"), and the
    quotation may be a whole article («Άρθρο N …»)."""
    body = N.amending_article(y, n, art, must)
    texts = [p['text'] for p in body]
    depth, starts = 0, []
    for i, t in enumerate(texts):
        if depth == 0 and re.match(start_re, t):
            starts.append(i)
        depth += t.count('«') - t.count('»')
        if depth < 0:
            raise SystemExit(f'{what}: unbalanced quotation marks')
    if depth:
        raise SystemExit(f'{what}: unbalanced quotation marks')
    nums = [int(texts[i].split('.')[0]) for i in starts]
    if nums != list(range(1, len(nums) + 1)) or sub not in nums:
        raise SystemExit(f'{what}: the article\'s own paragraphs are {nums}')
    a = starts[sub - 1]
    b = starts[sub] if sub < len(starts) else len(texts)
    blk = texts[a:b]
    head, sep, rest = blk[0].partition('ως εξής:')
    if not sep:
        raise SystemExit(f'{what}: no "ως εξής:" in the instruction')
    q = ([rest.strip()] if rest.strip() else []) + blk[1:]
    if not q or not q[0].startswith('«') or not re.search(r'»\.?$', q[-1]):
        raise SystemExit(f'{what}: the restatement is not one quotation')
    q = [q[0][1:]] + q[1:]
    q[-1] = re.sub(r'»\.?$', '', q[-1])
    if QFIX:
        q = [QFIX(l) for l in q]
    return head + sep, q


ITEM_RE = r'^((στ|[α-ω]{1,3})\) |\d+[Α-Ω]?\. |[Α-Ω]\. )'


def restate_span(u: dict, key: str, scope: tuple, first: str, end_re: str, src: tuple, ops: list[tuple], what: str,
                 allowed: dict | None = None) -> dict:
    """The lines of unit `key` from the one line starting with `first` (inside the scope: from the one line starting
    with scope[0] up to the next line starting with scope[1], or the unit's end) up to the next line matching `end_re`
    (or the scope's end) replaced by the quotation in `src` (instruction, quotation lines), after checking it
    against the described changes `ops`. For an item (περ.) or a paragraph inside an annex."""
    instr, q = src
    q = split_run_on(q, what)
    if not q[0].startswith(first):
        raise SystemExit(f'{what}: the quotation does not open with {first!r}: {q[0][:30]}')
    lines = u[key]
    s0 = [i for i, l in enumerate(lines) if l.startswith(scope[0])]
    if len(s0) != 1:
        raise SystemExit(f'{what}: scope {scope[0]!r} found {len(s0)} times in {key}')
    s1 = next((i for i in range(s0[0] + 1, len(lines)) if scope[1] and lines[i].startswith(scope[1])), len(lines))
    hits = [i for i in range(s0[0], s1) if lines[i].startswith(first)]
    if len(hits) != 1:
        raise SystemExit(f'{what}: {first!r} found {len(hits)} times in the scope')
    i = hits[0]
    j = next((k for k in range(i + 1, s1) if re.match(end_re, lines[k])), s1)
    old_t, new_t = '\n'.join(lines[i:j]), '\n'.join(q)
    exp = apply_ops(old_t, new_t, instr, ops, what)
    compare(exp, new_t, what, allowed or {})
    u = dict(u)
    u[key] = lines[:i] + keep_layout(lines[i:j], q, what) + lines[j:]
    LOG.append(f'{what}: {key} {first.strip()} (after {scope[0]!r}) restated ({j - i} line(s) -> {len(q)}); '
               f'{len(ops)} described change(s) checked')
    return u


def remove_par(u: dict, key: str, y: int, n: int, art: str, must: str, par: str, phrase: str, what: str) -> dict:
    """Paragraph `par` of article `key` repealed: removed (with its items), as the corpus does for repeals."""
    body = N.amending_article(y, n, art, must)
    N.need(' '.join(p['text'] for p in body), phrase, what)
    lines = u[key]
    i = N.find_one(lines, f'{par}. ', f'{what}: {key} par. {par}')
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
        j += 1
    u = dict(u)
    u[key] = lines[:i] + lines[j:]
    LOG.append(f'{what}: {key} par. {par} repealed (removed, {j - i} line(s))')
    return u


# ---------------------------------------------------------------- the parts

def law_entry(y: int, n: int, number: int | None = None) -> tuple[str, dict]:
    num = number or N.law_number(y, n)
    key = f'n-{num}-{y}'
    return key, {'label': f'ν. {num}/{y}', 'kind': 'law', 'title': N.law_title(y, n), 'enacted': PS.signed(y, n),
                 'published': N.masthead(y, n), 'url': FL.fek_url(y, n), 'temporary_until': None, 'restores': None,
                 'note': None}


def commencement(y: int, n: int, art: str, phrase: str, what: str) -> None:
    """The amending law's commencement article holds `phrase` (checked in the issue)."""
    body = N.amending_article(y, n, art, 'Έναρξη ισχύος')
    N.need(' '.join(p['text'] for p in body), phrase, what)


def build(part_name: str, slug: str, y: int, n: int, law: int, desc: str, steps: list[dict],
          decisions: list[str], edit_other: bool = False, qfix=None, item_split: bool = False) -> dict:
    """The single-version part, then one version per step. A step: law (key), fek (y, n), number (law number when
    the issue's first line lacks the usual form), day (in force), note, edit (u -> u), check (commencement).
    edit_other: the edits also get the units that are not articles (the annexes, `parartima`) as lines; qfix and
    item_split: see QFIX and ITEM_SPLIT."""
    global QFIX, ITEM_SPLIT
    LOG.clear()
    DIFFS.clear()
    SPLITS.clear()
    LAYOUT.clear()
    QFIX, ITEM_SPLIT = qfix, item_split
    part, _ = PS.single_part(part_name, slug, y, n, law, desc)
    act = part['acts'][0]
    v0 = act['versions'][0]
    arts = {k: v['text'].rstrip('\n').split('\n') for k, v in v0['units'].items() if v['kind'] == 'art'}
    other = {k: v for k, v in v0['units'].items() if v['kind'] != 'art'}
    if {**N.as_units(arts), **other} != v0['units']:
        raise SystemExit(f'{part_name}: version 1 does not round-trip')
    meta = {k: {kk: vv for kk, vv in v.items() if kk != 'text'} for k, v in other.items()}

    def to_units(u: dict) -> dict:
        if not edit_other:
            return {**N.as_units(u), **other}
        return {**N.as_units({k: l for k, l in u.items() if k not in meta}),
                **{k: {**meta[k], 'text': '\n'.join(u[k]) + '\n'} for k in other if k in u}}

    if edit_other:
        arts = {**arts, **{k: v['text'].rstrip('\n').split('\n') for k, v in other.items()}}
        if to_units(arts) != v0['units'] or list(to_units(arts)) != list(v0['units']):
            raise SystemExit(f'{part_name}: version 1 does not round-trip with its other units')
    prev, u = v0['units'], arts
    issues = []
    for st in steps:
        sy, sn = st['fek']
        # GR-16: an amending act that is not a numbered law (an Act of Legislative Content) brings its own entry
        key, entry = st['entry'] if st.get('entry') else law_entry(sy, sn, st.get('number'))
        if key != st['law']:
            raise SystemExit(f'Α΄ {sn}/{sy} is {key}, not {st["law"]}')
        part['laws'][key] = entry
        st['check']()
        u = st['edit'](u)
        units = to_units(u)
        ch = N.changed(prev, units)
        if not ch:
            raise SystemExit(f'{part_name}: {key} changes nothing')
        day = st['day'] or entry['published']
        if st.get('same_day') and day != act['versions'][-1]['from'] or \
                not st.get('same_day') and day <= act['versions'][-1]['from']:
            raise SystemExit(f'{part_name}: {key} ({day}) is not after the version before it')
        url = FL.fek_url(sy, sn)
        act['versions'].append({'from': day, **({'same_day': True} if st.get('same_day') else {}),
                                'source_url': url, 'sha256': N.sha(url),
                                'changes': {k: units.get(k) for k in ch}, 'credits': {k: [key] for k in ch},
                                'note': st['note']})
        issues.append(f'{sn}/{sy} ({entry["label"]})')
        prev = units
    part['sources'].append({
        'name': f'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: the issues amending ν. {law}/{y}',
        'url': 'https://ia37rg02wpsa01.blob.core.windows.net/fek/', 'retrieved': '2026-11-01', 'requests': len(issues),
        'licence': part['sources'][0]['licence'],
        'notes': 'Series Α΄ issues ' + ', '.join(issues) + ', each with a text layer; issue number, date and law '
                 'number checked against each issue.'})
    first = part['decisions'][0]
    if 'its only version: no later law amends it' not in first:
        raise SystemExit(f'{part_name}: unexpected first decision')
    part['decisions'][0] = (f'ν. {law}/{y} ({desc}) is given as published in ΦΕΚ Α΄ {n}/{y}, then with each later '
                            'amendment, read in the amending law\'s own Gazette issue: ' + '; '.join(issues) + '.')
    part['decisions'][1:1] = decisions + [
        'Where an amending article lists its changes and then restates the article, the restatement (the amending '
        'law\'s own text) is used, and the parse checks that the listed changes applied to the old text give it; '
        'words the instruction adds or replaces without quoting them are taken from the restatement at the place it '
        'names. Any other difference is listed below with the decision that accepts it.']
    part['decisions'] += ([f'Parse log: {l}' for l in LOG] + [f'Restated wording: {l}' for l in DIFFS]
                          + [f'Reading the restatement: {l}' for l in SPLITS]
                          + [f'Layout: {l}' for l in LAYOUT])
    part['ai_use'] = [f'ν. {law}/{y} part: none. No model wrote or altered legal text; a model (Claude) wrote '
                      'parse_single.py and parse_multi.py, which read every word from the Gazette PDFs.']
    QFIX, ITEM_SPLIT = None, False
    return part


# ---------------------------------------------------------------- ν. 5178/2025

def p5178() -> dict:
    def e5301(u: dict) -> dict:
        return restate(u, 'art-037', 2026, 74, '78', 'άρθρου 37 ν. 5178/2025', [
            ('sub', 'απαλλαγής από την επιβολή', 'αναστολής της επιβολής'),
            ('sub', 'έως τις 31.12.2025', 'έως τις 31.12.2026'),
        ], 'ν. 5301/2026 art. 78')

    def e5322(u: dict) -> dict:
        par1 = ('1. Θεσπίζεται', '\n2. Η μεταφορά')
        u = restate(u, 'art-032', 2026, 117, '51', 'άρθρου 32 ν. 5178/2025', [
            # α) par. 1
            ('sub', 'και το κέντρο βιοτικών δραστηριοτήτων', '', par1),
            ('add', 'με την απόφαση της παρ. 9,', 'ή από τα άλλα κράτη μέλη της Ευρωπαϊκής Ένωσης,'),
            ('add', 'Ανατολικής Μακεδονίας και Θράκης', 'και στους πρόσθετους δήμους και δημοτικές ενότητες που '
             'δύναται να ορίζονται ως δήμοι και δημοτικές ενότητες μετεγκατάστασης με την απόφαση της παρ. 9'),
            ('take', None, '\n2. Η μεταφορά', ' Είναι δυνατή η χρηματοδότηση', '\n2. Η μεταφορά'),  # αδ) 2nd sentence
            # β) par. 2: περ. β) gains a second sentence; περ. γ) repealed
            ('take', None, '\nγ) Βεβαίωση περί εργασίας', '\nΑν ο αιτών είναι απόφοιτος', '\nγ) Καταργείται'),
            ('take', '\nγ) Βεβαίωση περί εργασίας', '\nδ) Σε περίπτωση', '\nγ) Καταργείται', '\nδ) Σε περίπτωση'),
            # γ) par. 3 περ. β): third, fourth and fifth sentences
            ('take', None, '\n4. Το ύψος', '\nΑν ο αιτών κατοικούσε', '\n4. Το ύψος'),
            # δ) par. 4 replaced
            ('take', '\n4. Το ύψος', '\n5. Η οικονομική', '\n4. Το ύψος', '\n5. Η οικονομική'),
            # ε) par. 5
            ('add_at', 'νέας εγκατάστασης του αιτούντος', 'νέας εγκατάστασης αιτούντος',
             'με την επιφύλαξη της προκαταβολής της πρώτης δόσης οικονομικής ενίσχυσης για την κάλυψη των εξόδων '
             'μετακίνησης στην περιοχή μετεγκατάστασης της παρ. 4'),
            # στ) par. 9
            ('add', 'οι προϋποθέσεις χορήγησης της οικονομικής ενίσχυσης,', 'οι όροι συμμετοχής των κατοίκων των άλλων '
             'κρατών μελών της Ευρωπαϊκής Ένωσης και τα δικαιολογητικά απόδειξης της κατοικίας και της υποβολής '
             'δήλωσης στα κράτη αυτά, οι όροι και οι προϋποθέσεις για να ορίζεται ως ωφελούμενη μονάδα απόφοιτος '
             'τμήματος ανώτατου εκπαιδευτικού ιδρύματος με έδρα εντός της περιφερειακής ενότητας στην οποία βρίσκεται '
             'ο δήμος ή η δημοτική ενότητα μετεγκατάστασης, οι όροι και οι προϋποθέσεις για τη χορήγηση προκαταβολής '
             'της πρώτης δόσης της οικονομικής ενίσχυσης για την κάλυψη εξόδων μετακίνησης,'),
            ('add', 'η διαδικασία έγκρισης και καταβολής της οικονομικής ενίσχυσης,', 'και της προκαταβολής της '
             'πρώτης δόσης της οικονομικής ενίσχυσης για την κάλυψη των εξόδων μετακίνησης,'),
            ('sub', 'Με όμοια απόφαση', 'Με την ίδια ή όμοια απόφαση', ('9. Με', None)),
        ], 'ν. 5322/2026 art. 51', allowed=A5322)
        u = add_unit(u, 'Άρθρο 32Α', 2026, 117, '52', 'ν. 5178/2025', 'ν. 5322/2026 art. 52 par. 1', q_index=0)
        return add_unit(u, 'Άρθρο 40Α', 2026, 117, '52', 'ν. 5178/2025', 'ν. 5322/2026 art. 52 par. 2', q_index=1)

    restated_rule = ('The restatement is the amending law\'s own text, so it governs (the rule decided for '
                     'ν. 5067/2023): this change is made by ν. 5322/2026 itself.')
    accent = ('The published text of ν. 5178/2025 carries a doubled accent mark on this word in its text layer (a '
              'combining acute after an accented letter); the restatement prints the word plainly. Not a change of '
              'wording.')
    A5322 = {('ή εικονικότητας πρόσ ληψης', ''): 'Par. 7 also loses the words «ή εικονικότητας πρόσληψης» (fictitious '
             'hiring), which the instruction does not list. ' + restated_rule,
             ('και τους εργοδότες αντιστοίχως', ''): 'Par. 7 also loses the words «και τους εργοδότες αντιστοίχως» '
             '(the employers), which the instruction does not list. ' + restated_rule,
             ('κοινή́', 'κοινή'): accent, ('εφαρμογή́', 'εφαρμογή'): accent}
    steps = [
        {'law': 'n-5301-2026', 'fek': (2026, 74), 'day': None, 'edit': e5301,
         'check': lambda: commencement(2026, 74, '127', '1. Με την επιφύλαξη των παρ. 2 έως 5, ο παρών νόμος ισχύει '
                                       'από τη δημοσίευσή του', 'ν. 5301/2026 art. 127'),
         'note': 'ν. 5301/2026 art. 78 (ΦΕΚ Α΄ 74/2026), in force on publication (art. 127 par. 1; art. 78 is in Part '
                 'Ε, which par. 2-5 do not defer): art. 37 now suspends the special tax on television advertising for '
                 'regional broadcasters until 31.12.2026; the article is restated.'},
        {'law': 'n-5322-2026', 'fek': (2026, 117), 'day': None, 'edit': e5322,
         'check': lambda: commencement(2026, 117, '99', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του',
                                       'ν. 5322/2026 art. 99'),
         'note': 'ν. 5322/2026 arts. 51-52 (ΦΕΚ Α΄ 117/2026), in force on publication (art. 99): the Demographic '
                 'Development Programme of art. 32 opened to residents of other EU member states and to graduates, '
                 'with an advance on the first instalment (art. 32 restated); arts. 32Α and 40Α added (processing of '
                 'personal data).'},
    ]
    return build('40-n5178', 'nomos-5178-2025', 2025, 22, 5178,
                 'gender balance among directors of listed companies', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-01. Amending: '
                     'ν. 5301/2026 art. 78 and ν. 5322/2026 arts. 51-52. ν. 5322/2026 art. 59 (how applications '
                     'already made are handled) changes no words of the law. Issues after Α΄ 177/2026 were not '
                     'searched.'])


def add_par(u: dict, key: str, y: int, n: int, art: str, must: str, par: str, instr_phrase: str, what: str,
            q_index: int = 0) -> dict:
    """A paragraph («N. …», a whole-paragraph quotation) added at the end of article `key`."""
    instr, qs = amending(y, n, art, must)
    N.need(instr, instr_phrase, what)
    q = split_run_on(qs[q_index], what)
    if not q[0].startswith(f'{par}. '):
        raise SystemExit(f'{what}: the quotation is not par. {par}: {q[0][:30]}')
    lines = u[key]
    nums = [int(m.group(1)) for l in lines for m in [re.match(r'^(\d+)\. ', l)] if m]
    if not nums or nums[-1] != int(par) - 1:
        raise SystemExit(f'{what}: {key} does not end with par. {int(par) - 1}')
    u = dict(u)
    u[key] = lines + q
    LOG.append(f'{what}: {key} gains par. {par} at its end ({len(q)} line(s))')
    return u


def repeal_unit(u: dict, key: str, y: int, n: int, art: str, must: str, phrases: list[str], what: str) -> dict:
    """A whole article repealed: its unit is removed (the file is deleted on that day)."""
    body = N.amending_article(y, n, art, must)
    t = ' '.join(p['text'] for p in body)
    for ph in phrases:
        N.need(t, ph, what)
    if key not in u:
        raise SystemExit(f'{what}: no {key}')
    heads, _ = N.head_split(u[key])
    if heads:
        raise SystemExit(f'{what}: {key} opens with headings {heads}; removing it would lose them')
    u = dict(u)
    del u[key]
    LOG.append(f'{what}: {key} repealed (removed)')
    return u


# ---------------------------------------------------------------- ν. 5188/2025

def p5188() -> dict:
    def e5305(u: dict) -> dict:
        return restate(u, 'art-020', 2026, 85, '19', 'άρθρου 20 ν. 5188/2025', [
            ('take', '\nΗλεκτρονική εφαρμογή «mystreet» για', '\n1. Οι πολίτες', '\nΗλεκτρονική εφαρμογή', '\n1. Οι πολίτες'),
            ('take', None, '\n3. Το Υπουργείο', ' Η ως άνω εφαρμογή δύναται', '\n3. Το Υπουργείο'),
        ], 'ν. 5305/2026 art. 19')

    def e5314(u: dict) -> dict:
        return repeal_unit(u, 'art-029', 2026, 103, '773', 'Καταργούμενες διατάξεις',
                           ['Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:',
                            '3. το άρθρο 29 του ν. 5188/2025 (Α’ 49),'], 'ν. 5314/2026 art. 773 par. Β no. 3')

    def e5321(u: dict) -> dict:
        u = add_unit(u, 'Άρθρο 20Α', 2026, 114, '45', 'Προσθήκη άρθρου 20Α στον ν. 5188/2025',
                     'ν. 5321/2026 art. 45 par. 1', q_index=0)
        return add_par(u, 'art-025', 2026, 114, '45', 'Προσθήκη άρθρου 20Α στον ν. 5188/2025', '3',
                       'Στο άρθρο 25 του ν. 5188/2025, περί εξουσιοδοτικών διατάξεων, προστίθεται παρ. 3 ως εξής:',
                       'ν. 5321/2026 art. 45 par. 2', q_index=1)

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2, 3 και 4.', 'ν. 5314/2026 art. 774')
        # ν. 5321/2026 art. 54 later replaced art. 773 of the Code (corrections); its par. Β still repeals art. 29
        body = N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής Αυτοδιοίκησης')
        N.need(' '.join(p['text'] for p in body), '3. το άρθρο 29 του ν. 5188/2025 (Α’ 49),', 'ν. 5321/2026 art. 54')
        LOG.append('ν. 5321/2026 art. 54 replaces art. 773 of the Local Government Code (corrections); its new par. Β '
                   'no. 3 repeals art. 29 of ν. 5188/2025 in the same words, so it changes nothing here')

    steps = [
        {'law': 'n-5305-2026', 'fek': (2026, 85), 'day': None, 'edit': e5305,
         'check': lambda: commencement(2026, 85, '43', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην '
                                       'Εφημερίδα της Κυβερνήσεως, με την επιφύλαξη της παρ. 2.', 'ν. 5305/2026 art. 43'),
         'note': 'ν. 5305/2026 art. 19 (ΦΕΚ Α΄ 85/2026), in force on publication (art. 43 par. 1; par. 2 concerns '
                 'another law): art. 20 gets a new title and a third sentence in par. 2 (the «mystreet» application '
                 'may carry other public-space data); the article is restated.'},
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Β no. 3: art. 29 repealed '
                 'from the Code\'s commencement, its publication (art. 774 par. 1).'},
        {'law': 'n-5321-2026', 'fek': (2026, 114), 'day': None, 'edit': e5321,
         'check': lambda: commencement(2026, 114, '58', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του',
                                       'ν. 5321/2026 art. 58'),
         'note': 'ν. 5321/2026 art. 45 (ΦΕΚ Α΄ 114/2026), in force on publication (art. 58): art. 20Α added (register '
                 'of access points and parking places for persons with disabilities); art. 25 gains par. 3.'},
    ]
    return build('41-n5188', 'nomos-5188-2025', 2025, 49, 5188, 'measures implementing the Data Governance Act',
                 steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-01. Amending: '
                     'ν. 5305/2026 art. 19, ν. 5314/2026 art. 773 (repeal of art. 29) and ν. 5321/2026 art. 45 (which '
                     'does amend ν. 5188/2025: it adds art. 20Α and art. 25 par. 3). Other mentions (Α΄ 58/2026, '
                     'ν. 5314/2026 art. 576, ν. 5321/2026 arts. 21 and 54) only refer to it. Issues after Α΄ '
                     '177/2026 were not searched.'])


# ---------------------------------------------------------------- ν. 5255/2025

def p5255() -> dict:
    M108 = 'ν. 5255/2025'

    def e5301(u: dict) -> dict:
        return restate(u, 'art-060', 2026, 74, '83', 'Τροποποίηση άρθρου 60 ν. 5255/2025', [
            ('add', 'ή προνοιακού χαρακτήρα', ', ούτε στο όριο των επιδοτήσεων της παρ. 1 του άρθρου 48 του Κώδικα '
             'Φόρου Προστιθέμενης Αξίας (Κώδικας Φ.Π.Α., ν. 5144/2024, Α’ 162), περί ειδικού καθεστώτος αγροτών'),
        ], 'ν. 5301/2026 art. 83 par. 1')

    def e5297(u: dict) -> dict:
        return restate_par(u, 'art-038', 2026, 64, '245', 'Τροποποίηση παρ. 6 άρθρου 38 ν. 5255/2025', '6', [
            ('add', 'για το έτος 2026', 'και μέχρι την κατά το δεύτερο εδάφιο μεταφορά πιστώσεων στον νέο Ειδικό '
             'Φορέα της παρ. 1 του άρθρου 30'),
            ('sub_at', 'Υπουργείου Ανάπτυξης (Ε.Φ. 1036-401-0000000 «Διυπηρεσιακή Μονάδα Ελέγχου Αγοράς» και '
             '1036- 801-0000000 «Δαπάνες της Ανεξάρτητης Διοικητικής Αρχής «Συνήγορος του Καταναλωτή» που καλύπτονται '
             'από τον προϋπολογισμό του Υπουργείου Ανάπτυξης») και σε περίπτωση που αυτές δεν επαρκούν, δύνανται να '
             'καλύπτονται από τις υπό κατανομή πιστώσεις του ειδικού φορέα του προϋπολογισμού του Υπουργείου Εθνικής '
             'Οικονομίας και Οικονομικών «Γενικές Κρατικές Δαπάνες», σύμφωνα με το άρθρο 59 του ν. 4270/2014',
             'Υπουργείου Ανάπτυξης (Ε.Φ. 1036-401-0000000 «Διυπηρεσιακή Μονάδα Ελέγχου Αγοράς» και '
             '1036801-0000000 «Δαπάνες της Ανεξάρτητης Διοικητικής Αρχής «Συνήγορος του Καταναλωτή» που καλύπτονται '
             'από τον προϋπολογισμό του Υπουργείου Ανάπτυξης») και σε περίπτωση που αυτές δεν επαρκούν, δύνανται να '
             'καλύπτονται από τις υπό κατανομή πιστώσεις του ειδικού φορέα του προϋπολογισμού του Υπουργείου Εθνικής '
             'Οικονομίας και Οικονομικών «Γενικές Κρατικές Δαπάνες», σύμφωνα με το άρθρο 59 του ν. 4270/2014',
             'προϋπολογισμού του Ε.Φ. 1036-401-0000000 («Διυπηρεσιακή Μονάδα Ελέγχου Αγοράς»), του Ε.Φ. '
             '1036-801-0000000 («Δαπάνες της Ανεξάρτητης Διοικητικής Αρχής «Συνήγορος του Καταναλωτή»») και του Ε.Φ. '
             '1036-205-0000000 («Γενική Γραμματεία Εμπορίου») του προϋπολογισμού του Υπουργείου Ανάπτυξης, κατά το '
             'μέρος που αναλογούν σε δαπάνες των υπηρεσιών της παρ. 1 του άρθρου 14'),
            ('take', None, ' Για κάθε ένα από τα επόμενα έτη', ' Πιστώσεις για εκκρεμείς δεσμεύσεις', ' Για κάθε ένα από τα επόμενα έτη'),  # β)
        ], 'ν. 5297/2026 art. 245 par. 1', allowed=A5297)

    def e5317(u: dict) -> dict:
        w = 'ν. 5317/2026 art. 117'
        must = 'ν. 5255/2025'
        u = restate_par(u, 'art-009', 2026, 108, '117', must, '1', [
            ('sub', ', εξαιρουμένης της διαμεσολαβητικής αρμοδιότητας του Υποδιοικητή Συνηγόρου του Καταναλωτή', ''),
            ('add', 'προσωπικού τους', ', κατά τρόπο που δεν θίγει τη λειτουργική ανεξαρτησία του Υποδιοικητή '
             'Συνηγόρου του Καταναλωτή, όταν αυτός ασκεί τη διαμεσολαβητική του αρμοδιότητα'),
            ('take', None, None, '\nη) Επικαιροποιεί', None),  # β) item η) added
        ], f'{w} par. 1', sub=1, allowed=A5317)
        u = restate_par(u, 'art-013', 2026, 108, '117', must, '8', [
            ('sub', 'αρχαιότερο Βοηθό Συνήγορο', 'Γενικό Διευθυντή της Εξωδικαστικής Επίλυσης Διαφορών')],
            f'{w} par. 2', sub=2, allowed=A5317)
        u = restate_par(u, 'art-018', 2026, 108, '117', must, '6', [
            ('sub', ', μη συμπεριλαμβανομένων της οικογενειακής παροχής και του επιδόματος θέσης ευθύνης,',
             ', η οποία συμψηφίζεται σύμφωνα με το άρθρο 53 του ν. 5313/2026 (Α’ 102), μη συμπεριλαμβανομένου του '
             'επιδόματος θέσης ευθύνης,')], f'{w} par. 3', sub=3, allowed=A5317)
        u = restate_par(u, 'art-023', 2026, 108, '117', must, '3', [
            ('add', 'Στους Ελεγκτές της Αρχής', ', που είναι εγγεγραμμένοι στο Μητρώο Ελεγκτών της παρ. 8 του άρθρου '
             '15 του ν. 4753/2020 (Α’ 227),')], f'{w} par. 4', sub=4, allowed=A5317)
        u = restate_par(u, 'art-037', 2026, 108, '117', must, '8', [
            ('sub', 'ένα (1) επιπλέον έτος', 'δύο (2) επιπλέον έτη')], f'{w} par. 5', sub=5, allowed=A5317)
        u = restate_par(u, 'art-038', 2026, 108, '117', must, '2', [
            ('sub', 'που δεν υπερβαίνει τους έξι (6) μήνες', 'που δεν υπερβαίνει τους δώδεκα (12) μήνες')],
            f'{w} par. 6', sub=6, allowed=A5317)
        return restate_par(u, 'art-038', 2026, 108, '117', must, '4', [
            ('sub', 'έξι (6) μήνες', 'τους δώδεκα (12) μήνες')], f'{w} par. 7', sub=7, allowed=A5317)

    A5297: dict = {}
    A5317 = {('στο', 'στη'): 'In art. 23 par. 3 the instruction adds «που είναι εγγεγραμμένοι στο Μητρώο Ελεγκτών», '
             'while the restatement prints «εγγεγραμμένοι στη Μητρώο Ελεγκτών» (so in the Gazette text layer too). '
             'The restatement is the amending law’s own text, so it governs and is kept as printed; «στη» there is '
             'evidently a misprint for «στο».',
             ('και', ''):'ν. 5317/2026 art. 117 par. 1 restates art. 9 par. 1 «μετά από νομοτεχνικές βελτιώσεις» '
             '(after drafting improvements), in its own words: its items now open with a capital and end with a full '
             'stop, so the «και» before item ζ) goes. The restatement is the amending law’s own text and governs.'}

    def chk5301() -> None:
        commencement(2026, 74, '127', '5. Η ισχύς του άρθρου 83, περί μη υπολογισμού της ενίσχυσης', M108)
        commencement(2026, 74, '127', 'αρχίζει από την 28η Νοεμβρίου 2025.', 'ν. 5301/2026 art. 127 par. 5')

    def chk5317() -> None:
        commencement(2026, 108, '143', '1. Με την επιφύλαξη των παρ. 2, 3 και 4, η ισχύς του παρόντος νόμου αρχίζει '
                     'από τη δημοσίευσή του', 'ν. 5317/2026 art. 143')
        in_part(2026, 108, '117', 'ΜΕΡΟΣ ΣΤ’', 'ΜΕΡΟΣ Ζ’', 'ν. 5317/2026')

    steps = [
        {'law': 'n-5297-2026', 'fek': (2026, 64), 'day': None, 'edit': e5297,
         'check': lambda: commencement(2026, 64, '257', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του',
                                       'ν. 5297/2026 art. 257'),
         'note': 'ν. 5297/2026 art. 245 par. 1 (ΦΕΚ Α΄ 64/2026), in force on publication (art. 257): art. 38 par. 6 '
                 '(the Authority\'s 2026 expenses) restated with new second to fifth sentences.'},
        {'law': 'n-5301-2026', 'fek': (2026, 74), 'day': None, 'edit': e5301, 'check': chk5301,
         'note': 'ν. 5301/2026 art. 83 par. 1 (ΦΕΚ Α΄ 74/2026), published on 15 May 2026 and in force from 28 '
                 'November 2025 (art. 127 par. 5): the support of art. 60 is not counted towards the VAT threshold '
                 'for farmers; the article is restated. Dated by its publication (the retroactive effect is noted in '
                 'the decisions).'},
        {'law': 'n-5317-2026', 'fek': (2026, 108), 'day': None, 'edit': e5317, 'check': chk5317,
         'note': 'ν. 5317/2026 art. 117 (ΦΕΚ Α΄ 108/2026), in force on publication (art. 143 par. 1; art. 117 is in '
                 'Part ΣΤ, which pars. 2-4 do not defer): arts. 9 par. 1, 13 par. 8, 18 par. 6, 23 par. 3, 37 par. 8 '
                 'and 38 pars. 2 and 4 amended and restated.'},
    ]
    return build('46-n5255', 'nomos-5255-2025', 2025, 219, 5255,
                 'the Independent Authority for Market Control and Consumer Protection', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-01. Amending: '
                     'ν. 5297/2026 art. 245 par. 1, ν. 5301/2026 art. 83 par. 1 and ν. 5317/2026 art. 117. ν. '
                     '5297/2026 art. 245 par. 2 and ν. 5301/2026 art. 83 par. 2 are the amending laws\' own provisions '
                     'and change no words of ν. 5255/2025. Issues after Α΄ 177/2026 were not searched.',
                     'ν. 5301/2026 (ΦΕΚ Α΄ 74/2026, published 15 May 2026) has retroactive effect from 28 November '
                     '2025 for its art. 83 (art. 127 par. 5), the day ν. 5255/2025 itself was published; its change '
                     '(art. 60) is dated by its publication, 15 May 2026, as for every retroactive change in the '
                     'corpus. The text of art. 60 as amended applies from 28 November 2025.'])


# ---------------------------------------------------------------- ν. 5261/2025

def small_co2(y: int, n: int, anchors: tuple[str, str]) -> int:
    """On the pages from the one holding anchors[0] to the one holding anchors[1] (the amending articles), the number
    of «2»s set after «CO» as their own span in smaller type than the «CO» (a subscript the text layer reads as a plain
    2); stops if such a page also has a «CO2» in one span (which would be printed as a plain 2)."""
    import fitz
    doc = fitz.open(FL._key(FL.fek_url(y, n), None))
    pages = [[i for i, pg in enumerate(doc) if a in re.sub(r'\s+', ' ', pg.get_text())] for a in anchors]
    if any(len(p) != 1 for p in pages):
        raise SystemExit(f'Α΄ {n}/{y}: anchors found on pages {pages}')
    small = 0
    for i in range(pages[0][0], pages[1][0] + 1):
        for b in doc[i].get_text('dict')['blocks']:
            for l in b.get('lines', []):
                sp = l['spans']
                for j, s in enumerate(sp):
                    if 'CO2' in s['text']:
                        raise SystemExit(f'Α΄ {n}/{y} page {i + 1}: «CO2» in one span')
                    if s['text'].endswith('CO') and j + 1 < len(sp) and sp[j + 1]['text'].startswith('2'):
                        if not sp[j + 1]['size'] < s['size'] - 1:
                            raise SystemExit(f'Α΄ {n}/{y} page {i + 1}: a «2» after «CO» in the same type size')
                        small += 1
    return small


def p5261() -> dict:
    W = 'ν. 5299/2026 art. 68'
    M68 = 'Διόρθωση παροραμάτων στον ν. 5261/2025'

    def blk(sub: int) -> tuple[str, list[str]]:
        return sub_block(2026, 67, '68', M68, sub, f'{W} par. {sub}')

    def e5299(u: dict) -> dict:
        # art. 68: errata corrected, each paragraph restated
        u = restate_par(u, 'art-007', 2026, 67, '68', M68, '2', [
            ('sub', 'δέσμευσης', 'λειτουργίας που περιέχει τη δυνατότητα δέσμευσης,')], f'{W} par. 1', src=blk(1))
        u = restate_par(u, 'art-017', 2026, 67, '68', M68, '3', [
            ('sub', 'τα οποία', 'τις εγκαταστάσεις δέσμευσης των οποίων', ('Αντίγραφο', None))], f'{W} par. 2',
            src=blk(2))
        u = restate(u, 'art-023', 2026, 67, '68', M68, [
            ('sub', 'πληρούται η περ. γ)', 'πληρούνται οι όροι της περ. γ)'),
            ('del', 'διαθέσιμο στην Ευρωπαϊκή Επιτροπή', 'και'),
            ('sub', 'έκδοσή τους', 'διατύπωσή τους')], f'{W} par. 3', src=blk(3))
        u = restate_span(u, 'art-027', ('2. ', '3. '), 'α) ', ITEM_RE, blk(4), [
            ('punct', 'δεκαπέντε (15) ετών', ',', 'και')], f'{W} par. 4', allowed=A5299)
        u = restate_par(u, 'art-040', 2026, 67, '68', M68, '8', [
            ('add', 'εγγυήσεων', 'ή άλλων ισοδύναμων με αυτές εχεγγύων', ('β) οι αποδεκτοί', None))],
            f'{W} par. 5', src=blk(5))
        # the annexes are one unit: each change is placed inside its annex, chapter and paragraph
        ann = u['parartima']
        heads = {h: [i for i, l in enumerate(ann) if (l == h if h.startswith('ΠΑΡΑΡΤΗΜΑ') else l.startswith(h))] for h in
                 ('ΠΑΡΑΡΤΗΜΑ Ι', 'ΠΑΡΑΡΤΗΜΑ ΙΙ', 'ΠΑΡΑΡΤΗΜΑ IV', 'ΠΑΡΑΡΤΗΜΑ V', 'Φάση 3.1', 'Φάση 3.2',
                                       'Οι ακόλουθες επιλογές εξετάζονται', '3. Επικαιροποίηση του σχεδίου',
                                       'Β. Παρακολούθηση μετά το κλείσιμο')}
        if any(len(v) != 1 for v in heads.values()):
            raise SystemExit(f'{W}: annex anchors not found once each: {heads}')
        one = {h: v[0] for h, v in heads.items()}
        if not (one['ΠΑΡΑΡΤΗΜΑ Ι'] < one['Φάση 3.1'] < one['Φάση 3.2'] < one['ΠΑΡΑΡΤΗΜΑ ΙΙ']
                < one['ΠΑΡΑΡΤΗΜΑ IV'] < one['Οι ακόλουθες επιλογές εξετάζονται'] < one['3. Επικαιροποίηση του σχεδίου']
                < one['Β. Παρακολούθηση μετά το κλείσιμο'] < one['ΠΑΡΑΡΤΗΜΑ V']):
            raise SystemExit(f'{W}: annex headings out of order: {heads}')
        if not ann[one['ΠΑΡΑΡΤΗΜΑ IV'] + 1].endswith('Α. Κατάρτιση και επικαιροποίηση του σχεδίου παρακολούθησης') \
                or not ann[one['ΠΑΡΑΡΤΗΜΑ IV'] + 3].startswith('2. Κατάρτιση του σχεδίου'):
            raise SystemExit(f'{W}: Annex IV does not open with its Chapter A and par. 2')
        LOG.append(f'{W} pars. 6-8: Annex I Phase 3.1 par. 2; Annex IV Chapter A par. 2 (its sixth sentence opens '
                   '«Οι ακόλουθες επιλογές εξετάζονται») and par. 3, located inside the annexes unit')
        u = restate_span(u, 'parartima', ('Φάση 3.1', 'Φάση 3.2'), '2. ', r'^(\d+\. |Φάση )', blk(6), [
            ('sub_at', 'και επακόλουθες αντιδράσεις, ιδίως τη μεταβολή του pH, τον σχηματισμό ορυκτών και τη '
             'συνεκτίμηση εκπόνησης αντιδραστικών μοντέλων για την αξιολόγηση των επενεργειών',
             'και επακόλουθες αντιδράσεις, ιδίως τη μεταβολή του pH, τον σχηματισμό ορυκτών και τη συνεκτίμηση '
             'αντιδραστικών μοντέλων για την αξιολόγηση των επενεργειών',
             'και επακόλουθων αντιδράσεων, ιδίως της μεταβολής του pH, του σχηματισμού ορυκτών και της συνεκτίμησης '
             'αντιδραστικών μοντέλων για την αξιολόγηση των επενεργειών')], f'{W} par. 6', allowed=A5299)
        u = restate_span(u, 'parartima', ('Οι ακόλουθες επιλογές εξετάζονται', '3. Επικαιροποίηση του σχεδίου'),
                         'γ) ', ITEM_RE, blk(7), [('sub', 'πέραν', '')], f'{W} par. 7', allowed=A5299)
        u = restate_span(u, 'parartima', ('3. Επικαιροποίηση του σχεδίου', 'Β. Παρακολούθηση μετά το κλείσιμο'),
                         'α) ', ITEM_RE, blk(8), [('sub', 'προσδίδεται', 'εξασφαλίζεται')], f'{W} par. 8',
                         allowed=A5299)
        # art. 69: art. 36Α added
        u = add_unit(u, 'Άρθρο 36Α', 2026, 67, '69', 'Προσθήκη άρθρου 36Α στον ν. 5261/2025', 'ν. 5299/2026 art. 69')
        # art. 88 par. 2: art. 75 par. 9 repealed
        return remove_par(u, 'art-075', 2026, 67, '88', 'Τροποποίηση παρ. 1 άρθρου 45 ν. 5106/2024', '9',
                          '2. Η παρ. 9 του άρθρου 75 του ν. 5261/2025 (Α’ 231) καταργείται.', 'ν. 5299/2026 art. 88 par. 2')

    co2 = ('In the restatements and the added article of ν. 5299/2026 (arts. 68-69, ΦΕΚ Α΄ 67/2026) the 2 of CO₂ is '
           'set as a smaller digit after «CO» (8 pt against 10.5 pt), which the text layer reads as a plain 2; the '
           'parse checks that every such 2 on those pages is in the smaller type and writes it CO₂, as ν. 5261/2025 '
           'itself mostly does. Its annexes keep the forms their own text layer gives (CO2, and in Annex IV CΟ2 with a '
           'Greek Ο); the check of described changes reads these forms as one word, and a restated line that differs '
           'from the published line only in this form or in line breaks keeps the published line (listed under '
           'Layout), so each change shows only the amending law\'s changes. Not a change of wording.')
    A5299 = {('ευρώ/ τόνο', 'ευρώ/τόνο'): 'Art. 27 par. 2 περ. α): the published text reads «ευρώ/ τόνο», the '
             'restatement «ευρώ/τόνο»; the same words, spaced differently.',
             ('', 'εκπόνησης'): 'Annex I Phase 3.1 par. 2 περ. ια): the instruction quotes the replaced words without '
             '«εκπόνησης» (the published text reads «τη συνεκτίμηση εκπόνησης αντιδραστικών μοντέλων») and the new '
             'words without it too, but the restatement keeps it («της συνεκτίμησης εκπόνησης αντιδραστικών '
             'μοντέλων»). The restatement is the amending law\'s own text, so it governs; the word stays, as before.'}

    def chk5299() -> None:
        commencement(2026, 67, '113', 'Ο παρών νόμος ισχύει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, '
                     'εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 5299/2026 art. 113')
        for art, must in (('68', M68), ('69', 'Προσθήκη άρθρου 36Α στον ν. 5261/2025'),
                          ('88', 'Τροποποίηση παρ. 1 άρθρου 45 ν. 5106/2024')):
            t = ' '.join(p['text'] for p in N.amending_article(2026, 67, art, must))
            if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|από την έναρξη', t, re.I):
                raise SystemExit(f'ν. 5299/2026 art. {art} has words on its own commencement: read it')
        plain = sum(' '.join(p['text'] for p in N.amending_article(2026, 67, art, must)).count('CO2')
                    for art, must in (('68', M68), ('69', 'Προσθήκη άρθρου 36Α στον ν. 5261/2025')))
        small = small_co2(2026, 67, ('λειτουργίας που περιέχει τη δυνατότητα δέσμευσης',
                                     'εξασφαλίζεται εμπιστοσύνη στις παραδοχές'))
        if plain != small:
            raise SystemExit(f'ν. 5299/2026 arts. 68-69: {plain} «CO2» read, {small} small-type 2s on their pages')
        LOG.append(f'ν. 5299/2026 arts. 68-69: {plain} «CO2» in the text layer, {small} smaller-type 2s after «CO» on '
                   'their pages, none in one span: written CO₂')
        LOG.append('ν. 5299/2026 has no words on its own commencement in arts. 68, 69 and 88: in force on publication '
                   '(art. 113)')

    steps = [
        {'law': 'n-5299-2026', 'fek': (2026, 67), 'day': None, 'edit': e5299, 'check': chk5299,
         'note': 'ν. 5299/2026 (ΦΕΚ Α΄ 67/2026), in force on publication (art. 113): art. 68 corrects errata in arts. 7 '
                 'par. 2, 17 par. 3, 23, 27 par. 2 περ. α) and 40 par. 8 and in Annexes I and IV (each restated); art. '
                 '69 adds art. 36Α (use of the foreshore, seabed and subsoil for carbon dioxide exploration and '
                 'storage); art. 88 par. 2 repeals art. 75 par. 9.'},
    ]
    return build('47-n5261', 'nomos-5261-2025', 2025, 231, 5261, 'carbon dioxide capture, transport and storage', steps, [
        'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in '
        'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
        '58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; and the official search.et.gr relation '
        'index for the issue (as read on 2026-10-30), which lists ΦΕΚ Α΄ 67/2026 only. Amending: ν. 5299/2026 arts. '
        '68, 69 and 88 par. 2. Other mentions only refer to it: ν. 5299/2026 art. 50 (the subjects of its Part), the '
        'Spatial Planning and Urban Planning Code ratified by ν. 5306/2026 (ΦΕΚ Α΄ 88/2026), whose source tables cite '
        'art. 75 pars. 3, 4, 5, 8 and 9 as amendments of other laws and whose list of repealed provisions (its Annex '
        'Α΄) does not name ν. 5261/2025, ν. 5314/2026 art. 383 and ΦΕΚ Α΄ 122/2026 art. 34. Issues after Α΄ 177/2026 '
        'were not searched.',
        'ν. 5299/2026 art. 68 corrects errata («Διόρθωση παροραμάτων») by amendment, with no words on when the '
        'corrections apply, so they are dated by the law\'s commencement, its publication (5 May 2026), like its other '
        'changes.',
        'A repealed paragraph is removed (art. 75 par. 9); the paragraphs after it keep their numbers.',
        co2], edit_other=True, qfix=lambda l: l.replace('CO2', 'CO₂'), item_split=True)


# ---------------------------------------------------------------- ν. 5194/2025

def insert_pars(u: dict, key: str, y: int, n: int, art: str, must: str, sub: int, after: str, labels: list[str],
                phrase: str, what: str) -> dict:
    """Paragraphs (labels, e.g. 4α, 4β) added after paragraph `after` of article `key`: the quotation of the amending
    article's own paragraph `sub` (sub_block), each quoted paragraph opening with its label."""
    instr, q = sub_block(y, n, art, must, sub, what, start_re=r'^\d+\.(?: |[α-ω]\) )')
    N.need(instr, phrase, what)
    q = split_run_on(q, what)
    if [l.split(' ', 1)[0] for l in q] != [f'{x}.' for x in labels]:
        raise SystemExit(f'{what}: the quotation is not paragraphs {labels}: {[l[:8] for l in q]}')
    lines = u[key]
    i = N.find_one(lines, f'{after}. ', f'{what}: {key} par. {after}')
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ωα-ω]?\. ', lines[j]):
        j += 1
    if j < len(lines) and not lines[j].startswith(f'{int(after) + 1}. '):
        raise SystemExit(f'{what}: par. {after} of {key} is followed by {lines[j][:10]!r}')
    u = dict(u)
    u[key] = lines[:j] + q + lines[j:]
    LOG.append(f'{what}: {key} gains pars. {", ".join(labels)} after par. {after} ({len(q)} line(s))')
    return u


def p5194() -> dict:
    def e5234(u: dict) -> dict:
        # ΦΕΚ Α΄ 167/2025 numbers its articles in words («Άρθρο δεύτερο»), which the column reader keeps inside the
        # chapter title paragraph: the instruction is that paragraph from «Άρθρο δεύτερο» on, the quotation follows it
        w = 'ν. 5234/2025 art. δεύτερο'
        paras = N.fek_paras(2025, 167)
        hits = [i for i, p in enumerate(paras) if 'Άρθρο δεύτερο' in p['text']
                and 'Στον ν. 5194/2025 (Α’ 66), μετά το άρθρο 34' in p['text']]
        if len(hits) != 1:
            raise SystemExit(f'{w}: instruction found {len(hits)} times')
        i = hits[0]
        instr = paras[i]['text'][paras[i]['text'].index('Άρθρο δεύτερο'):]
        N.need(instr, 'Προσθήκη άρθρου 34Α στον ν. 5194/2025', w)
        N.need(instr, 'προστίθεται άρθρο 34Α ως εξής:', w)
        j = next(k for k in range(i + 1, len(paras)) if paras[k]['kind'] == 'struct')
        qs = [[p['text'] for p in q] for q in N.quotes(paras[i + 1:j])]
        if len(qs) != 1:
            raise SystemExit(f'{w}: {len(qs)} quotations')
        q = quoted_unit(qs[0], 'Άρθρο 34Α', w)
        if 'art-034-a' in u:
            raise SystemExit(f'{w}: art-034-a already exists')
        u = dict(u)
        u['art-034-a'] = q
        LOG.append(f'{w}: art-034-a added ({len(q)} lines)')
        return u

    def chk5234() -> None:
        t = ' '.join(p['text'] for p in N.fek_paras(2025, 167))
        N.need(t, 'Άρθρο τρίτο Έναρξη ισχύος Η ισχύς του παρόντος άρχεται από τη δημοσίευσή του στην Εφημερίδα της '
                  'Κυβερνήσεως.', 'ν. 5234/2025 art. τρίτο')

    def e5302(u: dict) -> dict:
        return insert_pars(u, 'art-033', 2026, 78, '63', 'Επαναφορά διοικητικής και περιουσιακής αυτοτέλειας', 7, '4',
                           ['4α', '4β'], 'Στο άρθρο 33 του ν. 5194/2025 (Α’ 66), περί αναδιάταξης του νοσοκομειακού '
                           'χάρτη Δυτικής Αττικής, προστίθενται παρ. 4α και 4β ως εξής:', 'ν. 5302/2026 art. 63 par. 7')

    def chk5302() -> None:
        commencement(2026, 78, '101', '1. Με την επιφύλαξη των παρ. 2, 3, 4, 5, 6 και 7 η ισχύς του παρόντος νόμου '
                     'αρχίζει από τη δημοσίευσή του', 'ν. 5302/2026 art. 101')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 78, '101', 'Έναρξη ισχύος'))
        if re.search(r'άρθρου 63\b|άρθρο 63\b', t):
            raise SystemExit('ν. 5302/2026 art. 101 names art. 63: read it')
        LOG.append('ν. 5302/2026 art. 101 pars. 2-7 defer arts. 12(1), 16, 17, 53(1)-(3), 57(1) and 82, not art. 63')

    steps = [
        {'law': 'n-5234-2025', 'fek': (2025, 167), 'day': None, 'edit': e5234, 'check': chk5234,
         'note': 'ν. 5234/2025 art. δεύτερο (ΦΕΚ Α΄ 167/2025), in force on publication (art. τρίτο): art. 34Α added '
                 '(the organisation charts of three Stavros Niarchos Foundation hospitals, by joint ministerial '
                 'decision).'},
        {'law': 'n-5302-2026', 'fek': (2026, 78), 'day': None, 'edit': e5302, 'check': chk5302,
         'note': 'ν. 5302/2026 art. 63 par. 7 (ΦΕΚ Α΄ 78/2026), in force on publication (art. 101 par. 1; pars. 2-7 '
                 'do not name art. 63): art. 33 gains pars. 4α and 4β (a dermatology department moved to the Nikaia '
                 'hospital, whose first medical sector gains fifteen beds).'},
    ]
    return build('58-n5194', 'nomos-5194-2025', 2025, 66, 5194,
                 'the Association of Dietitians-Nutritionists of Greece and other health provisions', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-01, which lists '
                     'ΦΕΚ Α΄ 167/2025 and Α΄ 78/2026. Amending: ν. 5234/2025 art. δεύτερο and ν. 5302/2026 art. 63 '
                     'par. 7. Other mentions only refer to it: ΦΕΚ Α΄ 184/2025 (art. 53) and Α΄ 228/2025, which '
                     'extends a deadline that art. 42 of ν. 5194/2025 had extended, without changing its words. '
                     'Issues after Α΄ 177/2026 were not searched.'])


# ---------------------------------------------------------------- ν. 5176/2025

def p5176() -> dict:
    def e5324(u: dict) -> dict:
        return add_unit(u, 'Άρθρο 13Α', 2026, 121, '137', 'Προσθήκη άρθρου 13Α στον ν. 5176/2025',
                        'ν. 5324/2026 art. 137')

    def chk5324() -> None:
        commencement(2026, 121, '141', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2,3 και 4.', 'ν. 5324/2026 art. 141')
        in_part(2026, 121, '137', 'ΜΕΡΟΣ ΣΤ’', 'ΜΕΡΟΣ Ζ’', 'ν. 5324/2026')
        body = ' '.join(p['text'] for p in N.amending_article(2026, 121, '141', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+, )*137\b|Μέρους ΣΤ', body):
            raise SystemExit('ν. 5324/2026 art. 141 names art. 137 or Part ΣΤ: read it')
        LOG.append('ν. 5324/2026 art. 141 pars. 2-4 defer arts. 6, 7, 11(3) and 13(2) of Part Α, Part Β and art. 136(3), '
                   'not art. 137 (Part ΣΤ); the issue\'s first line reads «ΝΟΜΟΣ ΥΠ’ ΑΡΙΘΜ 5324», without the usual '
                   'full stop')

    steps = [
        {'law': 'n-5324-2026', 'fek': (2026, 121), 'day': None, 'edit': e5324, 'check': chk5324,
         'note': 'ν. 5324/2026 art. 137 (ΦΕΚ Α΄ 121/2026), in force on publication (art. 141 par. 1; art. 137 is in '
                 'Part ΣΤ, which pars. 2-4 do not defer): art. 13Α added (doctors\' certifications for athletes\' health '
                 'cards already granted stay valid for five years from 7 February 2025).'},
    ]
    return build('48-n5176', 'nomos-5176-2025', 2025, 17, 5176, 'amateur and professional sport', steps, [
        'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in '
        'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
        '58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; and the official search.et.gr relation '
        'index for the issue, fetched on 2026-11-01, which lists ΦΕΚ Α΄ 121/2026 only. Amending: ν. 5324/2026 art. 137, '
        'which adds art. 13Α (the scan saw it only as a reference: «Στον ν. 5176/2025 (Α’ 17), προστίθεται άρθρο 13Α»). '
        'Issues after Α΄ 177/2026 were not searched.'])


# ---------------------------------------------------------------- ν. 5229/2025

def p5229() -> dict:
    def e5313(u: dict) -> dict:
        return restate(u, 'art-016', 2026, 102, '124', 'Τροποποίηση άρθρου 16 ν. 5229/2025', [
            ('sub', 'όχι πέραν της 30ής.6.2026', 'όχι πέραν της 30ής.6.2027')], 'ν. 5313/2026 art. 124')

    def chk5313() -> None:
        commencement(2026, 102, '137', '1. Με την επιφύλαξη των παρ. 2 έως 11, η ισχύς του παρόντος νόμου αρχίζει από '
                     'τη δημοσίευσή του', 'ν. 5313/2026 art. 137')
        in_part(2026, 102, '124', 'ΜΕΡΟΣ ΣΤ’', 'ΜΕΡΟΣ Ζ’', 'ν. 5313/2026')
        body = ' '.join(p['text'] for p in N.amending_article(2026, 102, '137', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+, )*124\b|Μέρος ΣΤ|έως 1[2-9]\d\b', body):
            raise SystemExit('ν. 5313/2026 art. 137 may defer art. 124: read it')
        LOG.append('ν. 5313/2026 art. 137 pars. 2-11 defer provisions of Parts Α-Ε and arts. 105-115, not art. 124 '
                   '(Part ΣΤ)')

    steps = [
        {'law': 'n-5313-2026', 'fek': (2026, 102), 'day': None, 'edit': e5313, 'check': chk5313,
         'note': 'ν. 5313/2026 art. 124 (ΦΕΚ Α΄ 102/2026), in force on publication (art. 137 par. 1; art. 124 is in '
                 'Part ΣΤ, which pars. 2-11 do not defer): art. 16, the time limit on arts. 13-15, moves from 30 June '
                 '2026 to 30 June 2027; the article is restated.'},
    ]
    return build('50-n5229', 'nomos-5229-2025', 2025, 158, 5229,
                 'social housing exchange, social rent and the three-child status', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-01, which lists '
                     'ΦΕΚ Α΄ 102/2026 only. Amending: ν. 5313/2026 art. 124. Other mentions only refer to it: the '
                     'Local Government Code ratified by ν. 5314/2026 (ΦΕΚ Α΄ 103/2026: art. 553 par. 6 and its '
                     'tables of competences), ν. 5322/2026 arts. 46 and 54 (ΦΕΚ Α΄ 117/2026), and Cabinet Act 20 of '
                     '22.7.2026 (ΦΕΚ Α΄ 116/2026), which amends Cabinet Act 10/28.5.2025 and names ν. 5229/2025 among '
                     'its grounds. Issues after Α΄ 177/2026 were not searched.',
                     'Art. 16 limits arts. 13-15 in time (until the Ministry\'s organisation decree, and no later than '
                     'a set day). ν. 5313/2026 moved that day from 30 June 2026 to 30 June 2027 before it came, so '
                     'arts. 13-15 have stayed in force throughout.'])


# ---------------------------------------------------------------- ν. 5263/2025

def p5263() -> dict:
    def e5305(u: dict) -> dict:
        return add_par(u, 'art-039', 2026, 85, '32', 'Προσθήκη παρ. 3 στο άρθρο 39 του ν. 5263/2025', '3',
                       'Στο άρθρο 39 του ν. 5263/2025 (Α’ 238), περί μεταβατικών διατάξεων αυτού, προστίθεται παρ. 3 ως '
                       'εξής:', 'ν. 5305/2026 art. 32')

    def e5321(u: dict) -> dict:
        # the quotation opens inside the instruction paragraph («Άρθρο εικοστό δεύτερο Διαχείριση) and runs over the
        # paragraphs after it: art. 8 of ν. 5263/2025 holds the company's statute, whose articles are numbered in words
        w = 'ν. 5321/2026 art. 38'
        body = N.amending_article(2026, 114, '38', 'Τροποποίηση εσωτερικού άρθρου εικοστού δεύτερου άρθρου 8 ν. 5263/2025')
        texts = [p['text'] for p in body]
        head, sep, rest = texts[0].partition('διαμορφώνεται ως εξής: «')
        if not sep or rest != 'Άρθρο εικοστό δεύτερο Διαχείριση' or not texts[-1].endswith('»'):
            raise SystemExit(f'{w}: the restatement is not where expected: {rest[:40]!r}')
        q = ['Άρθρο εικοστό δεύτερο', 'Διαχείριση'] + texts[1:-1] + [texts[-1][:-1]]
        if sum(t.count('«') - t.count('»') for t in texts) != 0:
            raise SystemExit(f'{w}: unbalanced quotation marks')
        LOG.append(f'{w}: the quotation opens in the instruction paragraph: «Άρθρο εικοστό δεύτερο Διαχείριση» read as '
                   'the inner article\'s number and title')
        return restate_span(u, 'art-008', ('Άρθρο εικοστό δεύτερο', 'Άρθρο εικοστό τρίτο'), 'Άρθρο εικοστό δεύτερο',
                            r'^Άρθρο ', (head + sep, q), [
                                ('sub', 'του επόμενου έτους από τη σύστασή της', 'του έτους της σύστασής της')], w)

    def chk5305() -> None:
        commencement(2026, 85, '43', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη της παρ. 2.', 'ν. 5305/2026 art. 43')
        commencement(2026, 85, '43', '2. Η ισχύς του δεύτερου εδαφίου της παρ. 2 του άρθρου 22 του ν. 4727/2020',
                     'ν. 5305/2026 art. 43 par. 2')
        LOG.append('ν. 5305/2026 art. 43 par. 2 defers only a provision added to ν. 4727/2020 (by its art. 21), not '
                   'art. 32')

    def chk5321() -> None:
        commencement(2026, 114, '58', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του', 'ν. 5321/2026 art. 58')
        t = ' '.join(p['text'] for p in N.amending_article(
            2026, 114, '38', 'Τροποποίηση εσωτερικού άρθρου εικοστού δεύτερου άρθρου 8 ν. 5263/2025'))
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', t, re.I):
            raise SystemExit('ν. 5321/2026 art. 38 has words on its own commencement: read it')
        LOG.append('ν. 5321/2026 art. 38 has no words on its own commencement: in force on publication (art. 58)')

    steps = [
        {'law': 'n-5305-2026', 'fek': (2026, 85), 'day': None, 'edit': e5305, 'check': chk5305,
         'note': 'ν. 5305/2026 art. 32 (ΦΕΚ Α΄ 85/2026), in force on publication (art. 43 par. 1): art. 39 gains par. 3 '
                 '(the company formerly Η.Δ.Υ.Κ.Α. keeps its 2026 salary grant from the Ministry of Digital Governance '
                 'until a joint ministerial decision, and no later than 31 December 2026).'},
        {'law': 'n-5321-2026', 'fek': (2026, 114), 'day': None, 'edit': e5321, 'check': chk5321,
         'note': 'ν. 5321/2026 art. 38 (ΦΕΚ Α΄ 114/2026), in force on publication (art. 58): in the statute of the Greek '
                 'AI Factory S.A. (art. 8), art. εικοστό δεύτερο par. 1: the first financial year now ends on 31 '
                 'December of the year the company is set up; the inner article is restated.'},
    ]
    return build('53-n5263', 'nomos-5263-2025', 2025, 238, 5263, 'the Greek AI factory', steps, [
        'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in '
        'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
        '58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; and the official search.et.gr relation '
        'index for the issue, fetched on 2026-11-01, which lists ΦΕΚ Α΄ 85/2026 and Α΄ 114/2026. Amending: ν. '
        '5305/2026 art. 32 and ν. 5321/2026 art. 38. ν. 5321/2026 art. 12 only refers to it. Issues after Α΄ '
        '177/2026 were not searched.'])


# ---------------------------------------------------------------- ν. 5253/2025

def p5253() -> dict:
    """One version (no later law changes its words), with the dated start a later law set for provisions it added to
    another law, checked in that law's issue and recorded in the decisions."""
    LOG.clear()
    part, _ = PS.single_part('54-n5253', 'nomos-5253-2025', 2025, 212, 5253,
                             'the organisation of the public broadcaster ERT S.A.')
    w = 'ν. 5325/2026 art. 67'
    t = ' '.join(p['text'] for p in N.amending_article(2026, 122, '67', 'Μετάθεση έναρξης ισχύος'))
    N.need(t, 'Η ισχύς των παρ. 1 έως 15 του άρθρου 6Α του ν. 4173/2013 (Α’ 169), όπως προστέθηκαν με το άρθρο 8 του '
              'ν. 5253/2025 (Α’ 212) αρχίζει την 1η Ιανουαρίου 2027, πλην της περ. ε) της παρ. 3 του άρθρου 6Α, όπως '
              'τροποποιήθηκε με το άρθρο 35 του ν. 5308/2026 (Α’ 91).', w)
    if N.law_number(2026, 122) != 5325 or N.masthead(2026, 122) != '2026-07-31':
        raise SystemExit(f'{w}: Α΄ 122/2026 is not ν. 5325/2026 of 31 July 2026')
    t35 = ' '.join(p['text'] for p in N.amending_article(2026, 91, '35', 'Αντικατάσταση περ. ε) παρ. 3 άρθρου 6Α ν. 4173/2013'))
    N.need(t35, 'Η περ. ε) της παρ. 3 του άρθρου 6Α του ν. 4173/2013 (Α’ 169)', 'ν. 5308/2026 art. 35')
    if '5253' in t35 or N.law_number(2026, 91) != 5308:
        raise SystemExit('ν. 5308/2026 art. 35: read it')
    art8 = part['acts'][0]['versions'][0]['units']['art-008']['text']
    N.need(art8, 'Άρθρο 6Α', 'ν. 5253/2025 art. 8')
    d0 = part['decisions'][0]
    a = 'its only version: no later law amends it.'
    if a not in d0:
        raise SystemExit('54-n5253: unexpected first decision')
    N.need(part['decisions'][1], 'όπως προστίθενται με το άρθρο 8 του παρόντος, αρχίζει την 1η Σεπτεμβρίου 2026.',
           'ν. 5253/2025 art. 43 par. 2')
    part['decisions'][0] = d0[:d0.index(a)] + (
        'its only version: no later law changes its words. Amending laws were looked for three ways: a full-text scan '
        'of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue '
        'and in the Gazette PDF where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by '
        'hand; and the official search.et.gr relation index for the issue, fetched on 2026-11-01, which lists ΦΕΚ Α΄ '
        '122/2026 only (below). Issues after Α΄ 177/2026 were not searched.')
    part['decisions'][1:1] = [
        'Dated start: ν. 5253/2025 art. 43 par. 2 starts paras. 1-15 of art. 6Α of ν. 4173/2013, as added by its art. 8 '
        '(the procedure for collecting the public broadcasting fee), on 1 September 2026; ν. 5325/2026 art. 67 (ΦΕΚ Α΄ '
        '122/31.7.2026) moves that start to 1 January 2027, except art. 6Α par. 3 περ. ε) as replaced by ν. 5308/2026 art. 35 (ΦΕΚ Α΄ 91/2026). This '
        'changes no words of ν. 5253/2025, so it is not a version; art. 8 reads as published throughout. ν. 5308/2026 '
        'art. 35 replaces that item in ν. 4173/2013 itself and does not amend ν. 5253/2025.']
    return part


# ---------------------------------------------------------------- ν. 5113/2024

def p5113() -> dict:
    def e5313(u: dict) -> dict:
        return remove_par(u, 'art-064', 2026, 102, '58', 'Καταργούμενες διατάξεις Μέρους Γ’', '2',
                          'καταργείται η παρ. 2 του άρθρου 64 του ν. 5113/2024', 'ν. 5313/2026 art. 58 par. 1')

    def chk5313() -> None:
        commencement(2026, 102, '137', '1. Με την επιφύλαξη των παρ. 2 έως 11, η ισχύς του παρόντος νόμου αρχίζει από '
                     'τη δημοσίευσή του', 'ν. 5313/2026 art. 137')
        in_part(2026, 102, '58', 'ΜΕΡΟΣ Γ’', 'ΜΕΡΟΣ Δ’', 'ν. 5313/2026')
        body = ' '.join(p['text'] for p in N.amending_article(2026, 102, '137', 'Έναρξη ισχύος'))
        N.need(body, '6. Το Μέρος Γ’ τίθεται σε ισχύ από τη δημοσίευση του παρόντος νόμου, εκτός από:',
               'ν. 5313/2026 art. 137 par. 6')
        if re.search(r'άρθρ\w+ (?:\d+, )*58\b|έως 5[89]\b', body):
            raise SystemExit('ν. 5313/2026 art. 137 may defer art. 58: read it')
        LOG.append('ν. 5313/2026 art. 137 par. 6 puts Part Γ’ in force on publication except arts. 49-56; art. 58 is '
                   'not among them')

    steps = [
        {'law': 'n-5313-2026', 'fek': (2026, 102), 'day': None, 'edit': e5313, 'check': chk5313,
         'note': 'ν. 5313/2026 art. 58 par. 1 (ΦΕΚ Α΄ 102/2026), in force on publication (art. 137 pars. 1 and 6; '
                 'art. 58 is in Part Γ’ and is not among the provisions par. 6 dates otherwise): art. 64 par. 2, '
                 'which had added par. 5 to art. 11 of ν. 4354/2015, is repealed.'},
    ]
    return build('66-n5113', 'nomos-5113-2024', 2024, 96, 5113,
                 'third-party motor liability insurance (Directive (EU) 2021/2118) and other provisions', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2024 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, which lists '
                     'ΦΕΚ Α΄ 102/2026 only ("Ακύρωση"). Amending: ν. 5313/2026 art. 58 par. 1. The only other mention, '
                     'ν. 5305/2026 art. 36 (ΦΕΚ Α΄ 85/2026), refers to arts. 18, 20, 23 and 24 of ν. 5113/2024 and '
                     'changes none of them. Issues after Α΄ 177/2026 were searched only through the official index.',
                     'The repealed art. 64 par. 2 said that pay differences already paid to the staff named in the '
                     'par. 5 that art. 64 par. 1 added to art. 11 of ν. 4354/2015 are not recovered. ν. 5313/2026 '
                     'art. 51 widens that par. 5 (from 24 June 2023, art. 137 par. 6 γ) and gives the same rule in '
                     'its own par. 2 for the wider group: changes to ν. 4354/2015 and new text of ν. 5313/2026, '
                     'outside this act. Here the repeal is dated by the publication of ν. 5313/2026 (25 June 2026), '
                     'the day art. 58 par. 1 takes effect.',
                     'ν. 5113/2024 art. 73 par. 2: art. 64 par. 1 applies from 24 June 2023, before the law was '
                     'published; like the provisions the law starts later, it is shown from publication.'])


# ---------------------------------------------------------------- ν. 5216/2025

def p5216() -> dict:
    w = 'ν. 5302/2026'
    must = '5216/2025'

    def e5302(u: dict) -> dict:
        u = restate(u, 'art-028', 2026, 78, '39', must, [
            ('add', 'περ. β) έως η) της παρ. 1', 'και της παρ. 4'),
            ('add_at', 'πώλησης της περ. ε) της παρ. 1', 'πώλησης της περ. ε) της παρ. 1,',
             'καθώς και η απαγόρευση της παρ. 4'),
            ('take', None, None, '\n5. Στους χώρους', None),  # γ) par. 5 added
        ], f'{w} art. 39', allowed=A39)
        u = restate(u, 'art-032', 2026, 78, '40', must, [
            ('add', 'Οι έλεγχοι', ', δειγματοληψίες', ('4. Το Γενικό Χημείο', None)),
            ('add', 'τη βεβαίωση των παραβάσεων και την επιβολή κυρώσεων είναι',
             'οι περιφερειακές Χημικές Υπηρεσίες του Γενικού Χημείου του Κράτους,'),
            ('sub', 'Το Γενικό Χημείο', 'Οι υπηρεσίες της Γενικής Διεύθυνσης του Γενικού Χημείου'),
            ('add', 'τον εργαστηριακό και τον φυσικοχημικό έλεγχο',
             'και τον έλεγχο της ταξινόμησης, επισήμανσης και συσκευασίας'),
        ], f'{w} art. 40', allowed=A40)
        u = restate(u, 'art-033', 2026, 78, '41', must, [
            ('del', 'κατά παράβαση των άρθρων', '28'),
            # αβ) new second and third sentences of par. 1, β) new par. 1α
            ('take', None, '\n2. Σε περίπτωση', ' Σε περίπτωση πώλησης μέσω αυτόματου πωλητή', '\n2. Σε περίπτωση'),
            # γα) new second sentence of par. 2
            ('take', None, ' Σε περίπτωση δεύτερης υποτροπής', ' Εφόσον πρόκειται για κατάστημα',
             ' Σε περίπτωση δεύτερης υποτροπής'),
            # γβ) words added at the end of the third sentence
            ('append', 'εκτός του διοικητικού προστίμου ανακαλείται οριστικά η άδεια λειτουργίας',
             'και, εφόσον πρόκειται για κατάστημα που υπόκειται σε γνωστοποίηση διακόπτεται η λειτουργία του με '
             'σφράγισή του, για χρονικό διάστημα έξι (6) μηνών'),
            # γγ) the fourth sentence deleted
            ('take', ' Η υποτροπή λαμβάνεται υπόψη και για το ύψος του επιβαλλόμενου προστίμου.', '\n3. Αν', None,
             '\n3. Αν'),
            ('add', 'τον εργαστηριακό και φυσικοχημικό έλεγχο',
             'και τον έλεγχο της ταξινόμησης, επισήμανσης και συσκευασίας'),
            ('add', 'επιβάλλεται πρόστιμο', 'ύψους από διακόσια (200) έως τριάντα χιλιάδες (30.000) ευρώ',
             ('\n3. Αν', None)),
            # δβ) new second to fifth sentences of par. 3
            ('take', None, ' Η διαδικασία επιβολής του προστίμου', ' Σε περίπτωση υποτροπής το πρόστιμο διπλασιάζεται',
             ' Η διαδικασία επιβολής του προστίμου'),
            ('sub', 'Τμήματος Παρακολούθησης και Ελέγχου Καπνικών και Μη Καπνικών Προϊόντων της Διεύθυνσης '
             'Επιδημιολογικής Επιτήρησης και Πρόληψης μη Μεταδοτικών Νοσημάτων', 'Επιστημονικού Συμβουλίου'),
        ], f'{w} art. 41', allowed=A41)
        u = restate_par(u, 'art-034', 2026, 78, '42', must, '1', [
            ('sub', 'στην παρ. 2', 'στην παρ. 4')], f'{w} art. 42')
        return restate_par(u, 'art-054', 2026, 78, '72', must, '1', [
            ('add', 'από την 1η.7.2025 έως την 31η.12.2025', 'και από την 1η.6.2026 έως την 30ή.9.2026')],
            f'{w} art. 72')

    A39: dict = {}
    D40 = ('ν. 5302/2026 art. 40 restates art. 32 «μετά από νομοτεχνικές βελτιώσεις» (after drafting improvements) with '
           'changes it does not list: par. 2 adds the abbreviation «(Ε.Ο.Δ.Υ.)»; par. 3 cites the new National Customs '
           'Code (ν. 5222/2025, Α’ 134: art. 131 par. 2, art. 159 par. 2, arts. 168-192) in place of the old one (ν. '
           '2960/2001, Α’ 265: art. 119Α par. 1, art. 142 par. 2, arts. 150-177); par. 4 reads «αρμόδιες» for «αρμόδιο», '
           'to agree with its new plural subject. The restatement is the amending law’s own text and governs.')
    S40 = 'Part of the same unlisted update of art. 32 par. 3 to the new National Customs Code (see «εοδυ» above).'
    A40 = {('', 'εοδυ'): D40,
           ('αρμόδιο', 'αρμόδιες'): 'Agreement with the new plural subject of art. 32 par. 4 (see «εοδυ» above).',
           **{k: S40 for k in [('1', '2'), ('119α', '131'), ('142', '159'), ('150', '168'), ('177', '192'),
                               ('2960/2001', '5222/2025'), ('265', '134')]}}
    A41: dict = {}

    def chk5302() -> None:
        commencement(2026, 78, '101', '1. Με την επιφύλαξη των παρ. 2, 3, 4, 5, 6 και 7 η ισχύς του παρόντος νόμου '
                     'αρχίζει από τη δημοσίευσή του', 'ν. 5302/2026 art. 101')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 78, '101', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*(?:39|40|41|42|72)\b', t):
            raise SystemExit('ν. 5302/2026 art. 101 names art. 39-42 or 72: read it')
        LOG.append('ν. 5302/2026 art. 101 pars. 2-7 defer arts. 12(1), 16, 17, 53(1)-(3), 57(1) and 82, not arts. '
                   '39-42 or 72')

    steps = [
        {'law': 'n-5302-2026', 'fek': (2026, 78), 'day': None, 'edit': e5302, 'check': chk5302,
         'note': 'ν. 5302/2026 arts. 39-42 and 72 (ΦΕΚ Α΄ 78/2026), in force on publication (art. 101 par. 1; pars. 2-7 '
                 'do not name them): arts. 28, 32 and 33 amended and restated (a notice against sales to minors, '
                 'regional chemical services as control authorities, new fines and closures); art. 34 par. 1 and art. '
                 '54 par. 1 (travel allowance also from 1 June to 30 September 2026) restated.'},
    ]
    return build('67-n5216', 'nomos-5216-2025', 2025, 118, 5216,
                 'protection of minors from tobacco and alcohol, non-tobacco products and other provisions', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, which lists '
                     'ΦΕΚ Α΄ 78/2026 only. Amending: ν. 5302/2026 arts. 39, 40, 41, 42 and 72. The only other '
                     'mentions, in the Local Government Code ratified by ν. 5314/2026 (ΦΕΚ Α΄ 103/2026: art. 356, '
                     'the municipal police\'s powers, and a table of competences), refer to it. Issues after Α΄ '
                     '177/2026 were searched only through the official index.',
                     'ΦΕΚ Α΄ 118/2025 prints the topographic plans that arts. 49 and 50 attach as Annexes Α and Β as '
                     'images on 12 pages (2784-2795), with no text layer; they are left out (no OCR). Arts. 49 and 50 '
                     'are given in full.'])


# ---------------------------------------------------------------- ν. 5142/2024

def p5142() -> dict:
    def e5337(u: dict) -> dict:
        # ΦΕΚ Α΄ 156/2026 numbers its articles in words (art. δεύτερο): the instruction is the paragraph that opens
        # «Στο άρθρο 30 του ν. 5142/2024», the restatement the quotation in the paragraphs after it
        w = 'ν. 5337/2026 art. δεύτερο'
        paras = N.fek_paras(2026, 156)
        hits = [i for i, p in enumerate(paras) if p['text'].startswith('Στο άρθρο 30 του ν. 5142/2024 (Α’ 158)')]
        if len(hits) != 1:
            raise SystemExit(f'{w}: instruction found {len(hits)} times')
        i = hits[0]
        N.need(paras[i - 1]['text'], 'Τροποποίηση άρθρου 30 ν. 5142/2024', w)
        j = next(k for k in range(i + 1, len(paras)) if paras[k]['text'] == 'Άρθρο τρίτο')
        qs = [[p['text'] for p in q] for q in N.quotes(paras[i + 1:j])]
        if len(qs) != 1:
            raise SystemExit(f'{w}: {len(qs)} quotations')
        LOG.append(f'{w}: the issue numbers its articles in words; instruction and quotation read from the paragraphs '
                   'after the heading «Τροποποίηση άρθρου 30 ν. 5142/2024»')
        return restate(u, 'art-030', 2026, 156, '', '', [
            ('sub', 'ενός εκατομμυρίου πεντακοσίων χιλιάδων (1.500.000) ευρώ', 'δύο εκατομμυρίων (2.000.000) ευρώ')],
            w, allowed=A5337, src=(paras[i]['text'], qs[0]))

    A5337 = {('τον', 'του'): 'In art. 30 the published text reads «κυρώθηκε με το άρθρο πρώτο τον ν. 5133/2024»; the '
             'restatement by ν. 5337/2026 reads «του ν. 5133/2024», correcting the misprint without listing it. The '
             'restatement is the amending law’s own text and governs.'}

    def chk5337() -> None:
        t = ' '.join(p['text'] for p in N.fek_paras(2026, 156))
        N.need(t, 'Άρθρο τρίτο Έναρξη ισχύος Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                  'Κυβερνήσεως και του Πρωτοκόλλου, που κυρώνεται, από την πλήρωση των προϋποθέσεων της παρ. 3 αυτού.',
               'ν. 5337/2026 art. τρίτο')
        LOG.append('ν. 5337/2026 art. τρίτο: the law is in force on publication; only the ratified Protocol waits for its '
                   'own conditions')

    def e5321(u: dict) -> dict:
        return restate(u, 'art-032', 2026, 114, '29', 'Προσθήκη παρ. 2, 3 και 4 στο άρθρο 32 του ν. 5142/2024', [
            ('take', 'Μεταβατική διάταξη\n', 'Όπου', 'Μεταβατικές διατάξεις\n1. ', 'Όπου'),  # α) title, β) par. 1
            ('take', None, None, '\n2. Κατά την πρώτη εφαρμογή', None),  # γ) pars. 2-4 added
        ], 'ν. 5321/2026 art. 29')

    def chk5321() -> None:
        commencement(2026, 114, '58', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του', 'ν. 5321/2026 art. 58')

    steps = [
        {'law': 'n-5321-2026', 'fek': (2026, 114), 'day': None, 'edit': e5321, 'check': chk5321,
         'note': 'ν. 5321/2026 art. 29 (ΦΕΚ Α΄ 114/2026), in force on publication (art. 58): art. 32 gets a new title, '
                 'its paragraph becomes par. 1 and pars. 2-4 are added (transitional rules for the first application of '
                 'arts. 8-10); the article is restated.'},
        {'law': 'n-5337-2026', 'fek': (2026, 156), 'day': None, 'edit': e5337, 'check': chk5337,
         'note': 'ν. 5337/2026 art. δεύτερο (ΦΕΚ Α΄ 156/2026), in force on publication (art. τρίτο): in art. 30 the '
                 'amount of the Greece-Cyprus memorandum\'s proceeds rises from 1,500,000 to 2,000,000 euro; the article '
                 'is restated.'},
    ]
    return build('70-n5142', 'nomos-5142-2024', 2024, 158, 5142,
                 'completion of the cadastral survey, simpler procedures and the Hellenic Cadastre', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2024 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, which lists '
                     'ΦΕΚ Α΄ 114/2026 and Α΄ 156/2026. Amending: ν. 5321/2026 art. 29 and ν. 5337/2026 art. δεύτερο. '
                     'Other mentions only refer to it: ν. 5321/2026 art. 27 and the codification in ΦΕΚ Α΄ 88/2026, '
                     'which names arts. 16 and 17 of ν. 5142/2024 (amendments of ν. 4495/2017) in its source notes and '
                     'correspondence table. Issues after Α΄ 177/2026 were searched only through the official index.'])


# ---------------------------------------------------------------- ν. 5131/2024

def p5131() -> dict:
    def e5222(u: dict) -> dict:
        return restate_par(u, 'art-034', 2025, 134, '264', 'Αντικατάσταση παρ. 1 άρθρου 34 ν. 5131/2024', '1', [
            ('take', '1. ', None, '1. ', None)], 'ν. 5222/2025 art. 264')

    def chk5222() -> None:
        commencement(2025, 134, '275', '1. Με την επιφύλαξη των επόμενων παραγράφων, η ισχύς του παρόντος νόμου '
                     'αρχίζει από τη δημοσίευσή του', 'ν. 5222/2025 art. 275')
        t = ' '.join(p['text'] for p in N.amending_article(2025, 134, '275', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*264\b|έως 2[67]\d\b', t):
            raise SystemExit('ν. 5222/2025 art. 275 may defer art. 264: read it')
        LOG.append('ν. 5222/2025 art. 275 pars. 2 ff. date other provisions, not art. 264')

    def e5297(u: dict) -> dict:
        return repeal_unit(u, 'art-048', 2026, 64, '231', 'Καταργούμενες διατάξεις', [
            'Από την έναρξη ισχύος του παρόντος καταργούνται:',
            'ε) το άρθρο 48 του ν. 5131/2024 (Α’ 128), περί παράτασης της προθεσμίας ολοκλήρωσης των επενδυτικών '
            'σχεδίων του ν. 4399/2016.'], 'ν. 5297/2026 art. 231 περ. ε)')

    def chk5297() -> None:
        commencement(2026, 64, '257', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του', 'ν. 5297/2026 art. 257')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 64, '230', 'Μεταβατικές διατάξεις'))
        N.need(t, 'ζ) η περ. θ) του άρθρου 231 του παρόντος, μόνο ως προς το άρθρο 13 του ν. 4864/2021.',
               'ν. 5297/2026 art. 230')
        LOG.append('ν. 5297/2026 art. 230 par. 1 keeps only art. 231 περ. θ) from pending applications, not περ. ε)')

    steps = [
        {'law': 'n-5222-2025', 'fek': (2025, 134), 'day': None, 'edit': e5222, 'check': chk5222,
         'note': 'ν. 5222/2025 art. 264 (ΦΕΚ Α΄ 134/2025), in force on publication (art. 275 par. 1): art. 34 par. 1 '
                 'replaced (the Hellenic Corporation of Assets and Participations adopts its new statute and internal '
                 'rules by 31 December 2025).'},
        {'law': 'n-5297-2026', 'fek': (2026, 64), 'day': None, 'edit': e5297, 'check': chk5297,
         'note': 'ν. 5297/2026 art. 231 περ. ε) (ΦΕΚ Α΄ 64/2026), in force on publication (art. 257): art. 48, which had '
                 'amended ν. 5079/2023 (time limit of investment plans under ν. 4399/2016), repealed.'},
    ]
    return build('71-n5131', 'nomos-5131-2024', 2024, 128, 5131,
                 'restructuring of the Hellenic Corporation of Assets and Participations and other provisions', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2024 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, which lists '
                     'ΦΕΚ Α΄ 134/2025 only ("Αντικατάσταση"). Amending: ν. 5222/2025 art. 264 and ν. 5297/2026 art. '
                     '231 περ. ε) (a repeal, which the index does not list). Other mentions only refer to it: the '
                     'codification in ΦΕΚ Α΄ 88/2026, which names art. 42 par. 1 of ν. 5131/2024 (an amendment of ν. '
                     '4495/2017) in its source notes and correspondence table, and ΦΕΚ Α΄ 175/2026, financial '
                     'statements that describe its arts. 5 and 15. Issues after Α΄ 177/2026 were searched only '
                     'through the official index.',
                     'A repealed article is removed from the day the repeal takes effect, as elsewhere in the corpus.'])


def add_item(u: dict, key: str, y: int, n: int, art: str, must: str, item: str, prev: str, instr_phrase: str,
             what: str, q_index: int = 0) -> dict:
    """An item («στ) …», a whole quotation with any sub-items) added at the end of article `key`, whose last item
    is `prev`. The previous item keeps its closing punctuation as printed (the instruction does not change it)."""
    instr, qs = amending(y, n, art, must)
    N.need(instr, instr_phrase, what)
    q = qs[q_index]
    if not q[0].startswith(f'{item}) '):
        raise SystemExit(f'{what}: the quotation is not item {item}): {q[0][:30]}')
    lines = u[key]
    if not lines[-1].startswith(f'{prev}) '):
        raise SystemExit(f'{what}: {key} does not end with item {prev}): {lines[-1][:30]}')
    u = dict(u)
    u[key] = lines + q
    LOG.append(f'{what}: {key} gains item {item}) at its end ({len(q)} line(s))')
    return u


# ---------------------------------------------------------------- ν. 5029/2023

def p5029() -> dict:
    def e5128(u: dict) -> dict:
        u = restate_par(u, 'art-008', 2024, 118, '6', 'Συνδρομή', '1', [
            ('take', None, None, '\nΟι αποδέκτες-υπεύθυνοι', None)], 'ν. 5128/2024 art. 6')
        u = add_item(u, 'art-003', 2024, 118, '7', 'Εκστρατείες', 'στ', 'ε', 'προστίθεται περ. στ) ως εξής:',
                     'ν. 5128/2024 art. 7')
        return add_par(u, 'art-015', 2024, 118, '104', 'Εξουσιοδοτική', '5', 'προστίθεται παρ. 5 ως εξής:',
                       'ν. 5128/2024 art. 104')

    def chk5128() -> None:
        commencement(2024, 118, '125', '1. Με την επιφύλαξη των παρ. 2, 3, 4 και 5 η ισχύς του παρόντος αρχίζει από '
                     'τη δημοσίευσή του', 'ν. 5128/2024 art. 125')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 118, '125', 'Έναρξη ισχύος'))
        for ph in ['2. Η ισχύς του άρθρου 25 αρχίζει', '3. Η ισχύς της παρ. 1 του άρθρου 44 αρχίζει',
                   'η ισχύς του άρθρου 56 αρχίζει', '5. Η ισχύς του άρθρου 93 αρχίζει']:
            N.need(t, ph, 'ν. 5128/2024 art. 125')
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*(?:6|7|104)\b', t):
            raise SystemExit('ν. 5128/2024 art. 125 may date arts. 6, 7 or 104: read it')
        LOG.append('ν. 5128/2024 art. 125 pars. 2-5 date arts. 25, 44 par. 1, 56 and 93 only')

    steps = [
        {'law': 'n-5128-2024', 'fek': (2024, 118), 'day': None, 'edit': e5128, 'check': chk5128,
         'note': 'ν. 5128/2024 arts. 6, 7 and 104 (ΦΕΚ Α΄ 118/2024), in force on publication (art. 125 par. 1; pars. '
                 '2-5 date other articles): art. 8 par. 1 gains a fourth and fifth sentence (Special Advisers assist '
                 'the recipients of reports on the digital platform), art. 3 gains item στ) (information campaigns '
                 'and three-member committees), art. 15 gains par. 5 (a ministerial decision on those committees).'},
    ]
    return build('73-n5029', 'nomos-5029-2023', 2023, 55, 5029,
                 'prevention of and response to violence and bullying in schools and other provisions', steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2023 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, whose '
                     'timeline stops at 100 rows and shows no Α΄ issue. The scan finds one amending law, ν. '
                     '5128/2024 (ΦΕΚ Α΄ 118/2024): its arts. 6, 7 and 104 are the only ones that name ν. 5029/2023. '
                     'The 2026 issues read in the PDFs do not mention it. Issues after Α΄ 177/2026 were searched '
                     'only through the official index.',
                     'ν. 5128/2024 art. 7 adds item στ) after item ε) of art. 3, which ends with a full stop; the '
                     'instruction does not change that stop, so item ε) keeps it as printed.',
                     'ν. 5128/2024 art. 6 restates the whole of art. 8 par. 1 with the fourth and fifth sentences, '
                     'which the restatement sets as a second line of the paragraph; the first three sentences are '
                     'unchanged (checked word for word).'])


# ---------------------------------------------------------------- ν. 5075/2023

def p5075() -> dict:
    def e5164(u: dict) -> dict:
        u = repeal_unit(u, 'art-019', 2024, 202, '83', 'Καταργούμενες διατάξεις', [
            'α) το άρθρο 19 και η παρ. 1 του άρθρου 21 του ν. 5075/2023 (Α’ 206)'], 'ν. 5164/2024 art. 83 περ. α)')
        return remove_par(u, 'art-021', 2024, 202, '83', 'Καταργούμενες διατάξεις', '1',
                          'α) το άρθρο 19 και η παρ. 1 του άρθρου 21 του ν. 5075/2023 (Α’ 206)',
                          'ν. 5164/2024 art. 83 περ. α)')

    def chk5164() -> None:
        commencement(2024, 202, '84', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του', 'ν. 5164/2024 art. 84')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 202, '84', 'Έναρξη ισχύος'))
        N.need(t, '2. Η ισχύς του άρθρου 77 αρχίζει από την 1η Ιανουαρίου 2025.', 'ν. 5164/2024 art. 84')
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*83\b', t):
            raise SystemExit('ν. 5164/2024 art. 84 may date art. 83: read it')
        LOG.append('ν. 5164/2024 art. 84 par. 2 dates art. 77 only')

    def e5281(u: dict) -> dict:
        must = 'Καταργούμενες διατάξεις Μέρους Β'
        head = 'Από την έναρξη ισχύος του Μέρους Β’, καταργούνται:'
        u = repeal_unit(u, 'art-020', 2026, 28, '124', must, [head, 'στ) το άρθρο 20 του ν. 5075/2023 (Α’ 206)'],
                        'ν. 5281/2026 art. 124 περ. στ)')
        u = repeal_unit(u, 'art-021', 2026, 28, '124', must, [head, 'ζ) το άρθρο 21 του ν. 5075/2023'],
                        'ν. 5281/2026 art. 124 περ. ζ)')
        return repeal_unit(u, 'art-034', 2026, 28, '124', must, [head, 'η) το άρθρο 34 του ν. 5075/2023'],
                           'ν. 5281/2026 art. 124 περ. η)')

    def chk5281() -> None:
        commencement(2026, 28, '149', 'Με την επιφύλαξη της παρ. 2 του άρθρου 107 και της παρ. 2 του άρθρου 133, η '
                     'ισχύς του παρόντος αρχίζει από τη δημοσίευσή του', 'ν. 5281/2026 art. 149')
        t107 = ' '.join(p['text'] for p in N.amending_article(2026, 28, '107', 'Εξαίρεση'))
        N.need(t107, '2. Η ισχύς της περ. στ) της παρ. 1 και της παρ. 3 του άρθρου 162 του ν. 4662/2020, όπως '
               'τροποποιούνται με την παρ. 1, αρχίζει από την 1η.1.2027.', 'ν. 5281/2026 art. 107')
        t133 = ' '.join(p['text'] for p in N.amending_article(2026, 28, '133', 'Διαδικασία επιχορήγησης'))
        N.need(t133, '2. Το δεύτερο εδάφιο της παρ. 6 του άρθρου 12Β του ν. 4797/2021 ισχύει από την 1η.12.2025.',
               'ν. 5281/2026 art. 133')
        LOG.append('ν. 5281/2026 art. 149: the two exceptions (art. 107 par. 2, art. 133 par. 2) date provisions of '
                   'ν. 4662/2020 and ν. 4797/2021, so its Part Β, whose start art. 124 names, starts on publication')

    steps = [
        {'law': 'n-5164-2024', 'fek': (2024, 202), 'day': None, 'edit': e5164, 'check': chk5164,
         'note': 'ν. 5164/2024 art. 83 περ. α) (ΦΕΚ Α΄ 202/2024), in force on publication (art. 84 par. 1; par. 2 '
                 'dates art. 77 only): art. 19 (transfer of the National Observatory of Athens to the Ministry of '
                 'Climate Crisis and Civil Protection) and art. 21 par. 1 repealed.'},
        {'law': 'n-5281-2026', 'fek': (2026, 28), 'day': None, 'edit': e5281, 'check': chk5281,
         'note': 'ν. 5281/2026 art. 124 περ. στ)-η) (ΦΕΚ Α΄ 28/2026), from the start of its Part Β, which is its '
                 'publication (art. 149): arts. 20 (transfer of the National Meteorological Service), 21 (enabling '
                 'provisions) and 34 (priority wildfire-protection works) repealed.'},
    ]
    return build('74-n5075', 'nomos-5075-2023', 2023, 206, 5075,
                 'restructuring of civil protection and the national air rescue and medical transport mechanism',
                 steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2023 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, which lists '
                     'ΦΕΚ Α΄ 202/2024 only ("Ακύρωση"). Amending: ν. 5164/2024 art. 83 περ. α) and ν. 5281/2026 art. '
                     '124 περ. στ)-η) (repeals, the second of which the index does not list). In ΦΕΚ Α΄ 202/2024 the '
                     'restated commencement paragraphs 2 and 3 just before art. 83 belong to art. 82, which corrects '
                     'ν. 5140/2024, not ν. 5075/2023. The 2026 issues read in the PDFs do not mention it. Issues '
                     'after Α΄ 177/2026 were searched only through the official index.',
                     'A repealed article or paragraph is removed from the day the repeal takes effect, as elsewhere '
                     'in the corpus; art. 21 loses par. 1 in 2024 and the rest of the article in 2026.'])


# ---------------------------------------------------------------- ν. 5130/2024

# The Diavgeia record of the revocation decision that ν. 5313/2026 art. 123 par. 4 names (its metadata only)
DIAVGEIA_5130 = {'ada': '9ΠΕΔ46ΜΤΛΒ-47Ψ', 'protocol': 'ΤΕΑ/10/3.018-σλη΄', 'issued': '2026-08-17',
                 'subject': 'ΑΠΟΦΑΣΗ ΑΝΑΚΛΗΣΗΣ ΑΠΟΦΑΣΗΣ ΕΝΤΑΞΗΣ ΠΡΑΞΗΣ', 'issuer': 'ΥΠΟΥΡΓΕΙΟ ΠΡΟΣΤΑΣΙΑΣ ΤΟΥ ΠΟΛΙΤΗ'}


def p5130() -> dict:
    def e5314(u: dict) -> dict:
        return remove_par(u, 'art-044', 2026, 103, '773', 'Καταργούμενες διατάξεις', '2',
                          '7. η παρ. 2 του άρθρου 44 του ν. 5130/2024 (Α’ 127),', 'ν. 5314/2026 art. 773 par. Β no. 7')

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2, 3 και 4.', 'ν. 5314/2026 art. 774')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '774', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*773\b|έως 77\d\b', t):
            raise SystemExit('ν. 5314/2026 art. 774 may defer art. 773: read it')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '773', 'Καταργούμενες διατάξεις'))
        N.need(t, 'Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:', 'ν. 5314/2026 art. 773 par. Β')
        body = N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής Αυτοδιοίκησης')
        N.need(' '.join(p['text'] for p in body), '7. η παρ. 2 του άρθρου 44 του ν. 5130/2024 (Α’ 127),',
               'ν. 5321/2026 art. 54')
        LOG.append('ν. 5314/2026 art. 774 pars. 2-4 do not date art. 773; ν. 5321/2026 art. 54 replaces art. 773 '
                   '(corrections) and its par. Β no. 7 repeals art. 44 par. 2 of ν. 5130/2024 in the same words, so it '
                   'changes nothing here')

    def e5313(u: dict) -> dict:
        return repeal_unit(u, 'art-045', 2026, 102, '123', 'Ενίσχυση πρώτων ανταποκριτών', [
            '4. Από την ημερομηνία έκδοσης της απόφασης ανάκλησης της παρ. 3 καταργούνται:',
            'α) το άρθρο 45 του ν. 5130/2024 (Α’ 127), περί της επιχειρησιακής ενίσχυσης πρώτων ανταποκριτών Άμεσης '
            'Δράσης Αττικής και Θεσσαλονίκης'], 'ν. 5313/2026 art. 123 par. 4 α)')

    def chk5313() -> None:
        t = ' '.join(p['text'] for p in N.amending_article(2026, 102, '123', 'Ενίσχυση πρώτων ανταποκριτών'))
        N.need(t, 'ορίζεται η πρώτη ημέρα του μήνα έκδοσης της απόφασης ανάκλησης της υπό στοιχεία '
               'ΤΕΑ/10/3.018-κε’/12.9.2024 απόφασης ένταξης', 'ν. 5313/2026 art. 123 par. 3')
        N.need(t, '«6017450»', 'ν. 5313/2026 art. 123 par. 3')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 102, '137', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*123\b|έως 1[23]\d\b', t):
            raise SystemExit('ν. 5313/2026 art. 137 may date art. 123: read it')
        LOG.append('ν. 5313/2026 art. 137 does not date art. 123; its par. 4 sets its own day, the issue of the '
                   f'revocation decision ({DIAVGEIA_5130["issued"]})')

    d = DIAVGEIA_5130
    steps = [
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Β no. 7, from the Code\'s '
                 'commencement, its publication (art. 774 par. 1): art. 44 par. 2 (which had amended art. 45 par. 2 '
                 'of ν. 5043/2023 on extending municipal support contracts) repealed.'},
        {'law': 'n-5313-2026', 'fek': (2026, 102), 'day': d['issued'], 'edit': e5313, 'check': chk5313,
         'note': f'ν. 5313/2026 art. 123 par. 4 α) (ΦΕΚ Α΄ 102/2026): art. 45 (financial reward for the first '
                 'responders of the Attica and Thessaloniki Rapid Response Directorates) repealed from the day the '
                 'decision revoking the inclusion decision ΤΕΑ/10/3.018-κε’/12.9.2024 is issued: '
                 f'{d["issued"][8:].lstrip("0")} August 2026 (decision {d["protocol"]}, ΑΔΑ {d["ada"]}).'},
    ]
    part = build('75-n5130', 'nomos-5130-2024', 2024, 127, 5130,
                 'asset declarations, placement of foreign minors, retrial after ECtHR judgments and other provisions',
                 steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2024 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, whose '
                     'timeline stops at 100 rows and lists ΦΕΚ Α΄ 102/2026 ("Ακύρωση"). Amending: ν. 5314/2026 art. '
                     '773 par. Β no. 7 (ΦΕΚ Α΄ 103/2026; ν. 5321/2026 art. 54, ΦΕΚ Α΄ 114/2026, restates that list '
                     'with no. 7 unchanged) and ν. 5313/2026 art. 123 par. 4 α) (ΦΕΚ Α΄ 102/2026). Issues after Α΄ '
                     '177/2026 were searched only through the official index.',
                     'ν. 5313/2026 art. 123 par. 4 repeals art. 45 "from the date the revocation decision of par. 3 '
                     'is issued", par. 3 naming the decision that revokes the inclusion decision '
                     'ΤΕΑ/10/3.018-κε’/12.9.2024 of the action with ΟΠΣ code «6017450». That decision is a '
                     'ministerial act outside the Gazette. It is identified by its record in the official Diavgeia '
                     f'transparency programme: ΑΔΑ {d["ada"]}, protocol number {d["protocol"]} (the same series as '
                     f'the inclusion decision), issuer {d["issuer"]}, subject «{d["subject"]}», date of issue '
                     f'{d["issued"]}; it is the only revocation decision the programme lists for that code after '
                     'ν. 5313/2026 was published. The repeal is dated by that day; the date comes from the record, '
                     'not from the decision\'s own text. Par. 4 β) (a joint ministerial decision, Β΄ 5629) is outside '
                     'this act.',
                     'A repealed article or paragraph is removed from the day the repeal takes effect, as elsewhere '
                     'in the corpus. Art. 44 keeps its title, which names the amendment its par. 2 made.'])
    part['sources'].append({
        'name': f'Πρόγραμμα Διαύγεια (diavgeia.gov.gr): record ΑΔΑ {d["ada"]} ({d["issuer"]}, {d["protocol"]})',
        'url': f'https://diavgeia.gov.gr/decision/view/{d["ada"]}', 'retrieved': '2026-11-02', 'requests': 2,
        'licence': 'Official record of a public administrative act (ν. 4727/2020, Πρόγραμμα Διαύγεια); only its '
                   'metadata (protocol number, issuer, subject, date of issue) is used.',
        'notes': 'Dates the repeal of art. 45 by ν. 5313/2026 art. 123 par. 4 α).'})
    return part


# ---------------------------------------------------------------- ν. 5057/2023

def p5057() -> dict:
    def e5079(u: dict) -> dict:
        return restate_par(u, 'art-032', 2023, 215, '69', 'Τροποποίηση παρ. 1 άρθρου 32 ν. 5057/2023', '1', [
            ('take', '31η.12.2023', '.', '29η.2.2024', '.')], 'ν. 5079/2023 art. 69')

    def chk5079() -> None:
        commencement(2023, 215, '123', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται ειδικότερα.', 'ν. 5079/2023 art. 123')
        instr, _ = amending(2023, 215, '69', 'Τροποποίηση παρ. 1 άρθρου 32 ν. 5057/2023')
        N.need(instr, 'τροποποιείται ως προς την καταληκτική ημερομηνία και η παρ. 1 διαμορφώνεται ως εξής:',
               'ν. 5079/2023 art. 69')
        LOG.append('ν. 5079/2023 art. 123: in force on publication; art. 69 gives no day of its own')

    def e5149(u: dict) -> dict:
        return restate(u, 'art-010', 2024, 169, '75', 'άρθρου 10 ν. 5057/2023', [
            ('add', 'δυνάμει του άρθρου 49 του ν. 4940/2022 (Α’ 112)',
             ', ανανεώθηκαν με το άρθρο 10 του ν. 5057/2023 (Α’ 164)'),
            ('sub', 'έως τις 31.10.2024.', 'έως τις 30.4.2025', ('1. ', '\n2. ')),
            ('add', 'οι οποίες έχουν συναφθεί σύμφωνα με το άρθρο 36 του ν. 4765/2021 (Α’ 6)',
             ', ανανεώθηκαν με το άρθρο 10 του ν. 5057/2023'),
            ('sub', 'έως τις 31.10.2024.', 'έως τις 30.4.2025.', ('\n2. ', '\n3. ')),
            ('take', None, None, '\n5. ', None)], 'ν. 5149/2024 art. 75 par. 2', q_index=1)

    def chk5149() -> None:
        commencement(2024, 169, '76', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη '
                     'δημοσίευσή του', 'ν. 5149/2024 art. 76')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 169, '76', 'Έναρξη ισχύος'))
        N.need(t, '2. Η ισχύς του Μέρους Β’ αρχίζει από την 1η.1.2025', 'ν. 5149/2024 art. 76 par. 2')
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*75\b', t):
            raise SystemExit('ν. 5149/2024 art. 76 may date art. 75: read it')
        in_part(2024, 169, '75', 'ΜΕΡΟΣ Δ’', 'ΜΕΡΟΣ Ε’', 'ν. 5149/2024')
        LOG.append('ν. 5149/2024 art. 76 par. 2 dates Part Β’ (and arts. 41-45, 50) only; art. 75 is in Part Δ’')

    def e5161(u: dict) -> dict:
        # the issue prints no closing » after the restated art. 14: the quotation ends before par. 2 of art. 15
        instr, qs = amending(2024, 196, '15', 'ν. 5057/2023')
        q = qs[0]
        k = next(i for i, l in enumerate(q) if l.startswith('2. Στην παρ. 3 του άρθρου 32 του ν. 5057/2023'))
        if k != 3 or not q[k - 1].endswith('για την εφαρμογή του παρόντος.'):
            raise SystemExit('ν. 5161/2024 art. 15: the restated art. 14 does not end where expected')
        LOG.append('ν. 5161/2024 art. 15 par. 1: the issue prints no closing » after the restated art. 14; the '
                   'quotation is read up to par. 2 of art. 15')
        u = restate(u, 'art-014', 2024, 196, '15', 'ν. 5057/2023', [
            ('add', 'το οποίο διαχειρίζεται', 'η Διεύθυνση Φαρμάκου του Υπουργείου Υγείας, ορίζεται υπεύθυνος '
             'επεξεργασίας το Υπουργείο Υγείας και εκτελούσα την επεξεργασία είναι')], 'ν. 5161/2024 art. 15 par. 1',
            src=(instr, q[:k]), allowed={
                ('ορίζεται', ''): 'The restatement governs: it reads «υπεύθυνος επεξεργασίας είναι το Υπουργείο '
                                  'Υγείας» where the instruction quotes «ορίζεται υπεύθυνος επεξεργασίας το Υπουργείο '
                                  'Υγείας».',
                ('', 'είναι'): 'The restatement governs (the same change as «ορίζεται» above).',
                ('', 'ν'): 'The restatement governs: it prints «του ν. ν. 4270/2014», with «ν.» twice.'})
        # ... and closes both quotations at the end of par. 2 («... του άρθρου 14.»»): the second » is that close
        h2, q2 = sub_quote(2024, 196, '15', 'ν. 5057/2023', 2, 'ν. 5161/2024 art. 15 par. 2')
        if len(q2) != 1 or not q2[-1].endswith('του άρθρου 14.»'):
            raise SystemExit('ν. 5161/2024 art. 15 par. 2: the quotation does not end with «14.»»»')
        q2 = [q2[0][:-1]]
        LOG.append('ν. 5161/2024 art. 15 par. 2: the quotation ends «… του άρθρου 14.»»», closing the restated art. '
                   '14 as well; the second » is not part of art. 32 par. 3')
        return restate_par(u, 'art-032', 2024, 196, '15', 'ν. 5057/2023', '3', [
            ('add', 'οι κυρώσεις για την περίπτωση μη συμμόρφωσής τους',
             'το όργανο που διαπιστώνει και επιβάλλει τις κυρώσεις και η διαδικασία επιβολής τους')],
            'ν. 5161/2024 art. 15 par. 2', src=(h2, q2))

    def chk5161() -> None:
        commencement(2024, 196, '50', '1. Με την επιφύλαξη της παρ. 2 η ισχύς του παρόντος αρχίζει από τη '
                     'δημοσίευσή του', 'ν. 5161/2024 art. 50')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 196, '50', 'Έναρξη ισχύος'))
        N.need(t, '2. Η ισχύς του άρθρου 13 αρχίζει από την 1η.1.2024.', 'ν. 5161/2024 art. 50 par. 2')
        LOG.append('ν. 5161/2024 art. 50 par. 2 dates art. 13 only')

    def e5209(u: dict) -> dict:
        return restate(u, 'art-015', 2025, 100, '131', 'ν. 5057/2023', [
            ('take', None, None, ' Στην περίπτωση διάθεσης', None)], 'ν. 5209/2025 art. 131')

    def chk5209() -> None:
        t = ' '.join(p['text'] for p in N.amending_article(2025, 100, '132', 'Έναρξη ισχύος'))
        N.need(t, '1. Η ισχύς των Μερών Α’ έως Δ’ αρχίζει τρεις (3) μήνες μετά από τη δημοσίευσή του',
               'ν. 5209/2025 art. 132 par. 1')
        N.need(t, 'καθώς και στ) του Μέρους Ε’, αρχίζουν από τη δημοσίευση του παρόντος στην Εφημερίδα της '
               'Κυβερνήσεως.', 'ν. 5209/2025 art. 132 par. 2 στ)')
        in_part(2025, 100, '131', 'ΜΕΡΟΣ Ε’', 'ΜΕΡΟΣ ΣΤ’', 'ν. 5209/2025')
        instr, _ = amending(2025, 100, '131', 'ν. 5057/2023')
        N.need(instr, 'προστίθεται δεύτερο εδάφιο και το άρθρο 15 διαμορφώνεται ως εξής:', 'ν. 5209/2025 art. 131')
        LOG.append('ν. 5209/2025 art. 132 par. 2 στ): Part Ε’ (arts. 116-131) in force on publication')

    def e5216(u: dict) -> dict:
        return restate_par(u, 'art-032', 2025, 118, '47', 'ν. 5057/2023', '3', [
            ('sub', 'Ψηφιακής Διακυβέρνησης και Υγείας',
             'Υγείας, Εθνικής Οικονομίας και Οικονομικών και Ψηφιακής Διακυβέρνησης')], 'ν. 5216/2025 art. 47',
            allowed={('για την', 'σε'): 'The restatement governs: the instruction restates par. 3 «μετά από '
                                        'νομοτεχνικές βελτιώσεις» (after drafting improvements), and it reads «οι '
                                        'κυρώσεις σε περίπτωση μη συμμόρφωσής τους» for «οι κυρώσεις για την '
                                        'περίπτωση μη συμμόρφωσής τους».'})

    def chk5216() -> None:
        commencement(2025, 118, '61', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν προβλέπεται διαφορετικά στις επιμέρους διατάξεις του.',
                     'ν. 5216/2025 art. 61')
        LOG.append('ν. 5216/2025 art. 61: in force on publication; art. 47 gives no day of its own')

    steps = [
        {'law': 'n-5079-2023', 'fek': (2023, 215), 'day': None, 'edit': e5079, 'check': chk5079,
         'note': 'ν. 5079/2023 art. 69 (ΦΕΚ Α΄ 215/2023), in force on publication (art. 123): in art. 32 par. 1 the '
                 'latest day to which the Minister of Health may extend the stay of specialising nurses becomes '
                 '29 February 2024.'},
        {'law': 'n-5149-2024', 'fek': (2024, 169), 'day': None, 'edit': e5149, 'check': chk5149,
         'note': 'ν. 5149/2024 art. 75 par. 2 (ΦΕΚ Α΄ 169/2024), in force on publication (art. 76 par. 1; art. 75 is '
                 'in Part Δ’, which par. 2 does not date otherwise): art. 10 restated, the renewed contracts of the '
                 'General Secretariat for Natural Disaster Recovery running to 30 April 2025; par. 5 added.'},
        {'law': 'n-5161-2024', 'fek': (2024, 196), 'day': None, 'edit': e5161, 'check': chk5161,
         'note': 'ν. 5161/2024 art. 15 (ΦΕΚ Α΄ 196/2024), in force on publication (art. 50 par. 1; par. 2 dates art. '
                 '13 only): art. 14 restated (the Ministry of Health\'s Medicines Directorate manages the medicines '
                 'tracking system; controller and processor named); art. 32 par. 3 restated (the body that imposes '
                 'the penalties and the procedure).'},
        {'law': 'n-5209-2025', 'fek': (2025, 100), 'day': None, 'edit': e5209, 'check': chk5209,
         'note': 'ν. 5209/2025 art. 131 (ΦΕΚ Α΄ 100/2025), in force on publication (art. 132 par. 2 στ): Part Ε’): '
                 'art. 15 gains a second sentence (no prescriber\'s signature and stamp or recipient\'s signature for '
                 'medicines delivered at home or at service points).'},
        {'law': 'n-5216-2025', 'fek': (2025, 118), 'day': None, 'edit': e5216, 'check': chk5216,
         'note': 'ν. 5216/2025 art. 47 (ΦΕΚ Α΄ 118/2025), in force on publication (art. 61): art. 32 par. 3 restated '
                 '(the joint decision is made by the Ministers of Health, National Economy and Finance, and Digital '
                 'Governance).'},
    ]
    return build('77-n5057', 'nomos-5057-2023', 2023, 164, 5057,
                 'COVID-19 vaccination, health staff, the National Public Health Organisation and other provisions',
                 steps, [
                     'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2023 to '
                     'Α΄ 177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF '
                     'where it does not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; '
                     'and the official search.et.gr relation index for the issue, fetched on 2026-11-02, whose '
                     'timeline stops at 100 rows and shows no Α΄ issue. Amending: ν. 5079/2023 art. 69, ν. 5149/2024 '
                     'art. 75 par. 2, ν. 5161/2024 art. 15, ν. 5209/2025 art. 131 and ν. 5216/2025 art. 47. Other '
                     'mentions only refer to it: ν. 5079/2023 art. 66 par. 1 α) extends to 31 March 2024 the COVID-19 '
                     'rules whose validity art. 3 par. 1 α) had extended, and ν. 5161/2024 art. 44 par. 4 extends art. '
                     '11 par. 2 to 31 December 2025; both extend validity and change no words of ν. 5057/2023. ΦΕΚ Α΄ '
                     '162/2024 (the VAT Code codification) and ΦΕΚ Α΄ 88/2026 (a codification, its art. 273 and its '
                     'correspondence table) name it only as a source. Issues after Α΄ 177/2026 were searched only '
                     'through the official index.',
                     'ν. 5161/2024 art. 15 (ΦΕΚ Α΄ 196/2024) prints no closing » after the restated art. 14 and '
                     'closes both quotations at the end of its par. 2 («… κατ’ εφαρμογή του άρθρου 14.»»»): the '
                     'restated art. 14 is read up to par. 2, and art. 32 par. 3 ends «… του άρθρου 14.».',
                     'Words an instruction changes without quoting them (ν. 5079/2023 art. 69: the closing day; ν. '
                     '5149/2024: the new par. 5; ν. 5209/2025: the second sentence) are taken from the restatement.'])


# ---------------------------------------------------------------- ν. 5256/2025

def p5256() -> dict:
    def e5305(u: dict) -> dict:
        w16, w17 = 'ν. 5305/2026 art. 16', 'ν. 5305/2026 art. 17'
        # the issue prints no closing » after the restated art. 32: the quotation runs to the end of art. 16
        texts = [p['text'] for p in N.amending_article(2026, 85, '16', 'Αντικατάσταση άρθρου 32 ν. 5256/2025')]
        if (len(texts) < 3 or texts[1] != '«Άρθρο 32' or not texts[0].endswith('αντικαθίσταται ως εξής:')
                or '«' in texts[0] or any(t.count('«') != t.count('»') for t in texts[2:])
                or not texts[-1].startswith('9. ')):
            raise SystemExit(f'{w16}: the restatement is not as expected')
        LOG.append(f'{w16}: the issue prints no closing » after the restated art. 32; the quotation is read from '
                   '«Άρθρο 32 to the end of art. 16 (par. 9)')
        u = restate(u, 'art-032', 2026, 85, '16', '', [
            ('take', 'Υποβολή ψηφιακού', None, 'Έκδοση και υποβολή', None)], w16,
            src=(texts[0] + ' «', [texts[1][1:]] + texts[2:]))
        return restate(u, 'art-041', 2026, 85, '17', 'Αντικατάσταση άρθρου 41 ν. 5256/2025', [
            ('take', 'Εξουσιοδοτικές διατάξεις', None, 'Εξουσιοδοτικές διατάξεις', None)], w17)

    def chk5305() -> None:
        commencement(2026, 85, '43', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη της παρ. 2.', 'ν. 5305/2026 art. 43')
        commencement(2026, 85, '43', '2. Η ισχύς του δεύτερου εδαφίου της παρ. 2 του άρθρου 22 του ν. 4727/2020',
                     'ν. 5305/2026 art. 43 par. 2')
        for art, must in (('16', 'Αντικατάσταση άρθρου 32 ν. 5256/2025'), ('17', 'Αντικατάσταση άρθρου 41 ν. 5256/2025')):
            instr = ' '.join(p['text'] for p in N.amending_article(2026, 85, art, must))
            if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
                raise SystemExit(f'ν. 5305/2026 art. {art} has words on its own commencement: read it')
        LOG.append('ν. 5305/2026 art. 43 par. 2 defers only a provision added to ν. 4727/2020 (by its art. 21), not '
                   'arts. 16-17; their instructions have no words on their own commencement')

    steps = [
        {'law': 'n-5305-2026', 'fek': (2026, 85), 'day': None, 'edit': e5305, 'check': chk5305,
         'note': 'ν. 5305/2026 arts. 16 and 17 (ΦΕΚ Α΄ 85/2026), in force on publication (art. 43 par. 1): art. 32 '
                 '(the digital copy of the identity card for private-sector bodies) and art. 41 (its enabling '
                 'provisions) are replaced; both articles are restated.'},
    ]
    return build('78-n5256', 'nomos-5256-2025', 2025, 223, 5256, 'digital road safety and other provisions', steps, [
        'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in '
        'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
        '58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; and the official search.et.gr relation '
        'index for the issue, fetched on 2026-11-02, which lists ΦΕΚ Α΄ 85/2026 as its only Α΄ issue (its Β΄ rows are '
        'ministerial decisions, which do not amend a statute). Amending: ν. 5305/2026 arts. 16 and 17. Issues after Α΄ '
        '177/2026 were searched only through the official index.',
        'Art. 49 par. 2 starts Chapter Δ of Part Α (arts. 11-15) with the issue of the joint ministerial decision of '
        'art. 23 par. 8, which is not published in ΦΕΚ Α΄ and whose date was not found; as for every law here, the '
        'text is shown from publication.'])



# ---------------------------------------------------------------- ν. 5179/2025 (GR-13)

def p5179() -> dict:
    w113, w114 = 'ν. 5324/2026 art. 113', 'ν. 5324/2026 art. 114'

    def e5324(u: dict) -> dict:
        u = restate(u, 'art-019', 2026, 121, '113', 'Τροποποίηση άρθρου 19 ν. 5179/2025', [
            ('take', '6 ΠΕ ΕΝΗΜΕΡΩΣΗΣ', '\n7 ', '6 ΠΕ ΕΠΙΚΟΙΝΩΝΙΑΣ', '\n7 '),
            ('sub', '33', '32'),
            ('sub', '3', '4', ('1 ΥΕ ΦΥΛΑΚΩΝ ΥΕ ΦΥΛΑΚΩΝ ', ' ΥΕ ΝΥΧΤΟΦΥΛΑΚΩΝ'))], w113,
            allowed=ALLOWED_5179.get('art-019', {}))
        return restate(u, 'art-020', 2026, 121, '114', 'Τροποποίηση άρθρου 20 ν. 5179/2025', [
            ('sub', 'πενήντα δύο (52)', 'πενήντα οκτώ (58)'),
            ('sub', '3', '4', ('1 ΔΕ ΔΙΟΙΚΗΤΙΚΟΥ', '\n2 ΔΕ')),
            ('sub', '2', '7', ('ΥΕ ΦΥΛΑΚΩΝ ΥΕ ΦΥΛΑΚΩΝ ', None))], w114,
            allowed=ALLOWED_5179.get('art-020', {}))

    def chk5324() -> None:
        commencement(2026, 121, '141', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2,3 και 4.', 'ν. 5324/2026 art. 141')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 121, '141', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*11[34]\b|έως 1[1-3]\d\b', t):
            raise SystemExit('ν. 5324/2026 art. 141 may date arts. 113-114: read it')
        for art, must in (('113', 'Τροποποίηση άρθρου 19 ν. 5179/2025'), ('114', 'Τροποποίηση άρθρου 20 ν. 5179/2025')):
            instr = ' '.join(p['text'] for p in N.amending_article(2026, 121, art, must))
            if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
                raise SystemExit(f'ν. 5324/2026 art. {art} has words on its own commencement: read it')
        LOG.append('ν. 5324/2026 art. 141 pars. 2-4 date arts. 6, 7, 11 par. 3 and 13 par. 2 of Part Α΄, Part Β΄ and '
                   'art. 136 par. 3 only; arts. 113-114 take effect on publication')

    steps = [
        {'law': 'n-5324-2026', 'fek': (2026, 121), 'number': 5324, 'day': None, 'edit': e5324, 'check': chk5324,
         'note': 'ν. 5324/2026 arts. 113 and 114 (ΦΕΚ Α΄ 121/2026), in force on publication (art. 141 par. 1): the '
                 'tables of permanent posts (art. 19) and of posts under private-law contracts of indefinite term '
                 '(art. 20) are amended; both articles are restated.'},
    ]
    return build('79-n5179', 'nomos-5179-2025', 2025, 26, 5179,
                 'reorganisation of the National Gallery and other cultural bodies', steps, DECISIONS_5179)


_R5179 = 'The restatement (ν. 5324/2026\'s own text) governs and is used as printed.'
ALLOWED_5179: dict = {
    'art-019': {
        ('', 'α/α κλαδος ειδικοτητα αριθμος θεσεων'):
            'The restated Table 1 runs onto a second page and repeats its header row there. ' + _R5179,
        ('hardware', 'hardware}'): 'The restatement prints a closing brace for the closing parenthesis. ' + _R5179,
        ('software', '{software'): 'The restatement prints an opening brace for the opening parenthesis. ' + _R5179,
        ('π ε μεταφραστω ν', 'πε μεταφραστων'): 'Spacing only: the 2025 issue\'s text layer splits the word. '
                                                  + _R5179,
        ('κατηγοριατε', 'κατηγορια τε'): 'Spacing only: the 2025 issue\'s text layer runs the words together. '
                                         + _R5179,
        ('μηχανικων', 'τεχνολογικων εφαρμογων'):
            'Table 2, row 2: the branch «ΤΕ ΜΗΧΑΝΙΚΩΝ» becomes «ΤΕ ΤΕΧΝΟΛΟΓΙΚΩΝ ΕΦΑΡΜΟΓΩΝ», a change the '
            'instruction does not list. ' + _R5179,
        ('ουρωρων', 'θυρωρων'): 'Table 3, row 4: «ΟΥΡΩΡΩΝ» (a misprint) reads «ΘΥΡΩΡΩΝ». ' + _R5179,
        ('4', '1'): 'The caption of Table 4 reads «1. ΚΑΤΗΓΟΡΙΑ Υ.Ε.» in the restatement (was «4.»). ' + _R5179,
        ('προσωπικού καθαριότητας εσωτερικών χώρων', 'προσωπικου καθαριοτητας εσωτερικων χωρων'):
            'Accents only (capitals). ' + _R5179,
        ('καοαριοτητας', 'καθαριοτητας'): '«ΚΑΟΑΡΙΟΤΗΤΑΣ» (a misprint) reads «ΚΑΘΑΡΙΟΤΗΤΑΣ». ' + _R5179,
    },
    # art-020: GR-13 listed «οργα-νικές» and «αορί-στου» here (soft hyphens inside a line of the 2025 issue, read as
    # hyphens); since GR-14 the reader joins them (parse_n4624.SOFT_MID), so the restatement matches word for word
}
DECISIONS_5179: list[str] = [
    'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in '
    'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
    '58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; and the official search.et.gr relation index '
    'for the issue, fetched on 2026-11-02, whose Α΄ rows are ΦΕΚ Α΄ 121/2026 and Α΄ 103/2026 (its Γ΄ rows are '
    'appointments, which do not amend a statute). Amending: ν. 5324/2026 arts. 113 and 114 (ΦΕΚ Α΄ 121/2026). The '
    'Local Government Code ratified by ν. 5314/2026 (ΦΕΚ Α΄ 103/2026) names the law once, in art. 383, which lists '
    'the fee of art. 94 among municipal revenues: it refers to the law and changes none of its words. Issues after '
    'Α΄ 177/2026 were searched only through the official index.',
    'The staff tables of arts. 19 and 20 are read row by row from the table rules printed in the Gazette: each row '
    'is one line, its cells left to right (serial number, branch, speciality, number of posts); where one branch '
    'has several specialities, each speciality is followed by its own number of posts. In the restated Table 3 of '
    'art. 19 (ν. 5324/2026) the issue draws a rule under the row\'s first line, so row 4 reads as two lines.',
]


# ---------------------------------------------------------------- ν. 5218/2025 (GR-13)

def p5218() -> dict:
    w243, w251 = 'ν. 5297/2026 art. 243', 'ν. 5297/2026 art. 251'

    def e5297(u: dict) -> dict:
        u = restate(u, 'art-071', 2026, 64, '243', 'Τροποποίηση άρθρου 71 ν. 5218/2025', [
            ('add', 'μεταξύ του φορέα', 'ανάπτυξης ή/και του φορέα'),
            ('add', 'του φορέα', 'ανάπτυξης ή του φορέα', ('α) φορείς', None))], w243,
            allowed=ALLOWED_5218.get('art-071', {}))
        instr, qs = amending(2026, 64, '251', 'Τροποποίηση παρ. 3 άρθρου ενδέκατου του καταστατικού')
        N.need(instr, 'που κυρώθηκε με το άρθρο 53 του ν. 5218/2025 (Α’ 125)', w251)
        return restate_span(u, 'art-053', ('Άρθρο ενδέκατο', 'Άρθρο δωδέκατο'), '3. ', r'^\d+\. ', (instr, qs[0]), [
            ('sub', 'στην κατηγορία εκπαίδευσης Π.Ε.', 'στις κατηγορίες εκπαίδευσης Π.Ε. και Τ.Ε.')], w251,
            allowed=ALLOWED_5218.get('art-053', {}))

    def chk5297() -> None:
        commencement(2026, 64, '257', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 5297/2026 art. 257')
        for art, must in (('243', 'Τροποποίηση άρθρου 71 ν. 5218/2025'),
                          ('251', 'Τροποποίηση παρ. 3 άρθρου ενδέκατου του καταστατικού')):
            instr = ' '.join(p['text'] for p in N.amending_article(2026, 64, art, must))
            if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
                raise SystemExit(f'ν. 5297/2026 art. {art} has words on its own commencement: read it')
        LOG.append('ν. 5297/2026 art. 257: in force on publication; arts. 243 and 251 give no day of their own')

    def e5314(u: dict) -> dict:
        return remove_par(u, 'art-031', 2026, 103, '773', 'Καταργούμενες διατάξεις', '4',
                          '2. η παρ. 4 του άρθρου 31 του ν. 5218/2025 (Α’ 125),', 'ν. 5314/2026 art. 773 par. Β no. 2')

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2, 3 και 4.', 'ν. 5314/2026 art. 774')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '774', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*773\b|έως 77\d\b', t):
            raise SystemExit('ν. 5314/2026 art. 774 may defer art. 773: read it')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '773', 'Καταργούμενες διατάξεις'))
        N.need(t, 'Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:', 'ν. 5314/2026 art. 773 par. Β')
        body = N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής Αυτοδιοίκησης')
        N.need(' '.join(p['text'] for p in body), '2. η παρ. 4 του άρθρου 31 του ν. 5218/2025 (Α’ 125),',
               'ν. 5321/2026 art. 54')
        LOG.append('ν. 5314/2026 art. 774 pars. 2-4 do not date art. 773; ν. 5321/2026 art. 54 replaces art. 773 '
                   '(corrections) and its par. Β no. 2 repeals art. 31 par. 4 of ν. 5218/2025 in the same words, so it '
                   'changes nothing here')

    steps = [
        {'law': 'n-5297-2026', 'fek': (2026, 64), 'day': None, 'edit': e5297, 'check': chk5297,
         'note': 'ν. 5297/2026 arts. 243 and 251 (ΦΕΚ Α΄ 64/2026), in force on publication (art. 257): art. 71 '
                 '(industrial and business areas) restated, and par. 3 of art. ενδέκατο of the statute of «Εθνικό '
                 'Σύστημα Διαπίστευσης Α.Ε.» set out in art. 53 restated.'},
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Β no. 2, from the Code\'s '
                 'commencement, its publication (art. 774 par. 1): art. 31 par. 4 repealed.'},
    ]
    return build('80-n5218', 'nomos-5218-2025', 2025, 125, 5218,
                 'training for public procurement staff, public contracts and other provisions', steps, DECISIONS_5218)


ALLOWED_5218: dict = {
    'art-053': {('της', 'των'): 'Statute art. ενδέκατο par. 3: «της αναγκών» (a misprint) reads «των αναγκών» in the '
                               'restatement, which (ν. 5297/2026\'s own text) governs and is used as printed.'},
}
DECISIONS_5218: list[str] = [
    'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026, in '
    'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
    '58-127, 143, 144, 147, 148, 174, 175), every mention read by hand; and the official search.et.gr relation index '
    'for the issue, fetched on 2026-11-02, whose Α΄ rows are ΦΕΚ Α΄ 64/2026, Α΄ 103/2026 and Α΄ 114/2026 (its Β΄ and '
    'Γ΄ rows are a ministerial decision and an appointment, which do not amend a statute). Amending: ν. 5297/2026 '
    'arts. 243 and 251 (ΦΕΚ Α΄ 64/2026) and ν. 5314/2026 art. 773 par. Β no. 2 '
    '(ΦΕΚ Α΄ 103/2026; ν. 5321/2026 art. 54, ΦΕΚ Α΄ 114/2026, restates that list with no. 2 unchanged). Issues after '
    'Α΄ 177/2026 were searched only through the official index.',
    'Art. 53 sets out the statute of «Εθνικό Σύστημα Διαπίστευσης Α.Ε.» in full, so ν. 5297/2026 art. 251, which '
    'amends par. 3 of art. ενδέκατο of that statute ("ratified by art. 53 of ν. 5218/2025"), changes the words of '
    'art. 53 and is applied there.',
    'The table of teaching posts in art. 77 is read row by row from the table rules printed in the Gazette: each row '
    'is one line, its cells left to right (branch, speciality, number of posts); a branch with two specialities '
    'gives each its own number of posts.',
    'A repealed paragraph is removed from the day the repeal takes effect, as elsewhere in the corpus.',
]

# ---------------------------------------------------------------- ν. 4937/2022 (GR-15)

def p4937() -> dict:
    w = 'ν. 5314/2026 art. 773 par. Α no. 31'
    must = 'Καταργούμενες διατάξεις'
    phrases = ['Α. Από την έναρξη ισχύος του παρόντος:', '31. τα άρθρα 16 και 45 του ν. 4937/2022 (Α’ 106),']

    def e5314(u: dict) -> dict:
        u = repeal_unit(u, 'art-016', 2026, 103, '773', must, phrases, w)
        return repeal_unit(u, 'art-045', 2026, 103, '773', must, phrases, w)

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2, 3 και 4.', 'ν. 5314/2026 art. 774')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '774', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*773\b|έως 77\d\b', t):
            raise SystemExit('ν. 5314/2026 art. 774 may defer art. 773: read it')
        body = N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής Αυτοδιοίκησης')
        bt = ' '.join(p['text'] for p in body)
        N.need(bt, 'Β. Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:', 'ν. 5321/2026 art. 54')
        N.need(bt, '28. τα άρθρα 16 και 45 του ν. 4937/2022 (Α’ 106),', 'ν. 5321/2026 art. 54')
        LOG.append('ν. 5314/2026 art. 774 pars. 2-4 do not date art. 773; ν. 5321/2026 art. 54 replaces art. 773 '
                   '(corrections): in its new list the repeal of arts. 16 and 45 of ν. 4937/2022 is par. Β no. 28, in '
                   'the same words and also from the Code\'s commencement, so it changes nothing here')

    steps = [
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Α no. 31, from the Code\'s '
                 'commencement, its publication (art. 774 par. 1): arts. 16 and 45 repealed.'},
    ]
    return build('92-n4937', 'nomos-4937-2022', 2022, 106, 4937,
                 'digital service of documents in criminal and civil proceedings, release of the Hellenic Police from '
                 'serving documents, and other provisions', steps, DECISIONS_4937)


DECISIONS_4937: list[str] = [
    'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2022 to Α΄ 177/2026, in '
    'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
    '58-127, 143, 144, 147, 148, 174, 175), every mention of the law read by hand; and the official search.et.gr '
    'relation index for the issue, fetched on 2026-11-02, whose only Α΄ row is ΦΕΚ Α΄ 161/2024 (its Β΄ and Γ΄ rows '
    'are ministerial decisions and appointments, which do not amend a statute). Amending: ν. 5314/2026 art. 773 '
    'par. Α no. 31 (ΦΕΚ Α΄ 103/2026), which repeals arts. 16 and 45; ν. 5321/2026 art. 54 (ΦΕΚ Α΄ 114/2026) replaces '
    'art. 773 with corrections, and its new par. Β no. 28 repeals them in the same words. ΦΕΚ Α΄ 161/2024 (ν. 5143/2024) art. 57 par. 2 names art. 32 of ν. 4937/2022 in '
    'the words it gives art. 3 par. 5 of ν. 4440/2016, a reference only; ΦΕΚ Α΄ 142/2022 art. 40 extends again a '
    'term that art. 40 of ν. 4937/2022 had extended, without changing its words; ΦΕΚ Α΄ 48/2025 art. 193, Α΄ '
    '170/2025 art. 6, Α΄ 239/2025 art. 57, Α΄ 102/2026 arts. 59 and 60 and Α΄ 103/2026 arts. 303 and 686 and its '
    'annex refer to it only. Issues after Α΄ 177/2026 were searched only through the official index.',
    'ν. 5039/2023 art. 132 par. 8 (ΦΕΚ Α΄ 83/2023, read in the Gazette PDF) repeals art. 15 "as regards the part '
    'that concerns the costs of leasing aircraft of the Fire Service and the General Secretariat for Civil '
    'Protection, for the year 2024 and after". It names no words of art. 15 and removes none: it narrows what the '
    'article covers from 2024. Art. 15 is therefore kept as published, and this partial repeal is recorded here '
    'rather than as a version.',
    'A repealed article is removed from the day the repeal takes effect, as elsewhere in the corpus. Arts. 16 and 45 '
    'amended other laws (ν. 4662/2020 and ν. 3852/2010); their repeal is applied to the words of ν. 4937/2022 here, '
    'and what it does to those other laws is not part of this record.',
]

# ---------------------------------------------------------------- ν. 4703/2020 (GR-15)

def insert_item(u: dict, key: str, y: int, n: int, art: str, must: str, par: str, item: str, prev: str,
                instr_phrase: str, what: str, q_index: int = 0) -> dict:
    """An item («δ) …», a whole quotation) added at the end of paragraph `par` of article `key`, whose last item is
    `prev`; the previous item keeps its closing punctuation as printed (the instruction does not change it)."""
    instr, qs = amending(y, n, art, must)
    N.need(instr, instr_phrase, what)
    q = qs[q_index]
    if not q[0].startswith(f'{item}) '):
        raise SystemExit(f'{what}: the quotation is not item {item}): {q[0][:30]}')
    lines = u[key]
    i = N.find_one(lines, f'{par}. ', f'{what}: {key} par. {par}')
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
        j += 1
    if not lines[j - 1].startswith(f'{prev}) '):
        raise SystemExit(f'{what}: par. {par} of {key} does not end with item {prev}): {lines[j - 1][:30]}')
    u = dict(u)
    u[key] = lines[:j] + q + lines[j:]
    LOG.append(f'{what}: {key} par. {par} gains item {item}) at its end ({len(q)} line(s))')
    return u


def p4703() -> dict:
    w = 'ν. 5322/2026 art. 72 par. 1'

    def e5322(u: dict) -> dict:
        return insert_item(u, 'art-016', 2026, 117, '72', 'Τροποποίηση παρ. 4 άρθρου 16 ν. 4703/2020', '4', 'δ', 'γ',
                           'Στην παρ. 4 του άρθρου 16 του ν. 4703/2020 (Α’ 131), περί Ιδρύματος Μέριμνας και Αριστείας '
                           'της Ελληνικής Αστυνομίας, προστίθεται περ. δ) ως εξής:', w)

    def chk5322() -> None:
        commencement(2026, 117, '99', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν προβλέπεται διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 5322/2026 art. 99')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 117, '72', 'Τροποποίηση παρ. 4 άρθρου 16 ν. 4703/2020'))
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', t.split('«', 1)[0], re.I):
            raise SystemExit(f'{w}: words on its own commencement: read it')
        N.need(t, '2. Ειδικά η εισφορά που αφορά στο έτος 2026 καταβάλλεται τον επόμενο μήνα από τη δημοσίευση', w)
        LOG.append('ν. 5322/2026 art. 99: in force on publication; art. 72 gives no day of its own (its par. 2, on '
                   'when the 2026 contribution is paid, and par. 3, on adjusting it, are its own provisions)')

    steps = [
        {'law': 'n-5322-2026', 'fek': (2026, 117), 'day': None, 'edit': e5322, 'check': chk5322,
         'note': 'ν. 5322/2026 art. 72 par. 1 (ΦΕΚ Α΄ 117/2026), in force on publication (art. 99): art. 16 par. 4 '
                 'gains item δ), a yearly contribution of the Hellenic Police staff to the Foundation.'},
    ]
    return build('95-n4703', 'nomos-4703-2020', 2020, 131, 4703, 'public outdoor assemblies and other provisions',
                 steps, DECISIONS_4703)


DECISIONS_4703: list[str] = [
    'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2020 to Α΄ 177/2026, in '
    'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
    '58-127, 143, 144, 147, 148, 174, 175), every mention of the law read by hand; and the official search.et.gr '
    'relation index for the issue, fetched on 2026-11-02, whose only later Α΄ row is ΦΕΚ Α΄ 117/2026 (its Β΄ row is '
    'a ministerial decision, which does not amend a statute). Amending: ν. 5322/2026 art. 72 par. 1 (ΦΕΚ Α΄ '
    '117/2026). Presidential decrees 72/2020 (ΦΕΚ Α΄ 167/2020), 75/2020 (Α΄ 173/2020) and 10/2021 (Α΄ 19/2021) are '
    'made under it or cite it; ν. 4764/2020 art. 178 (Α΄ 256/2020), ν. 5187/2025 arts. 30 and 42 (Α΄ 48/2025) and '
    'ν. 5240/2025 art. 39 (Α΄ 184/2025) refer to it only. Issues after Α΄ 177/2026 were searched only through the '
    'official index.',
    'ν. 4760/2020 art. 33 (ΦΕΚ Α΄ 247/2020) provides that art. 18 par. 2 applies from 26 June 2019, a start before '
    'the law was published. It changes no words, so it is recorded here and not as a version; as for every law '
    'here, the text is shown from publication.',
]

# ---------------------------------------------------------------- ν. 4950/2022 (GR-15)

def remove_item(u: dict, key: str, y: int, n: int, art: str, must: str, par: str, item: str, phrase: str,
                what: str) -> dict:
    """Item `item` of paragraph `par` of article `key` repealed: its line (and any sub-items) removed. The item
    must stand on its own line, after the paragraph's first line."""
    body = N.amending_article(y, n, art, must)
    N.need(' '.join(p['text'] for p in body), phrase, what)
    lines = u[key]
    i = N.find_one(lines, f'{par}. ', f'{what}: {key} par. {par}')
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
        j += 1
    hits = [k for k in range(i + 1, j) if lines[k].startswith(f'{item}) ')]
    if len(hits) != 1:
        raise SystemExit(f'{what}: item {item}) found {len(hits)} times in par. {par} of {key}')
    a = hits[0]
    b = next((k for k in range(a + 1, j) if re.match(ITEM_RE, lines[k]) and not lines[k].startswith(item)), j)
    u = dict(u)
    u[key] = lines[:a] + lines[b:]
    LOG.append(f'{what}: {key} par. {par} item {item}) repealed (removed, {b - a} line(s))')
    return u


def p4950() -> dict:
    w = 'ν. 5173/2025 art. 17'
    must = 'Καταργούμενες διατάξεις'
    phrase = ('Από την έναρξη ισχύος του παρόντος καταργούνται η παρ. 1 και η περ. β) της παρ. 2 του άρθρου 50 του ν. '
              '4950/2022 (Α’ 128), περί του Εθνικού Συστήματος Τραύματος.')

    def e5173(u: dict) -> dict:
        u = remove_item(u, 'art-050', 2025, 11, '17', must, '2', 'β', phrase, w)
        return remove_par(u, 'art-050', 2025, 11, '17', must, '1', phrase, w)

    def chk5173() -> None:
        commencement(2025, 11, '24', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2 και 3.', 'ν. 5173/2025 art. 24')
        t = ' '.join(p['text'] for p in N.amending_article(2025, 11, '24', 'Έναρξη ισχύος'))
        N.need(t, '2. Η ισχύς των άρθρων 18, 19 και 20 αρχίζει την 9η.02.2025.', w)
        N.need(t, '3. Η ισχύς του άρθρου 23, περί της διασφάλισης των πιστώσεων υγειονομικής περίθαλψης των '
                  'στρατιωτικών νοσοκομείων, αρχίζει από την 1η Ιανουαρίου 2025.', w)
        LOG.append('ν. 5173/2025 art. 24: in force on publication; its pars. 2 and 3 date arts. 18-20 and 23 only, '
                   'not art. 17')

    steps = [
        {'law': 'n-5173-2025', 'fek': (2025, 11), 'day': None, 'edit': e5173, 'check': chk5173,
         'note': 'ν. 5173/2025 art. 17 (ΦΕΚ Α΄ 11/2025), from its commencement, its publication (art. 24 par. 1): '
                 'art. 50 par. 1 and par. 2 item β) repealed.'},
    ]
    return build('97-n4950', 'nomos-4950-2022', 2022, 128, 4950,
                 'measures against the COVID-19 pandemic, protection of public health and other urgent provisions',
                 steps, DECISIONS_4950)


DECISIONS_4950: list[str] = [
    'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2022 to Α΄ 177/2026, in '
    'legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does not (2026: '
    '58-127, 143, 144, 147, 148, 174, 175), every mention of the law read by hand; and the official search.et.gr '
    'relation index for the issue, fetched on 2026-11-02, whose timeline is cut off at 100 rows; its only Α΄ row is '
    'ΦΕΚ Α΄ 11/2025 (the others are Β΄, Γ΄, Υ.Ο.Δ.Δ. and Α.Σ.Ε.Π. issues: decisions, appointments and staff '
    'notices, which do not amend a statute). Amending: ν. 5173/2025 art. 17 (ΦΕΚ Α΄ 11/2025). ν. 4999/2022 art. 63 '
    '(ΦΕΚ Α΄ 225/2022) lets doctors kept in service under art. 39 of ν. 4950/2022 stay longer, without changing its '
    'words; ν. 5157/2024 art. 13 (ΦΕΚ Α΄ 187/2024) refers to art. 49. Issues after Α΄ 177/2026 were searched only '
    'through the official index.',
    'A repealed paragraph or item is removed from the day the repeal takes effect, as elsewhere in the corpus. After '
    'ν. 5173/2025 art. 17, art. 50 keeps only par. 2 item α), printed as it stands («2. α) …»).',
]

PARTS: dict = {'40-n5178': p5178, '41-n5188': p5188, '46-n5255': p5255, '47-n5261': p5261, '58-n5194': p5194,
               '48-n5176': p5176, '50-n5229': p5229, '53-n5263': p5263, '54-n5253': p5253,
               '66-n5113': p5113, '67-n5216': p5216, '70-n5142': p5142, '71-n5131': p5131, '73-n5029': p5029, '74-n5075': p5075,
               '75-n5130': p5130, '77-n5057': p5057, '78-n5256': p5256, '79-n5179': p5179, '80-n5218': p5218,
               '92-n4937': p4937, '95-n4703': p4703, '97-n4950': p4950,
               '990-n5122': lambda: p5122(), '991-n5063': lambda: p5063(), '992-n4780': lambda: p4780()}


# ---------------------------------------------------------------- GR-15 batch 2 (part names 990+ sort after 99-)

def _search15(law: int, year: int, index: str, found: str) -> str:
    return (f'Amending laws were looked for three ways: a full-text scan of every ΦΕΚ Α΄ issue from {year} to Α΄ '
            '177/2026, in legalize-gr (commit 36cb88a374cd) where it has the issue and in the Gazette PDF where it does '
            'not (2026: 58-127, 143, 144, 147, 148, 174, 175), every mention of the law read by hand; and the official '
            f'search.et.gr relation index for the issue, fetched on 2026-11-02, {index}. {found} Issues after Α΄ '
            '177/2026 were searched only through the official index.')


def p5122() -> dict:
    w = 'ν. 5255/2025 art. 50'

    def e5255(u: dict) -> dict:
        return restate(u, 'art-011', 2025, 219, '50', 'Τροποποίηση άρθρου 11 ν. 5122/2024', [
            ('sub', 'ν. 4399/2016 και ν. 3908/2011', 'νόμων 4887/2022, 4399/2016 και 3908/2011'),
            # the instruction quotes «… στους νόμους 3908/2011 …»; the published text reads «… στους ν. 3908/2011 …»
            ('sub_at', 'έχουν υπαχθεί στους ν. 3908/2011 (Α’ 8) και 4399/2016 (Α’ 117)',
             'έχουν υπαχθεί στους νόμους 3908/2011 (Α’ 8) και 4399/2016 (Α’ 117)',
             'έχουν υπαχθεί στους νόμους 4887/2022 (Α’ 16), 4399/2016 (Α’ 117) και 3908/2011 (Α’ 8),'),
        ], w, allowed=ALLOWED_5122)

    def chk5255() -> None:
        commencement(2025, 219, '64', '1. Με την επιφύλαξη της παρ. 2, ο παρών νόμος ισχύει από τη δημοσίευσή του '
                     'στην Εφημερίδα της Κυβερνήσεως, εκτός αν άλλως ορίζεται στις επιμέρους διατάξεις του.',
                     'ν. 5255/2025 art. 64')
        t = ' '.join(p['text'] for p in N.amending_article(2025, 219, '64', 'Έναρξη ισχύος'))
        N.need(t, '2. Το άρθρο 47, περί της αναγραφής της πορείας διαμόρφωσης της τελικής τιμής', w)
        instr = ' '.join(p['text'] for p in N.amending_article(2025, 219, '50', 'Τροποποίηση άρθρου 11 ν. 5122/2024'))
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
            raise SystemExit(f'{w}: words on its own commencement: read it')
        LOG.append('ν. 5255/2025 art. 64: in force on publication; its par. 2 dates art. 47 only; art. 50 gives no day '
                   'of its own')

    steps = [
        {'law': 'n-5255-2025', 'fek': (2025, 219), 'day': None, 'edit': e5255, 'check': chk5255,
         'note': 'ν. 5255/2025 art. 50 (ΦΕΚ Α΄ 219/2025), in force on publication (art. 64 par. 1): art. 11 (the tax '
                 'exemption incentive) extended to investment plans under ν. 4887/2022; the article is restated.'},
    ]
    return build('990-n5122', 'nomos-5122-2024', 2024, 108, 5122,
                 'disqualified directors (art. 1 of Directive (EU) 2019/1151) and other urgent provisions', steps, [
                     _search15(5122, 2024, 'whose only later Α΄ row is ΦΕΚ Α΄ 219/2025 (its Β΄ row is a ministerial '
                               'decision, which does not amend a statute)',
                               'Amending: ν. 5255/2025 art. 50 (ΦΕΚ Α΄ 219/2025), the only article that names it.'),
                 ])


ALLOWED_5122: dict = {}


def p5063() -> dict:
    w = 'ν. 5140/2024 art. 67'

    def e5140(u: dict) -> dict:
        return restate_par(u, 'art-008', 2024, 154, '67', 'Τροποποίηση παρ. 1 άρθρου 8 ν. 5063/2023', '1', [
            ('sub', 'κατά την περίοδο 2023-2024', 'κατά την εμβολιαστική περίοδο κάθε έτους'),
            ('sub', 'το συμβατικό τετραδύναμο αδρανοποιημένο εμβόλιο κατά της γρίπης (κατηγορίας QIVe και QIVc)',
             'το εμβόλιο κατά της γρίπης, το οποίο προσδιορίζεται κάθε έτος με σχετική εγκύκλιο του Υπουργείου Υγείας '
             'μετά από εισήγηση της Εθνικής Επιτροπής Εμβολιασμών'),
        ], w)

    def chk5140() -> None:
        commencement(2024, 154, '73', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, υπό την επιφύλαξη των παρ. 2 έως 5.', 'ν. 5140/2024 art. 73')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 154, '73', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*67\b|έως 6\d\b|έως 7\d\b', t):
            raise SystemExit('ν. 5140/2024 art. 73 may defer art. 67: read it')
        instr = ' '.join(p['text'] for p in N.amending_article(2024, 154, '67', 'Τροποποίηση παρ. 1 άρθρου 8 ν. 5063/2023'))
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
            raise SystemExit(f'{w}: words on its own commencement: read it')
        LOG.append('ν. 5140/2024 art. 73: in force on publication; its pars. 2-5 date other provisions of that law, '
                   'not art. 67')

    steps = [
        {'law': 'n-5140-2024', 'fek': (2024, 154), 'day': None, 'edit': e5140, 'check': chk5140,
         'note': 'ν. 5140/2024 art. 67 (ΦΕΚ Α΄ 154/2024), in force on publication (art. 73 par. 1): art. 8 par. 1 '
                 '(flu vaccination of adults) now covers every vaccination season and the vaccine the Ministry names '
                 'each year; the paragraph is restated.'},
    ]
    return build('991-n5063', 'nomos-5063-2023', 2023, 184, 5063,
                 'the national network of enhanced care units for stroke patients and other urgent provisions', steps, [
                     _search15(5063, 2023, 'whose only later Α΄ row is ΦΕΚ Α΄ 154/2024 (its Β΄ rows are ministerial '
                               'decisions, which do not amend a statute)',
                               'Amending: ν. 5140/2024 art. 67 (ΦΕΚ Α΄ 154/2024), the only article that names it.'),
                 ])


def p4780() -> dict:
    w184, w185 = 'ν. 4876/2021 art. 184', 'ν. 4876/2021 art. 185'

    def e4876(u: dict) -> dict:
        u = restate_par(u, 'art-032', 2021, 251, '184', 'Τροποποίηση παρ. 1 άρθρου 32 ν. 4780/2021', '1', [
            ('sub', 'έντεκα (11)', 'δεκατρείς (13)')], w184)
        return restate_par(u, 'art-029', 2021, 251, '185', 'Τροποποίηση της παρ. 9 του άρθρου 29', '9', [
            ('take', None, None, ' Έως τη δημοσίευση του ως άνω διατάγματος', None)], w185, allowed={
            ('οικονομικά', ''): 'Art. 29 par. 9, first sentence: the restatement reads «υποστηρίζεται διοικητικά και '
                                'τεχνικά» where the published text reads «διοικητικά, οικονομικά και τεχνικά»; the '
                                'instruction names only the added third sentence (financial support now comes from the '
                                'Ministry of Finance). The restatement (ν. 4876/2021\'s own text) governs and is used '
                                'as printed.'})

    def chk4876() -> None:
        commencement(2021, 251, '186', 'Η ισχύς του παρόντος, αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά σε επιμέρους διατάξεις.', 'ν. 4876/2021 art. 186')
        for art, must in (('184', 'Τροποποίηση παρ. 1 άρθρου 32 ν. 4780/2021'),
                          ('185', 'Τροποποίηση της παρ. 9 του άρθρου 29')):
            instr = ' '.join(p['text'] for p in N.amending_article(2021, 251, art, must))
            if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
                raise SystemExit(f'ν. 4876/2021 art. {art}: words on its own commencement: read it')
        LOG.append('ν. 4876/2021 art. 186: in force on publication; arts. 184 and 185 give no day of their own')

    steps = [
        {'law': 'n-4876-2021', 'fek': (2021, 251), 'day': None, 'edit': e4876, 'check': chk4876,
         'note': 'ν. 4876/2021 arts. 184 and 185 (ΦΕΚ Α΄ 251/2021), in force on publication (art. 186): the National '
                 'Bioethics and Technoethics Committee grows from eleven to thirteen members (art. 32 par. 1), and art. '
                 '29 par. 9 gains a third sentence on the financial support of the National Commission for Human '
                 'Rights; both paragraphs are restated.'},
    ]
    return build('992-n4780', 'nomos-4780-2021', 2021, 30, 4780,
                 'the National Accessibility Authority, the National Commission for Human Rights and the National '
                 'Bioethics and Technoethics Committee', steps, [
                     _search15(4780, 2021, 'whose only later Α΄ row is ΦΕΚ Α΄ 251/2021',
                               'Amending: ν. 4876/2021 arts. 184 and 185 (ΦΕΚ Α΄ 251/2021). The presidential decree '
                               'in ΦΕΚ Α΄ 128/2023 (the organisation of the National Commission for Human Rights) is '
                               'made under it and cites it only.'),
                     'Art. 185 adds the third sentence of art. 29 par. 9 without quoting it ("a third sentence on the '
                     'financial support of the Commission"): the sentence is taken from the restated paragraph.',
                 ])


# ---------------------------------------------------------------- GR-16: ν. 4955/2022 (split start, as for ν. 4800/2021)

# Part Α (arts. 1-25) starts on 13.2.2023 (art. 68 par. 2), except two sub-provisions of the inner articles that arts.
# 13 and 14 restate, which start on publication. Of arts. 13 and 14 the first version holds only the lines that carry
# those sub-provisions (by line index in the article as published): the article's heading and title, its instruction,
# the inner article's heading and title, and the sub-provision (for art. 13 with the opening words of its paragraph).
SPLIT_4955 = {
    'day': '2023-02-13',
    'clause': ('2. Η ισχύς των άρθρων 1 έως 25 του Μέρους Α’ αρχίζει από τις 13 Φεβρουαρίου 2023 πλην της περ. β’ της '
               'παρ. 2 του εσωτερικού άρθρου 64 του ν. 2960/2001 (Α’ 265) του άρθρου 13 του παρόντος και της παρ. 3 του '
               'εσωτερικού άρθρου 65 του ίδιου νόμου του άρθρου 14 του παρόντος που ισχύουν από τη δημοσίευση του '
               'παρόντος.'),
    'late': [f'art-{i:03d}' for i in range(1, 26)],
    'partial': {'art-013': ([0, 1, 2, 3, 4, 6, 8], ['«Άρθρο 64', '2. Για να παρασχεθεί η άδεια της παρ. 1',
                                                    'β) να μην έχει καταδικαστεί']),
                'art-014': ([0, 1, 2, 3, 4, 9], ['«Άρθρο 65', '3. Με αποφάσεις του Υπουργού Οικονομικών'])},
    'retro': '3. Η ισχύς του άρθρου 52 αρχίζει από τις 5 Ιουλίου 2022.',
}


def split_4955(part: dict) -> dict:
    """The built part (published text, then ν. 4972/2022) with Part Α moved to its own start day: the first version
    holds arts. 26-68 and the two early sub-provisions of arts. 13 and 14; on 13.2.2023 arts. 1-25 come in full,
    credited to the law itself."""
    s = SPLIT_4955
    act = part['acts'][0]
    v0 = act['versions'][0]
    units = v0['units']
    flat = units['art-068']['text']
    for c in (s['clause'], s['retro'], '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
              'Κυβερνήσεως με την επιφύλαξη των παρ. 2 και 3.'):
        if c not in flat.split('\n'):
            raise SystemExit(f'ν. 4955/2022: art. 68 does not read {c[:60]!r}')
    if not units['art-001']['text'].startswith('ΜΕΡΟΣ Α’') or not units['art-026']['text'].startswith('ΜΕΡΟΣ Β’'):
        raise SystemExit('ν. 4955/2022: Part Α is not arts. 1-25')
    if any(k in s['late'] for v in act['versions'][1:] for k in v['changes']):
        raise SystemExit('ν. 4955/2022: a later version changes Part Α: the split must be re-read')
    early = {}
    for k, (idx, starts) in s['partial'].items():
        lines = units[k]['text'].rstrip('\n').split('\n')
        keep = [lines[i] for i in idx]
        if keep[0] != f'Άρθρο {int(k[4:])}' or not keep[2].startswith(f'Στο άρθρο {starts[0][7:]} του ν. 2960/2001') \
                or len(keep) != len(starts) + 4 or \
                not all(l.startswith(x) for l, x in zip([keep[3]] + keep[5:], starts)):
            raise SystemExit(f'ν. 4955/2022: {k}: the early lines are not where expected: {[l[:30] for l in keep]}')
        early[k] = {**units[k], 'text': '\n'.join(keep) + '\n'}
    pub = v0['from']
    key = 'n-4955-2022'
    v0['units'] = {k: (early[k] if k in early else u) for k, u in units.items() if k not in s['late'] or k in early}
    v0['note'] = ('ν. 4955/2022 as published in ΦΕΚ Α΄ 139/2022: arts. 26-68, which its commencement article puts in '
                  'force on publication, and of arts. 13 and 14 only the two sub-provisions in force then; Part Α '
                  '(arts. 1-25) follows on 13.2.2023.')
    act['versions'].append({'from': s['day'], 'source_url': v0['source_url'], 'sha256': v0['sha256'],
                            'changes': {k: units[k] for k in s['late']}, 'credits': {k: [key] for k in s['late']},
                            'note': 'Part Α of ν. 4955/2022 (arts. 1-25, the transposition of Directive (EU) 2020/262) '
                                    'takes effect on 13.2.2023 (art. 68 par. 2); arts. 13 and 14 now in full.'})
    dec = part['decisions']
    i = next(i for i, x in enumerate(dec) if x.startswith('ν. 4955/2022 is dated '))
    dec[i] = ('ν. 4955/2022 starts in steps, by its own commencement article (art-068): «' + ' '.join(
        l for l in flat.split('\n') if re.match(r'^[123]\. ', l)) + '» So the first version (' + pub + ', publication, '
        'the date on the issue\'s masthead) holds arts. 26-68 and, of Part Α, only the two sub-provisions in force on '
        'publication; Part Α (arts. 1-25) is added in full on 2023-02-13, credited to the law itself, the day art. 68 '
        'par. 2 names.')
    dec[i + 1:i + 1] = [
        'ν. 4955/2022 arts. 13 and 14 restate arts. 64 and 65 of ν. 2960/2001 (the National Customs Code). Art. 68 par. '
        '2 starts on publication item β) of par. 2 of the restated art. 64 (art. 13) and par. 3 of the restated art. 65 '
        '(art. 14). In the first version those two articles hold only the lines that carry them, as printed: the '
        'article\'s heading and title, its instruction (which lists every change it makes to the inner article), the '
        'inner article\'s heading and title, and the sub-provision itself, for art. 13 after the opening words of its '
        'par. 2, which item β) completes. The rest of each article is added on 2023-02-13. The instruction and the '
        'inner headings are shown from publication because they are the words that carry those sub-provisions into ν. '
        '2960/2001.',
        'ν. 4955/2022 art. 52 (a new second sentence of art. 146 par. 3 of ν. 4808/2021) starts on 5 July 2022 by art. '
        '68 par. 3, nine days before the law was published (14 July 2022). As for every law in this corpus, the text '
        'is shown from publication; the earlier day the law gives it, 2022-07-05, is recorded here and not as a '
        'version.',
    ]
    return part


def p4955() -> dict:
    w = 'ν. 4972/2022 art. 164'
    must = 'Αντικατάσταση άρθρου 54 ν. 4955/2022'

    def e4972(u: dict) -> dict:
        return restate(u, 'art-054', 2022, 181, '164', must, [
            ('take', 'Ρύθμιση θεμάτων Διεύθυνσης', None, 'Ρύθμιση θεμάτων Διεύθυνσης', None)], w)

    def chk4972() -> None:
        commencement(2022, 181, '192', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά σε επιμέρους διατάξεις.', 'ν. 4972/2022 art. 192')
        instr = ' '.join(p['text'] for p in N.amending_article(2022, 181, '164', must))
        N.need(instr, 'Το άρθρο 54 του ν. 4955/2022 (Α’ 139) αντικαθίσταται ως εξής:', w)
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
            raise SystemExit(f'{w}: words on its own commencement: read it')
        LOG.append('ν. 4972/2022 art. 192: in force on publication, "unless the provisions say otherwise"; art. 164 '
                   'gives no day of its own')

    steps = [
        {'law': 'n-4972-2022', 'fek': (2022, 181), 'day': None, 'edit': e4972, 'check': chk4972,
         'note': 'ν. 4972/2022 art. 164 (ΦΕΚ Α΄ 181/2022), in force on publication (art. 192): art. 54 replaced; the '
                 'Directorate of Tax Policy gains a new department for codifying tax law.'},
    ]
    part = build('993-n4955', 'nomos-4955-2022', 2022, 139, 4955,
                 'the general arrangements for excise duty (Directive (EU) 2020/262), customs representation and the '
                 'profession of customs representative, other customs and tax provisions and other urgent provisions',
                 steps, [
                     _search15(4955, 2022, 'whose only later Α΄ row is ΦΕΚ Α΄ 181/2022 ("Αντικατάσταση"; its Β΄ rows '
                               'are ministerial decisions, which do not amend a statute)',
                               'Amending: ν. 4972/2022 art. 164 (ΦΕΚ Α΄ 181/2022), which replaces art. 54. ΦΕΚ Α΄ '
                               '134/2025 art. 4 names art. 32 of ν. 4955/2022 in a definition, a reference only.'),
                     'Art. 164 of ν. 4972/2022 replaces the whole of art. 54 ("αντικαθίσταται ως εξής"): the new '
                     'article is its own text, used as printed.',
                 ])
    return split_4955(part)


PARTS.update({'993-n4955': lambda: p4955()})


# ---------------------------------------------------------------- GR-16: ν. 4713/2020

def pnp_article(y: int, n: int, ordinal: str, must: str, what: str) -> tuple[str, list[str]]:
    """(instruction, quotation lines) of «Άρθρο <ordinal>» of an Act of Legislative Content, whose articles are
    numbered in words (amending_article reads numbered articles only): title lines naming `must`, one instruction
    paragraph, then one quotation up to the next article."""
    paras = N.fek_paras(y, n)
    hits = [i for i, p in enumerate(paras) if p['text'] == f'Άρθρο {ordinal}']
    if len(hits) != 1:
        raise SystemExit(f'{what}: Άρθρο {ordinal} found {len(hits)} times in Α΄ {n}/{y}')
    i, title = hits[0] + 1, []
    while i < len(paras) and not paras[i]['text'].startswith('Στο '):
        title.append(paras[i]['text'])
        i += 1
    if must not in ' '.join(title) or len(title) > 3:
        raise SystemExit(f'{what}: title {title!r} does not name {must!r}')
    instr, i, q = paras[i]['text'], i + 1, []
    while i < len(paras) and not re.match(r'^Άρθρο [α-ωά-ώ ]+$', paras[i]['text']):
        q.append(paras[i]['text'])
        i += 1
    if not q or not q[0].startswith('«') or not re.search(r'»\.?$', q[-1]):
        raise SystemExit(f'{what}: the article is not one instruction and one quotation')
    q = [q[0][1:]] + q[1:]
    q[-1] = re.sub(r'»\.?$', '', q[-1])
    return instr, q


PNP_4713 = ('pnp-2020-08-22', 2020, 161)


def p4713() -> dict:
    key, y, n = PNP_4713
    wp, w121 = 'Π.Ν.Π. της 22.8.2020 art. πέμπτο', 'ν. 4763/2020 art. 121'
    must_p = 'Ρύθμιση ζητημάτων πρόσληψης προσωπικού'
    title = N.law_title(y, n)
    if not title.startswith('ΝΟΜΟΘΕΤΙΚΟΥ ΠΕΡΙΕΧΟΜΕΝΟΥ Έκτακτα μέτρα για την ενίσχυση των αστικών συγκοινωνιών'):
        raise SystemExit(f'{wp}: unexpected title {title[:60]!r}')
    entry = {'label': 'Π.Ν.Π. της 22.8.2020', 'kind': 'decree',
             'title': 'Πράξη Νομοθετικού Περιεχομένου: ' + title[len('ΝΟΜΟΘΕΤΙΚΟΥ ΠΕΡΙΕΧΟΜΕΝΟΥ '):],
             'enacted': PS.signed(y, n), 'published': N.masthead(y, n), 'url': FL.fek_url(y, n),
             'temporary_until': None, 'restores': None, 'note': None}

    def epnp(u: dict) -> dict:
        instr, q = pnp_article(y, n, 'πέμπτο', must_p, wp)
        N.need(instr, 'Στο άρθρο 34 του ν. 4713/2020 (Α’ 147) προστίθενται παρ. 3 και 4, ως εξής:', wp)
        q = split_run_on(q, wp)
        if [l.split(' ', 1)[0] for l in q] != ['3.', '4.']:
            raise SystemExit(f'{wp}: the quotation is not pars. 3 and 4: {[l[:8] for l in q]}')
        lines = u['art-034']
        nums = [int(m.group(1)) for l in lines for m in [re.match(r'^(\d+)\. ', l)] if m]
        if nums != [1, 2]:
            raise SystemExit(f'{wp}: art-034 has pars. {nums}')
        u = dict(u)
        u['art-034'] = lines + q
        LOG.append(f'{wp}: art-034 gains pars. 3 and 4 at its end ({len(q)} line(s))')
        return u

    def chkpnp() -> None:
        if (entry['enacted'], entry['published']) != ('2020-08-22', '2020-08-22'):
            raise SystemExit(f'{wp}: signed {entry["enacted"]}, published {entry["published"]}')
        t = ' '.join(p['text'] for p in N.fek_paras(y, n))
        N.need(t, 'Η ισχύς της παρούσας, η οποία θα κυρωθεί νομοθετικά κατά την παρ. 1 του άρθρου 44 του Συντάγματος, '
               'αρχίζει από τη δημοσίευσή της στην Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις '
               'επιμέρους διατάξεις της.', wp)
        instr, q = pnp_article(y, n, 'πέμπτο', must_p, wp)
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr + ' ' + ' '.join(q), re.I):
            raise SystemExit(f'{wp}: words on its own commencement: read them')
        # the ratifying law reprints the Act: its words of art. πέμπτο against the Act's own
        r = ' '.join(p['text'] for p in N.fek_paras(2020, 177))
        N.need(r, 'Κυρώνεται και έχει ισχύ νόμου από τη δημοσίευσή της στην Εφημερίδα της Κυβερνήσεως, η από 22.8.2020 '
               'Πράξη Νομοθετικού Περιεχομένου', 'ν. 4722/2020 art. 2')
        a = r.find('Στο άρθρο 34 του ν. 4713/2020')
        b = r.find('Άρθρο έκτο', a)
        if a < 0 or b < 0 or r.count('Στο άρθρο 34 του ν. 4713/2020') != 1:
            raise SystemExit('ν. 4722/2020: the reprint of art. πέμπτο was not found once')
        mine = words(instr + ' ' + ' '.join(q))
        theirs = words(r[a:b].replace('“', '«').replace('”', '»'))
        sm = difflib.SequenceMatcher(a=mine, b=theirs, autojunk=False)
        dif = [(' '.join(mine[i1:i2]), ' '.join(theirs[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes()
               if op != 'equal']
        LOG.append('ν. 4722/2020 art. 2 ratifies the Act "from its publication" and reprints it; its art. πέμπτο '
                   + ('reads word for word as the Act' if not dif else
                      'differs only in: ' + '; '.join(f'«{x}» / «{y}»' for x, y in dif)))
        if len(dif) > 2:
            raise SystemExit(f'ν. 4722/2020 reprint differs: {dif}')

    must121 = 'Τροποποίηση της παρ. 14 του άρθρου 30 του ν. 4713/2020'

    def e4763(u: dict) -> dict:
        return restate_par(u, 'art-030', 2020, 254, '121', must121, '14', [
            ('take', None, None, ' Θέσεις Διευθυντών', None)], w121)

    def chk4763() -> None:
        commencement(2020, 254, '171', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του', 'ν. 4763/2020 art. 171')
        instr = ' '.join(p['text'] for p in N.amending_article(2020, 254, '121', must121))
        N.need(instr, 'Στην παρ. 14 του άρθρου 30 του ν. 4713/2020 (Α’ 147) προστίθεται δεύτερο εδάφιο και η παρ. 14 '
               'διαμορφώνεται ως εξής:', w121)
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
            raise SystemExit(f'{w121}: words on its own commencement: read it')
        LOG.append('ν. 4763/2020 art. 171: in force on publication; art. 121 gives no day of its own')

    steps = [
        {'law': key, 'entry': (key, entry), 'fek': (y, n), 'day': None, 'edit': epnp, 'check': chkpnp,
         'note': 'The Act of Legislative Content of 22.8.2020 (ΦΕΚ Α΄ 161/2020), in force on publication (its art. '
                 'δέκατο τρίτο), art. πέμπτο: art. 34 gains pars. 3 and 4 (funding of the school cleaning contracts, '
                 'and cleaning until the staff are hired). Ratified by ν. 4722/2020 art. 2 (ΦΕΚ Α΄ 177/2020).'},
        {'law': 'n-4763-2020', 'fek': (2020, 254), 'day': None, 'edit': e4763, 'check': chk4763,
         'note': 'ν. 4763/2020 art. 121 (ΦΕΚ Α΄ 254/2020), in force on publication (art. 171): art. 30 par. 14 '
                 'restated; vacant posts of Directors of Education are filled on the Selection Council\'s proposal.'},
    ]
    return build('994-n4713', 'nomos-4713-2020', 2020, 147, 4713,
                 'modernising private education and other urgent provisions of the Ministry of Education and Religious '
                 'Affairs', steps, DECISIONS_4713)


DECISIONS_4713: list[str] = [
    _search15(4713, 2020, 'whose only later Α΄ rows name ΦΕΚ Α΄ 254/2020 («Τροποποίηση», «Αντικατάσταση»; its Β΄ and '
              'Γ΄ rows are ministerial decisions and appointments, which do not amend a statute)',
              'Amending: the Act of Legislative Content of 22.8.2020 (ΦΕΚ Α΄ 161/2020) art. πέμπτο, which adds pars. 3 '
              'and 4 to art. 34 (the index does not list it), and ν. 4763/2020 art. 121 (ΦΕΚ Α΄ 254/2020), which '
              'restates art. 30 par. 14. ν. 4763/2020 art. 71 and ν. 4823/2021 art. 232 (ΦΕΚ Α΄ 136/2021) refer to it '
              'only.'),
    'An Act of Legislative Content (Πράξη Νομοθετικού Περιεχομένου, Constitution art. 44 par. 1) has the force of '
    'law from its publication and is then ratified by a law. The Act of 22.8.2020 is credited as itself (kind '
    '"decree"), dated by its publication in ΦΕΚ Α΄ 161/2020 (22 August 2020), from which its art. δέκατο τρίτο puts '
    'it in force. ν. 4722/2020 art. 2 (ΦΕΚ Α΄ 177/2020, 15 September 2020) ratifies it and reprints its text; it '
    'changes nothing in art. πέμπτο, so the ratification is recorded here and not as a version.',
    'ν. 4753/2020 art. 55 (ΦΕΚ Α΄ 227/2020) extends the force of art. 35 "as regards" the compensation of volunteer '
    'school traffic wardens to the school year 2020-2021. It removes and adds no words of art. 35, so it is '
    'recorded here and not as a version.',
    'Art. 35\'s own second sentence makes it apply from 1.3.2020, before the law was published (29 July 2020). As for '
    'every law in this corpus, the text is shown from publication; that earlier day, 2020-03-01, is recorded here and '
    'not as a version.',
    'ν. 4763/2020 art. 121 says it adds a second sentence to art. 30 par. 14; the restated paragraph adds two (the '
    'second and the third: vacant posts are filled on the Selection Council\'s proposal, and the Council is convened '
    'for it). The restatement (ν. 4763/2020\'s own text) governs and is used as printed.',
]


# ---------------------------------------------------------------- GR-16: ν. 5123/2024 (starts in steps)

# art. 31: Part Γ (arts. 27-30) on publication except art. 27 (16.9.2024); Parts Α (arts. 1-2) and Β (arts. 3-26) on
# the publication of the art. 24 par. 1 decision, otherwise 31.12.2024; art. 24 par. 3 lets two Ministers move Part
# Β's start. Read in series Β΄: ΦΕΚ Β΄ 7024/2024 moves Part Β to 30.6.2025; ΦΕΚ Β΄ 3333/2025 (the art. 24 par. 1
# decision) fixes 30.06.2025 as the Register's first day. Art. 31 itself is shown from publication.
SPLIT_5123 = [
    ('2024-09-16', ['art-027'], 'Art. 27 of ν. 5123/2024 takes effect on 16.9.2024 (art. 31 par. 2).'),
    ('2024-12-31', ['art-001', 'art-002'], 'Part Α of ν. 5123/2024 (arts. 1-2, purpose and subject) takes effect on '
     '31.12.2024 (art. 31 par. 1: no decision under art. 24 par. 1 was published by then).'),
    ('2025-06-30', [f'art-{i:03d}' for i in range(3, 27)], 'Part Β of ν. 5123/2024 (arts. 3-26, the law of pledge and '
     'the Electronic Register of Pledges) takes effect on 30.6.2025, the day to which joint ministerial decision 41802 '
     'ΕΞ 2024 (ΦΕΚ Β΄ 7024/2024) moved it under art. 24 par. 3, and the day the Register starts operating under the '
     'decision of art. 24 par. 1 (ΦΕΚ Β΄ 3333/2025).'),
]
CLAUSE_5123 = ['1. Η ισχύς των Μερών Α’ και Β’ αρχίζει από τη δημοσίευση της απόφασης της παρ. 1 του άρθρου 24, περί '
               'έναρξης της παραγωγικής λειτουργίας του Ηλεκτρονικού Μητρώου Ενεχύρων, άλλως την 31η Δεκεμβρίου 2024.',
               '2. Η ισχύς του Μέρους Γ’ αρχίζει από τη δημοσίευση του παρόντος, εξαιρουμένου του άρθρου 27, η ισχύς '
               'του οποίου αρχίζει από τη 16η Σεπτεμβρίου 2024.']


def b_issue(y: int, n: int) -> str:
    """Plain text of a cached series Β΄ issue (decisions read to date a start the law leaves to them)."""
    import fitz
    p = FL._key(FL.fek_url(y, n, '02'), None)
    return re.sub(r'\s+', ' ', '\n'.join(pg.get_text() for pg in fitz.open(p)))


def split_5123(part: dict) -> dict:
    act = part['acts'][0]
    v0 = act['versions'][0]
    units = v0['units']
    lines = units['art-031']['text'].split('\n')
    if [l for l in lines if re.match(r'^\d\. ', l)] != CLAUSE_5123:
        raise SystemExit('ν. 5123/2024: art. 31 does not read as expected')
    for k, first in (('art-001', 'ΜΕΡΟΣ Α’'), ('art-003', 'ΜΕΡΟΣ Β’'), ('art-027', 'ΜΕΡΟΣ Γ’'), ('art-031', 'ΜΕΡΟΣ Δ’')):
        if not units[k]['text'].startswith(first):
            raise SystemExit(f'ν. 5123/2024: {k} does not open {first}')
    if list(units) != [f'art-{i:03d}' for i in range(1, 32)]:
        raise SystemExit('ν. 5123/2024: units are not arts. 1-31')
    t = b_issue(2024, 7024)
    for need in ('και ιδίως της παρ. 3 του άρθρου 24 και του άρθρου 31 αυτού',
                 'Την μετάθεση της έναρξης ισχύος του Μέρους Β’ του ν. 5123/2024', '(Α’ 109) για τις 30.6.2025.'):
        N.need(t, need, 'ΦΕΚ Β΄ 7024/2024')
    t = b_issue(2025, 3333)
    N.need(t, 'Ορίζεται η 30.06.2025, ημέρα Δευτέρα, ως ημερομηνία για την έναρξη λειτουργίας του Ηλεκτρονικού Μητρώου '
              'Ενεχύρων του ν. 5123/2024 (Α’ 109)', 'ΦΕΚ Β΄ 3333/2025')
    N.need(t, 'Τεύχος B’ 3333/30.06.2025', 'ΦΕΚ Β΄ 3333/2025')
    late = [k for _, ks, _ in SPLIT_5123 for k in ks]
    key = 'n-5123-2024'
    for day, ks, _ in SPLIT_5123:
        if any(k in v.get('changes', {}) for v in act['versions'][1:] if v['from'] <= day for k in ks):
            raise SystemExit(f'ν. 5123/2024: an amendment before {day} touches {ks}: the split must be re-read')
    v0['units'] = {k: u for k, u in units.items() if k not in late}
    v0['note'] = ('ν. 5123/2024 as published in ΦΕΚ Α΄ 109/2024: only the articles in force on publication (arts. 28-30 '
                  'of Part Γ, and art. 31, the commencement article); the rest follows on the days art. 31 sets.')
    vs = act['versions'] + [{'from': day, 'source_url': v0['source_url'], 'sha256': v0['sha256'],
                             'changes': {k: units[k] for k in ks}, 'credits': {k: [key] for k in ks}, 'note': note}
                            for day, ks, note in SPLIT_5123]
    act['versions'] = [vs[0]] + sorted(vs[1:], key=lambda v: v['from'])
    dec = part['decisions']
    i = next(i for i, x in enumerate(dec) if x.startswith('ν. 5123/2024 is dated '))
    dec[i] = ('ν. 5123/2024 starts in steps, by its own commencement article (art-031): «' + ' '.join(CLAUSE_5123) +
              '» Art. 24 par. 1 leaves the Register\'s first day to a decision of the Board of the Hellenic Cadastre, '
              'and art. 24 par. 3 lets the Ministers of Justice and of Digital Governance move the start of Part Β. '
              'So the first version (2024-07-19, publication, the date on the issue\'s masthead) holds arts. 28-30 '
              'and art. 31 (the commencement article, shown from publication since it is the provision that sets '
              'those days); art. 27 follows on 2024-09-16, Part Α (arts. 1-2) on 2024-12-31 and Part Β (arts. 3-26) '
              'on 2025-06-30, each credited to the law itself.')
    dec[i + 1:i + 1] = [
        'The start of Parts Α and Β was dated from the decisions themselves, read in the Gazette (series Β΄): joint '
        'ministerial decision 41802 ΕΞ 2024 (ΦΕΚ Β΄ 7024/2024, 20 December 2024), made under art. 24 par. 3 and art. '
        '31, moves the start of Part Β to 30.6.2025; the Board\'s decision under art. 24 par. 1 (ΦΕΚ Β΄ 3333/2025, '
        'published 30 June 2025) fixes 30.06.2025, a Monday, as the day the Register starts operating. A search of the '
        'official search.et.gr index for the Register\'s name in series Β΄ (2024 and 2025) finds those two and three '
        'later Board decisions on how the Register works (ΦΕΚ Β΄ 2882/2025, 4613/2025, 6469/2025), none of which '
        'dates a Part. No decision under art. 24 par. 1 was published by 31 December 2024, so Part Α, which no '
        'decision moved, is dated by art. 31 par. 1\'s other day, 2024-12-31; Part Β is dated 2025-06-30, the day '
        'both decisions name.',
    ]
    return part


def p5123() -> dict:
    w = 'ν. 5142/2024 art. 5 par. 1'
    must = 'Τροποποίηση άρθρου 29 ν. 5123/2024'

    def e5142(u: dict) -> dict:
        return restate(u, 'art-029', 2024, 158, '5', must, [('sub', 'Σεπτεμβρίου', 'Οκτωβρίου')], w,
                       allowed=ALLOWED_5123)

    def chk5142() -> None:
        commencement(2024, 158, '34', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή '
                     'του στην Εφημερίδα της Κυβερνήσεως.', 'ν. 5142/2024 art. 34')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 158, '34', 'Έναρξη ισχύος'))
        N.need(t, '2. Η ισχύς του Κεφαλαίου Β’ του Μέρους Β’ αρχίζει', 'ν. 5142/2024 art. 34')
        paras = N.fek_paras(2024, 158)
        pos = [i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == 'Άρθρο 5']
        mb = [i for i, p in enumerate(paras) if p['kind'] == 'struct' and p['text'].startswith('ΜΕΡΟΣ Β’')]
        kb = [i for i, p in enumerate(paras) if p['kind'] == 'struct' and p['text'].startswith('ΚΕΦΑΛΑΙΟ Β’')]
        if len(pos) != 1 or not mb or not any(mb[-1] < k for k in kb) or \
                not mb[-1] < pos[0] < min(k for k in kb if k > mb[-1]):
            raise SystemExit('ν. 5142/2024: art. 5 is not in Part Β Chapter Α')
        instr = ' '.join(p['text'] for p in N.amending_article(2024, 158, '5', must))
        N.need(instr, '2. Η παρ. 1 εφαρμόζεται και για δηλώσεις, οι οποίες υποβλήθηκαν από τη 15η Σεπτεμβρίου 2024.', w)
        LOG.append('ν. 5142/2024 art. 34: in force on publication; its par. 2 dates Chapter Β of Part Β, and art. 5 lies '
                   'in Chapter Α of Part Β')

    steps = [
        {'law': 'n-5142-2024', 'fek': (2024, 158), 'day': None, 'edit': e5142, 'check': chk5142,
         'note': 'ν. 5142/2024 art. 5 par. 1 (ΦΕΚ Α΄ 158/2024), in force on publication (art. 34 par. 1): art. 29 '
                 'restated; local authorities may file cadastral ownership declarations free of charge until 15 '
                 'October 2024 (15 September before).'},
    ]
    part = build('998-n5123', 'nomos-5123-2024', 2024, 109, 5123,
                 'modernising the law of pledge and a single Electronic Register of Pledges over movables, claims and '
                 'other rights, and other provisions', steps, [
                     _search15(5123, 2024, 'whose only later Α΄ row is ΦΕΚ Α΄ 158/2024 (its Β΄ row, ΦΕΚ Β΄ 4765/2024, '
                               'read in the Gazette, is a Cadastre decision that cites art. 28 only)',
                               'Amending: ν. 5142/2024 art. 5 (ΦΕΚ Α΄ 158/2024), which restates art. 29. ΦΕΚ Α΄ 56/2025 '
                               'art. 29 names it, a reference only.'),
                     'ν. 5142/2024 art. 5 says it replaces «Σεπτεμβρίου» by «Οκτωβρίου» and adds a second sentence, '
                     'then restates art. 29 "after legislative-drafting improvements"; the restated article has one '
                     'sentence, the old one with the new month. The restatement (ν. 5142/2024\'s own text) governs and '
                     'is used as printed. Its par. 2 applies the change also to declarations filed from 15 September '
                     '2024, before it was published (4 October 2024); as for every law in this corpus, the text is '
                     'shown from publication, and that earlier day is recorded here and not as a version.',
                 ])
    return split_5123(part)


ALLOWED_5123: dict = {}

PARTS.update({'994-n4713': lambda: p4713(), '998-n5123': lambda: p5123()})


# ---------------------------------------------------------------- GR-16 batch 2 (part names 999-, 9990+: sort after 998-)

def _chk5255(w: str, art: str, must: str) -> None:
    commencement(2025, 219, '64', '1. Με την επιφύλαξη της παρ. 2, ο παρών νόμος ισχύει από τη δημοσίευσή του στην '
                 'Εφημερίδα της Κυβερνήσεως, εκτός αν άλλως ορίζεται στις επιμέρους διατάξεις του.', 'ν. 5255/2025 art. 64')
    t = ' '.join(p['text'] for p in N.amending_article(2025, 219, '64', 'Έναρξη ισχύος'))
    N.need(t, '2. Το άρθρο 47, περί της αναγραφής της πορείας διαμόρφωσης της τελικής τιμής', 'ν. 5255/2025 art. 64')
    instr = ' '.join(p['text'] for p in N.amending_article(2025, 219, art, must))
    if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
        raise SystemExit(f'{w}: words on its own commencement: read it')
    LOG.append(f'ν. 5255/2025 art. 64: in force on publication; its par. 2 dates art. 47 only; art. {art} gives no day '
               'of its own')


def p4965() -> dict:
    w = 'ν. 5255/2025 art. 52'
    must = 'Τροποποίηση άρθρου 4 ν. 4965/2022'

    def e5255(u: dict) -> dict:
        return restate(u, 'art-004', 2025, 219, '52', must, [
            ('take', None, None, ' Τα δικαιώματα των παρ. 6 και 7', None)], w)

    steps = [
        {'law': 'n-5255-2025', 'fek': (2025, 219), 'day': None, 'edit': e5255,
         'check': lambda: _chk5255(w, '52', must),
         'note': 'ν. 5255/2025 art. 52 (ΦΕΚ Α΄ 219/2025), in force on publication (art. 64 par. 1): art. 4 (succession '
                 'to rights) gains a second and a third sentence, on the further purposes for which the new operators '
                 'may exercise those rights; the article is restated.'},
    ]
    return build('9990-n4965', 'nomos-4965-2022', 2022, 162, 4965,
                 'the restructuring of the Elefsina Shipyards and other development provisions', steps, [
                     _search15(4965, 2022, 'whose only later Α΄ row is ΦΕΚ Α΄ 219/2025 (its Β΄ and Γ΄ rows are '
                               'ministerial decisions and appointments, which do not amend a statute)',
                               'Amending: ν. 5255/2025 art. 52 (ΦΕΚ Α΄ 219/2025), which restates art. 4. ν. 5144/2024 '
                               '(ΦΕΚ Α΄ 162/2024, the VAT Code) names art. 28 of ν. 4965/2022 in its table of codified '
                               'provisions, as one source of the VAT provision it codifies; ΦΕΚ Α΄ 203/2022 art. 86 and Α΄ '
                               '137/2023 art. 39 name it in the words they give another law. These are references only.'),
                     'Art. 52 of ν. 5255/2025 adds the second and third sentences of art. 4 without quoting them '
                     'apart: they are taken from the restated article.',
                 ])


def p4792() -> dict:
    w69, w28 = 'ν. 4821/2021 art. 69', 'ν. 5087/2024 art. 28'
    m69, m28 = 'Διαγραφή προσωπικών δεδομένων', 'Προσθήκη άρθρου 4Α'

    def e4821(u: dict) -> dict:
        return restate_par(u, 'art-027', 2021, 134, '69', m69, '6', [
            ('take', 'δ) Το σύνολο', None, 'δ) Το σύνολο', None)], w69, allowed=ALLOWED_4792)

    def chk4821() -> None:
        commencement(2021, 134, '119', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν προβλέπεται διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 4821/2021 art. 119')
        instr = ' '.join(p['text'] for p in N.amending_article(2021, 134, '69', m69))
        N.need(instr, 'Η περ. δ’ της παρ. 6 του άρθρου 27 του ν. 4792/2021 (Α’ 54) τροποποιείται ως προς τον αριθμό των '
               'ημερών και η παρ. 6 διαμορφώνεται ως εξής:', w69)
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
            raise SystemExit(f'{w69}: words on its own commencement: read it')
        LOG.append('ν. 4821/2021 art. 119: in force on publication; art. 69 gives no day of its own')

    def e5087(u: dict) -> dict:
        instr, _ = amending(2024, 25, '28', m28)
        N.need(instr, 'Στον ν. 4792/2021 (Α’ 54) προστίθεται άρθρο 4Α ως εξής:', w28)
        u = add_unit(u, 'Άρθρο 4Α', 2024, 25, '28', m28, w28)
        return {k: u[k] for k in sorted(u, key=lambda k: (k[:7], k))}  # art-004-a after art-004

    def chk5087() -> None:
        commencement(2024, 25, '58', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται ειδικότερα.', 'ν. 5087/2024 art. 58')
        instr = ' '.join(p['text'] for p in N.amending_article(2024, 25, '28', m28))
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr.split('«', 1)[0], re.I):
            raise SystemExit(f'{w28}: words on its own commencement: read it')
        LOG.append('ν. 5087/2024 art. 58: in force on publication; art. 28 gives no day of its own')

    steps = [
        {'law': 'n-4821-2021', 'fek': (2021, 134), 'day': None, 'edit': e4821, 'check': chk4821,
         'note': 'ν. 4821/2021 art. 69 (ΦΕΚ Α΄ 134/2021), in force on publication (art. 119): art. 27 par. 6 item δ), '
                 'the self-test platform\'s data are deleted after thirty days instead of seven; the paragraph is '
                 'restated.'},
        {'law': 'n-5087-2024', 'fek': (2024, 25), 'day': None, 'edit': e5087, 'check': chk5087,
         'note': 'ν. 5087/2024 art. 28 (ΦΕΚ Α΄ 25/2024), in force on publication (art. 58): new art. 4Α, the prohibitions '
                 'of arts. 3 and 4 apply whatever law governs the supply agreement (art. 3 par. 4 of Directive (EU) '
                 '2019/633).'},
    ]
    return build('9991-n4792', 'nomos-4792-2021', 2021, 54, 4792,
                 'unfair trading practices in business-to-business relationships in the agricultural and food supply '
                 'chain (Directive (EU) 2019/633) and other provisions', steps, [
                     _search15(4792, 2021, 'whose later Α΄ rows are ΦΕΚ Α΄ 134/2021 and Α΄ 25/2024 (its Β΄ rows are '
                               'ministerial decisions, which do not amend a statute)',
                               'Amending: ν. 4821/2021 art. 69 (ΦΕΚ Α΄ 134/2021), which restates art. 27 par. 6, and ν. '
                               '5087/2024 art. 28 (ΦΕΚ Α΄ 25/2024), which adds art. 4Α. ΦΕΚ Α΄ 63/2021 and Α΄ 169/2021 '
                               'name art. 27 in their own provisions, references only.'),
                     'ν. 4821/2021 art. 69 says it changes item δ) of art. 27 par. 6 "as regards the number of days" '
                     'without quoting words, and restates the paragraph: the new item δ) is taken from the restatement.',
                 ])


ALLOWED_4792: dict = {
    ('self test', 'selftest'): 'Art. 27 par. 6 item γ): the published text reads «(self- test)», the restatement '
                               'prints «(selftest)»; the instruction names only item δ). The restatement (ν. '
                               '4821/2021\'s own text) governs and is used as printed.',
}

PARTS.update({'9990-n4965': lambda: p4965(), '9991-n4792': lambda: p4792()})



# ---------------------------------------------------------------- GR-17: ν. 5107/2024, ν. 5028/2023, ν. 5172/2025

_OWN_START = r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ'


def _no_own_start(y: int, n: int, art: str, must: str, what: str) -> str:
    instr = ' '.join(p['text'] for p in N.amending_article(y, n, art, must))
    if re.search(_OWN_START, instr.split('«', 1)[0], re.I):
        raise SystemExit(f'{what}: words on its own commencement: read it')
    return instr


def p5107() -> dict:
    w = 'ν. 5229/2025 art. 28'
    must = 'Τροποποίηση παρ. 4 άρθρου 20 ν. 5107/2024'

    def e5229(u: dict) -> dict:
        instr, _ = amending(2025, 158, '28', must)
        N.need(instr, 'α) στο πρώτο εδάφιο, πριν από τις λέξεις «όλων των κλάδων» προστίθενται οι λέξεις «κατηγορίας '
               'Πανεπιστημιακής Εκπαίδευσης (ΠΕ) ή Τεχνολογικής Εκπαίδευσης (ΤΕ), β) προστίθεται δεύτερο εδάφιο και η '
               'παρ. 4 διαμορφώνεται ως εξής:', w)
        return restate_par(u, 'art-020', 2025, 158, '28', must, '4', [
            ('take', None, 'όλων των κλάδων', 'κατηγορίας Πανεπιστημιακής Εκπαίδευσης (ΠΕ) ή Τεχνολογικής',
             'όλων των κλάδων'),
            ('take', None, None, ' Ειδικά στο Τμήμα Κεντρικού Πρωτοκόλλου', None)], w)

    def chk5229() -> None:
        commencement(2025, 158, '36', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν άλλως ορίζεται σε επιμέρους διατάξεις.', 'ν. 5229/2025 art. 36')
        _no_own_start(2025, 158, '28', must, w)
        LOG.append('ν. 5229/2025 art. 36: in force on publication; art. 28 gives no day of its own')

    steps = [
        {'law': 'n-5229-2025', 'fek': (2025, 158), 'day': None, 'edit': e5229, 'check': chk5229,
         'note': 'ν. 5229/2025 art. 28 (ΦΕΚ Α΄ 158/2025), in force on publication (art. 36): art. 20 par. 4, the heads '
                 'of the Human Resources and Services Directorate and its departments; where no official of the named '
                 'branches is available, only officials of university or technological education may head them, and '
                 'a second sentence covers the Central Registry Department; the paragraph is restated.'},
    ]
    return build('9992-n5107', 'nomos-5107-2024', 2024, 64, 5107,
                 'the Housing and Work for the Homeless programme and social welfare services', steps, [
                     _search15(5107, 2024, 'whose only later row is ΦΕΚ Α΄ 158/2025',
                               'Amending: ν. 5229/2025 art. 28 (ΦΕΚ Α΄ 158/2025), which restates art. 20 par. 4. ν. '
                               '5314/2026 (ΦΕΚ Α΄ 103/2026, the Local Government Code) names art. 6 of ν. 5107/2024 in '
                               'its table of the provisions it codifies; it neither amends nor repeals it (a code '
                               'that restates a provision does not change the law it came from).'),
                     'ν. 5229/2025 art. 28 item α) opens the words it adds with « but prints no closing », and places '
                     'them before the words «όλων των κλάδων»; item β) adds a second sentence without quoting it '
                     'apart. Both are taken from the restated paragraph, at the places the instruction names.',
                 ])


def p5028() -> dict:
    w44, w35 = 'ν. 5256/2025 art. 44', 'ν. 5326/2026 art. 35'
    m44, m35 = 'Τροποποίηση περ. 2 παρ. Ι. Παραρτήματος ν. 5028/2023', 'Τροποποίηση άρθρου 17 ν. 5028/2023'

    def e5256(u: dict) -> dict:
        instr, qs = amending(2025, 223, '44', m44)
        N.need(instr, 'Στην περ. 2 της παρ. Ι, του Παραρτήματος του ν. 5028/2023 (Α’ 54),', w44)
        if len(qs) != 1 or len(qs[0]) != 1 or not qs[0][0].startswith('2. Με την παράδοση στις 18.4.2024'):
            raise SystemExit(f'{w44}: the restatement is not one item 2')
        new = qs[0][0] + '.'
        lines = list(u['parartima'])
        hit = [i for i, l in enumerate(lines) if l.startswith('2. Με την παράδοση στις 18.4.2024')]
        if (len(hit) != 1 or lines.index('Ι. Βήματα Οδικού Χάρτη') > hit[0]
                or any(l.startswith('ΙΙ') for l in lines) or not lines[hit[0] + 1].startswith('3. ')):
            raise SystemExit(f'{w44}: item 2 of par. Ι not found once in the Annex')
        old = lines[hit[0]]
        if not old.endswith('στις έδρες αυτές.'):
            raise SystemExit(f'{w44}: item 2 ends {old[-30:]!r}')
        exp = apply_ops(old, new, instr, [
            ('sub', 'άμεσα', 'σταδιακά'), ('sub', 'στις μεταβατικές έδρες', 'σε μεταβατικές έδρες')], w44)
        compare(exp, new, w44, {})
        lines[hit[0]] = new
        LOG.append(f'{w44}: Annex par. Ι item 2 restated; 2 described changes checked')
        u = dict(u)
        u['parartima'] = lines
        return u

    def chk5256() -> None:
        commencement(2025, 223, '49', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή '
                     'του στην Εφημερίδα της Κυβερνήσεως. 2. Η ισχύς του Κεφαλαίου Δ’ του Μέρους Α’ αρχίζει',
                     'ν. 5256/2025 art. 49')
        in_part(2025, 223, '44', 'ΜΕΡΟΣ Γ’', 'ΜΕΡΟΣ Δ’', w44)
        _no_own_start(2025, 223, '44', m44, w44)
        LOG.append('ν. 5256/2025 art. 49: in force on publication except Chapter Δ΄ of Part Α΄; art. 44 (Part Γ΄) gives '
                   'no day of its own')

    def e5326(u: dict) -> dict:
        return restate(u, 'art-017', 2026, 125, '35', m35, [
            ('sub', 'έναν (1) Σύμβουλο Επικρατείας', 'ένα (1) μέλος του Συμβουλίου της Επικρατείας'),
            ('take', None, None, ' Οι δικαστικοί λειτουργοί του πρώτου εδαφίου', None)], w35)

    def chk5326() -> None:
        _chk5326()
        in_part(2026, 125, '35', 'ΜΕΡΟΣ Γ’', 'ΜΕΡΟΣ Δ’', w35)
        _no_own_start(2026, 125, '35', m35, w35)

    steps = [
        {'law': 'n-5256-2025', 'fek': (2025, 223), 'day': None, 'edit': e5256, 'check': chk5256,
         'note': 'ν. 5256/2025 art. 44 (ΦΕΚ Α΄ 223/2025), in force on publication (art. 49 par. 1): Annex, par. Ι item '
                 '2, the pilot telematic court offices start gradually, at transitional seats; the item is restated.'},
        {'law': 'n-5326-2026', 'fek': (2026, 125), 'day': None, 'edit': e5326, 'check': chk5326,
         'note': 'ν. 5326/2026 art. 35 (ΦΕΚ Α΄ 125/2026), in force on publication (art. 111 par. 1): art. 17, the '
                 'Roadmap Monitoring Committee takes a member of the Council of State, and its judicial members other '
                 'than the one seconded to the Special Legal Service may be honorary; the article is restated.'},
    ]
    return build('9994-n5028', 'nomos-5028-2023', 2023, 54, 5028,
                 'the regions and jurisdiction of the ordinary administrative courts and their telematic sessions',
                 steps, [
                     _search15(5028, 2023, 'whose later Α΄ rows are ΦΕΚ Α΄ 223/2025 and Α΄ 125/2026 (its Β΄ and Γ΄ '
                               'rows are ministerial decisions and appointments, which do not amend a statute; the law '
                               'gives no power to amend its Annex by decision)',
                               'Amending: ν. 5256/2025 art. 44 (ΦΕΚ Α΄ 223/2025), which restates item 2 of par. Ι of '
                               'the Annex, and ν. 5326/2026 art. 35 (ΦΕΚ Α΄ 125/2026), which restates art. 17.'),
                     'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Α no. 22 repealed art. '
                     '42 from the Code\'s commencement, 29.6.2026. ν. 5321/2026 art. 54 (ΦΕΚ Α΄ 114/2026), "correction '
                     'of errors", replaced the whole of art. 773 with effect from that same day (its par. 2: «Η παρ. 1 '
                     'ισχύει από την 29η.6.2026.»), and its new list has no such entry: its no. 19 ends «του ν. '
                     '5037/2023 (Α’ 54),» (the issue of ν. 5028/2023, not that of ν. 5037/2023) and no. 21 follows it, '
                     'as if a line had fallen out. The law as printed governs: from 29.6.2026 the repeal list in force '
                     'does not name art. 42, so art. 42 is kept, and no version is made.',
                     'ν. 5256/2025 art. 44 restates item 2 of par. Ι of the Annex; its quotation ends «…στις έδρες '
                     'αυτές». with the full stop outside it. The item keeps the full stop it was published with, as '
                     'every item of the Annex ends with one.',
                     'ν. 5326/2026 art. 35 adds a fourth sentence to art. 17 without quoting it apart: it is taken from '
                     'the restated article.',
                 ], edit_other=True)


def _chk5326() -> None:
    commencement(2026, 125, '111', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος νόμου αρχίζει από τη '
                 'δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις '
                 'του. 2. Η ισχύς του Μέρους Α’, των άρθρων 45 έως 51, 59 και 61 αρχίζει από την 16η.9.2026. 3. Η ισχύς '
                 'του άρθρου 68 αρχίζει από την 1η.10.2026.', 'ν. 5326/2026 art. 111')
    LOG.append('ν. 5326/2026 art. 111: in force on publication, except Part Α΄ and arts. 45-51, 59, 61 (16.9.2026) and '
               'art. 68 (1.10.2026)')


def p5172() -> dict:
    w = 'ν. 5326/2026 art. 67 par. 1'
    must = 'Τροποποίηση άρθρου 47 ν. 5172/2025'

    def e5326(u: dict) -> dict:
        instr, qs = amending(2026, 125, '67', must)
        N.need(instr, '1. Στο άρθρο 47 του ν. 5172/2025 (Α’ 10), περί εξουσιοδοτικών διατάξεων, επέρχονται οι '
               'ακόλουθες τροποποιήσεις: α) στην παρ. 1, αα) στο πρώτο εδάφιο, προστίθενται οι λέξεις «και του κατά '
               'περίπτωση συναρμόδιου Υπουργού», αβ) στο δεύτερο εδάφιο, οι λέξεις «Με όμοια» αντικαθίστανται από τις '
               'λέξεις «Με απόφαση του Υπουργού Δικαιοσύνης», β) στην παρ. 2 η λέξη «επαγγέλματος» αντικαθίσταται από '
               'τη λέξη «Λειτουργήματος» και οι παρ. 1 και 2 διαμορφώνονται ως εξής:', w)
        q = qs[0]
        if len(q) != 2:
            raise SystemExit(f'{w}: the restatement is not pars. 1 and 2')
        u = restate_par(u, 'art-047', 2026, 125, '67', must, '1', [
            ('take', None, ' εκδίδονται πρωτόκολλα', ' και του κατά περίπτωση συναρμόδιου Υπουργού', ' εκδίδονται'),
            ('sub', 'Με όμοια', 'Με απόφαση του Υπουργού Δικαιοσύνης')], w, allowed=ALLOWED_5172, src=(instr, [q[0]]))
        return restate_par(u, 'art-047', 2026, 125, '67', must, '2', [
            ('sub', 'επαγγέλματος', 'Λειτουργήματος')], w, src=(instr, [q[1]]))

    def chk5326() -> None:
        _chk5326()
        in_part(2026, 125, '67', 'ΜΕΡΟΣ Ε’', 'ΜΕΡΟΣ ΣΤ’', w)
        _no_own_start(2026, 125, '67', must, w)

    steps = [
        {'law': 'n-5326-2026', 'fek': (2026, 125), 'day': None, 'edit': e5326, 'check': chk5326,
         'note': 'ν. 5326/2026 art. 67 par. 1 (ΦΕΚ Α΄ 125/2026), in force on publication (art. 111 par. 1): art. 47 '
                 'pars. 1 and 2, the forensic service protocols are issued jointly with the competent minister, the '
                 'quality indicators by the Minister of Justice, and the code of ethics names the forensic '
                 '"λειτούργημα"; the paragraphs are restated.'},
    ]
    return build('9995-n5172', 'nomos-5172-2025', 2025, 10, 5172,
                 'new forms of violence against women (Directive (EU) 2024/1385) and domestic violence', steps, [
                     _search15(5172, 2025, 'whose later Α΄ rows are ΦΕΚ Α΄ 76/2025 and Α΄ 125/2026 (its Β΄ rows are '
                               'ministerial decisions, which do not amend a statute)',
                               'Amending: ν. 5326/2026 art. 67 par. 1 (ΦΕΚ Α΄ 125/2026), which restates art. 47 pars. 1 '
                               'and 2. ΦΕΚ Α΄ 76/2025 names ν. 5172/2025 only in the purpose of one of its Parts (art. '
                               '25), which amends other laws; ΦΕΚ Α΄ 130/2025 names it in a table of codified '
                               'provisions. These are references only.'),
                     'ΦΕΚ Α΄ 118/2025 art. 57 par. 2 extends "from its expiry, for six more months" the time limit of '
                     'the second sentence of art. 87. It names no words of art. 87 and changes none, so art. 87 is kept '
                     'as published and the extension is recorded here rather than as a version.',
                     'ν. 5326/2026 art. 67 adds the words «και του κατά περίπτωση συναρμόδιου Υπουργού» to the first '
                     'sentence of art. 47 par. 1 without naming where; they are placed where the restatement has them, '
                     'after «Με απόφαση του Υπουργού Δικαιοσύνης».',
                 ])


ALLOWED_5172: dict = {
    ('απόφαση', ''): 'Art. 47 par. 1, second sentence: the instruction replaces the words «Με όμοια» by «Με απόφαση του '
                     'Υπουργού Δικαιοσύνης», which applied to «Με όμοια απόφαση καθορίζονται» would read «Με απόφαση του '
                     'Υπουργού Δικαιοσύνης απόφαση καθορίζονται»; the restatement reads «Με απόφαση του Υπουργού '
                     'Δικαιοσύνης καθορίζονται». The restatement (ν. 5326/2026\'s own text) governs and is used as '
                     'printed.',
}

PARTS.update({'9992-n5107': lambda: p5107(), '9994-n5028': lambda: p5028(), '9995-n5172': lambda: p5172()})



# ---------------------------------------------------------------- GR-17: ν. 4770/2021

def p4770() -> dict:
    w73, w25 = 'ν. 4811/2021 art. 73', 'ν. 4832/2021, Code art. 25 par. 1 item η)'
    m73 = 'Τροποποίηση των παρ. 7, 8 και 9 του άρθρου 16 του ν. 4770/2021'

    def e4811(u: dict) -> dict:
        instr, qs = amending(2021, 108, '73', m73)
        N.need(instr, 'Οι παρ. 7, 8 και 9 του άρθρου 16 του ν. 4770/2021 (Α’ 15) τροποποιούνται ως προς την καταληκτική '
               'ημερομηνία των προθεσμιών και διαμορφώνονται ως εξής:', w73)
        q = qs[0]
        if len(q) != 3:
            raise SystemExit(f'{w73}: the restatement is not pars. 7, 8 and 9')
        for par, line in zip(('7', '8', '9'), q):
            u = restate_par(u, 'art-016', 2021, 108, '73', m73, par, [('take', f'{par}. ', None, f'{par}. ', None)],
                            w73, src=(instr, [line]))
        return u

    def chk4811() -> None:
        commencement(2021, 108, '78', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν άλλως προβλέπεται σε επιμέρους διατάξεις του.', 'ν. 4811/2021 art. 78')
        _no_own_start(2021, 108, '73', m73, w73)
        LOG.append('ν. 4811/2021 art. 78: in force on publication; art. 73 gives no day of its own')

    def e4832(u: dict) -> dict:
        t = ' '.join(p['text'] for p in N.amending_article(2021, 172, '25', 'Καταργούμενες διατάξεις'))
        N.need(t, '1. Από την έναρξη της ισχύος του παρόντος καταργούνται οι ακόλουθες διατάξεις:', w25)
        N.need(t, 'η) τα άρθρα 1 έως 12 του ν. 4770/2021 (Α’ 15).', w25)
        heads, _ = N.head_split(u['art-001'])
        if heads != ['ΚΕΦΑΛΑΙΟ Α’', 'ΟΛΟΚΛΗΡΩΜΕΝΗ ΘΑΛΑΣΣΙΑ ΠΟΛΙΤΙΚΗ ΣΤΟΝ ΝΗΣΙΩΤΙΚΟ ΧΩΡΟ'] or \
                not u['art-013'][0].startswith('ΚΕΦΑΛΑΙΟ Β’'):
            raise SystemExit(f'{w25}: arts. 1-12 are not the whole of Chapter Α’')
        for k in range(2, 13):
            if N.head_split(u[f'art-{k:03d}'])[0]:
                raise SystemExit(f'{w25}: art-{k:03d} opens with headings')
        u = {k: v for k, v in u.items() if not ('art-001' <= k <= 'art-012')}
        LOG.append(f'{w25}: art-001 to art-012 repealed (removed), with the heading of Chapter Α’, which they make up')
        return u

    def chk4832() -> None:
        commencement(2021, 172, '26', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως.', 'ν. 4832/2021, Code art. 26')
        LOG.append('ν. 4832/2021, Code art. 26: in force on publication')

    steps = [
        {'law': 'n-4811-2021', 'fek': (2021, 108), 'day': None, 'edit': e4811, 'check': chk4811,
         'note': 'ν. 4811/2021 art. 73 (ΦΕΚ Α΄ 108/2021), in force on publication (art. 78): art. 16 pars. 7-9, the '
                 'support measures for seafarers run to 30 June 2021; the paragraphs are restated.'},
        {'law': 'n-4832-2021', 'fek': (2021, 172), 'day': None, 'edit': e4832, 'check': chk4832,
         'note': 'ν. 4832/2021 (ΦΕΚ Α΄ 172/2021), which ratifies the Code on integrated maritime policy for the islands '
                 'and the Transport Equivalent: Code art. 25 par. 1 item η), in force on publication (art. 26), repeals '
                 'arts. 1-12 (Chapter Α’), whose subject the Code now covers.'},
    ]
    return build('9996-n4770', 'nomos-4770-2021', 2021, 15, 4770,
                 'integrated maritime policy for the islands, international shipping obligations and the Hellenic '
                 'Coast Guard', steps, [
                     _search15(4770, 2021, 'whose later Α΄ rows are ΦΕΚ Α΄ 108/2021 and Α΄ 251/2021 (its Β΄ and Δ΄ '
                               'rows are ministerial decisions and other acts, which do not amend a statute)',
                               'Amending: ν. 4811/2021 art. 73 (ΦΕΚ Α΄ 108/2021), which restates art. 16 pars. 7-9, and ν. '
                               '4832/2021 (ΦΕΚ Α΄ 172/2021, not listed by the index), whose Code repeals arts. 1-12. ΦΕΚ Α΄ '
                               '251/2021 art. 83 provides that the Act of Legislative Content article which art. 19 of '
                               'ν. 4770/2021 replaced applies also in the academic year 2021-2022: it names no words of '
                               'ν. 4770/2021 and changes none. ΦΕΚ Α΄ 150/2022, Α΄ 18/2023 and Α΄ 19/2023 refer to its '
                               'arts. 33 and 40 only.'),
                     'ν. 4770/2021 art. 55 starts art. 14 on 1 September 2020 and art. 43 on 19 March 2020, before the '
                     'law was published; both are shown from publication.',
                     'ν. 4811/2021 art. 73 says it changes art. 16 pars. 7-9 "as regards the end date of the time '
                     'limits" without quoting words, and restates them: the paragraphs are taken from the '
                     'restatement, which governs. Beyond the dates (31.5.2021 and 30.4.2021 become 30.6.2021) it also '
                     'reads, in par. 7, «Στην περίπτωση, που» (a comma added), «εκ των επιδομάτων» for «εκ του '
                     'επιδομάτων» and «στο ανωτέρω» for «σε ανωτέρω», and in par. 9 «για έναν (1) μήνα κάθε φορά» for '
                     '«για τριάντα (30) ημέρες κάθε φορά», and it adds commas in all three.',
                     'The Code ratified by ν. 4832/2021 repeals arts. 1-12, the whole of Chapter Α’; the chapter heading '
                     'goes with them.',
                 ])


PARTS.update({'9996-n4770': lambda: p4770()})



# ---------------------------------------------------------------- GR-17: ν. 5161/2024

def p5161() -> dict:
    w39, w22, w107 = 'ν. 5167/2024 art. 39', 'ν. 5243/2025 art. 22', 'ν. 5243/2025 art. 107'
    m39 = 'Αντικατάσταση παρ. 1 άρθρου 6 ν. 5161/2024'
    m22, m107 = 'Τροποποίηση άρθρου 22 ν. 5161/2024', 'Αντικατάσταση παρ. 1 άρθρου 48 ν. 5161/2024'

    def e5167(u: dict) -> dict:
        instr, qs = amending(2024, 207, '39', m39)
        N.need(instr, 'Η παρ. 1 του άρθρου 6 του ν. 5161/2024 (Α’ 196), περί του χρόνου παραμονής στην υπηρεσία ιατρών '
               'κλάδου Εθνικού Συστήματος Υγείας, αντικαθίσταται ως εξής:', w39)
        return restate_par(u, 'art-006', 2024, 207, '39', m39, '1', [('take', '1. ', None, '1. ', None)], w39,
                           src=(instr, qs[0]))

    def chk5167() -> None:
        commencement(2024, 207, '54', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 5167/2024 art. 54')
        _no_own_start(2024, 207, '39', m39, w39)
        LOG.append('ν. 5167/2024 art. 54: in force on publication; art. 39 gives no day of its own')

    def e5243(u: dict) -> dict:
        instr, _ = amending(2025, 187, '22', m22)
        N.need(instr, 'ββ) προστίθεται δεύτερο εδάφιο, γ) η παρ. 2 αντικαθίσταται, δ) στην παρ. 3, οι λέξεις «και του '
               'Τ.Υ.Π.Ε.Τ.», όπου αυτές αναφέρονται, αντικαθίστανται από τις λέξεις «, του Τ.Υ.Π.Ε.Τ. και του '
               'Λ.Υ.Μ.-Σ.Ο.Ε.Λ.», ε) η παρ. 4 αντικαθίσταται, και το άρθρο 22 διαμορφώνεται ως εξής:', w22)
        a, b = 'και του Τ.Υ.Π.Ε.Τ.', ', του Τ.Υ.Π.Ε.Τ. και του Λ.Υ.Μ.-Σ.Ο.Ε.Λ.'
        u = restate(u, 'art-022', 2025, 187, '22', m22, [
            ('sub', 'και Ταμείου Υγείας Προσωπικού Εθνικής Τραπέζης της Ελλάδος',
             ', Ταμείου Υγείας Προσωπικού Εθνικής Τραπέζης της Ελλάδος και Λογαριασμού Υγείας Μελών Σώματος Ορκωτών '
             'Ελεγκτών Λογιστών'),
            ('add', 'και το Ταμείο Υγείας Προσωπικού Εθνικής Τραπέζης της Ελλάδος (Τ.Υ.Π.Ε.Τ.)',
             'και από 1ης.1.2025 ο Λογαριασμός Υγείας Μελών Σώματος Ορκωτών Ελεγκτών Λογιστών (Λ.Υ.Μ.-Σ.Ο.Ε.Λ.)'),
            ('take', None, '\n2. ', ' Για τον Ε.Δ.Ο.Ε.Α.Π.', '\n2. '),
            ('take', '\n2. ', '\n3. ', '\n2. ', '\n3. '),
            ('sub', a, b, ('\n3. ', ' δεν μπορεί')),
            ('sub', a, b, (' επί του αριθμού', ' κατά περίπτωση')),
            ('take', '\n4. ', None, '\n4. ', None)], w22)
        instr, qs = amending(2025, 187, '107', m107)
        N.need(instr, 'Η παρ. 1 του άρθρου 48 του ν. 5161/2024 (Α’ 196), περί εξουσιοδοτικών διατάξεων αντικαθίσταται '
               'ως εξής:', w107)
        return restate_par(u, 'art-048', 2025, 187, '107', m107, '1', [('take', '1. ', None, '1. ', None)], w107,
                           src=(instr, qs[0]))

    def chk5243() -> None:
        commencement(2025, 187, '117', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2 και 3. 2. Η περ. α’ της παρ. 1 του άρθρου 12 του ν. '
                     '4578/2018 (Α’ 200), όπως τροποποιήθηκε με το άρθρο 50 του παρόντος, ισχύει από την 1η.1.2023. 3. '
                     'Η ισχύς της περ. β’ της παρ. 2 του άρθρου 10 του ν. 3329/2005 (Α’ 81), όπως τροποποιήθηκε με το '
                     'άρθρο 62 του παρόντος, ισχύει από την 1η.1.2026.', 'ν. 5243/2025 art. 117')
        _no_own_start(2025, 187, '22', m22, w22)
        _no_own_start(2025, 187, '107', m107, w107)
        LOG.append('ν. 5243/2025 art. 117: in force on publication; pars. 2-3 date arts. 50 and 62 only; arts. 22 and '
                   '107 give no day of their own')

    steps = [
        {'law': 'n-5167-2024', 'fek': (2024, 207), 'day': None, 'edit': e5167, 'check': chk5167,
         'note': 'ν. 5167/2024 art. 39 (ΦΕΚ Α΄ 207/2024), in force on publication (art. 54): art. 6 par. 1, every NHS '
                 'doctor and dentist reaching 67 on 31 December 2024 may stay in service until 31 December 2027, not '
                 'only those of the listed specialties; the paragraph is replaced.'},
        {'law': 'n-5243-2025', 'fek': (2025, 187), 'day': None, 'edit': e5243, 'check': chk5243,
         'note': 'ν. 5243/2025 arts. 22 and 107 (ΦΕΚ Α΄ 187/2025), in force on publication (art. 117 par. 1): art. 22, '
                 'the health account of the members of the Body of Certified Auditors joins the pharmaceutical '
                 'expenditure measures from 1 January 2025, and pars. 2 and 4 are replaced (the article is restated); '
                 'art. 48 par. 1, the joint decision on applying art. 22, is replaced.'},
    ]
    return build('9997-n5161', 'nomos-5161-2024', 2024, 196, 5161,
                 'the National Health System and the monitoring of pharmaceutical expenditure', steps, [
                     _search15(5161, 2024, 'whose later Α΄ rows are ΦΕΚ Α΄ 207/2024 and Α΄ 187/2025 (its Β΄, Γ΄ and '
                               'Υ.Ο.Δ.Δ. rows are ministerial decisions and appointments, which do not amend a statute)',
                               'Amending: ν. 5167/2024 art. 39 (ΦΕΚ Α΄ 207/2024), which replaces art. 6 par. 1, and ν. '
                               '5243/2025 arts. 22 and 107 (ΦΕΚ Α΄ 187/2025), which restate art. 22 and replace art. 48 '
                               'par. 1.'),
                     'Several later laws move or extend time limits that ν. 5161/2024 sets, without changing its words: '
                     'ν. 5167/2024 art. 37 par. 8 item β) (the time limits of art. 27 par. 1 items ζ) and η) and par. 3 '
                     'item β)); ΦΕΚ Α΄ 49/2025, Α΄ 118/2025 art. 42 and Α΄ 228/2025 art. 250 extend again measures '
                     'that art. 27 or art. 44 had extended; ν. 5243/2025 art. 57 par. 4 makes an exception to art. 6. '
                     'None names words of ν. 5161/2024, so they are recorded here rather than as versions.',
                     'ν. 5161/2024 art. 50 par. 2 starts art. 13 on 1 January 2024, before the law was published; it is '
                     'shown from publication.',
                     'ν. 5243/2025 art. 22 adds a second sentence to art. 22 par. 1 and replaces its pars. 2 and 4 '
                     'without quoting them apart: they are taken from the restated article.',
                 ])


PARTS.update({'9997-n5161': lambda: p5161()})



# ---------------------------------------------------------------- GR-17: ν. 4686/2020

PNP_4686 = ('pnp-2020-08-10', 2020, 157)


def pnp_inline(y: int, n: int, ordinal: str, title: str, what: str) -> tuple[str, str]:
    """(instruction, quoted words) of «Άρθρο <ordinal>» of an Act of Legislative Content whose one paragraph holds the
    instruction and its quotation inline: the article line, its title, that paragraph, then a heading (ΜΕΡΟΣ ...)."""
    paras = N.fek_paras(y, n)
    hits = [i for i, p in enumerate(paras) if p['text'] == f'Άρθρο {ordinal}']
    if len(hits) != 1:
        raise SystemExit(f'{what}: Άρθρο {ordinal} found {len(hits)} times in Α΄ {n}/{y}')
    i = hits[0]
    if paras[i + 1]['text'] != title or not paras[i + 3]['text'].startswith('ΜΕΡΟΣ '):
        raise SystemExit(f'{what}: Άρθρο {ordinal} is not one titled paragraph')
    t = paras[i + 2]['text']
    m = re.fullmatch(r'([^«»]+ ως εξής: )«([^«»]+)»\.', t)
    if not m:
        raise SystemExit(f'{what}: not one instruction with one quotation: {t[:80]!r}')
    return m.group(1).strip(), m.group(2)


def p4686() -> dict:
    key, y, n = PNP_4686
    wp, w39, w148 = 'Π.Ν.Π. της 10.8.2020 art. δέκατο έβδομο', 'ν. 4825/2021 art. 39', 'ν. 4939/2022 art. 148'
    m39 = 'Τροποποίηση της παρ. 1 του άρθρου 48 του ν. 4686/2020'
    title = N.law_title(y, n)
    if not title.startswith('Επείγουσες ρυθμίσεις αντιμετώπισης εκτάκτων αναγκών του Εθνικού Συστήματος Υγείας'):
        raise SystemExit(f'{wp}: unexpected title {title[:60]!r}')
    entry = {'label': 'Π.Ν.Π. της 10.8.2020', 'kind': 'decree',
             'title': 'Πράξη Νομοθετικού Περιεχομένου: ' + title,
             'enacted': PS.signed(y, n), 'published': N.masthead(y, n), 'url': FL.fek_url(y, n),
             'temporary_until': None, 'restores': None, 'note': None}
    first = 'Είναι δυνατή η, κατά παρέκκλιση κάθε άλλης διάταξης, παροχή σύγχρονης εξ αποστάσεως εκπαίδευσης'

    def epnp(u: dict) -> dict:
        instr, q = pnp_inline(y, n, 'δέκατο έβδομο', 'Παροχή σύγχρονης εξ αποστάσεως εκπαίδευσης', wp)
        N.need(instr, 'Το πρώτο εδάφιο της παρ. 1 του άρθρου 63 του ν. 4686/2020 (Α’ 96) αντικαθίσταται ως εξής:', wp)
        lines = list(u['art-063'])
        i = N.find_one(lines, '1. ', f'{wp}: art-063 par. 1')
        old = lines[i]
        end = old.find('. Η ταυτόχρονη διδασκαλία')
        if not old.startswith('1. ' + first) or end < 0 or old[3:end].count('. ') or not q.endswith('.'):
            raise SystemExit(f'{wp}: the first sentence of art. 63 par. 1 is not where expected')
        lines[i] = '1. ' + q + old[end + 1:]
        LOG.append(f'{wp}: art-063 par. 1, first sentence replaced')
        u = dict(u)
        u['art-063'] = lines
        return u

    def chkpnp() -> None:
        if (entry['enacted'], entry['published']) != ('2020-08-10', '2020-08-10'):
            raise SystemExit(f'{wp}: signed {entry["enacted"]}, published {entry["published"]}')
        t = ' '.join(p['text'] for p in N.fek_paras(y, n))
        N.need(t, 'Η ισχύς της παρούσας, η οποία θα κυρωθεί νομοθετικά κατά την παρ. 1 του άρθρου 44 του Συντάγματος, '
               'αρχίζει από τη δημοσίευσή της στην Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις '
               'επιμέρους διατάξεις της.', wp)
        instr, q = pnp_inline(y, n, 'δέκατο έβδομο', 'Παροχή σύγχρονης εξ αποστάσεως εκπαίδευσης', wp)
        if re.search(r'η ισχύς|έναρξη ισχύος|ισχύ(?:ει|ουν) από|αναδρομ', instr + ' ' + q, re.I):
            raise SystemExit(f'{wp}: words on its own commencement: read them')
        # ν. 4722/2020 art. 1 ratifies the Act and reprints it: its words of art. δέκατο έβδομο against the Act's own
        r = re.sub(r'\s+', ' ', ' '.join(p['text'] for p in N.fek_paras(2020, 177)))
        N.need(r, 'Κυρώνεται και έχει ισχύ νόμου από τη δημοσίευσή της στην Εφημερίδα της Κυβερνήσεως, η από 10.8.2020 '
               'Πράξη Νομοθετικού Περιεχομένου', 'ν. 4722/2020 art. 1')
        a = r.find('Άρθρο δέκατο έβδομο Παροχή σύγχρονης εξ αποστάσεως εκπαίδευσης')
        b = r.find('ΜΕΡΟΣ Ε', a)
        if a < 0 or b < 0 or r.count('Άρθρο δέκατο έβδομο Παροχή σύγχρονης') != 1:
            raise SystemExit('ν. 4722/2020 art. 1: the reprint of art. δέκατο έβδομο not found once')
        if words(r[a:b]) != words(f'Άρθρο δέκατο έβδομο Παροχή σύγχρονης εξ αποστάσεως εκπαίδευσης {instr} {q}'):
            raise SystemExit('ν. 4722/2020 art. 1: the reprint of art. δέκατο έβδομο differs from the Act')
        LOG.append(f'{wp}: in force on publication (art. εικοστό); ν. 4722/2020 art. 1 ratifies the Act and reprints '
                   'art. δέκατο έβδομο in the same words')

    def e4825(u: dict) -> dict:
        instr, qs = amending(2021, 157, '39', m39)
        N.need(instr, 'Το τελευταίο εδάφιο της παρ. 1 του άρθρου 48 του ν. 4686/2020 (Α’ 96) αντικαθίσταται και η παρ. '
               '1 διαμορφώνεται ως εξής:', w39)
        return restate_par(u, 'art-048', 2021, 157, '39', m39, '1', [('take', '1. ', None, '1. ', None)], w39,
                           src=(instr, qs[0]))

    def chk4825() -> None:
        commencement(2021, 157, '73', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή '
                     'του στην Εφημερίδα της Κυβερνήσεως. 2. Ειδικώς η ισχύς της παρ. 4 του άρθρου 72 αρχίζει από την '
                     '1η Ιουλίου 2022.', 'ν. 4825/2021 art. 73')
        _no_own_start(2021, 157, '39', m39, w39)
        LOG.append('ν. 4825/2021 art. 73: in force on publication except art. 72 par. 4; art. 39 gives no day of its own')

    def e4939(u: dict) -> dict:
        return repeal_unit(u, 'art-058', 2022, 111, '148', 'Καταργούμενες διατάξεις', [
            'Από τη δημοσίευση του παρόντος καταργούνται:', 'στ) το άρθρο 58 του ν. 4686/2020 (Α’ 96),'], w148)

    def chk4939() -> None:
        body = N.amending_article(2022, 145, '42', 'Τροποποίηση άρθρου 148 ν. 4939/2022')
        bt = ' '.join(p['text'] for p in body)
        N.need(bt, 'Η περ. δ) του άρθρου 148 του ν. 4939/2022 (Α’ 111) αντικαθίσταται και το άρθρο 148 διαμορφώνεται ως '
               'εξής:', 'ΦΕΚ Α΄ 145/2022 art. 42')
        N.need(bt, 'Από τη δημοσίευση του παρόντος καταργούνται:', 'ΦΕΚ Α΄ 145/2022 art. 42')
        N.need(bt, 'στ) το άρθρο 58 του ν. 4686/2020 (Α’ 96),', 'ΦΕΚ Α΄ 145/2022 art. 42')
        LOG.append('ν. 4939/2022 art. 148: from its publication; ΦΕΚ Α΄ 145/2022 art. 42 replaces item δ) and restates '
                   'art. 148, keeping item στ) (art. 58 of ν. 4686/2020) in the same words')

    steps = [
        {'law': key, 'entry': (key, entry), 'fek': (y, n), 'day': None, 'edit': epnp, 'check': chkpnp,
         'note': 'Act of Legislative Content of 10.8.2020 (ΦΕΚ Α΄ 157/2020), art. δέκατο έβδομο, in force on '
                 'publication (art. εικοστό); ratified by ν. 4722/2020 art. 1 (ΦΕΚ Α΄ 177/2020): the first sentence '
                 'of art. 63 par. 1 (synchronous distance education) is replaced.'},
        {'law': 'n-4825-2021', 'fek': (2021, 157), 'day': None, 'edit': e4825, 'check': chk4825,
         'note': 'ν. 4825/2021 art. 39 (ΦΕΚ Α΄ 157/2021), in force on publication (art. 73 par. 1): art. 48 par. 1, the '
                 'special allowance is paid from Public Investment Programme funds; the paragraph is restated.'},
        {'law': 'n-4939-2022', 'fek': (2022, 111), 'day': None, 'edit': e4939, 'check': chk4939,
         'note': 'ν. 4939/2022, the Code on reception and international protection (ΦΕΚ Α΄ 111/2022), art. 148 item '
                 'στ), from its publication: art. 58 (the register of NGOs) repealed.'},
    ]
    return build('9998-n4686', 'nomos-4686-2020', 2020, 96, 4686,
                 'migration law, amending ν. 4636/2019, 4375/2016 and 4251/2014, and other provisions', steps, [
                     _search15(4686, 2020, 'whose only later Α΄ row is ΦΕΚ Α΄ 157/2021 (its Β΄, Γ΄ and Υ.Ο.Δ.Δ. rows are '
                               'ministerial decisions and appointments, which do not amend a statute)',
                               'Amending: the Act of Legislative Content of 10.8.2020 (ΦΕΚ Α΄ 157/2020, not listed by '
                               'the index), art. δέκατο έβδομο, which replaces the first sentence of art. 63 par. 1; ν. '
                               '4825/2021 art. 39 (ΦΕΚ Α΄ 157/2021), which restates art. 48 par. 1; ν. 4939/2022 art. '
                               '148 (ΦΕΚ Α΄ 111/2022), which repeals art. 58, and ΦΕΚ Α΄ 145/2022 art. 42, which '
                               'restates that article keeping the repeal. ΦΕΚ Α΄ 255/2020 and Α΄ 212/2022 (the '
                               'Ministry\'s organisation decree and its amendment) and Α΄ 157/2021 arts. 37, 40, 42 '
                               'and 71 refer to it only.'),
                     'The Act of Legislative Content of 10.8.2020 is credited as itself (an act of the President of '
                     'the Republic with the force of law), from its own publication; ν. 4722/2020 art. 1 (ΦΕΚ Α΄ '
                     '177/2020) ratifies it and reprints its art. δέκατο έβδομο in the same words (checked), so the '
                     'ratification makes no version of its own.',
                     'Later laws extend the staff posts of arts. 53 and 55 (ΦΕΚ Α΄ 251/2021 art. 138, Α΄ 230/2022 art. '
                     '134, Α΄ 215/2023 art. 122, Α΄ 76/2024 art. 32, Α΄ 207/2024 art. 34, Α΄ 239/2025 art. 121) '
                     'without changing the words of ν. 4686/2020; they are recorded here rather than as versions.',
                     'ν. 4825/2021 art. 39 says it replaces the last sentence of art. 48 par. 1 and restates the '
                     'paragraph; the restatement, which governs, also differs in its first sentence: where the '
                     'published text reads «το ποσό του οποίου καθορίζεται από τη διαφορά που προκύπτει από το ύψος του '
                     'συνόλου των μηνιαίων τακτικών αποδοχών τους» it prints «το ποσό του τακτικών αποδοχών τους» (as '
                     'if words had fallen out), and it ends «του αντίστοιχου κλιμακίου και βαθμού» for «του αντίστοιχου '
                     'κλάδου, ειδικότητας, βαθμού και κλιμακίου». The paragraph is used as the restatement prints it.',
                 ])


PARTS.update({'9998-n4686': lambda: p4686()})


# ---------------------------------------------------------------- GR-18: ν. 4680/2020

def p4680() -> dict:
    w63, w111 = 'ν. 4921/2022 art. 63', 'ν. 5078/2023 art. 111'
    m63 = 'Θέματα εποπτείας της Επιτροπής Κεφαλαιαγοράς επί των Ταμείων Επαγγελματικής Ασφάλισης'

    def e4921(u: dict) -> dict:
        instr, qs = amending(2022, 75, '63', m63)
        N.need(instr, '2. Στην παρ. 5 του άρθρου 33 του ν. 4680/2020 (Α’ 72), περί της απόφασης της Επιτροπής '
               'Κεφαλαιαγοράς', w63)
        N.need(instr, 'επέρχονται οι εξής τροποποιήσεις: α) προστίθεται νέο πρώτο εδάφιο, β) τροποποιείται το παλαιό '
               'πρώτο εδάφιο, ως προς το αντικείμενο της εξουσιοδότησης, και η παρ. 5 διαμορφώνεται ως εξής:', w63)
        N.need(instr, '3. Το πρώτο εδάφιο της παρ. 10 του άρθρου 47 του ν. 4680/2020, περί της εποπτείας και του ελέγχου '
               'που ασκεί η Επιτροπή Κεφαλαιαγοράς', w63)
        N.need(instr, 'και η παρ. 10 διαμορφώνεται ως εξής:', w63)
        if len(qs) != 3 or len(qs[1]) != 1 or len(qs[2]) != 1:
            raise SystemExit(f'{w63}: the quotations are not par. 1\'s, art. 33 par. 5 and art. 47 par. 10')
        # par. 2: a new first sentence and the old first (only) sentence changed, neither quoted: the whole paragraph
        # comes from the restatement
        u = restate_par(u, 'art-033', 2022, 75, '63', m63, '5', [('take', '5. ', None, '5. ', None)], w63 + ' par. 2',
                        src=(instr, qs[1]))
        # par. 3: only the first sentence changes; the second must read as before
        return restate_par(u, 'art-047', 2022, 75, '63', m63, '10', [
            ('take', '10. ', ' Η απόφαση αυτή', '10. ', ' Η απόφαση αυτή')], w63 + ' par. 3', src=(instr, qs[2]))

    def chk4921() -> None:
        commencement(2022, 75, '82', '4. Οι λοιπές διατάξεις, όπου δεν ορίζεται διαφορετικά, ισχύουν από τη δημοσίευση '
                     'του παρόντος στην Εφημερίδα της Κυβερνήσεως.', 'ν. 4921/2022 art. 82')
        in_part(2022, 75, '63', 'ΜΕΡΟΣ Γ’', 'ΜΕΡΟΣ Δ’', w63)
        _no_own_start(2022, 75, '63', m63, w63)
        LOG.append('ν. 4921/2022 art. 82 par. 4: Part Γ’ (art. 63) in force on publication (pars. 1-3 start only '
                   'Chapters Α’, Β’ and Ε’ of Part Β’ later); art. 63 gives no day of its own')

    def e5078(u: dict) -> dict:
        t = ' '.join(p['text'] for p in N.amending_article(2023, 211, '111', 'Καταργούμενες διατάξεις'))
        N.need(t, 'Από την έναρξη ισχύος του παρόντος, καταργούνται:', w111)
        N.need(t, 'γ. τα άρθρα 1 έως 60 του ν. 4680/2020 (Α’ 72), περί της ενσωμάτωσης στην ελληνική νομοθεσία της '
               'Οδηγίας (ΕΕ) 2016/2341', w111)
        if [k for k in u if k > 'art-060'] != ['art-061', 'art-062', 'art-063', 'art-064', 'art-065']:
            raise SystemExit(f'{w111}: the articles after art. 60 are not 61-65')
        heads, _ = N.head_split(u['art-059'])
        if heads != ['ΚΕΦΑΛΑΙΟ ΣΤ’', 'ΤΕΛΙΚΕΣ ΔΙΑΤΑΞΕΙΣ'] or N.head_split(u['art-060'])[0] or \
                N.head_split(u['art-061'])[0]:
            raise SystemExit(f'{w111}: Chapter ΣΤ’ does not open at art. 59 and run on past art. 61')
        out = {k: v for k, v in u.items() if k > 'art-060'}
        out['art-061'] = heads + u['art-061']
        LOG.append(f'{w111}: art-001 to art-060 repealed (removed); Chapter ΣΤ’ (arts. 59-65) keeps arts. 61-65, so '
                   'its heading now opens art-061')
        return out

    def chk5078() -> None:
        commencement(2023, 211, '195', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των οριζομένων στις επόμενες παραγράφους.', 'ν. 5078/2023 art. 195')
        t = ' '.join(p['text'] for p in N.amending_article(2023, 211, '195', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ [^.]{0,40}\b111\b', t):
            raise SystemExit('ν. 5078/2023 art. 195 names art. 111: read it')
        LOG.append('ν. 5078/2023 art. 195 par. 1: in force on publication; pars. 2-7 do not name art. 111')

    steps = [
        {'law': 'n-4921-2022', 'fek': (2022, 75), 'day': None, 'edit': e4921, 'check': chk4921,
         'note': 'ν. 4921/2022 art. 63 pars. 2-3 (ΦΕΚ Α΄ 75/2022), in force on publication (art. 82 par. 4): art. 33 '
                 'par. 5 (cash held for running costs; a new first sentence puts the cash with the custodian) and art. '
                 '47 par. 10 (the sanctions the Capital Market Commission imposes) are restated.'},
        {'law': 'n-5078-2023', 'fek': (2023, 211), 'day': None, 'edit': e5078, 'check': chk5078,
         'note': 'ν. 5078/2023 art. 111 item γ. (ΦΕΚ Α΄ 211/2023), in force on publication (art. 195 par. 1): arts. 1-60 '
                 '(the transposition of Directive (EU) 2016/2341, which ν. 5078/2023 replaces) repealed.'},
    ]
    return build('9999-n4680', 'nomos-4680-2020', 2020, 72, 4680,
                 'transposition of Directive (EU) 2016/2341 on institutions for occupational retirement provision, and '
                 'other provisions', steps, [
                     _search15(4680, 2020, 'whose later rows are ΦΕΚ Α΄ 75/2022 and a Β΄ issue (a ministerial decision, '
                               'which does not amend a statute)',
                               'Amending: ν. 4921/2022 art. 63 pars. 2-3 (ΦΕΚ Α΄ 75/2022), which restate art. 33 par. 5 '
                               'and art. 47 par. 10, and ν. 5078/2023 art. 111 (ΦΕΚ Α΄ 211/2023, not listed by the '
                               'index), which repeals arts. 1-60. ΦΕΚ Α΄ 113/2022 art. 28, Α΄ 88/2023 art. 48 and Α΄ '
                               '132/2026 art. 44 refer to it only, and Α΄ 211/2023 art. 85 deletes references to its '
                               'art. 5 from ν. 5042/2023, leaving its own words unchanged.'),
                     'ν. 4921/2022 art. 63 par. 2 adds a first sentence to art. 33 par. 5 and changes the old one "as '
                     'regards the subject of the authorisation", and par. 3 changes the first sentence of art. 47 par. '
                     '10 "so that" the Commission imposes the sanctions of pars. 1, 2, 3 and 5 of art. 94 of ν. '
                     '4099/2012 for breaches of the legislation in force; neither quotes words apart from the restated '
                     'paragraph, which governs. In art. 47 par. 10 the parse checks that the second sentence is '
                     'unchanged.',
                     'ν. 5078/2023 repeals arts. 1-60, Chapters Α’ to Ε’ and the first two articles of Chapter ΣΤ’ (Final '
                     'provisions); arts. 61-65 stay in force, so the heading of Chapter ΣΤ’ now opens art. 61, which '
                     'that version shows as changed for this reason only.',
                     'ν. 4680/2020 art. 62 par. 1 repeals other provisions from 13 January 2019, and art. 63 restates '
                     'art. 24 of ν. 4618/2019 with a start of its own; these act on other laws, and are shown as printed.',
                     'In the issue the commencement article (art. 65) is set below both columns of the last page, in '
                     'the left column\'s place, after art. 64 at the foot of the right column; it is read after art. 64 '
                     '(that page only).',
                 ])


PARTS.update({'9999-n4680': lambda: p4680()})


# ---------------------------------------------------------------- GR-18: ν. 4735/2020

def repeal_arts(u: dict, keys: list[str], what: str) -> dict:
    """Whole articles repealed. A heading that opens a repealed article (a chapter's) moves to the next article that
    stays, if that article is in the same chapter (no heading of its own and none in between); if the whole chapter
    goes, the heading goes with it. Each move is logged."""
    missing = [k for k in keys if k not in u]
    if missing:
        raise SystemExit(f'{what}: no {missing}')
    order = list(u)
    out = dict(u)
    for k in keys:
        heads, body = N.head_split(u[k])
        del out[k]
        if not heads:
            continue
        nxt = None
        for k2 in order[order.index(k) + 1:]:
            if N.head_split(u[k2])[0]:
                break
            if k2 not in keys:
                nxt = k2
                break
        if nxt:
            out[nxt] = heads + out[nxt]
            LOG.append(f'{what}: the heading {" / ".join(heads)} that opened {k} now opens {nxt}')
        else:
            LOG.append(f'{what}: the heading {" / ".join(heads)} goes with {k} (the whole chapter is repealed)')
    LOG.append(f'{what}: {", ".join(keys)} repealed (removed)')
    return out


def p4735() -> dict:
    w48, w34, w54, w65 = 'ν. 4772/2021 art. 48', 'ν. 4807/2021 art. 34', 'ν. 4809/2021 art. 54', 'ν. 4809/2021 art. 65'
    w4808, w68, w64, w394 = 'ν. 4808/2021 art. 54', 'ν. 4825/2021 art. 68', 'ν. 4886/2022 art. 64', 'ν. 4957/2022 art. 394'
    w17, w102, w773 = 'ν. 5062/2023 art. 17', 'ν. 5224/2025 art. 102', 'ν. 5314/2026 art. 773 (as replaced by ν. 5321/2026 art. 54)'
    m48, m34 = 'Μεταβατική διάταξη για επιλογή διοικήσεων', 'Απογραφή ακίνητης περιουσίας'
    m54 = 'Έναρξη ισχύος της παρ. 2 του άρθρου 66'
    m64, m394, m102 = 'Διαδικασία επιλογής διοικήσεων', 'Επιλογή διοικήσεων στον δημόσιο τομέα', 'Δυνατότητα χρήσης αθλητικών'
    late66 = ' Η ρύθμιση της παρούσας τίθεται σε ισχύ έξι (6) μήνες μετά από τη δημοσίευσή της στην Εφημερίδα της Κυβερνήσεως.'

    def e4772(u: dict) -> dict:
        instr, qs = amending(2021, 17, '48', m48)
        N.need(instr, 'Η παρ. 2 του άρθρου 22 του ν. 4735/2020 (Α’ 197) αντικαθίσταται ως εξής:', w48)
        return restate_par(u, 'art-022', 2021, 17, '48', m48, '2', [('take', '2. ', None, '2. ', None)], w48,
                           src=(instr, qs[0]))

    def chk4772() -> None:
        t = ' '.join(p['text'] for p in N.fek_paras(2021, 17))
        N.need(t, '1. Με την επιφύλαξη των παρ. 2, 3 και 4, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην '
               'Εφημερίδα της Κυβερνήσεως.', 'ν. 4772/2021 art. 49')
        N.need(t, '2. Η ισχύς του άρθρου 31 αρχίζει από την 1η.1.2021.', 'ν. 4772/2021 art. 49')
        N.need(t, '4. Η ισχύς των άρθρων 28, 34 και 35 αρχίζει από την 25η Ιανουαρίου 2021.', 'ν. 4772/2021 art. 49')
        _no_own_start(2021, 17, '48', m48, w48)
        LOG.append(f'{w48}: in force on publication (art. 49 par. 1; pars. 2-5 name arts. 31, 33, 28, 34, 35 and 36 only)')

    def e4807(u: dict) -> dict:
        instr, qs = amending(2021, 96, '34', m34)
        N.need(instr, 'Η παρ. 1 του άρθρου 53 του ν. 4735/2020 (Α’ 197) αναφορικά με την καταληκτική προθεσμία '
               'διενέργειας απογραφής', w34)
        N.need(instr, 'και η παρ. 2 του ιδίου άρθρου, αναφορικά με την καταχώριση της εγκεκριμένης έκθεσης, '
               'τροποποιούνται και το άρθρο 53 διαμορφώνεται ως εξής:', w34)
        return restate(u, 'art-053', 2021, 96, '34', m34, [('take', '1. ', None, '1. ', None)], w34)

    def chk4807() -> None:
        commencement(2021, 96, '62', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του.', 'ν. 4807/2021 art. 62')
        _no_own_start(2021, 96, '34', m34, w34)
        LOG.append(f'{w34}: in force on publication (art. 62); art. 34 gives no day of its own')

    def e4808(u: dict) -> dict:
        return repeal_unit(u, 'art-031', 2021, 101, '54', 'Καταργούμενες διατάξεις', [
            'Από την έναρξη ισχύος του παρόντος καταργούνται:', 'θ. το άρθρο 31 του ν. 4735/2020 (Α’ 197).'], w4808)

    def chk4808() -> None:
        commencement(2021, 101, '165', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως με την επιφύλαξη των ειδικότερων διατάξεων.', 'ν. 4808/2021 art. 165')
        LOG.append(f'{w4808}: from the law\'s commencement, its publication (art. 165)')

    def e4809(u: dict) -> dict:
        instr, qs = amending(2021, 102, '54', m54)
        N.need(instr, 'Στο άρθρο 75 του ν. 4735/2020 (Α’ 197) προστίθεται παρ. 2 και το άρθρο διαμορφώνεται ως εξής:', w54)
        u = restate(u, 'art-075', 2021, 102, '54', m54, [('take', 'Η ισχύς', None, '1. Η ισχύς', None)], w54)
        t = ' '.join(p['text'] for p in N.amending_article(2021, 102, '65', 'Καταργούμενες διατάξεις'))
        N.need(t, 'Με την έναρξη ισχύος του παρόντος καταργούνται:', w65)
        N.need(t, 'θ) το δεύτερο εδάφιο της παρ. 2 του άρθρου 66 του ν. 4735/2020 (Α’ 197) και', w65)
        lines = list(u['art-066'])
        i = N.find_one(lines, '2. ', f'{w65}: art-066 par. 2')
        if not lines[i].endswith('ΟΤΑ α’ και β’ βαθμού.' + late66) or i + 1 >= len(lines) or \
                not lines[i + 1].startswith('3. '):
            raise SystemExit(f'{w65}: art. 66 par. 2 is not two sentences ending as expected')
        lines[i] = lines[i][:-len(late66)]
        u = dict(u)
        u['art-066'] = lines
        LOG.append(f'{w65}: art-066 par. 2, second sentence repealed (removed)')
        return u

    def chk4809() -> None:
        commencement(2021, 102, '66', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις. 2. Η ισχύς των άρθρων 20, 24, '
                     '25 και 26 αρχίζει από την αγωνιστική περίοδο 2021-2022.', 'ν. 4809/2021 art. 66')
        # art. 54 is itself about a start (of art. 66 par. 2): its own words are checked without its heading
        instr, _ = amending(2021, 102, '54', m54)
        if re.search(_OWN_START, instr.split('«', 1)[0].replace('Έναρξη ισχύος της παρ. 2', ''), re.I):
            raise SystemExit(f'{w54}: words on its own commencement: read them')
        # ν. 4818/2021 art. 64 restates art. 65 of ν. 4809/2021, deleting only item γ): item θ) stays as it was
        b = ' '.join(p['text'] for p in N.amending_article(2021, 124, '64', 'Δικαιώματα γηπεδούχων'))
        N.need(b, 'Από τις καταργούμενες διατάξεις του άρθρου 65 του ν. 4809/2021 (Α’ 102) διαγράφεται η περ. γ’', 'ν. 4818/2021 art. 64')
        N.need(b, 'θ) το δεύτερο εδάφιο της παρ. 2 του άρθρου 66 του ν. 4735/2020 (Α’ 197) και', 'ν. 4818/2021 art. 64')
        LOG.append(f'{w54} and art. 65: in force on publication (art. 66 par. 1); ν. 4818/2021 art. 64 restates art. 65 '
                   'keeping item θ) in the same words')

    def e4825(u: dict) -> dict:
        instr, _ = amending(2021, 157, '68', m54)
        N.need(instr, 'Στην παρ. 2 του άρθρου 75 του ν. 4735/2020 (Α’ 197), η οποία προστέθηκε με το άρθρο 54 του ν. '
               '4809/2021', w68)
        return restate(u, 'art-075', 2021, 157, '68', m54, [('sub', '1η.9.2021', '1η.8.2022')], w68)

    def chk4825() -> None:
        commencement(2021, 157, '73', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή '
                     'του στην Εφημερίδα της Κυβερνήσεως. 2. Ειδικώς η ισχύς της παρ. 4 του άρθρου 72 αρχίζει από την '
                     '1η Ιουλίου 2022.', 'ν. 4825/2021 art. 73')
        LOG.append(f'{w68}: in force on publication (art. 73 par. 1)')

    def e4886(u: dict) -> dict:
        instr, qs = amending(2022, 12, '64', m64)
        N.need(instr, 'Η παρ. 1 του άρθρου 20 του ν. 4735/2020 (Α’197) τροποποιείται, προκειμένου να αποσαφηνισθεί η '
               'διατήρηση σε ισχύ της διαδικασίας κοινοβουλευτικής ακρόασης ή παροχής γνώμης, και η παρ. 1 διαμορφώνεται '
               'ως εξής:', w64)
        return restate_par(u, 'art-020', 2022, 12, '64', m64, '1', [
            ('take', '1. ', None, '1. ', None)], w64, src=(instr, qs[0]))

    def chk4886() -> None:
        commencement(2022, 12, '73', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του. 2. Η ισχύς του άρθρου 4 '
                     'αρχίζει την 1η.7.2022.', 'ν. 4886/2022 art. 73')
        _no_own_start(2022, 12, '64', m64, w64)
        LOG.append(f'{w64}: in force on publication (art. 73 par. 1); art. 64 gives no day of its own')

    def e4957(u: dict) -> dict:
        instr, qs = amending(2022, 141, '394', m394)
        N.need(instr, 'Η περ. (α) της παρ. 3 του άρθρου 20 του ν. 4735/2020 (Α’ 197), περί της επιλογής διοικήσεων στον '
               'δημόσιο τομέα, τροποποιείται, ως προς τα απαιτούμενα προσόντα συμμετοχής', w394)
        return restate_par(u, 'art-020', 2022, 141, '394', m394, '3', [('take', '(α) ', '\n(β) ', '(α) ', '\n(β) ')],
                           w394, src=(instr, qs[0]))

    def chk4957() -> None:
        commencement(2022, 141, '489', '1. Το παρόν ισχύει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, εκτός '
                     'αν άλλως ορίζεται στις επιμέρους διατάξεις του.', 'ν. 4957/2022 art. 489')
        t = ' '.join(p['text'] for p in N.amending_article(2022, 141, '489', 'Έναρξη ισχύος'))
        if re.search(r'\b394\b|έως 39\d\b', t):
            raise SystemExit(f'{w394}: art. 489 may date it: read it')
        _no_own_start(2022, 141, '394', m394, w394)
        LOG.append(f'{w394}: in force on publication (art. 489 par. 1; its other paragraphs do not name art. 394)')

    def e5062(u: dict) -> dict:
        t = ' '.join(p['text'] for p in N.amending_article(2023, 183, '17', 'Καταργούμενες διατάξεις'))
        N.need(t, 'Από την έναρξη ισχύος του παρόντος καταργούνται τα άρθρα 20 έως 23 του ν. 4735/2020 (Α’ 197)', w17)
        if N.head_split(u['art-020'])[0] != ['ΚΕΦΑΛΑΙΟ Β’', 'ΕΠΙΛΟΓΗ ΔΙΟΙΚΗΣΕΩΝ ΣΤΟΝ ΔΗΜΟΣΙΟ ΤΟΜΕΑ'] or \
                not N.head_split(u['art-024'])[0]:
            raise SystemExit(f'{w17}: arts. 20-23 are not the whole of Chapter Β’')
        return repeal_arts(u, ['art-020', 'art-021', 'art-022', 'art-023'], w17)

    def chk5062() -> None:
        commencement(2023, 183, '24', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως.', 'ν. 5062/2023 art. 24')
        LOG.append(f'{w17}: in force on publication (art. 24)')

    def e5224(u: dict) -> dict:
        instr, qs = amending(2025, 142, '102', m102)
        return restate_par(u, 'art-066', 2025, 142, '102', m102, '2', [
            ('sub', 'στο ηλεκτρονικό μητρώο αθλητικών σωματείων του άρθρου 142 του ν. 4714/2020 (Α’ 148),',
             'στο πληροφοριακό σύστημα «e-Kouros» του άρθρου 18 του ν. 5085/2024 (Α’ 17)')], w102, src=(instr, qs[0]))

    def chk5224() -> None:
        commencement(2025, 142, '176', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη '
                     'δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως.', 'ν. 5224/2025 art. 176')
        t = ' '.join(p['text'] for p in N.amending_article(2025, 142, '176', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*102\b|έως 10\d\b|(?:9\d|10\d) έως', t):
            raise SystemExit(f'{w102}: art. 176 may date it: read it')
        _no_own_start(2025, 142, '102', m102, w102)
        LOG.append(f'{w102}: in force on publication (art. 176 par. 1; par. 2 does not name art. 102)')

    def e5314(u: dict) -> dict:
        u = repeal_arts(u, ['art-038', 'art-039', 'art-040', 'art-048', 'art-055', 'art-063'], w773)
        lines = list(u['art-066'])
        for par in ('1', '2', '4'):
            i = N.find_one(lines, f'{par}. ', f'{w773}: art-066 par. {par}')
            j = i + 1
            while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
                j += 1
            lines = lines[:i] + lines[j:]
        u['art-066'] = lines
        LOG.append(f'{w773}: art-066 pars. 1, 2 and 4 repealed (removed); par. 3 stays')
        lines = list(u['art-068'])
        i = N.find_one(lines, '1. ', f'{w773}: art-068 par. 1')
        j = i + 1
        while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
            j += 1
        u['art-068'] = lines[:i] + lines[j:]
        LOG.append(f'{w773}: art-068 par. 1 repealed (removed, {j - i} line(s))')
        return u

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2, 3 και 4.', 'ν. 5314/2026 art. 774')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '774', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*773\b|έως 77\d\b', t):
            raise SystemExit('ν. 5314/2026 art. 774 may defer art. 773: read it')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '773', 'Καταργούμενες διατάξεις'))
        N.need(t, 'Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:', 'ν. 5314/2026 art. 773 par. Β')
        N.need(t, '52. τα άρθρα 38 έως 40, 48, 52, 54, 55, 63, 66 και παρ. 1 του άρθρου 68 του ν. 4735/2020 (Α’ 197),',
               'ν. 5314/2026 art. 773 par. Β no. 52')
        b = ' '.join(p['text'] for p in N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής '
                                                                          'Αυτοδιοίκησης'))
        N.need(b, '48. τα άρθρα 38 έως 40, 48, 55, 63, οι παρ. 1, 2 και 4 του άρθρου 66 και η παρ. 1 του άρθρου 68 του ν. '
               '4735/2020 (Α’ 197),', 'ν. 5321/2026 art. 54 (art. 773 par. Β no. 48)')
        N.need(b, 'Β. Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:', 'ν. 5321/2026 art. 54')
        N.need(b, '2. Η παρ. 1 ισχύει από την 29η.6.2026.', 'ν. 5321/2026 art. 54 par. 2')
        if b.count('4735/2020') != 1:
            raise SystemExit('ν. 5321/2026 art. 54: ν. 4735/2020 named more than once')
        LOG.append('ν. 5314/2026 art. 774 pars. 2-4 do not date art. 773; ν. 5321/2026 art. 54 replaces art. 773 from '
                   '29.6.2026 (its par. 2), the Code\'s own first day, and its par. Β no. 48 is the list in force')

    steps = [
        {'law': 'n-4772-2021', 'fek': (2021, 17), 'day': None, 'edit': e4772, 'check': chk4772,
         'note': 'ν. 4772/2021 art. 48 (ΦΕΚ Α΄ 17/2021), in force on publication (art. 49 par. 1): art. 22 par. 2 '
                 'replaced (when a term ends before a successor is selected, it is extended or the post filled for the '
                 'time being; a new selection starts within 20 days).'},
        {'law': 'n-4807-2021', 'fek': (2021, 96), 'day': None, 'edit': e4807, 'check': chk4807,
         'note': 'ν. 4807/2021 art. 34 (ΦΕΚ Α΄ 96/2021), in force on publication (art. 62): art. 53 (inventory of the '
                 'property of municipal nurseries: deadline 31.12.2021, registration also at the cadastral office) '
                 'restated.'},
        {'law': 'n-4808-2021', 'fek': (2021, 101), 'day': None, 'edit': e4808, 'check': chk4808,
         'note': 'ν. 4808/2021 art. 54 item θ. (ΦΕΚ Α΄ 101/2021), from its commencement, its publication (art. 165): '
                 'art. 31 (child-raising leave of private-law staff) repealed.'},
        {'law': 'n-4809-2021', 'fek': (2021, 102), 'day': None, 'same_day': True, 'edit': e4809, 'check': chk4809,
         'note': 'ν. 4809/2021 (ΦΕΚ Α΄ 102/2021), in force on publication (art. 66 par. 1): art. 54 adds art. 75 par. 2 '
                 '(art. 66 par. 2 starts on 1.9.2021; the article is restated), and art. 65 item θ) repeals the second '
                 'sentence of art. 66 par. 2 (its own start, six months after publication).'},
        {'law': 'n-4825-2021', 'fek': (2021, 157), 'day': None, 'edit': e4825, 'check': chk4825,
         'note': 'ν. 4825/2021 art. 68 (ΦΕΚ Α΄ 157/2021), in force on publication (art. 73 par. 1): in art. 75 par. 2 '
                 'the date 1.9.2021 becomes 1.8.2022; the article is restated.'},
        {'law': 'n-4886-2022', 'fek': (2022, 12), 'day': None, 'edit': e4886, 'check': chk4886,
         'note': 'ν. 4886/2022 art. 64 (ΦΕΚ Α΄ 12/2022), in force on publication (art. 73 par. 1): art. 20 par. 1 '
                 'restated, keeping the parliamentary hearing or opinion where the law provides for one.'},
        {'law': 'n-4957-2022', 'fek': (2022, 141), 'day': None, 'edit': e4957, 'check': chk4957,
         'note': 'ν. 4957/2022 art. 394 (ΦΕΚ Α΄ 141/2022), in force on publication (art. 489 par. 1): art. 20 par. 3 '
                 'item (α), the degree required (also a technological degree or a postgraduate title); the paragraph '
                 'is restated.'},
        {'law': 'n-5062-2023', 'fek': (2023, 183), 'day': None, 'edit': e5062, 'check': chk5062,
         'note': 'ν. 5062/2023 art. 17 (ΦΕΚ Α΄ 183/2023), in force on publication (art. 24): arts. 20-23 (Chapter Β’, '
                 'selection of administrations in the public sector, which ν. 5062/2023 replaces) repealed.'},
        {'law': 'n-5224-2025', 'fek': (2025, 142), 'day': None, 'edit': e5224, 'check': chk5224,
         'note': 'ν. 5224/2025 art. 102 (ΦΕΚ Α΄ 142/2025), in force on publication (art. 176 par. 1): in art. 66 par. 2 '
                 'the electronic register of sports clubs becomes the «e-Kouros» information system; the paragraph is '
                 'restated.'},
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Β, from the Code\'s '
                 'commencement, its publication (art. 774 par. 1), in the words ν. 5321/2026 art. 54 gave that article '
                 'from the same day: arts. 38-40, 48, 55 and 63, art. 66 pars. 1, 2 and 4 and art. 68 par. 1 repealed.'},
    ]
    return build('99990-n4735', 'nomos-4735-2020', 2020, 197, 4735,
                 'the Greek Citizenship Code, the selection of administrations in the public sector, the General '
                 'Secretariat for Human Resources of the Public Administration and local government', steps, [
                     _search15(4735, 2020, 'whose 100 rows (the most it returns) are Β΄, Γ΄ and Υ.Ο.Δ.Δ. issues of '
                               '2024-2026 (ministerial decisions and appointments, which do not amend a statute) and ΦΕΚ '
                               'Α΄ 142/2025',
                               'Amending: ν. 4772/2021 art. 48 (Α΄ 17/2021), ν. 4807/2021 art. 34 (Α΄ 96/2021), ν. '
                               '4808/2021 art. 54 (Α΄ 101/2021), ν. 4809/2021 arts. 54 and 65 (Α΄ 102/2021; ν. 4818/2021 '
                               'art. 64, Α΄ 124/2021, restates art. 65 keeping its item θ), ν. 4825/2021 art. 68 (Α΄ '
                               '157/2021), ν. 4886/2022 art. 64 (Α΄ 12/2022), ν. 4957/2022 art. 394 (Α΄ 141/2022), ν. '
                               '5062/2023 art. 17 (Α΄ 183/2023), ν. 5224/2025 art. 102 (Α΄ 142/2025) and the Local '
                               'Government Code, ν. 5314/2026 art. 773 (Α΄ 103/2026), as ν. 5321/2026 art. 54 (Α΄ '
                               '114/2026) replaced it. Every other mention (about 60 articles in some 40 issues, from Α΄ '
                               '204/2020 to Α΄ 142/2026) applies or refers to the selection procedure of arts. 20-23, to '
                               'art. 38 (Home Help), art. 56 or the citizenship provisions, without changing words of ν. '
                               '4735/2020; those of note are listed below.'),
                     'Provisions that act on ν. 4735/2020 without changing its words are recorded here, not as '
                     'versions: ν. 4745/2020 art. 93 (Α΄ 214/2020) and ν. 5043/2023 art. 44 (Α΄ 91/2023) '
                     'declare the true meaning of art. 67 and of art. 20 par. 2; ΦΕΚ Α΄ 195/2022 art. 82 lets certain '
                     'clubs use municipal sports grounds from 1.8.2022 to 31.7.2023 notwithstanding art. 66 par. 2 and '
                     'art. 75 par. 2; ΦΕΚ Α΄ 48/2023 art. 77 par. 3 funds the Home Help programme from 1.1.2023 '
                     'notwithstanding art. 38 par. 2; ν. 5062/2023 art. 15 and ΦΕΚ Α΄ 215/2023 art. 86 deal with posts '
                     'filled under art. 22 par. 2 and with references to arts. 20-23 after their repeal; ΦΕΚ Α΄ 78/2026 '
                     'art. 57 par. 2 ends the terms of deputy hospital governors serving under art. 22 par. 2.',
                     'Starts: art. 38 par. 3 starts art. 38 on 1.10.2020, before publication (12.10.2020), and art. 66 '
                     'par. 2 first started six months after publication (its own second sentence), then, once ν. '
                     '4809/2021 had repealed that sentence, on 1.9.2021 and, by ν. 4825/2021, on 1.8.2022 (art. 75 par. '
                     '2). As for every law here, the text is shown from publication; the changes to art. 75 and to art. '
                     '66 par. 2 are shown on the days the amending laws took effect.',
                     'Restatements, each used as printed: ν. 4772/2021 replaces art. 22 par. 2 as a whole; ν. 4807/2021 '
                     'changes art. 53 pars. 1 and 2 "as regards" the deadline and the registration, and its restatement '
                     'also reads «κατά την παρ. 2» for «κατά τις διατάξεις της παρ. 2» in par. 1; ν. 4809/2021 adds art. '
                     '75 par. 2, so the published single paragraph of art. 75 is numbered 1; ν. 4886/2022 adds to art. '
                     '20 par. 1 the words keeping the parliamentary hearing, quoted only in its restatement; ν. 5224/2025 '
                     'prints «Ο.Τ.Α.» where art. 66 par. 2 read «ΟΤΑ».',
                     'The Local Government Code (ν. 5314/2026) as published repeals, in its art. 773 par. Β no. 52, '
                     'arts. 38-40, 48, 52, 54, 55, 63, 66 and art. 68 par. 1 from its commencement, 29.6.2026. ν. '
                     '5321/2026 art. 54 ("correction of errors") replaced the whole of art. 773 with effect from that '
                     'same day, and its par. Β no. 48 names arts. 38-40, 48, 55 and 63, pars. 1, 2 and 4 of art. 66 and '
                     'art. 68 par. 1: arts. 52 and 54 and art. 66 par. 3 are not repealed. The list in force governs, '
                     'and that one change is credited to the Code.',
                     'When arts. 20-23 (Chapter Β’) are repealed, the chapter heading goes with them; when arts. 38-40 '
                     'are repealed, the heading of Chapter Ε’ (art. 38 alone) goes with it, and the heading of Chapter '
                     'ΣΤ’, which opened art. 39, now opens art. 41, the first article left in that chapter.',
                     'In the issue the heading of Chapter Η’ and the commencement article (art. 75) are set below both '
                     'columns of the last page, in the left column\'s place, after art. 74 at the foot of the right '
                     'column; they are read after art. 74 (that page only).',
                 ])


PARTS.update({'99990-n4735': lambda: p4735()})


# ---------------------------------------------------------------- GR-18: ν. 5134/2024

SPLIT_5134 = {
    'day': '2024-09-16',
    'clause': '1. Η ισχύς του Μέρους Α’, περί των παρεμβάσεων στον Κώδικα Πολιτικής Δικονομίας (π.δ. 503/1985, Α’ 182), '
              'του Μέρους Β’, περί των παρεμβάσεων στον Κώδικα Ποινικής Δικονομίας (ν. 4620/2019, Α’ 96), του Μέρους Γ’, '
              'περί των παρεμβάσεων στον Κώδικα Οργανισμού Δικαστηρίων και Κατάστασης Δικαστικών Λειτουργών (ν. '
              '4938/2022, Α’ 109) και των άρθρων 104, 105, 106, 108 και 109 του Μέρους Ε’ αρχίζει από τη 16η.9.2024.',
    'rest': '2. Η ισχύς των λοιπών διατάξεων του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως, '
            'εκτός αν άλλως ορίζεται σε επιμέρους διατάξεις.',
    'late': [f'art-{k:03d}' for k in list(range(1, 94)) + [104, 105, 106, 108, 109]],
}


def split_5134(part: dict) -> dict:
    """The built part with Parts Α-Γ (arts. 1-93) and arts. 104-106, 108, 109 moved to their start day, 16.9.2024: the
    first version holds the rest; the late articles come as published on 16.9.2024, credited to the law itself, before
    any amendment (which comes later)."""
    s = SPLIT_5134
    act = part['acts'][0]
    v0 = act['versions'][0]
    units = v0['units']
    lines = units['art-120']['text'].rstrip('\n').split('\n')
    if lines[-2:] != [s['clause'], s['rest']]:
        raise SystemExit(f'ν. 5134/2024: art. 120 does not read as expected: {[l[:50] for l in lines[-2:]]}')
    heads = {k: N.head_split(units[k]['text'].split('\n'))[0][:1] for k in ('art-001', 'art-053', 'art-061', 'art-094',
                                                                            'art-104', 'art-120')}
    if heads != {'art-001': ['ΜΕΡΟΣ Α’'], 'art-053': ['ΜΕΡΟΣ Β’'], 'art-061': ['ΜΕΡΟΣ Γ’'], 'art-094': ['ΜΕΡΟΣ Δ’'],
                 'art-104': ['ΜΕΡΟΣ Ε’'], 'art-120': ['ΜΕΡΟΣ ΣΤ’']}:
        raise SystemExit(f'ν. 5134/2024: the Parts do not open where expected: {heads}')
    if act['versions'][1]['from'] <= s['day']:
        raise SystemExit('ν. 5134/2024: an amendment takes effect before the late start: the split must be re-read')
    pub = v0['from']
    key = 'n-5134-2024'
    late = [k for k in units if k in s['late']]
    if len(late) != len(s['late']):
        raise SystemExit('ν. 5134/2024: late articles missing')
    v0['units'] = {k: u for k, u in units.items() if k not in s['late']}
    v0['note'] = ('ν. 5134/2024 as published in ΦΕΚ Α΄ 146/2024: only the articles its commencement article puts in '
                  'force on publication (Part Δ’, arts. 94-103, and arts. 107 and 110-120 of Parts Ε’ and ΣΤ’); Parts '
                  'Α’-Γ’ and arts. 104-106, 108 and 109 follow on 16.9.2024.')
    act['versions'].insert(1, {'from': s['day'], 'source_url': v0['source_url'], 'sha256': v0['sha256'],
                               'changes': {k: units[k] for k in late}, 'credits': {k: [key] for k in late},
                               'note': 'Parts Α’-Γ’ of ν. 5134/2024 (arts. 1-93: the Codes of Civil and Criminal '
                                       'Procedure and the Code of Courts) and arts. 104-106, 108 and 109 take effect on '
                                       '16.9.2024 (art. 120 par. 1).'})
    dec = part['decisions']
    i = next(i for i, x in enumerate(dec) if x.startswith('ν. 5134/2024 is dated '))
    dec[i] = (f'ν. 5134/2024 starts in two steps, by its own commencement article (art-120): «{s["clause"]} {s["rest"]}» '
              f'So the first version ({pub}, publication, the date on the issue\'s masthead) holds only the articles in '
              f'force then (arts. 94-103, 107 and 110-120); the other {len(late)} articles are added on {s["day"]}, '
              'credited to the law itself. The heading of Part Ε’, printed above art. 104, comes with that article.')
    return part


def p5134() -> dict:
    w72 = 'ν. 5140/2024 art. 72 par. 1'
    m72 = 'Μεταβατικές διατάξεις για την εφαρμογή του νέου δικαστικού χάρτη'

    def e5140(u: dict) -> dict:
        return remove_par(u, 'art-051', 2024, 154, '72', m72, '4',
                          '1. Η παρ. 4 του άρθρου 51 του ν. 5134/2024 (Α’ 146), περί μεταβατικής διάταξης, καταργείται.',
                          w72)

    def chk5140() -> None:
        commencement(2024, 154, '73', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, υπό την επιφύλαξη των παρ. 2 έως 5.', 'ν. 5140/2024 art. 73')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 154, '73', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*72\b|έως 7\d\b', t):
            raise SystemExit(f'{w72}: art. 73 may date art. 72: read it')
        _no_own_start(2024, 154, '72', m72, w72)
        LOG.append(f'{w72}: in force on publication (art. 73 par. 1; pars. 2-5 do not name art. 72)')

    steps = [
        {'law': 'n-5140-2024', 'fek': (2024, 154), 'day': None, 'edit': e5140, 'check': chk5140,
         'note': 'ν. 5140/2024 art. 72 par. 1 (ΦΕΚ Α΄ 154/2024), in force on publication (art. 73 par. 1): art. 51 par. '
                 '4 (transitional filing of pleadings at the seat of the court of first instance) repealed.'},
    ]
    part = build('99991-n5134', 'nomos-5134-2024', 2024, 146, 5134,
                 'amendments to the Codes of Civil and Criminal Procedure and the Code of Courts and Judicial Officers '
                 'for the unified first instance (ν. 5108/2024), the judicial police and other urgent provisions',
                 steps, [
                     _search15(5134, 2024, 'whose only later Α΄ row is ΦΕΚ Α΄ 154/2024 ("Τροποποίηση", "Ακύρωση"; its '
                               'Β΄ and Γ΄ rows are ministerial decisions and appointments, which do not amend a '
                               'statute)',
                               'Amending: ν. 5140/2024 art. 72 par. 1 (ΦΕΚ Α΄ 154/2024), which repeals art. 51 par. 4; '
                               'the scan finds no other article that names ν. 5134/2024, and the 2026 issues read in '
                               'the PDFs do not mention it.'),
                     'ν. 5134/2024 art. 19 prints two opening quotation marks («Άρθρο 208 … «1. Τίτλο …) and one '
                     'closing mark; the text is kept as printed.',
                 ])
    return split_5134(part)


PARTS.update({'99991-n5134': lambda: p5134()})


# ---------------------------------------------------------------- GR-18: ν. 5164/2024

def p5164() -> dict:
    w57, w773 = 'ν. 5255/2025 art. 57', 'ν. 5314/2026 art. 773 par. Β no. 5'
    m57 = 'Μετάθεση χρόνου έναρξης υποχρεώσεων'
    big = ('όπως ορίζονται στο Παράρτημα Α’ του ν. 4308/2014 και υπερβαίνουν κατά την ημερομηνία κλεισίματος του '
           'ισολογισμού τους')
    big_new = ('σύμφωνα με την παρ. 3 του άρθρου 31 του ν. 4308/2014, ο οποίος υπερβαίνει κατά την ημερομηνία κλεισίματος '
               'του ισολογισμού του')
    big18 = big.replace('υπερβαίνουν κατά', 'υπερβαίνουν, κατά')
    big18_new = big_new.replace('υπερβαίνει κατά', 'υπερβαίνει, κατά')

    def e5255(u: dict) -> dict:
        instr, qs = amending(2025, 219, '57', m57)
        N.need(instr, '1. Στην παρ. 1 του άρθρου 14 του ν. 5164/2024 (Α’ 202), περί του χρόνου έναρξης των υποχρεώσεων '
               'του Κεφαλαίου Α’, επέρχονται οι ακόλουθες τροποποιήσεις:', w57)
        N.need(instr, '3. Στον ν. 5164/2024 προστίθεται άρθρο 14Α ως εξής:', w57)
        N.need(instr, '4. Στο άρθρο 18 του ν. 5164/2024, περί του χρόνου έναρξης των υποχρεώσεων του Κεφαλαίου Β’, '
               'επέρχονται οι εξής τροποποιήσεις:', w57)
        common = [('add', '1ης Ιανουαρίου 2024', 'και στο εξής')]
        late = [('sub', '1ης Ιανουαρίου 2025', '1ης Ιανουαρίου 2027 και στο εξής')]
        u = restate_par(u, 'art-014', 2025, 219, '57', m57, '1', common + [('sub_at', big18, big, big_new)] + late + [
            ('sub', '1ης Ιανουαρίου 2026', '1ης Ιανουαρίου 2028 και στο εξής')], w57 + ' par. 1', src=(instr, qs[0]))
        u = restate_par(u, 'art-014', 2025, 219, '57', m57, '3', common + [('sub_at', big18, big, big_new)] + late + [
            ('sub', 'β)', 'ββ)', ('\nβ) σε', ' εκδότες')),
            ('sub', 'όπως ορίζονται στο Παράρτημα Α’ του ν. 4308/2014', 'σύμφωνα με την παρ. 3 του άρθρου 31 του ν. '
             '4308/2014'),
            ('sub_at', '1η Ιανουαρίου 2026', '1ης Ιανουαρίου 2026', '1ης Ιανουαρίου 2028 και στο εξής')],
            w57 + ' par. 2', src=(instr, qs[1]))
        u = add_unit(u, 'Άρθρο 14Α', 2025, 219, '57', m57, w57 + ' par. 3', q_index=2)
        return restate(u, 'art-018', 2025, 219, '57', m57, common + [('sub', big18, big18_new)] + late + [
            ('sub', 'όπως ορίζονται στο Παράρτημα Α’', 'σύμφωνα με την παρ. 3 του άρθρου 31'),
            ('sub', '1ης Ιανουαρίου 2026', '1ης Ιανουαρίου 2028 και στο εξής')], w57 + ' par. 4', q_index=3,
            allowed={('οποίες', 'οποίοι'): 'Not among the listed changes: the restatement (ν. 5255/2025\'s own text) '
                     'governs and is used as printed.'})

    def chk5255() -> None:
        commencement(2025, 219, '64', '1. Με την επιφύλαξη της παρ. 2, ο παρών νόμος ισχύει από τη δημοσίευσή του στην '
                     'Εφημερίδα της Κυβερνήσεως, εκτός αν άλλως ορίζεται στις επιμέρους διατάξεις του. 2. Το άρθρο 47',
                     'ν. 5255/2025 art. 64')
        _no_own_start(2025, 219, '57', m57, w57)
        LOG.append(f'{w57}: in force on publication (art. 64 par. 1; par. 2 dates art. 47 only)')

    def e5314(u: dict) -> dict:
        return repeal_unit(u, 'art-077', 2026, 103, '773', 'Καταργούμενες διατάξεις', [
            'Από την έναρξη ισχύος του παρόντος Κώδικα, καταργούνται:', '5. το άρθρο 77 του ν. 5164/2024 (Α’ 202),'],
            w773)

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της '
                     'Κυβερνήσεως, με την επιφύλαξη των παρ. 2, 3 και 4.', 'ν. 5314/2026 art. 774')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '774', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*773\b|έως 77\d\b', t):
            raise SystemExit('ν. 5314/2026 art. 774 may defer art. 773: read it')
        b = ' '.join(p['text'] for p in N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής '
                                                                          'Αυτοδιοίκησης'))
        N.need(b, '5. το άρθρο 77 του ν. 5164/2024', 'ν. 5321/2026 art. 54')
        if b.count('5164/2024') != 1:
            raise SystemExit('ν. 5321/2026 art. 54: ν. 5164/2024 named more than once')
        LOG.append('ν. 5314/2026 art. 774 pars. 2-4 do not date art. 773; ν. 5321/2026 art. 54 replaces art. 773 from '
                   'the Code\'s first day and its par. Β no. 5 repeals art. 77 of ν. 5164/2024 in the same words')

    steps = [
        {'law': 'n-5255-2025', 'fek': (2025, 219), 'day': None, 'edit': e5255, 'check': chk5255,
         'note': 'ν. 5255/2025 art. 57 pars. 1-4 (ΦΕΚ Α΄ 219/2025), in force on publication (art. 64 par. 1): the '
                 'sustainability-reporting obligations of art. 14 pars. 1 and 3 and art. 18 move to financial years '
                 'from 1 January 2027 and 2028 ("stop-the-clock"); art. 14Α (transitional consolidated reports by a '
                 'subsidiary, to 6 January 2030) is added.'},
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'ν. 5314/2026, the Local Government Code (ΦΕΚ Α΄ 103/2026), art. 773 par. Β no. 5, from the Code\'s '
                 'commencement, its publication (art. 774 par. 1): art. 77 (school expenses among the compulsory '
                 'expenses of municipalities) repealed.'},
    ]
    return build('99992-n5164', 'nomos-5164-2024', 2024, 202, 5164,
                 'corporate sustainability reporting (Directive (EU) 2022/2464), accounting categories, the General '
                 'Commercial Registry and other provisions', steps, [
                     _search15(5164, 2024, 'whose only later Α΄ row is ΦΕΚ Α΄ 219/2025 (its Β΄ rows are ministerial '
                               'decisions, which do not amend a statute)',
                               'Amending: ν. 5255/2025 art. 57 (ΦΕΚ Α΄ 219/2025) and the Local Government Code, ν. '
                               '5314/2026 art. 773 (ΦΕΚ Α΄ 103/2026; ν. 5321/2026 art. 54, ΦΕΚ Α΄ 114/2026, repeats the '
                               'repeal in the same words). ΦΕΚ Α΄ 10/2025 art. 92 lets the statutory auditor also give '
                               'the assurance of the art. 7 reports for financial year 2024, without changing words of '
                               'ν. 5164/2024; ΦΕΚ Α΄ 105/2026 art. 11 refers to it only.'),
                     'ν. 5255/2025 art. 57 lists each change to art. 14 pars. 1 and 3 and art. 18 and restates them; '
                     'the parse applies the listed changes and checks them against the restatements, which govern. In '
                     'par. 3 the listed changes also correct the item letter «β)» to «ββ)»; the restatement also prints '
                     '«1ης Ιανουαρίου 2026» where par. 3 read «1η Ιανουαρίου 2026» (the change of that date is '
                     'listed), and in art. 18 «οι οποίοι» where it read «οι οποίες».',
                 ])


PARTS.update({'99992-n5164': lambda: p5164()})



# GR-19: ν. 5195/2025 (ΦΕΚ Α΄ 73/2025)
def p5195() -> dict:
    w255, w102 = 'ν. 5259/2025 art. 255', 'ν. 5301/2026 art. 102'
    m255 = 'Τροποποίηση άρθρου 86 ν. 5195/2025'
    m102 = 'Τροποποίηση παρ. 5 και 6 άρθρου 78 ν. 5195/2025'
    old_d, new_d = '23 Ιανουαρίου 2026', '23 Σεπτεμβρίου 2026'

    def e5259(u: dict) -> dict:
        instr, _ = amending(2025, 228, '255', m255)
        N.need(instr, 'Στις παρ. 1 και 2 του άρθρου 86 του ν. 5195/2025 (Α’ 73),', w255)
        N.need(instr, 'οι λέξεις «23 Ιανουαρίου 2026» αντικαθίστανται από τις λέξεις «23 Σεπτεμβρίου 2026» και το '
               'άρθρο 86 διαμορφώνεται ως εξής:', w255)
        return restate(u, 'art-086', 2025, 228, '255', m255, [
            ('sub', old_d, new_d, ('1. Οι συμβάσεις', '2. Οι συμβάσεις')),
            ('sub', old_d, new_d, ('2. Οι συμβάσεις', '3. Το προσωπικό'))], w255, allowed=ALLOWED_5195)

    def chk5259() -> None:
        commencement(2025, 228, '268', '3. Με την επιφύλαξη των παρ. 4 έως 8 η ισχύς της Ενότητας III αρχίζει από τη '
                     'δημοσίευση του παρόντος στην Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις '
                     'επιμέρους διατάξεις του.', 'ν. 5259/2025 art. 268')
        t = ' '.join(p['text'] for p in N.amending_article(2025, 228, '268', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w* (?:\d+(?:, | και | έως ))*255\b|έως 2(?:5[6-9]|6\d)\b', t):
            raise SystemExit('ν. 5259/2025 art. 268 may date art. 255: read it')
        # the Ενότητα headings are plain paragraphs in this issue (not struct): the last one before art. 255
        paras = N.fek_paras(2025, 228)
        pos = [i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == 'Άρθρο 255']
        ens = [(i, p['text']) for i, p in enumerate(paras) if re.match(r'^ΕΝΟΤΗΤΑ [IΙVΧ]+$', p['text'])]
        if len(pos) != 1 or [t for i, t in ens if i < pos[0]][-1:] != ['ΕΝΟΤΗΤΑ ΙΙΙ']:
            raise SystemExit(f'ν. 5259/2025: art. 255 is not in Ενότητα III: {ens}')
        LOG.append('ν. 5259/2025: art. 255 lies in Ενότητα III')
        _no_own_start(2025, 228, '255', m255, w255)
        LOG.append(f'{w255}: in force on publication (art. 268 par. 3, Ενότητα III; pars. 4-8 do not name art. 255)')

    def e5301(u: dict) -> dict:
        instr, qs = amending(2026, 74, '102', m102)
        N.need(instr, '1. Στην παρ. 5 του άρθρου 78 του ν. 5195/2025 (Α’ 73),', w102)
        N.need(instr, '2. Στην παρ. 6 του άρθρου 78 του ν. 5195/2025 μετά από τις λέξεις', w102)
        if len(qs) != 2:
            raise SystemExit(f'{w102}: {len(qs)} quotations')
        u = restate_par(u, 'art-078', 2026, 74, '102', m102, '5', [
            ('add', 'που καταβλήθηκαν', 'και καταβάλλονται'),
            ('add', 'θεωρούνται νόμιμα', 'και δεν αναζητούνται')], w102 + ' par. 1', q_index=0)
        return restate_par(u, 'art-078', 2026, 74, '102', m102, '6', [
            ('add_at', 'σύμφωνα με τις παρ. 1, 2,', 'σύμφωνα με τις παραγράφους 1, 2,', '3,')], w102 + ' par. 2',
            q_index=1, allowed=ALLOWED_5195)

    def chk5301() -> None:
        commencement(2026, 74, '127', '1. Με την επιφύλαξη των παρ. 2 έως 5, ο παρών νόμος ισχύει από τη δημοσίευσή '
                     'του στην Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του.',
                     'ν. 5301/2026 art. 127')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 74, '127', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w* (?:\d+(?:, | και | έως ))*102\b|έως 1(?:0[3-9]|[1-2]\d)\b', t):
            raise SystemExit('ν. 5301/2026 art. 127 may date art. 102: read it')
        in_part(2026, 74, '102', 'ΜΕΡΟΣ ΣΤ’', 'ΜΕΡΟΣ Ζ’', 'ν. 5301/2026')
        _no_own_start(2026, 74, '102', m102, w102)
        LOG.append(f'{w102}: in force on publication (art. 127 par. 1; art. 102 lies in Part ΣΤ’, which pars. 2-6 '
                   'do not date)')

    steps = [
        {'law': 'n-5259-2025', 'fek': (2025, 228), 'day': None, 'edit': e5259, 'check': chk5259,
         'note': 'ν. 5259/2025 art. 255 (ΦΕΚ Α΄ 228/2025), in force on publication (art. 268 par. 3): in art. 86 pars. '
                 '1 and 2 the fixed-term contracts of the General Secretariat for Natural Disaster Recovery and State '
                 'Aid run to 23 September 2026 instead of 23 January 2026; the article is restated.'},
        {'law': 'n-5301-2026', 'fek': (2026, 74), 'day': None, 'edit': e5301, 'check': chk5301,
         'note': 'ν. 5301/2026 art. 102 (ΦΕΚ Α΄ 74/2026), in force on publication (art. 127 par. 1): art. 78 par. 5 '
                 '(retention bonuses of Hellenic Aerospace Industry staff) also covers amounts paid from now on, which '
                 'are not reclaimed, and par. 6 also names par. 3; both paragraphs are restated.'},
    ]
    return build('99993-n5195', 'nomos-5195-2025', 2025, 73, 5195,
                 'military hospitals, the staff of the Armed Forces and other provisions of the Ministry of National '
                 'Defence', steps, [
                     _search15(5195, 2025, 'whose later Α΄ rows are ΦΕΚ Α΄ 228/2025 and 74/2026 (its Β΄, Γ΄, Δ.Δ.Σ. '
                               'and Α.Σ.Ε.Π. rows are decisions and notices, which do not amend a statute)',
                               'Amending: ν. 5259/2025 art. 255 (ΦΕΚ Α΄ 228/2025) and ν. 5301/2026 art. 102 (ΦΕΚ Α΄ '
                               '74/2026). ΦΕΚ Α΄ 134/2026 art. 36 par. 2 extends again, to 31 October 2027, the '
                               'contracts that art. 86 pars. 1 and 2 extended, without changing words of ν. 5195/2025; '
                               'ΦΕΚ Α΄ 187/2025 arts. 106 and 115, 3/2026 arts. 89 and 283 and 117/2026 art. 71 refer '
                               'to it only.'),
                     'ν. 5195/2025 art. 93 starts art. 74 par. 1 thirty days after publication and art. 92 par. 2 on '
                     '4.8.2026 (and an amendment of ν. 2936/2001 on 1.1.2026); as in the other Greek parts, those '
                     'provisions are shown from publication, and these later starts are recorded here.',
                     'ν. 5301/2026 art. 102 par. 2 places its addition after the words «σύμφωνα με τις παραγράφους 1, '
                     '2,»; the text of art. 78 par. 6 reads «σύμφωνα με τις παρ. 1, 2,». The restated par. 6 also '
                     'writes out «της Ελληνικής Αεροπορικής Βιομηχανίας (Ε.Α.Β.) Α.Ε.» where it read «της Ε.Α.Β. '
                     'Α.Ε.»: the restatement is the amending law\'s own text and governs.',
                 ])


_R5195 = ('Not among the listed changes (ν. 5301/2026 art. 102 par. 2 lists only the added «3,»): the restated par. 6 '
          'is the amending law’s own text and governs.')
ALLOWED_5195: dict = {('', 'ελληνικής αεροπορικής βιομηχανίας'): _R5195, ('παρ', 'παραγράφους'): _R5195}

PARTS.update({'99993-n5195': lambda: p5195()})


def p5036() -> dict:
    """ν. 5036/2023, including art. 16 par. 1 on its own later start day."""
    def e5104(u: dict) -> dict:
        w = 'ν. 5104/2024 art. 91'
        instr, qs = amending(2024, 58, '91', 'ν. 5036/2023')
        N.need(instr, 'Η περ. β) του άρθρου 9 του ν. 5036/2023 (Α’ 77)', w)
        N.need(instr, 'αντικαθίσταται και το άρθρο 9 διαμορφώνεται ως εξής:', w)
        return restate(u, 'art-009', 2024, 58, '91', 'ν. 5036/2023',
                       [('take', 'β. ', '\nΕιδικά ', 'β. ', '\nΕιδικά ')], w, src=(instr, qs[0]))

    def e5131(u: dict) -> dict:
        return restate_par(u, 'art-064', 2024, 128, '41', 'ν. 5036/2023', '6',
                           [('sub', 'όχι πέραν της 30ής.6.2024', 'όχι πέραν της 31ης.12.2025')],
                           'ν. 5131/2024 art. 41 par. 1')

    def chk5104() -> None:
        commencement(2024, 58, '117', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως',
                     'ν. 5104/2024 art. 117')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 58, '117', 'Έναρξη ισχύος'))
        if re.search(r'\b91\b', t):
            raise SystemExit('ν. 5104/2024 art. 117 may defer art. 91')

    def chk5131() -> None:
        commencement(2024, 128, '52', 'Ο παρών νόμος ισχύει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως',
                     'ν. 5131/2024 art. 52')
        _no_own_start(2024, 128, '41', 'ν. 5036/2023', 'ν. 5131/2024 art. 41')

    steps = [
        {'law': 'n-5104-2024', 'fek': (2024, 58), 'day': None, 'edit': e5104, 'check': chk5104,
         'note': 'ν. 5104/2024 art. 91 (ΦΕΚ Α΄ 58/2024), in force on publication (art. 117): art. 9 item β replaced and the article restated.'},
        {'law': 'n-5131-2024', 'fek': (2024, 128), 'day': None, 'edit': e5131, 'check': chk5131,
         'note': 'ν. 5131/2024 art. 41 par. 1 (ΦΕΚ Α΄ 128/2024), in force on publication (art. 52): art. 64 par. 6 extends the outer limit to 31 December 2025.'},
    ]
    part = build('99996-n5036', 'nomos-5036-2023', 2023, 77, 5036,
                 'tax and social insurance debt arrangements and other urgent provisions', steps, [
                     'Amendment search: legalize-gr full-text mentions through ΦΕΚ Α΄ 177/2026, the 2026 gap Gazette issues, and the official issue relation index. ν. 5104/2024 art. 91 and ν. 5131/2024 art. 41 par. 1 change the law. ΦΕΚ Α΄ 88/2026 cites art. 70 only as an earlier change to ν. 4495/2017. The other mentions are references to provisions that ν. 5036/2023 changed in other laws.',
                     'In ΦΕΚ Α΄ 77/2023, the embedded restatement of art. 84 of ν. 4916/2022 under this law’s art. 67 has no opening « before its heading in the text layer. It remains inside art. 67; it is not this law’s art. 84.',
                 ])
    act = part['acts'][0]
    v0 = act['versions'][0]
    if act['versions'][1]['from'] <= '2023-06-01':
        raise SystemExit('ν. 5036/2023: amendment precedes art. 16 par. 1 start')
    full = v0['units']['art-016']
    lines = full['text'].rstrip('\n').split('\n')
    starts = [i for i, s in enumerate(lines) if s.startswith(('1. Η παρ. 1 αντικαθίσταται', '2. Η παρ. 3 αντικαθίσταται'))]
    if len(starts) != 2 or starts[0] >= starts[1] or not any(s.startswith('5. Η παρ. 1 ισχύει από την 1η.6.2023.') for s in lines):
        raise SystemExit('ν. 5036/2023: art. 16 par. 1 block or its start clause changed')
    pub_lines = lines[:starts[0]] + lines[starts[1]:]
    v0['units']['art-016'] = {**full, 'text': '\n'.join(pub_lines) + '\n'}
    v0['note'] = ('ν. 5036/2023 as published in ΦΕΚ Α΄ 77/2023: art. 16 par. 1 takes effect on 1 June 2023; '
                  'its other provisions are shown from publication, including retroactive clauses recorded in the decisions.')
    act['versions'].insert(1, {'from': '2023-06-01', 'source_url': v0['source_url'], 'sha256': v0['sha256'],
                               'changes': {'art-016': full}, 'credits': {'art-016': ['n-5036-2023']},
                               'note': 'Art. 16 par. 1 of ν. 5036/2023 takes effect on 1 June 2023 (art. 16 par. 5); the other lines of art. 16 were already in force.'})
    part['sources'][-1]['retrieved'] = '2026-11-03'
    part['decisions'].append('Art. 16 par. 1 of ν. 5036/2023 is inserted line by line on 1 June 2023 under art. 16 par. 5. Art. 106 par. 2 dates art. 84 from 1 January 2023 and art. 91 from 1 January 2022; both predate publication, so they are present in the publication version. Its other special dates concern provisions of other laws or events recorded here.')
    return part


PARTS.update({'99996-n5036': lambda: p5036()})


def p5027() -> dict:
    """ν. 5027/2023: dated amendments and the corrected Local Government Code repeal list."""
    def e5043(u: dict) -> dict:
        w = 'ν. 5043/2023 art. 26 par. 1'
        u = restate(u, 'art-077', 2023, 91, '26', 'ν. 5027/2023', [
            ('take', 'νομικά πρόσωπα αυτών', ' για την παροχή', 'νομικά πρόσωπα αυτών', ' για την παροχή'),
            ('take', 'π.δ. 164/2004 (Α’ 134)', '\n2.', 'π.δ. 164/2004 (Α’ 134)', '\n2.'),
            ('take', 'δικαίου δήμου,', 'μεταφέρεται', 'δικαίου δήμου,', 'μεταφέρεται'),
            ('take', 'φροντίδας,', '\n3.', 'φροντίδας.', '\n3.'),
            ('take', 'στα νομικά τους πρόσωπα', 'που υλοποιούν', 'στα νομικά τους πρόσωπα', 'που υλοποιούν'),
            ('take', None, None, '\n4.', None),
        ], w, allowed={('μόνιμου', 'μονίμου'): 'The restatement prints the genitive with the other accent; it governs.',
                       ('την', 'τη'): 'The restatement prints «κατά τη 18η.12.2018» rather than «κατά την 18η.12.2018»; it governs.',
                       ('τ ασεπ', 'τασεπ'): 'The restatement joins «τ. ΑΣΕΠ» as «τ.ΑΣΕΠ»; it governs.'})
        u = add_par(u, 'art-063', 2023, 91, '42', 'ν. 5027/2023', '4',
                    'προστίθεται παρ. 4 ως εξής:', 'ν. 5043/2023 art. 42')
        return u

    def e5046(u: dict) -> dict:
        w = 'ν. 5046/2023 art. 36 par. 1'
        instr, qs = amending(2023, 137, '36', 'ν. 5027/2023')
        return restate_par(u, 'art-035', 2023, 137, '36', 'ν. 5027/2023', '1',
                           [('take', 'ισχύ. ', 'Όπου ', 'ισχύ. ', 'Όπου ')], w, src=(instr, qs[0]))

    def e5217(u: dict) -> dict:
        return repeal_unit(u, 'art-017', 2025, 120, '97', 'Καταργούμενες διατάξεις',
                           ['Από την έναρξη ισχύος του παρόντος, καταργούνται:',
                            '2. Το άρθρο 17 του ν. 5027/2023 (Α’ 48)'], 'ν. 5217/2025 art. 97 no. 2')

    def e5270(u: dict) -> dict:
        w = 'ν. 5270/2026 art. 28'
        instr, qs = amending(2026, 9, '28', 'ν. 5027/2023')
        old = '\n'.join(u['art-033'])
        new = '\n'.join(qs[0])
        for phrase in ['Γενικού Σκοπού', 'Εποπτείας Περιφέρειας', 'άρθρα 61 έως 106 του Αστικού Κώδικα',
                       'προστίθενται νέες παρ. 1Α, 1Β και 1Γ', 'διαγράφονται οι λέξεις «Γενικού Σκοπού»']:
            N.need(instr, phrase, w)
        for phrase in ['Γενικού Σκοπού', 'άρθρων 61 έως 108', 'δημόσιας βάσης δεδομένων Ο.Κοι.Π.']:
            N.need(old, phrase, w + ' original')
        for phrase in ['Σωματεία Εποπτείας Περιφέρειας', '1Α. ', '1Β. ', '1Γ. ', 'άρθρα 61 έως 106']:
            N.need(new, phrase, w + ' restatement')
        return restate(u, 'art-033', 2026, 9, '28', 'ν. 5027/2023', [
            ('take', 'Σύσταση Μητρώου', '\n1.', 'Σύσταση Μητρώου', '\n1.'),
            ('take', '\n1.', '\n2.', '\n1.', '\n2.'),
            ('take', '\n3.', None, '\n3.', None),
        ], w, src=(instr, qs[0]))

    code_keys = [f'art-{n:03d}' for n in list(range(40, 46)) + list(range(47, 52)) + [56, 59]]

    def e5314(u: dict) -> dict:
        return repeal_arts(u, code_keys, 'ν. 5314/2026 art. 773 par. Α no. 21, as corrected by ν. 5321/2026 art. 54')

    def chk5043() -> None:
        commencement(2023, 91, '124', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του',
                     'ν. 5043/2023 art. 124')
        t = ' '.join(p['text'] for p in N.amending_article(2023, 91, '124', 'Έναρξη ισχύος'))
        N.need(t, '2. Τα άρθρα 61 και 63 τίθενται σε ισχύ από 1η Ιουλίου 2023.', 'ν. 5043/2023 art. 124')

    def chk5046() -> None:
        commencement(2023, 137, '46', 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του', 'ν. 5046/2023 art. 46')
        t = ' '.join(p['text'] for p in N.amending_article(2023, 137, '36', 'ν. 5027/2023'))
        N.need(t, '2. Η ισχύς του δεύτερου εδαφίου της παρ. 1 του άρθρου 35 του ν. 5027/2023, όπως προστίθεται με την παρ. 1 του παρόντος, αρχίζει την 1η.7.2023.', 'ν. 5046/2023 art. 36')

    def chk5217() -> None:
        commencement(2025, 120, '98', '1. Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως',
                     'ν. 5217/2025 art. 98')
        t = ' '.join(p['text'] for p in N.amending_article(2025, 120, '98', 'Έναρξη ισχύος'))
        if re.search(r'\b97\b', t):
            raise SystemExit('ν. 5217/2025 art. 98 may defer art. 97')

    def chk5270() -> None:
        commencement(2026, 9, '46', 'Η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του', 'ν. 5270/2026 art. 46')
        _no_own_start(2026, 9, '28', 'ν. 5027/2023', 'ν. 5270/2026 art. 28')

    def chk5314() -> None:
        commencement(2026, 103, '774', '1. Η ισχύς του παρόντος εκκινεί από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως',
                     'ν. 5314/2026 art. 774')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '774', 'Έναρξη ισχύος'))
        if re.search(r'άρθρ\w+ (?:\d+(?:, | και | έως ))*773\b|έως 77\d\b', t):
            raise SystemExit('ν. 5314/2026 art. 774 may defer art. 773')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 103, '773', 'Καταργούμενες διατάξεις'))
        N.need(t, '23. τα άρθρα 39 έως 51, 57 έως 59 του ν. 5027/2023 (Α’ 48)', 'ν. 5314/2026 printed list')
        t = ' '.join(p['text'] for p in N.amending_article(2026, 114, '54', 'Αντικατάσταση άρθρου 773 Κώδικα Τοπικής Αυτοδιοίκησης'))
        N.need(t, '21. τα άρθρα 40 έως 45, 47 έως 51, 56 και 59 του ν. 5027/2023 (Α’ 48)', 'ν. 5321/2026 corrected list')

    steps = [
        {'law': 'n-5043-2023', 'fek': (2023, 91), 'day': None, 'edit': e5043, 'check': chk5043,
         'note': 'ν. 5043/2023 arts. 26 par. 1 and 42 (ΦΕΚ Α΄ 91/2023), in force on publication: art. 77 restated and art. 63 par. 4 added.'},
        {'law': 'n-5046-2023', 'fek': (2023, 137), 'day': None, 'edit': e5046, 'check': chk5046,
         'note': 'ν. 5046/2023 art. 36 par. 1 (ΦΕΚ Α΄ 137/2023): a second sentence added to art. 35 par. 1; its stated 1 July 2023 start predates this issue’s publication.'},
        {'law': 'n-5217-2025', 'fek': (2025, 120), 'day': None, 'edit': e5217, 'check': chk5217,
         'note': 'ν. 5217/2025 art. 97 no. 2 (ΦΕΚ Α΄ 120/2025), in force on publication: art. 17 repealed.'},
        {'law': 'n-5270-2026', 'fek': (2026, 9), 'day': None, 'edit': e5270, 'check': chk5270,
         'note': 'ν. 5270/2026 art. 28 (ΦΕΚ Α΄ 9/2026), in force on publication: art. 33 restated with the regional associations register and pars. 1Α to 1Γ.'},
        {'law': 'n-5314-2026', 'fek': (2026, 103), 'day': None, 'edit': e5314, 'check': chk5314,
         'note': 'The Local Government Code, ν. 5314/2026 art. 773 par. Α no. 21 (ΦΕΚ Α΄ 103/2026), in force on publication, as corrected by ν. 5321/2026 art. 54, repeals arts. 40-45, 47-51, 56 and 59.'},
    ]
    part = build('99994-n5027', 'nomos-5027-2023', 2023, 48, 5027,
                 'public administration, local government and other provisions', steps, [
                     'Amendment search: every legalize-gr mention through ΦΕΚ Α΄ 177/2026, the 2026 gap issues and the official issue relation index. The textual amendments are ν. 5043/2023 arts. 26 and 42, ν. 5046/2023 art. 36, ν. 5217/2025 art. 97, ν. 5270/2026 art. 28 and the Local Government Code’s corrected repeal list. ν. 5056/2023 art. 53 par. 2 repealed art. 50 before its 1 January 2024 start, so it never enters an in-force version. Other mentions extend arrangements or refer to changes in other laws without changing this law’s words.',
                     'Art. 96 dates art. 64 from 31 December 2022, before publication, so it appears from publication. Arts. 52 and 85 govern board appointments after the current boards end; no calendar day for those events is stated, so the text is shown from publication with this qualification.',
                     'ν. 5043/2023 art. 26 restates art. 77: the restatement prints «κατά τη» for «κατά την», «μονίμου» for «μόνιμου», omits a comma before «ο οποίος», and joins «τ.ΑΣΕΠ» without the space in the earlier text. The restatement governs.',
                     'ν. 5046/2023 art. 36 par. 2 states 1 July 2023 for its added sentence, before publication of that issue on 29 July; under the corpus rule for starts before publication, the new sentence is dated from publication and the stated day is recorded here.',
                     'ν. 5321/2026 art. 54 replaced art. 773 of the Local Government Code as a correction: its list, not the list first printed in ν. 5314/2026, governs. It excludes arts. 39, 46, 57 and 58 of ν. 5027/2023, includes art. 56, and retains the repeal of art. 50, which ν. 5056/2023 had already repealed before commencement.',
                 ])
    act = part['acts'][0]
    v0 = act['versions'][0]
    if 'art-050' not in v0['units'] or act['versions'][-1]['changes'].get('art-050') is not None:
        raise SystemExit('ν. 5027/2023: art. 50 staging or repeal changed')
    v0['units'].pop('art-050')
    act['versions'][-1]['changes'].pop('art-050')
    act['versions'][-1]['credits'].pop('art-050')
    v0['note'] = 'ν. 5027/2023 as published in ΦΕΚ Α΄ 48/2023: art. 50 has a later start but was repealed by ν. 5056/2023 before that day, so it never appears in an in-force version.'
    part['sources'][-1]['retrieved'] = '2026-11-03'
    return part


PARTS.update({'99994-n5027': lambda: p5027()})


def p5090() -> dict:
    """ν. 5090/2024, with its publication, May and July commencement stages."""
    def e5108(u: dict) -> dict:
        w43 = 'ν. 5108/2024 art. 43'
        u = restate(u, 'art-136', 2024, 65, '43', 'ν. 5090/2024',
                    [('sub', 'και 463', ', 463 και 469')], w43)
        w58 = 'ν. 5108/2024 art. 58'
        instr, qs = amending(2024, 65, '58', 'ν. 5090/2024')
        if len(qs) != 1 or len(qs[0]) != 4 or qs[0][:2] != ['Άρθρο 137', 'Μεταβατικές διατάξεις'] or not qs[0][2].startswith('1. ') or not qs[0][3].startswith('5. '):
            raise SystemExit(f'{w58}: expected art. 137 heading and pars. 1, 5 in the source quotation')
        u = restate_par(u, 'art-137', 2024, 65, '58', 'ν. 5090/2024', '1', [
            ('take', '31.7.2024,', 'εκδικάζονται', '31.7.2024,', 'εκδικάζονται'),
            ('take', 'Οι υπόλοιπες υποθέσεις', 'αποσύρονται', 'Οι υπόλοιπες υποθέσεις', 'αποσύρονται'),
        ], w58 + ' par. 1', src=(instr, [qs[0][2]]))
        return restate_par(u, 'art-137', 2024, 65, '58', 'ν. 5090/2024', '5', [
            ('take', 'Όπου στις διατάξεις του Κώδικα Ποινικής Δικονομίας', 'γίνεται αναφορά',
             'Όπου στις διατάξεις του Κώδικα Ποινικής Δικονομίας', 'γίνεται αναφορά'),
            ('take', 'Τριμελές Εφετείο', None, 'Τριμελές Εφετείο', None),
        ], w58 + ' par. 5', src=(instr, [qs[0][3]]))

    def chk5108() -> None:
        commencement(2024, 65, '76', '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του',
                     'ν. 5108/2024 art. 76')
        t = ' '.join(p['text'] for p in N.amending_article(2024, 65, '76', 'Έναρξη ισχύος'))
        N.need(t, 'η ισχύς του Μέρους Α’ αρχίζει από την 16η.9.2024', 'ν. 5108/2024 art. 76')
        paras = N.fek_paras(2024, 65)
        for a in ('43', '58'):
            pos = [i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == f'Άρθρο {a}']
            if len(pos) != 1:
                raise SystemExit(f'ν. 5108/2024 art. {a}: not one heading')
            heads = [p['text'] for p in paras[:pos[0]] if p['kind'] == 'struct' and p['text'].startswith('ΜΕΡΟΣ ')]
            if not heads or heads[-1].startswith('ΜΕΡΟΣ Α'):
                raise SystemExit(f'ν. 5108/2024 art. {a}: may be in delayed Part Α: {heads[-2:]}')

    steps = [{'law': 'n-5108-2024', 'fek': (2024, 65), 'day': None, 'edit': e5108, 'check': chk5108,
              'note': 'ν. 5108/2024 arts. 43 and 58 (ΦΕΚ Α΄ 65/2024), in force on publication (art. 76 par. 1; these articles are outside deferred Part Α): art. 136 item α and art. 137 pars. 1 and 5 restated.'}]
    part = build('99995-n5090', 'nomos-5090-2024', 2024, 30, 5090,
                 'interventions in the Penal Code and Code of Criminal Procedure', steps, [
                     'Amendment search: every legalize-gr mention through ΦΕΚ Α΄ 177/2026, the 2026 gap issues, and the official issue relation index. ν. 5108/2024 arts. 43 and 58 directly amend this law. Other mentions refer to it or to codified provisions and do not change its words.',
                     'Art. 138 gives three start stages: publication for its listed articles and art. 136 item γ, 1 May 2024 for the remaining provisions except its nine deferred articles, and 1 July 2024 for arts. 9, 10, 23, 28, 60, 82, 87, 88 and 89. Art. 136 items α and β join its already effective item γ on 1 May. The text is applied line by line.',
                 ])
    act = part['acts'][0]
    v0 = act['versions'][0]
    full = v0['units']
    pub_ids = [4, 31, 32, 37, 38, 39, 40, 71, 95, 133, 134, 135, 136, 138]
    july_ids = [9, 10, 23, 28, 60, 82, 87, 88, 89]
    pub_keys = {f'art-{n:03d}' for n in pub_ids}
    july_keys = {f'art-{n:03d}' for n in july_ids}
    if not pub_keys <= full.keys() or not july_keys <= full.keys() or act['versions'][1]['from'] <= '2024-05-01':
        raise SystemExit('ν. 5090/2024: staged article set or amendment date changed')
    lines = full['art-138']['text'].rstrip('\n').split('\n')
    for phrase in ['1. Με την επιφύλαξη των παρ. 2 και 3 η ισχύς του παρόντος αρχίζει από την 1η.5.2024.',
                   '2. Η ισχύς των άρθρων 9, 10, 23, 28, 60, 82, 87, 88 και 89 αρχίζει από την 1η.7.2024.',
                   '3. Η ισχύς των άρθρων 4, 31, 32, 37, 38, 39, 40, 71, 95, 133, 134, 135 και της περ. γ) του άρθρου 136 αρχίζει από τη δημοσίευση του παρόντος στην Εφημερίδα της Κυβερνήσεως.']:
        if lines.count(phrase) != 1:
            raise SystemExit(f'ν. 5090/2024 art. 138 clause changed: {phrase[:35]}')
    a136 = full['art-136']
    ll = a136['text'].rstrip('\n').split('\n')
    ia = [i for i, s in enumerate(ll) if s.startswith('α) τα άρθρα 100,')]
    ib = [i for i, s in enumerate(ll) if s.startswith('β) τα άρθρα 50')]
    ic = [i for i, s in enumerate(ll) if s.startswith('γ) το άρθρο 98')]
    if len(ia) != 1 or len(ib) != 1 or len(ic) != 1 or not (ia[0]+1 == ib[0] and ib[0]+1 == ic[0] and ic[0] == len(ll)-1):
        raise SystemExit('ν. 5090/2024 art. 136 items are not in the expected lines')
    pub136 = {**a136, 'text': '\n'.join(ll[:ia[0]] + [ll[ic[0]]]) + '\n'}
    v0['units'] = {k: (pub136 if k == 'art-136' else u) for k, u in full.items() if k in pub_keys}
    v0['note'] = 'ν. 5090/2024 as published in ΦΕΚ Α΄ 30/2024: the articles named in art. 138 par. 3 and art. 136 item γ are in force from publication.'
    may = {k: u for k, u in full.items() if k not in pub_keys and k not in july_keys}
    may['art-136'] = a136
    act['versions'].insert(1, {'from': '2024-05-01', 'source_url': v0['source_url'], 'sha256': v0['sha256'],
                               'changes': may, 'credits': {k: ['n-5090-2024'] for k in may},
                               'note': 'The remaining provisions of ν. 5090/2024 except arts. 9, 10, 23, 28, 60, 82, 87, 88 and 89 take effect on 1 May 2024 (art. 138 par. 1); art. 136 items α and β join item γ.'})
    act['versions'].append({'from': '2024-07-01', 'source_url': v0['source_url'], 'sha256': v0['sha256'],
                            'changes': {k: u for k, u in full.items() if k in july_keys},
                            'credits': {k: ['n-5090-2024'] for k in full if k in july_keys},
                            'note': 'Arts. 9, 10, 23, 28, 60, 82, 87, 88 and 89 of ν. 5090/2024 take effect on 1 July 2024 (art. 138 par. 2).'})
    part['sources'][-1]['retrieved'] = '2026-11-03'
    return part


PARTS.update({'99995-n5090': lambda: p5090()})

def main(argv: list[str]) -> None:
    for name in (argv or list(PARTS)):
        part = PARTS[name]()
        out = PS.write_part(name, part)
        print('\n'.join(LOG + DIFFS + SPLITS + LAYOUT))
        print(f'wrote {out}: {len(part["acts"][0]["versions"])} versions')


if __name__ == '__main__':
    main(sys.argv[1:])
