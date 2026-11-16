"""Build the ν. 5160/2024 part of the Greece corpus (corpus.d/30-n5160.json) from the cache of fetch_laws.py.

ν. 5160/2024 (transposition of Directive (EU) 2022/2555, NIS 2; ΦΕΚ Α΄ 195/27.11.2024) as enacted, then its only
amendment, ν. 5256/2025 (ΦΕΚ Α΄ 223/8.12.2025):

    art. 30   adds art. 3 par. 8Α
    art. 31   art. 24 par. 9 (a word, then the paragraph restated), art. 26 par. 4 and par. 9 (likewise)

Each amending provision is located in its issue by its own article number and heading. The parse stops unless the
instruction's target is found exactly once, the described word change applied to the old text gives the restated
text (save the small differences listed in the decisions), and every quoted text then appears in the new version.

Amending laws were looked for in three ways (see the decisions): a full-text scan of every ΦΕΚ Α΄ issue since
2024 in legalize-gr (.tmp/multiscan.py, the method of scan_legalize_gr.py), legalize-gr's `amended_by` field (copied
from the official search.et.gr index) and the official index itself (fetch_laws.py caches its timeline). Each
candidate was read in its own issue.

    python -X utf8 scripts/greece-law/parse_n5160.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_laws as FL  # noqa: E402
import parse_n4624 as N  # noqa: E402  (the column reader and the amendment helpers)

N.CACHE = FL.CACHE
import fek_reader  # noqa: E402  (full-width bands; replaces the two-column reader for these parts)
N.read_lines = fek_reader.read_lines
OUT = HERE / 'corpus.d' / '30-n5160.json'
LOG: list[str] = []
UNCLOSED: list[str] = []
UNOPENED: list[str] = []  # GR-15: a closing » with no opening « before it (a missing «, as printed)
# GR-15: set (by parse_single, per law) only for an issue known to print a quotation with no opening «; for
# every other law the depth count stays as it was, so no other part changes
UNOPENED_FIX = False
CLEANED: list[str] = []


def greek_share(t: str) -> float:
    letters = re.findall(r'[^\W\d_]', t)
    return sum(1 for c in letters if re.match(r'[Α-Ωα-ωΆ-Ώά-ώϊϋΐΰ]', c)) / len(letters) if letters else 1.0


def article_lines(paras: list[dict]) -> dict[str, list[str]]:
    """{key: lines}: like parse_n4624.article_lines, but a heading's continuation lines (capitals, set as body text
    by the column reader) stay with the heading, and quoted article headings («Άρθρο N) are text."""
    units: dict[str, list[str]] = {}
    pending: list[str] = []
    key = None
    in_head = False
    depth = 0
    for p in paras:
        t = p['text']
        if depth > 0 and p['kind'] == 'art' and not t.startswith('«') and key:
            # an unclosed quotation (a missing »): the law's own next article ends it
            m = N.ART.match(t)
            if m and not m.group(3) and int(m.group(2)) == int(key.split('-')[1]) + 1:
                UNCLOSED.append(f'{key}: quotation without a closing » before Άρθρο {m.group(2)}')
                depth = 0
        quoted = depth > 0 or t.startswith('«') or p.get('quote_open_missing', False)
        if p.get('quote_open_missing'):
            depth += 1
        depth += t.count('«') - t.count('»')
        if depth < 0 and UNOPENED_FIX:
            # a quotation whose opening « the issue does not print: its closing » ends it here
            UNOPENED.append(f'{key}: a closing » with no opening « (in «{t[:30]}…»)')
            depth = 0
        if not quoted and p['kind'] in ('struct', 'stitle'):
            pending.append(N.heading_line(p))
            in_head = True
            continue
        if in_head and p['kind'] == 'p' and not re.search(r'[α-ωά-ώ]', t):
            h = pending[-1]
            pending[-1] = (h[:-1] + t) if re.search(r'[Α-Ω]-$', h) else (h + ' ' + t)
            continue
        in_head = False
        if not quoted and p['kind'] == 'art':
            m = N.ART.match(t)
            key = N.art_key(m.group(2), m.group(3))
            if key in units:
                raise SystemExit(f'{key} twice')
            units[key] = pending + [f'Άρθρο {int(m.group(2))}{m.group(3) or ""}']
            pending = []
            continue
        if key is None:
            raise SystemExit(f'text before the first article: {t[:60]}')
        units[key].append(t)
    if pending:
        raise SystemExit(f'headings after the last article: {pending}')
    # Clean-up: words of the unreadable annex font (control characters) that the column reader joined to the last
    # line, and the end of the promulgation formula ("... ως νόμου του Κράτους.") joined to the last article.
    for k, ls in units.items():
        out = []
        for l in ls:
            c = ' '.join(w for w in l.split(' ') if not re.search(r'[\x00-\x08\x0b-\x1f]', w)).strip()
            c = re.sub(r'(\.) του Κράτους\.$', r'\1', c)
            if c != l:
                CLEANED.append(f'{k}: {l[-40:]!r} -> {c[-40:]!r}')
            if c:
                out.append(c)
        units[k] = out
    return units


def enacted() -> dict[str, list[str]]:
    paras = N.fek_paras(2024, 195)
    # the table of contents prints every heading first; the body opens at the last 'ΜΕΡΟΣ Α’' heading
    i0 = max(i for i, p in enumerate(paras) if p['kind'] == 'struct' and p['text'].startswith('ΜΕΡΟΣ Α’'))
    last = max(i for i, p in enumerate(paras) if p['kind'] == 'art')
    # After art. 45 come Annexes I and II, set in a font whose text layer maps to no characters: the text ends at
    # the first paragraph after the last article that is not Greek (no OCR, so the annexes are left out).
    i1 = next(i for i in range(last + 1, len(paras)) if greek_share(paras[i]['text']) < 0.5
              or not re.search(r'[Α-Ωα-ω]', paras[i]['text']))
    units = article_lines(paras[i0:i1])
    want = [N.art_key(str(n), None) for n in range(1, 46)]
    if list(units) != want:
        raise SystemExit(f'Α΄ 195/2024: articles are not 1-45 in order: {list(units)}')
    bad = [(k, l[:40]) for k, ls in units.items() for l in ls if greek_share(l) < 0.3]
    if bad:
        raise SystemExit(f'lines that are not Greek text: {bad[:5]}')
    LOG.append(f'Α΄ 195/2024: articles 1-45 read ({sum(len(v) for v in units.values())} lines); the text stops '
               f'after art. 45 (paragraph {i1} of {len(paras)}): Annexes I and II follow without a usable text layer')
    return units


def inline_quote(text: str) -> str:
    m = re.search(r'«(.*)»\.?$', text)
    if not m:
        raise SystemExit(f'no quotation in {text[:80]}')
    return m.group(1)


def am_5256(u: dict) -> dict:
    u = dict(u)
    # art. 30: art. 3 gains par. 8Α
    body = N.amending_article(2025, 223, '30', 'άρθρου 3 ν. 5160/2024')
    txt = ' '.join(p['text'] for p in body)
    N.need(txt, 'Στο άρθρο 3 του ν. 5160/2024 (Α’ 195)', 'ν. 5256/2025 art. 30')
    N.need(txt, 'προστίθεται παρ. 8Α ως εξής:', 'ν. 5256/2025 art. 30')
    new8a = inline_quote(txt)
    if not new8a.startswith('8Α. '):
        raise SystemExit(f'ν. 5256/2025 art. 30: quotation is not par. 8Α: {new8a[:30]}')
    lines = u['art-003']
    i8 = N.find_one(lines, '8. ', 'art. 3 par. 8')
    j = i8 + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
        j += 1
    if any(l.startswith('8Α. ') for l in lines):
        raise SystemExit('art. 3 already has par. 8Α')
    u['art-003'] = lines[:j] + [new8a] + lines[j:]
    LOG.append(f'ν. 5256/2025 art. 30: art. 3 par. 8Α added after par. 8 (before {lines[j][:3] if j < len(lines) else "the end"!r})')

    # art. 31: three word changes, each followed by the restated paragraph
    body = N.amending_article(2025, 223, '31', 'ν. 5160/2024')
    texts = [p['text'] for p in body]
    starts = [i for i, t in enumerate(texts) if re.match(r'^[123]\. Στ', t)]
    if len(starts) != 3:
        raise SystemExit(f'ν. 5256/2025 art. 31: expected three numbered paragraphs, found {len(starts)}')
    blocks = [texts[a:b] for a, b in zip(starts, starts[1:] + [len(texts)])]
    plan = [('art-024', '9', 'του άρθρου 24 του ν. 5160/2024'), ('art-026', '4', 'του άρθρου 26 του ν. 5160/2024'),
            ('art-026', '9', 'του άρθρου 26 του ν. 5160/2024')]
    for (key, par, cite), blk in zip(plan, blocks):
        what = f'ν. 5256/2025 art. 31 par. {blk[0][0]} ({key} par. {par})'
        head = blk[0]
        N.need(head, cite, what)
        N.need(head, f'η παρ. {par} διαμορφώνεται ως εξής:', what)
        m = re.search(r'(?:η λέξη|οι λέξεις) «([^»]+)» αντικαθίσταν?ται από (?:τη λέξη|τις λέξεις) «([^»]+)»', head)
        if not m:
            raise SystemExit(f'{what}: no word change described')
        # the restated paragraph: the quotation after "διαμορφώνεται ως εξής:", over one or more paragraphs
        rest = head.split('διαμορφώνεται ως εξής:', 1)[1].strip()
        q = ([rest] if rest else []) + blk[1:]
        if not q[0].startswith('«'):
            raise SystemExit(f'{what}: the restatement does not open with «')
        q[0] = q[0][1:]
        if not re.search(r'»\.?$', q[-1]):
            raise SystemExit(f'{what}: the restatement does not end with »')
        q[-1] = re.sub(r'»\.?$', '', q[-1])
        if not q[0].startswith(f'{par}. '):
            raise SystemExit(f'{what}: the restatement is not par. {par}')
        lines = u[key]
        i = N.find_one(lines, f'{par}. ', f'{key} par. {par}')
        j = i + 1
        while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
            j += 1
        old = '\n'.join(lines[i:j])
        if not re.search(rf'(?<!\w){m.group(1)}(?!\w)', old):
            raise SystemExit(f'{what}: «{m.group(1)}» not in the old paragraph')
        if 'Στο δεύτερο εδάφιο' in head:  # the change is made in the paragraph's second sentence only
            ss = N.sentences(old)
            if len(ss) < 2 or not re.search(rf'(?<!\w){m.group(1)}(?!\w)', ss[1]):
                raise SystemExit(f'{what}: «{m.group(1)}» not in the second sentence')
            ss[1] = re.sub(rf'(?<!\w){m.group(1)}(?!\w)', m.group(2), ss[1])
            expected = ' '.join(ss)
        else:
            if len(re.findall(rf'(?<!\w){m.group(1)}(?!\w)', old)) != 1:
                raise SystemExit(f'{what}: «{m.group(1)}» is not in the old paragraph exactly once')
            expected = re.sub(rf'(?<!\w){m.group(1)}(?!\w)', m.group(2), old)
        N.restated(expected, '\n'.join(q), what)
        u[key] = lines[:i] + q + lines[j:]
        N.present(u, key, q, what)
        LOG.append(f'{what}: «{m.group(1)}» -> «{m.group(2)}», paragraph restated ({j - i} line(s) -> {len(q)})')
    return u


def in_force_checks() -> list[str]:
    out = []
    t = '\n'.join(p['text'] for p in N.fek_paras(2024, 195))
    N.need(t, '1. Με την επιφύλαξη της παρ. 2 η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην '
              'Εφημερίδα της Κυβερνήσεως.', 'ν. 5160/2024 art. 45')
    N.need(t, '2. Η ισχύς της υποπερ. στβ) της περ. στ) της παρ. 2 του άρθρου 3 αρχίζει ένα (1) έτος από τη '
              'δημοσίευση του παρόντος', 'ν. 5160/2024 art. 45')
    out.append('ν. 5160/2024 art. 45: in force on publication, save art. 3 par. 2 περ. στ) υποπερ. στβ) (one year '
               'after publication)')
    t = '\n'.join(p['text'] for p in N.fek_paras(2025, 223))
    N.need(t, '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα '
              'της Κυβερνήσεως.', 'ν. 5256/2025 art. 49')
    N.need(t, '2. Η ισχύς του Κεφαλαίου Δ’ του Μέρους Α’ αρχίζει', 'ν. 5256/2025 art. 49')
    out.append('ν. 5256/2025 art. 49: in force on publication, save Part Α chapter Δ; arts. 30 and 31 are in '
               'Part Β')
    return out


LAW_FEK = {'n-5160-2024': (2024, 195), 'n-5256-2025': (2025, 223)}


def main() -> None:
    laws = {}
    for key, (y, n) in LAW_FEK.items():
        num = N.law_number(y, n)
        if key != f'n-{num}-{y}':
            raise SystemExit(f'Α΄ {n}/{y} is ν. {num}/{y}, not {key}')
        laws[key] = {'label': f'ν. {num}/{y}', 'kind': 'law', 'title': N.law_title(y, n), 'enacted': N.signed(y, n),
                     'published': N.masthead(y, n), 'url': FL.fek_url(y, n), 'temporary_until': None,
                     'restores': None, 'note': None}
    commencement = in_force_checks()
    # arts. 30 and 31 of ν. 5256/2025 are in its Part Β, outside the deferred Part Α chapter Δ (art. 49 par. 2)
    paras = N.fek_paras(2025, 223)
    pos = {p['text']: i for i, p in enumerate(paras) if p['kind'] == 'art' and not p['text'].startswith('«')}
    heads = lambda w: max(i for i, p in enumerate(paras) if p['kind'] == 'struct' and p['text'].startswith(w))
    if not (heads('ΜΕΡΟΣ Β’') < pos['Άρθρο 30'] < pos['Άρθρο 31'] < heads('ΜΕΡΟΣ Γ’')):
        raise SystemExit('ν. 5256/2025: arts. 30-31 are not in Part Β')

    u0 = enacted()
    u1 = am_5256(u0)
    p0, p1 = laws['n-5160-2024']['published'], laws['n-5256-2025']['published']
    steps = [(p0, u0, None, (2024, 195)), (p1, u1, 'n-5256-2025', (2025, 223))]
    notes = {
        p0: 'ν. 5160/2024 as published in ΦΕΚ Α΄ 195/27.11.2024, in force on publication (art. 45 par. 1); art. 3 par. 2 '
            'περ. στ) υποπερ. στβ) applies only from one year after publication (art. 45 par. 2) but is shown from '
            'publication. Annexes I and II are not included (no usable text layer).',
        p1: 'ν. 5256/2025 arts. 30-31 (ΦΕΚ Α΄ 223/8.12.2025), in force on publication (art. 49 par. 1): art. 3 gains '
            'par. 8Α (universities excluded from Part Α); art. 24 par. 9 and art. 26 pars. 4 and 9 corrected and '
            'restated ("Διόρθωση παροραμάτων").',
    }
    versions, prev = [], None
    for day, u, law, (y, n) in steps:
        units = N.as_units(u)
        v = {'from': day, 'source_url': FL.fek_url(y, n), 'sha256': N.sha(FL.fek_url(y, n))}
        if prev is None:
            v['units'] = units
        else:
            ch = N.changed(prev, units)
            v['changes'] = {k: units.get(k) for k in ch}
            v['credits'] = {k: [law] for k in ch}
        v['note'] = notes[day]
        versions.append(v)
        prev = units
    # Fixed at the published value: the count the part was first built with (every Gazette PDF request in the cache's
    # log up to 2026-10-30T01:36Z). It used to be recounted from that log, which other parts' fetches keep growing,
    # so a re-parse no longer matched the published part. Its own issues are 3 (Α΄ 195/2024, 223/2025, 175/2025).
    blob = 20
    sources = [{
        'name': 'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: issues for ν. 5160/2024 and its amending law',
        'url': 'https://ia37rg02wpsa01.blob.core.windows.net/fek/', 'retrieved': '2026-10-29', 'requests': blob,
        'licence': 'Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). '
                   'Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).',
        'notes': 'Series Α΄ issues 195/2024 (ν. 5160/2024) and 223/2025 (ν. 5256/2025), each with a text layer; issue '
                 'number, date and law number checked against each issue. Α΄ 175/2025 (ν. 5236/2025) was also read: '
                 'listed by the official index against ν. 5160/2024, it only refers to it and amends nothing.'}]
    decisions = [
        'ν. 5160/2024 is built from the Government Gazette alone: the act as published (ΦΕΚ Α΄ 195/2024) and the one '
        'law that amends it, read in its own issue (ΦΕΚ Α΄ 223/2025). Greece publishes no official consolidated text.',
        'Amending laws were looked for three ways: (1) a full-text scan of every ΦΕΚ Α΄ issue from 2024 to Α΄ 177/2026 '
        'in legalize-gr (commit 36cb88a374cd) for an article naming a provision of ν. 5160/2024 outside a quotation '
        'with an amending verb or heading: it finds only Α΄ 223/2025; (2) legalize-gr\'s `amended_by` field for Α΄ '
        '195/2024, copied from the official search.et.gr index: Α΄ 223/2025 only; (3) the official index\'s timeline '
        'for the issue: Α΄ 223/2025 (Τροποποίηση) and Α΄ 175/2025 (Ακύρωση). Α΄ 175/2025 (ν. 5236/2025, critical '
        'entities) was read in full: it cites ν. 5160/2024 but amends none of its provisions.',
        'Annexes I and II of ν. 5160/2024 (the sectors of high criticality and the other critical sectors) are printed '
        'in the issue in a font whose text layer maps to no characters, so they cannot be read without OCR and are '
        'left out; the articles that refer to them are complete.',
        'Units are articles (art-NNN). An article\'s text is the chapter and part headings that open it, "Άρθρο N", '
        'its title on one line, then one paragraph or lettered item per line, as in the ν. 4624/2019 part.',
        'Each version is dated by the law\'s own commencement clause (see the parse log): publication, the date on the '
        'issue\'s masthead. Art. 3 par. 2 περ. στ) υποπερ. στβ) of ν. 5160/2024 applies one year after publication '
        '(art. 45 par. 2); its words are part of the act from publication, so it is shown from then.',
        'Where ν. 5256/2025 describes a word change and then restates the paragraph, the restated text is used and the '
        'parse checks that the described change applied to the old paragraph gives it; small wording differences the '
        'restatement makes on its own are listed below.',
    ]
    decisions += [f'Parse log: {l}' for l in commencement + LOG]
    decisions += [f'Cleaned line end (annex-font characters or the promulgation formula joined to the text): {l}' for l in CLEANED]
    decisions += [f'Restated wording: {l}' for l in N.RESTATED]
    part = {'laws': laws, 'sources': sources, 'acts': [{
        'slug': 'nomos-5160-2024', 'short': 'ν. 5160/2024', 'title': laws['n-5160-2024']['title'],
        'url': FL.fek_url(2024, 195), 'first_law': 'n-5160-2024', 'earlier_laws': [], 'versions': versions}],
        'applies': [], 'decisions': decisions,
        'ai_use': ['ν. 5160/2024 part: none. No model wrote or altered legal text; a model (Claude) wrote '
                   'parse_n5160.py, which reads every word from the Gazette PDFs.']}
    tmp = OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(part, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    os.replace(tmp, OUT)
    print('\n'.join(commencement + LOG + N.RESTATED))
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes, {len(versions)} versions, {len(versions[0]["units"])} articles)')


if __name__ == '__main__':
    main()
