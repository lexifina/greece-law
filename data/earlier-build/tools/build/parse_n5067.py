"""Build the ν. 5067/2023 part of the Greece corpus (corpus.d/60-n5067.json) from the cache of fetch_laws.py.

ν. 5067/2023 (measures for Regulation (EU) 2021/784 on terrorist content online, and other provisions; ΦΕΚ Α΄
189/20.11.2023) as published, then its only amendment, ν. 5282/2026 (ΦΕΚ Α΄ 30/2026):

    art. 64   art. 22 par. 1, first sentence: «μερική» becomes «πλήρη»; the paragraph restated

The amending article is located in its issue by its own number and heading. The parse stops unless the instruction's
target is found exactly once, the described word change applied to the old paragraph gives the restated paragraph,
and the quotation then appears in the new version.

Amending laws were looked for in three ways (see the decisions): a full-text scan of every ΦΕΚ Α΄ issue from 2023 to
Α΄ 177/2026, in legalize-gr where it has the issue (.tmp/multiscan.py) and in the Gazette PDF where it does not
(scan_gap.py); and the official search.et.gr relation index for the issue (fetch_laws.py caches its timeline).

    python -X utf8 scripts/greece-law/parse_n5067.py
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
import parse_n4624 as N  # noqa: E402  (amendment helpers)
import parse_n5160 as P5  # noqa: E402  (full-width column reader, article lines)
import parse_single as PS  # noqa: E402  (the body of a single law's issue)

N.CACHE = FL.CACHE
OUT = HERE / 'corpus.d' / '60-n5067.json'
LOG: list[str] = []
LAW_FEK = {'n-5067-2023': (2023, 189), 'n-5282-2026': (2026, 30)}


def am_5282(u: dict) -> dict:
    u = dict(u)
    body = N.amending_article(2026, 30, '64', 'ν. 5067/2023')
    texts = [p['text'] for p in body]
    head = ' '.join(texts)
    what = 'ν. 5282/2026 art. 64 (art-022 par. 1)'
    N.need(head, 'Στο πρώτο εδάφιο της παρ. 1 του άρθρου 22 του ν. 5067/2023 (Α’ 189)', what)
    N.need(head, 'η παρ. 1 διαμορφώνεται ως εξής:', what)
    m = re.search(r'η λέξη «([^»]+)» αντικαθίσταται από τη λέξη «([^»]+)»', head)
    if not m:
        raise SystemExit(f'{what}: no word change described')
    first = next(i for i, t in enumerate(texts) if 'διαμορφώνεται ως εξής:' in t)
    rest = texts[first].split('διαμορφώνεται ως εξής:', 1)[1].strip()
    q = ([rest] if rest else []) + texts[first + 1:]
    if not q[0].startswith('«') or not re.search(r'»\.?$', q[-1]):
        raise SystemExit(f'{what}: the restatement is not one quotation')
    q[0] = q[0][1:]
    q[-1] = re.sub(r'»\.?$', '', q[-1])
    if not q[0].startswith('1. '):
        raise SystemExit(f'{what}: the restatement is not par. 1')
    lines = u['art-022']
    i = N.find_one(lines, '1. ', 'art-022 par. 1')
    j = i + 1
    while j < len(lines) and not re.match(r'^\d+[Α-Ω]?\. ', lines[j]):
        j += 1
    old = '\n'.join(lines[i:j])
    ss = N.sentences(old)
    if len(re.findall(rf'(?<!\w){m.group(1)}(?!\w)', ss[0])) != 1:
        raise SystemExit(f'{what}: «{m.group(1)}» is not in the first sentence exactly once')
    ss[0] = re.sub(rf'(?<!\w){m.group(1)}(?!\w)', m.group(2), ss[0])
    N.restated(' '.join(ss), '\n'.join(q), what)
    u['art-022'] = lines[:i] + q + lines[j:]
    N.present(u, 'art-022', q, what)
    LOG.append(f'{what}: «{m.group(1)}» -> «{m.group(2)}» in the first sentence, paragraph restated '
               f'({j - i} line(s) -> {len(q)})')
    return u


def in_force_checks() -> list[str]:
    t = '\n'.join(p['text'] for p in N.fek_paras(2023, 189))
    N.need(t, 'Η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην Εφημερίδα της Κυβερνήσεως.',
           'ν. 5067/2023 art. 27')
    t = '\n'.join(p['text'] for p in N.fek_paras(2026, 30))
    N.need(t, '1. Με την επιφύλαξη της παρ. 2, η ισχύς του παρόντος νόμου αρχίζει από τη δημοσίευσή του στην '
              'Εφημερίδα της Κυβερνήσεως, εκτός αν ορίζεται διαφορετικά στις επιμέρους διατάξεις του.',
           'ν. 5282/2026 art. 76')
    N.need(t, '2. Η ισχύς των άρθρων 36, 40 και 41 αρχίζει από την 1η.5.2026.', 'ν. 5282/2026 art. 76')
    return ['ν. 5067/2023 art. 27: in force on publication',
            'ν. 5282/2026 art. 76: in force on publication, save arts. 36, 40 and 41 (from 1 May 2026); art. 64 '
            'sets no date of its own']


def main() -> None:
    laws = {}
    for key, (y, n) in LAW_FEK.items():
        num = N.law_number(y, n)
        if key != f'n-{num}-{y}':
            raise SystemExit(f'Α΄ {n}/{y} is ν. {num}/{y}, not {key}')
        laws[key] = {'label': f'ν. {num}/{y}', 'kind': 'law', 'title': N.law_title(y, n), 'enacted': PS.signed(y, n),
                     'published': N.masthead(y, n), 'url': FL.fek_url(y, n), 'temporary_until': None,
                     'restores': None, 'note': None}
    commencement = in_force_checks()
    P5.UNCLOSED.clear()
    P5.CLEANED.clear()
    u0, _ = PS.body(2023, 189, 5067)
    want = [N.art_key(str(n), None) for n in range(1, 28)]
    if list(u0) != want:
        raise SystemExit(f'Α΄ 189/2023: articles are not 1-27 in order: {list(u0)}')
    u1 = am_5282(u0)
    p0, p1 = laws['n-5067-2023']['published'], laws['n-5282-2026']['published']
    notes = {
        p0: f'ν. 5067/2023 as published in ΦΕΚ Α΄ 189/{p0[:4]}, in force on publication (art. 27).',
        p1: f'ν. 5282/2026 art. 64 (ΦΕΚ Α΄ 30/{p1[:4]}), in force on publication (art. 76 par. 1): in art. 22 par. 1 '
            'the assisting prosecutor serves full time («πλήρη») instead of part time («μερική»); the paragraph is '
            'restated.',
    }
    versions, prev = [], None
    for day, u, law, (y, n) in [(p0, u0, None, (2023, 189)), (p1, u1, 'n-5282-2026', (2026, 30))]:
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
    sources = [{
        'name': 'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: issues for ν. 5067/2023 and its amending law',
        'url': 'https://ia37rg02wpsa01.blob.core.windows.net/fek/', 'retrieved': '2026-11-01', 'requests': 2,
        'licence': 'Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). '
                   'Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).',
        'notes': 'Series Α΄ issues 189/2023 (ν. 5067/2023) and 30/2026 (ν. 5282/2026), each with a text layer; issue '
                 'number, date and law number checked against each issue.'}]
    decisions = [
        'ν. 5067/2023 is built from the Government Gazette alone: the act as published (ΦΕΚ Α΄ 189/2023) and the one '
        'law that amends it, read in its own issue (ΦΕΚ Α΄ 30/2026). Greece publishes no official consolidated text.',
        'Amending laws were looked for three ways: (1) a full-text scan of every ΦΕΚ Α΄ issue from 2023 to Α΄ 177/2026 '
        'for an article naming a provision of ν. 5067/2023 outside a quotation with an amending verb or heading, in '
        'legalize-gr (commit 36cb88a374cd) and, for the 2026 issues it lacks (58-127, 143, 144, 147, 148, 174, 175), '
        'in the Gazette PDFs themselves: it finds only Α΄ 30/2026; (2) legalize-gr\'s `amended_by` field for Α΄ '
        '189/2023: Α΄ 30/2026; (3) the official search.et.gr index\'s timeline for the issue: Α΄ 30/2026 is the only '
        'Α΄ issue listed as amending it. Issues after Α΄ 177/2026 were not searched.',
        'Units are articles (art-NNN), as in the other Greek parts: the headings that open an article, "Άρθρο N", its '
        'title, then one paragraph or item per line. Signatures are not units.',
        'Each version is dated by the law\'s own commencement clause: publication, the date on the issue\'s masthead.',
        'Where ν. 5282/2026 describes a word change and then restates the paragraph, the restated text is used and the '
        'parse checks that the described change applied to the old paragraph gives it.',
        'Decision: ν. 5282/2026 art. 64 restates art. 22 par. 1 in full, and that restatement is the law\'s own text, '
        'so it governs. Besides the described change («μερική» becomes «πλήρη») it makes one more: «Ανωτάτου '
        'Δικαστικού Συμβουλίου» is spelled «Ανώτατου Δικαστικού Συμβουλίου». That spelling change is made by '
        'ν. 5282/2026 itself and is credited to it with the rest of the paragraph.',
    ]
    decisions += [f'Parse log: {l}' for l in commencement + LOG]
    decisions += [f'ν. 5067/2023: ' + '; '.join(P5.UNCLOSED)] if P5.UNCLOSED else []
    decisions += [f'Cleaned line end (the promulgation formula joined to the text): {l}' for l in P5.CLEANED]
    decisions += [f'Restated wording: {l}' for l in N.RESTATED]
    part = {'laws': laws, 'sources': sources, 'acts': [{
        'slug': 'nomos-5067-2023', 'short': 'ν. 5067/2023', 'title': laws['n-5067-2023']['title'],
        'url': FL.fek_url(2023, 189), 'first_law': 'n-5067-2023', 'earlier_laws': [], 'versions': versions}],
        'applies': [], 'decisions': decisions,
        'ai_use': ['ν. 5067/2023 part: none. No model wrote or altered legal text; a model (Claude) wrote '
                   'parse_n5067.py, which reads every word from the Gazette PDFs.']}
    out = Path(os.environ.get('GR_OUT', OUT))
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(part, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    os.replace(tmp, out)
    print('\n'.join(commencement + LOG + N.RESTATED))
    print(f'wrote {out} ({out.stat().st_size} bytes, {len(versions)} versions, {len(versions[0]["units"])} articles)')


if __name__ == '__main__':
    main()
