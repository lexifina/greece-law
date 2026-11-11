"""Single-version parts of the Greece corpus: laws that no later law has amended, each as published.

For each law in LAWS: the act as published in its ΦΕΚ Α΄ issue (articles only; the column reader of parse_n4624.py
and the heading handling of parse_n5160.py), dated by its own commencement article. A law is listed here only after
the amendment search found nothing (decisions): a full-text scan of every ΦΕΚ Α΄ issue in legalize-gr (to Α΄ 177/2026)
and the official search.et.gr relation index (legalize-gr's `amended_by` field) for the issue.

    python -X utf8 scripts/greece-law/parse_single.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_laws as FL  # noqa: E402
import parse_n4624 as N  # noqa: E402
import parse_n5160 as P5  # noqa: E402

N.CACHE = FL.CACHE

# part file, act slug, (year, issue), law number, short English description (README and decisions)
LAWS = [
    # 40-n5178, 41-n5188, 46-n5255 and 47-n5261 were amended in 2026: parse_multi.py builds them on single_part()
    ('42-n5202', 'nomos-5202-2025', (2025, 84), 5202, 'screening of foreign direct investment'),
    ('43-n5232', 'nomos-5232-2025', (2025, 163), 5232, 'offences for breaching EU restrictive measures'),
    ('44-n5214', 'nomos-5214-2025', (2025, 109), 5214, 'resilience: civil protection and the Fire Service'),
    ('45-n5220', 'nomos-5220-2025', (2025, 131), 5220, 'railway safety and supervision'),
    # ('48-n5176', 'nomos-5176-2025', (2025, 17), 5176, 'amateur and professional sport'),  # built by parse_multi.py (GR-7)
    ('49-n5226', 'nomos-5226-2025', (2025, 154), 5226, 'returns of third-country nationals'),
    # ('50-n5229', 'nomos-5229-2025', (2025, 158), 5229, 'social housing exchange, social rent and the three-child status'),  # built by parse_multi.py (GR-7)
    ('51-n5237', 'nomos-5237-2025', (2025, 176), 5237, 'vocational training academies'),
    ('52-n5258', 'nomos-5258-2025', (2025, 227), 5258, 'the port and ship security supervision unit'),
    # ('53-n5263', 'nomos-5263-2025', (2025, 238), 5263, 'the Greek AI factory'),  # built by parse_multi.py (GR-7)
    # ('54-n5253', 'nomos-5253-2025', (2025, 212), 5253, 'the organisation of the public broadcaster ERT S.A.'),  # built by parse_multi.py (GR-7)
    ('55-n5173', 'nomos-5173-2025', (2025, 11), 5173, 'the national trauma system'),
    ('56-n5058', 'nomos-5058-2023', (2023, 170), 5058, 'hired vehicles without drivers in road haulage'),
    ('57-n5066', 'nomos-5066-2023', (2023, 188), 5066, 'disclosure of income tax information by certain companies'),
    # GR-8 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8
    ('61-n5215', 'nomos-5215-2025', (2025, 116), 5215, 'biomethane, hydrogen and other energy provisions'),
    ('62-n5212', 'nomos-5212-2025', (2025, 105), 5212, 'publicity and transparency in the print and online press'),
    ('63-n5121', 'nomos-5121-2024', (2024, 106), 5121, 'tourist infrastructure and tourism education'),
    ('64-n5170', 'nomos-5170-2025', (2025, 6), 5170, 'specifications for short-term rental properties'),
    ('65-n5111', 'nomos-5111-2024', (2024, 76), 5111, 'consumer protection and other provisions'),
    # GR-9 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8
    ('68-n5023', 'nomos-5023-2023', (2023, 34), 5023, 'equal treatment regardless of disability or chronic illness and other provisions'),
    ('69-n5025', 'nomos-5025-2023', (2023, 42), 5025, 'the institutional framework of sport'),
    # GR-10 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8
    ('72-n5073', 'nomos-5073-2023', (2023, 204), 5073, 'measures against tax evasion and other urgent provisions'),
    # GR-11 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8
    ('76-n5128', 'nomos-5128-2024', (2024, 118), 5128, 'the digital education portal, career guidance in secondary education and other provisions'),
    # GR-13 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8
    ('81-n5061', 'nomos-5061-2023', (2023, 179), 5061, 'sustainable tourism development'),
    ('82-n4998', 'nomos-4998-2022', (2022, 221), 4998, 'the national ETIAS unit and other urgent provisions'),
    ('83-n4995', 'nomos-4995-2022', (2022, 216), 4995, 'criminal records of third-country nationals (ECRIS, Directive (EU) 2019/884) and other urgent provisions'),
    ('84-n4947', 'nomos-4947-2022', (2022, 124), 4947, 'fraud and counterfeiting of non-cash means of payment (Directive (EU) 2019/713)'),
    ('85-n4967', 'nomos-4967-2022', (2022, 171), 4967, 'contracts for digital content and digital services (Directive (EU) 2019/770)'),
    # GR-14 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8. ν.
    # 4800/2021 starts in two steps (SPLIT)
    ('86-n4800', 'nomos-4800-2021', (2021, 81), 4800, 'parent-child relations, other family law matters and other urgent provisions'),
    ('87-n5001', 'nomos-5001-2022', (2022, 227), 5001, 'selection and training of court employees at the National School of Judges and other Ministry of Justice provisions'),
    ('88-n4985', 'nomos-4985-2022', (2022, 203), 4985, 'reform of the Penitentiary Code and other provisions'),
    ('89-n4672', 'nomos-4672-2020', (2020, 48), 4672, 'permitted uses of protected works for persons who are blind, visually impaired or otherwise print-disabled (Directive (EU) 2017/1564)'),
    ('90-n5252', 'nomos-5252-2025', (2025, 210), 5252, 'the Office of the Greek Presidency of the Council of the EU (second half of 2027)'),
    ('91-n5044', 'nomos-5044-2023', (2023, 135), 5044, 'lifting restrictions on registration in the special electoral rolls of voters abroad'),
    # GR-15 (2026-11-02): scanned in legalize-gr, the 2026 gap issues and a fresh official index; see NOTES_8. ν.
    # 4937/2022 (92) and ν. 4703/2020 (95) are built by parse_multi.py
    ('93-n4666', 'nomos-4666-2020', (2020, 35), 4666, 'amendment of ν. 4251/2014 transposing Directive (EU) 2016/801 on third-country nationals entering for research, studies, training, voluntary service, pupil exchange or au pairing'),
    ('94-n4996', 'nomos-4996-2022', (2022, 218), 4996, 'copyright and related rights in certain online transmissions of broadcasters and retransmissions of television and radio programmes (Directive (EU) 2019/789)'),
    ('96-n4767', 'nomos-4767-2021', (2021, 9), 4767, 'the breadth of the territorial sea in the Ionian Sea and around the Ionian Islands as far as Cape Tainaron'),
    # GR-15: dropped in GR-14 (reader), read now: the missing opening « (parse_n5160.UNOPENED) and Latin annex lines
    ('98-n4960', 'nomos-4960-2022', (2022, 145), 4960, 'the national guardianship system for unaccompanied minors, their accommodation and other provisions'),
    ('99-n4924', 'nomos-4924-2022', (2022, 80), 4924, 'technical specifications for alarm and signal weapons (Commission Implementing Directive (EU) 2019/69)'),
    # GR-16 (2026-11-02): scanned in legalize-gr (every mention), the 2026 gap issues and a fresh official index; see
    # NOTES_8. ν. 4955/2022 (993), 4713/2020 (994) and 5123/2024 (998) are built by parse_multi.py
    ('995-n4734', 'nomos-4734-2020', (2020, 196), 4734, 'amendment of ν. 4557/2018 on preventing money laundering and terrorist financing (Directive (EU) 2018/843 and art. 3 of Directive (EU) 2019/2177) and other provisions'),
    ('996-n5053', 'nomos-5053-2023', (2023, 158), 5053, 'strengthening work: transparent and predictable working conditions (Directive (EU) 2019/1152), simpler digital procedures and the digital work card, and the Ministry of Labour and the Labour Inspectorate'),
    ('997-n5089', 'nomos-5089-2024', (2024, 27), 5089, 'equality in civil marriage, amendment of the Civil Code and other provisions'),
    ('999-n4654', 'nomos-4654-2020', (2020, 15), 4654, 'the election of Members of Parliament (amendments to the electoral law, presidential decree 26/2012)'),
]
# the day each issue was fetched (parts 40-47: 2026-10-30)
RETRIEVED = {5226: '2026-11-01', 5237: '2026-11-01', 5258: '2026-11-01', 5173: '2026-11-01', 5058: '2026-11-01',
             5066: '2026-11-01', 5215: '2026-11-02', 5212: '2026-11-02', 5121: '2026-11-02', 5170: '2026-11-02',
             5111: '2026-11-02', 5113: '2026-11-02', 5216: '2026-11-02',
             5023: '2026-11-02', 5025: '2026-11-02', 5142: '2026-11-02', 5131: '2026-11-02',
             5073: '2026-11-02', 5029: '2026-11-02', 5075: '2026-11-02',
             5130: '2026-11-02', 5057: '2026-11-02', 5128: '2026-11-02', 5179: '2026-11-02', 5218: '2026-11-02',
             5061: '2026-11-02', 4998: '2026-11-02', 4995: '2026-11-02', 4947: '2026-11-02', 4967: '2026-11-02',
             4800: '2026-11-02', 5001: '2026-11-02', 4985: '2026-11-02', 4672: '2026-11-02', 5252: '2026-11-02',
             5044: '2026-11-02', 4937: '2026-11-02', 4666: '2026-11-02', 4996: '2026-11-02', 4703: '2026-11-02',
             4767: '2026-11-02', 4960: '2026-11-02', 4924: '2026-11-02', 5122: '2026-11-02', 5063: '2026-11-02',
             4780: '2026-11-02', 4955: '2026-11-02', 4713: '2026-11-02', 4734: '2026-11-02', 5053: '2026-11-02',
             5089: '2026-11-02', 5123: '2026-11-02', 4654: '2026-11-02', 4965: '2026-11-02', 4792: '2026-11-02',
             5195: '2026-11-02', 5027: '2026-11-02', 5090: '2026-11-02', 5036: '2026-11-02'}
# parts from 2026-11-01 on: the 2026 issues legalize-gr lacks were read too, and the official index fetched afresh
GAP_NOTE = ('legalize-gr lacks the ΦΕΚ Α΄ issues 58-127, 143, 144, 147, 148, 174 and 175 of 2026; those were read in '
            'the Gazette PDFs themselves (scan_gap.py) and every mention of the law in them checked by hand: none '
            'amends it. The timeline of the official index for the issue, fetched on 2026-11-01, lists no Α΄ issue as '
            'amending it. Issues after Α΄ 177/2026 were not searched.')
# parts from GR-8 on: the index was fetched on 2026-11-02, and some laws need their own account of the search
GAP_NOTE_8 = GAP_NOTE.replace('fetched on 2026-11-01', 'fetched on 2026-11-02')
NOTES_8 = {
    5215: ('Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2025 to Α΄ 177/2026 '
           'in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a quotation with '
           'an amending verb or heading; the ΦΕΚ Α΄ issues of 2026 that legalize-gr lacks (58-127, 143, 144, 147, 148, '
           '174 and 175), read in the Gazette PDFs themselves; and the timeline of the official search.et.gr index for '
           'the issue, fetched on 2026-11-02. The scan finds only Α΄ 231/2025 (ν. 5261/2025), which is also the one Α΄ '
           'issue the index lists against it ("Τροποποίηση"): read in its own issue, its art. 46 only refers to art. 25 '
           'of ν. 5215/2025 (its definition of low-carbon hydrogen) in two definitions it gives ν. 4001/2011. In the '
           '2026 issues read in the PDFs, every mention was read by hand: Α΄ 67/2026 art. 4 refers to the same '
           'definition; Α΄ 88/2026 (a codification) names arts. 56 and 63 of ν. 5215/2025, which amended other laws, '
           'only in its source notes and correspondence table. None amends ν. 5215/2025. Issues after Α΄ 177/2026 '
           'were searched only through the official index.'),
    5023: ('Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2023 to Α΄ 177/2026 '
           'in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a quotation with '
           'an amending verb or heading; the ΦΕΚ Α΄ issues of 2026 that legalize-gr lacks (58-127, 143, 144, 147, 148, '
           '174 and 175), read in the Gazette PDFs themselves; and the timeline of the official search.et.gr index for '
           'the issue, fetched on 2026-11-02, which lists no Α΄ issue against it. '
           'The scan finds only Α΄ 121/2025, a presidential decree codifying the law on equal treatment, which names art. 3 '
           'of ν. 5023/2023 (an amendment of ν. 4443/2016) only in its tables of sources and correspondence. The 2026 '
           'issues read in the PDFs do not mention it. None amends ν. 5023/2023. Issues after Α΄ 177/2026 were searched '
           'only through the official index.'),
    5025: ('Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2023 to Α΄ 177/2026 '
           'in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a quotation with '
           'an amending verb or heading; the ΦΕΚ Α΄ issues of 2026 that legalize-gr lacks (58-127, 143, 144, 147, 148, '
           '174 and 175), read in the Gazette PDFs themselves; and the timeline of the official search.et.gr index for '
           'the issue, fetched on 2026-11-02, which lists no Α΄ issue against it. '
           'The scan finds only Α΄ 118/2024 (ν. 5128/2024), whose art. 83 replaces par. 9 of art. 34 of ν. 2725/1999 and '
           'names art. 11 of ν. 5025/2023 (an earlier amendment of that article) for applications made under it: the '
           'text of ν. 5025/2023 itself is not changed. In the 2026 issues read in the PDFs, the one mention, Α΄ 64/2026 '
           'art. 115, dates the start of articles of ν. 4442/2016 by the publication of ν. 5025/2023. None amends ν. '
           '5025/2023. Issues after Α΄ 177/2026 were searched only through the official index.'),
    5073: ('Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2023 to Α΄ 177/2026 '
           'in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a quotation with '
           'an amending verb or heading; the ΦΕΚ Α΄ issues of 2026 that legalize-gr lacks (58-127, 143, 144, 147, 148, '
           '174 and 175), read in the Gazette PDFs themselves; and the timeline of the official search.et.gr index for '
           'the issue, fetched on 2026-11-02, which lists no Α΄ issue against it. '
           'The scan finds only Α΄ 162/2024, a presidential decree codifying the VAT Code, which names arts. 29 and 53 '
           'of ν. 5073/2023 (amendments of ν. 2859/2000) only in its notes of sources and its correspondence tables. '
           'The 2026 issues read in the PDFs do not mention it. None amends ν. 5073/2023. Issues after Α΄ 177/2026 '
           'were searched only through the official index. Its art. 59 starts some provisions on other days (arts. 5, '
           '9 and 27-29 on 1 January 2024, art. 57 on 1 December 2023, art. 55 par. 2 retroactively from 28 February '
           '2023, others by tax year or transaction); as for every law here, the text is shown from publication.'),
    5128: ('Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue from 2024 to Α΄ 177/2026 '
           'in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a quotation with '
           'an amending verb or heading; the ΦΕΚ Α΄ issues of 2026 that legalize-gr lacks (58-127, 143, 144, 147, 148, '
           '174 and 175), read in the Gazette PDFs themselves; and the timeline of the official search.et.gr index for '
           'the issue, fetched on 2026-11-02, whose 100 rows show no Α΄ issue. '
           'The scan finds only Α΄ 41/2025 and Α΄ 115/2025, presidential decrees that cite art. 61 of ν. 5128/2024 as '
           'the provision empowering them; neither changes its text. The 2026 issues read in the PDFs do not mention '
           'it. None amends ν. 5128/2024. Issues after Α΄ 177/2026 were searched only through the official index. Its '
           'art. 125 starts some provisions on other days (art. 25 from the 2025-2026 school year, art. 44 par. 1 from '
           'the 2024-2025 academic year, art. 93 on 1 July 2024, and by its par. 4 art. 56 from 4 September 2023 for '
           'the municipalities of Thessaly in a state of emergency); as for every law here, the text is shown from '
           'publication.'),
}


def _note13(law: int, year: int, index: str, found: str) -> str:
    """GR-13: the account of the three-way search for a single-version law."""
    return (f'Amending laws were looked for in three ways: a full-text scan of every ΦΕΚ Α΄ issue from {year} to Α΄ '
            '177/2026 in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a '
            'quotation with an amending verb or heading; the ΦΕΚ Α΄ issues of 2026 that legalize-gr lacks (58-127, 143, '
            '144, 147, 148, 174 and 175), read in the Gazette PDFs themselves, every mention read by hand; and the '
            f'timeline of the official search.et.gr index for the issue, fetched on 2026-11-02, {index}. {found} None '
            f'amends ν. {law}/{year}. Issues after Α΄ 177/2026 were searched only through the official index.')


NOTES_8.update({
    5061: _note13(5061, 2023, 'whose only Α΄ row is ΦΕΚ Α΄ 64/2026 (its Β΄ rows are ministerial decisions)',
                  'The scan finds no amending article. ν. 5297/2026 (ΦΕΚ Α΄ 64/2026) art. 248 par. 2 amends art. 45Α of '
                  'ν. 4933/2022, which ν. 5061/2023 had added to that law; it changes that law, and the words of ν. '
                  '5061/2023 itself stay as published.'),
    4998: _note13(4998, 2022, 'which lists no later issue', 'The scan finds no article that names it.'),
    4995: _note13(4995, 2022, 'whose later rows are Β΄ and Γ΄ issues (a ministerial decision and appointments, which do '
                  'not amend a statute)', 'The scan finds no article that names it.'),
    4947: _note13(4947, 2022, 'whose only later row is a Β΄ issue (a ministerial decision)',
                  'The scan finds no article that names it.'),
    4967: _note13(4967, 2022, 'whose only later row is a Β΄ issue (a ministerial decision)',
                  'The scan finds no amending article; ΦΕΚ Α΄ 108/2026 art. 81 names it only in a definition.'),
    4800: _note13(4800, 2021, 'whose only later rows are Γ΄ issues (appointments, which do not amend a statute)',
                  'The scan finds one mention: ΦΕΚ Α΄ 114/2022 cites a provision of another law "as supplemented by art. '
                  '23 of ν. 4800/2021", a reference only.'),
    # GR-14 (2026-11-02)
    5001: _note13(5001, 2022, 'whose later rows are Β΄ and Γ΄ issues (ministerial decisions and appointments) and one '
                  'issue of the Α.Σ.Ε.Π. series (a staff selection notice), none of which amends a statute',
                  'The scan finds no article that names it.'),
    4985: _note13(4985, 2022, 'whose later rows are Β΄ issues (ministerial decisions) and one Υ.Ο.Δ.Δ. issue (an '
                  'appointment), none of which amends a statute',
                  'The scan finds four mentions, in ΦΕΚ Α΄ 25/2023, 41/2023, 137/2023 and 164/2023: each grants further '
                  'sums or extends the time for commitments of the defence credits approved by arts. 86 and 87 of ν. '
                  '4985/2022, by adding to the other laws those articles amended (ν. 4361/2016 art. 32 and ν. 4258/2014 '
                  'art. 26); the words of ν. 4985/2022 itself stay as published.'),
    4672: _note13(4672, 2020, 'which lists no later issue',
                  'The scan finds one mention: ΦΕΚ Α΄ 215/2022 applies "subject to ν. 4672/2020", a reference only.'),
    5252: _note13(5252, 2025, 'which lists no later issue acting on it', 'The scan finds no article that names it.'),
    5044: _note13(5044, 2023, 'which lists no later issue acting on it',
                  'The scan finds one mention: ΦΕΚ Α΄ 170/2025 names it, a reference only.'),
    # GR-15 (2026-11-02)
    4666: _note13(4666, 2020, 'whose only later Α΄ row is ΦΕΚ Α΄ 17/2026 ("Αντικατάσταση")',
                  'The scan finds three mentions, each read by hand: ΦΕΚ Α΄ 96/2020 (ν. 4686/2020) art. 32 names it '
                  'inside the words it adds to art. 7 of ν. 4251/2014; ΦΕΚ Α΄ 81/2023 (the Migration Code, ν. '
                  '5038/2023) art. 9 names it in its list of residence permits; and ΦΕΚ Α΄ 17/2026 (ν. 5275/2026) art. '
                  '10, the issue the index lists, replaces in art. 9 of that Code the words that name ν. 4666/2020. '
                  'These are references only.'),
    4996: _note13(4996, 2022, 'whose only later Α΄ row is ΦΕΚ Α΄ 108/2026 ("Ακύρωση"; its Β΄ row is a ministerial '
                  'decision)',
                  'The scan finds no article in legalize-gr that names it. In the 2026 issues read in the PDFs, ΦΕΚ Α΄ '
                  '108/2026 (ν. 5317/2026, the issue the index lists) names it twice in art. 97, in the article it adds '
                  'to ν. 2251/1994 on the obligation to repair, a reference only; no article of that law repeals or '
                  'changes a provision of ν. 4996/2022.'),
    4767: _note13(4767, 2021, 'which lists no later issue acting on it',
                  'The scan finds one mention: presidential decree 33/2025 (ΦΕΚ Α΄ 59/2025) art. 1 names it for the '
                  'breadth of the territorial sea, a reference only.'),
    4960: _note13(4960, 2022, 'whose later rows are Β΄ issues (ministerial decisions), which do not amend a statute',
                  'The scan finds five mentions, each read by hand: ν. 5003/2022 art. 139 (ΦΕΚ Α΄ 230/2022), restated by '
                  'ν. 5043/2023 art. 65 (ΦΕΚ Α΄ 91/2023), extends how long art. 41 pars. 2 and 3 keep earlier '
                  'prosecutors\' orders in force, without changing its words; presidential decree 20/2023 (ΦΕΚ Α΄ '
                  '43/2023) and ν. 5187/2025 arts. 14 and 28 (ΦΕΚ Α΄ 48/2025) refer to it only.'),
    4924: _note13(4924, 2022, 'which lists no later issue', 'The scan finds no article that names it.'),
    # GR-16 (2026-11-02)
    4734: _note13(4734, 2020, 'whose only later Α΄ row is ΦΕΚ Α΄ 200/2020 (its Β΄ rows are ministerial decisions, which '
                  'do not amend a statute)',
                  'The scan finds mentions in thirteen issues, each read by hand: ν. 4736/2020 art. 27 (ΦΕΚ Α΄ 200/2020, '
                  'the issue the index lists) declares the true meaning of art. 4 item ιη) of ν. 4557/2018 as amended '
                  'by art. 3 of ν. 4734/2020, without changing the words of either; and ΦΕΚ Α΄ 256/2020, 68/2021, '
                  '124/2021, 215/2021, 23/2022, 94/2022, 150/2022, 203/2022, 25/2023, 41/2023, 137/2023 and 164/2023 '
                  'each grant further sums, or extend the time for commitments, for the defence credits approved by '
                  'arts. 37 and 38 of ν. 4734/2020, by adding to the laws those articles amended (ν. 4361/2016 art. 32 '
                  'and ν. 4258/2014 art. 26); the words of ν. 4734/2020 itself stay as published.') +
    ' Its commencement article (art. 39) starts par. 5 of art. 12 of ν. 4557/2018, as art. 7 amends it, on 10 July '
    '2020, before the law was published (8 October 2020). As for every law in this corpus, the text is shown from '
    'publication; that earlier day, 2020-07-10, is recorded here and not as a version.',
    5053: _note13(5053, 2023, 'whose only later Α΄ row is ΦΕΚ Α΄ 178/2025 (its Β΄ and Γ΄ rows are ministerial decisions '
                  'and appointments, which do not amend a statute)',
                  'The scan finds mentions in two issues, each read by hand. Presidential decree 62/2025 (ΦΕΚ Α΄ '
                  '121/2025), the Labour Code, codifies provisions of ν. 5053/2023 among its own articles and repeals '
                  'only presidential decree 80/2022, so it changes no words of ν. 5053/2023. ν. 5239/2025 (ΦΕΚ Α΄ '
                  '178/2025, the issue the index lists) arts. 4, 5 and 20 amend arts. 73, 75, 190 and 578 of that Code, '
                  'the articles "with which" arts. 6, 5, 10 and 21 of ν. 5053/2023 were codified: they change the '
                  'Code\'s words, and the words of ν. 5053/2023 itself stay as published.'),
    5089: _note13(5089, 2024, 'whose only later row is ΦΕΚ Α΄ 121/2025 (presidential decree 62/2025, the Labour Code)',
                  'The scan finds mentions only in that decree, which codifies provisions of ν. 5089/2024 (arts. 6, 7, '
                  '8, 9 and 12) among the Labour Code\'s own articles and repeals only presidential decree 80/2022: it '
                  'changes no words of ν. 5089/2024.'),
    4654: _note13(4654, 2020, 'which lists no later issue acting on it', 'The scan finds no article that names it.') +
    ' Its commencement article (art. 3) starts it on publication "subject to art. 54 of the Constitution", whose par. 1 '
    'makes a law on the electoral system apply from the elections after next unless it says otherwise by a '
    'two-thirds majority. That is a condition on when it applies, not on its words: as for the Constitution here, it '
    'is recorded in the text and here, not in the dates.',
})
# whole lines in Latin capitals that are table headers as printed (not a font fault): the not-Greek-text guard lets
# them through, they stay as printed, and the part's decisions name them (GR-11: ν. 5179/2025 art. 73)
LATIN_OK = {'A/A'}
LATIN_KEPT: list[tuple[str, str]] = []
LATIN_ANNEX: list[str] = []  # GR-15: Annex lines printed in Latin script, kept as printed
# GR-15: laws whose issue prints a quotation with no opening « (parse_n5160.UNOPENED_FIX): ν. 4960/2022 art. 17
# («Άρθρο 66 ΙΑ»). Per law, since the general quotation count relies on the old behaviour elsewhere
UNOPENED_LAWS = {4960}
# GR-18: issues whose commencement article is set under both columns of the last page, just above the promulgation
# formula, in the left column's place: (year, issue) -> (page index, its first words). The reader puts it after the
# right column on that page only (fek_reader.TAIL_PAGES); no other issue is read differently.
TAIL_FIX = {(2020, 72): (25, 'Άρθρο 65'), (2020, 197): (31, 'ΚΕΦΑΛΑΙΟ Η’')}
for (_y, _n), (_p, _w) in TAIL_FIX.items():
    P5.fek_reader.TAIL_PAGES[N.cpath(FL.fek_url(_y, _n)).name] = {_p: _w}
# GR-18: a commencement article that starts the whole law on a stated day before its publication (cross-country rule
# for retroactive starts): the law is dated from its publication day and the stated day goes in a decision line.
# GR-18: laws whose issue joins the whole promulgation formula to the last line of the last article (ν. 5134/2024):
# the sentence is cut off that line, for these laws only, and the decisions say so
PROMULGATION = ' Παραγγέλλομε τη δημοσίευση του παρόντος στην Εφημερίδα της Κυβερνήσεως και την εκτέλεσή του ως νόμου του Κράτους.'
PROMULGATION_JOINED = {5134}
# GR-18: laws whose commencement article starts some Parts on a later day and the rest on publication in a later
# paragraph (law -> the words of that paragraph); parse_multi.py splits them (split_5134)
CLAUSE_LATER_PAR = {5134: '2. Η ισχύς των λοιπών διατάξεων του παρόντος αρχίζει από τη δημοσίευσή του στην Εφημερίδα της '
                          'Κυβερνήσεως, εκτός αν άλλως ορίζεται σε επιμέρους διατάξεις.',
                    5090: '3. Η ισχύς των άρθρων 4, 31, 32, 37, 38, 39, 40, 71, 95, 133, 134, 135 και της περ. γ) του άρθρου 136 αρχίζει από τη δημοσίευση του παρόντος στην Εφημερίδα της Κυβερνήσεως.'}
RETRO_RE = re.compile(r'^(\d+\. )?[Ηη] ισχύς του παρόντος (νόμου )?αρχίζει από (\d{1,2})\.(\d{1,2})\.(\d{4})\.$')
SCAN_NOTE = ('Amending laws were looked for in two ways: a full-text scan of every ΦΕΚ Α΄ issue from the law\'s year to '
             'Α΄ 177/2026 in legalize-gr (commit 36cb88a374cd), for an article naming a provision of the law outside a '
             'quotation with an amending verb or heading, and the official search.et.gr relation index for the issue '
             '(legalize-gr\'s `amended_by` field, which lists no Α΄ issue). Neither finds any.')


def body(year: int, num: int, law: int) -> tuple[dict, int]:
    paras = N.fek_paras(year, num)
    first = paras[0]['text']
    if not re.match(rf'^ΝΟΜΟΣ ΥΠ’ ΑΡΙΘΜ\. {law}\b', first):
        raise SystemExit(f'Α΄ {num}/{year}: first line is not ν. {law}: {first[:60]}')
    starts = [i for i, p in enumerate(paras) if p['kind'] == 'struct' and re.match(r'^(ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ) Α’', p['text'])]
    arts = [i for i, p in enumerate(paras) if p['kind'] == 'art' and p['text'] == 'Άρθρο 1']
    i0 = max(starts) if starts else None
    if i0 is not None and paras[i0]['text'].startswith('ΚΕΦΑΛΑΙΟ'):
        # a Part heading (and its title lines) set just before the first Chapter opens the body too
        for j in range(i0 - 1, max(i0 - 4, 0), -1):
            if paras[j]['kind'] not in ('struct', 'stitle'):
                break
            if re.match(r'^ΜΕΡΟΣ Α’', paras[j]['text']):
                i0 = j
                break
    if i0 is None or (arts and arts[-1] < i0):
        # the headings that open the body: back from the body's "Άρθρο 1" over heading lines (no lowercase)
        i0 = arts[-1]
        while i0 > 1:
            prev = paras[i0 - 1]
            if prev['kind'] == 'art' or re.match(r'^(Άρθρο|ΠΑΡΑΡΤΗΜΑ)', prev['text']) or not (
                    prev['kind'] in ('struct', 'stitle') or not re.search(r'[α-ωά-ώ]', prev['text'])):
                break
            i0 -= 1
            if re.match(r'^ΜΕΡΟΣ Α’', prev['text']):
                break
        while i0 < arts[-1] and paras[i0]['kind'] not in ('struct',):
            i0 += 1  # start at a ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ line, never inside the table of contents
    last = max(i for i, p in enumerate(paras) if p['kind'] == 'art' and not p['text'].startswith('«'))
    end = next((i for i in range(last + 1, len(paras))
                if re.match(r'^(Παραγγέλλομε τη δημοσίευση|Αθήνα, \d|ΠΑΡΑΡΤΗΜΑ\b)', paras[i]['text'])), None)
    if end is None:
        end = next(i for i in range(last + 1, len(paras)) if P5.greek_share(paras[i]['text']) < 0.5
                   or not re.search(r'[Α-Ωα-ω]', paras[i]['text']))
    if law == 5036:
        # In art. 67, the restated art. 84 of ν. 4916/2022 has no opening « in the
        # text layer. Mark its heading as quoted without changing the Gazette words.
        target = [i for i in range(i0 + 1, end) if paras[i]['kind'] == 'art' and
                  paras[i]['text'] == 'Άρθρο 84' and
                  'Το άρθρο 84 του ν. 4916/2022' in paras[i - 1]['text'] and
                  'διαμορφώνεται ως εξής:' in paras[i - 1]['text']]
        if len(target) != 1:
            raise SystemExit(f'ν. 5036/2023: expected one embedded art. 84, got {target}')
        paras = list(paras)
        paras[target[0]] = {**paras[target[0]], 'quote_open_missing': True}
    units = P5.article_lines(paras[i0:end])
    nums = [k for k in units]
    if nums[0] != 'art-001':
        raise SystemExit(f'Α΄ {num}/{year}: first article is {nums[0]}')
    bad = [(k, l[:40]) for k, ls in units.items() for l in ls if P5.greek_share(l) < 0.3 and l not in LATIN_OK]
    LATIN_KEPT.extend(sorted({(k, l) for k, ls in units.items() for l in ls if l in LATIN_OK}))
    if bad:
        raise SystemExit(f'Α΄ {num}/{year}: lines that are not Greek text: {bad[:5]}')
    return units, end


NL = chr(10)
GAP = '[Η πηγή δεν δίνει αναγνώσιμο κείμενο για αυτή τη γραμμή.]'
NEW_PARA = re.compile(r'^(\d+\.\s|[α-ω]{1,2}\)\s|[ivx]+\)\s|ΠΑΡΑΡΤΗΜΑ|(Πρώτο|Δεύτερο|Τρίτο|Τέταρτο|Πέμπτο) μέρος)')
# GR-17: issues whose Annex sets single glyphs in a font that is not embedded (MinionPro-Regular, Identity-H), so the
# text layer gives the glyph id as a control character: ids 1 and 14 are the space and the hyphen of the font's
# standard (ISOAdobe) character set. Read as such for these issues only, so no other part changes.
ANNEX_CIDS = {(2023, 54): {chr(1): ' ', chr(14): '-'}}


def annex(year: int, num: int, last: int) -> tuple[dict, list[str]]:
    """The issue's ΠΑΡΑΡΤΗΜΑ (after the last article, before the promulgation formula) as one unit, read from the
    PDF's own text layer line by line (these pages are set in one column). A line in a font whose text layer maps to
    other characters is replaced by a marker saying so (no OCR)."""
    import fitz
    doc = fitz.open(N.cpath(FL.fek_url(year, num)))
    lines, on, done, seen = [], False, False, 0
    cids, mapped = ANNEX_CIDS.get((year, num), {}), collections.Counter()
    for page in doc:
        for l in page.get_text().split(NL):
            if cids and on:
                for k, v in cids.items():
                    mapped[k] += l.count(k)
                    l = l.replace(k, v)
                l = re.sub(r' {2,}', ' ', l).strip()
            t = N.norm_line(l.replace(chr(3), ' '))
            # the running head; GR-15: some issues print its Δ as the increment sign ∆ (U+2206)
            if not t or re.match(r'^(ΕΦΗΜΕΡΙ[Δ∆]Α [TΤ]?ΗΣ ΚΥΒΕΡΝΗΣΕΩΣ|Τεύχος [AΑ]’ |\d{1,5}$)', t):
                continue
            if re.match(rf'^Άρθρο {last}$', t):
                seen += 1
            if t.startswith('ΠΑΡΑΡΤΗΜΑ') and not on and seen >= 1:
                on = True
            elif on and t.startswith('Παραγγέλλομε τη δημοσίευση'):
                done = True
                break
            if on:
                lines.append((l, t))
        if done:
            break
    if not lines:
        return {}, []
    if sum(mapped.values()):
        TABLE_NOTES.append(f'ΦΕΚ Α΄ {num}/{year}: the Annex sets {mapped[chr(1)]} space(s) and {mapped[chr(14)]} '
                           'hyphen(s) in a font that the issue does not embed (MinionPro-Regular), so its text layer '
                           'gives glyph ids 1 and 14 instead of characters; in that font\'s standard (ISOAdobe) '
                           'character set they are the space and the hyphen, and are read as such.')
    gaps, paras, alone = [], [], set()
    for raw, t in lines:
        if P5.greek_share(t) < 0.3:
            # GR-15: only a line whose text layer holds control characters, or letters of neither Greek nor Latin
            # script, is an unmapped font; a line printed in Latin script (names, terms) is kept as printed, on a
            # line of its own (where the marker stood before)
            if re.search(r'[\x00-\x08\x0b-\x1f]', raw) or re.search(r'[^\W\d_A-Za-zΑ-Ωα-ωΆ-Ώά-ώϊϋΐΰ]', t):
                gaps.append(t[:40])
                paras.append(GAP)
            else:
                LATIN_ANNEX.append(t)
                paras.append(t)
                alone.add(len(paras) - 1)
            continue
        prev = paras[-1] if paras else None
        hyph = prev is not None and re.search(r'[α-ωά-ώ]-$', prev)
        if prev is None or prev == GAP or (len(paras) - 1) in alone or NEW_PARA.match(t) or \
                prev.startswith('ΠΑΡΑΡΤΗΜΑ') or \
                (re.search(r'[.:]$', prev) and re.match(r'^[Α-ΩΆ-Ώ]', t)) or \
                (not hyph and not re.search(r'[.,:;·)]$', prev) and len(prev) < 70 and re.match(r'^[Α-ΩΆ-Ώ]', t)):
            paras.append(t)
        elif hyph:
            paras[-1] = prev[:-1] + t
        else:
            paras[-1] = prev + ' ' + t
    return {'parartima': {'label': 'Παράρτημα', 'kind': 'annex', 'text': NL.join(paras) + NL}}, gaps


# GR-14: tables set in small type with no rules, inside a quotation, which the page reader leaves out (small type is
# kept only in ruled tables): law -> (article, page index, the unit's last line before the table, the table's top and
# bottom y, the left edge of its first column). Read here for that law only, so no other part changes.
SMALL_TABLES = {
    4800: ('art-023', 6, 'κατανέμονται κατά κατηγορία και κλάδο, ως εξής:', 95.0, 320.0, 300.0),
}
TABLE_NOTES: list[str] = []


def small_table(law: int, year: int, num: int, units: dict) -> dict:
    """The rows of a SMALL_TABLES table appended to its article, each row one line: the cells of the first column top
    to bottom, then those of the second. A row is a set of lines whose vertical extents overlap across the two columns
    (a cell of two lines beside a number centred on them is one row); a first-column line with nothing beside it is a
    row of its own. Stops unless the article's last line is the expected one and the last row closes the quotation."""
    if law not in SMALL_TABLES:
        return units
    import fitz
    key, pno, last, top, bottom, left = SMALL_TABLES[law]
    if not units[key][-1].endswith(last):
        raise SystemExit(f'ν. {law}/{year}: {key} does not end with the line before its table: {units[key][-1][-60:]}')
    page = fitz.open(N.cpath(FL.fek_url(year, num)))[pno]
    lines = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            t = N.norm_line(''.join(s['text'] for s in l['spans']))
            x0, y0, x1, y1 = l['bbox']
            if t and x0 >= left and top <= y0 and y1 <= bottom and max(s['size'] for s in l['spans']) < 9:
                lines.append({'t': t, 'x0': x0, 'y0': y0, 'y1': y1})
    xs = sorted({round(l['x0']) for l in lines})
    split = next((a + x) / 2 for a, x in zip(xs, xs[1:]) if x - a > 40)  # the columns: cut at the first wide gap
    col1 = sorted((l for l in lines if l['x0'] < split), key=lambda l: l['y0'])
    col2 = sorted((l for l in lines if l['x0'] >= split), key=lambda l: l['y0'])
    rows: list[tuple[list, list]] = []
    for l in col1:
        mates = [m for m in col2 if m['y0'] < l['y1'] and l['y0'] < m['y1']]
        if rows and mates and any(m in rows[-1][1] for m in mates):
            rows[-1][0].append(l)
            rows[-1][1].extend(m for m in mates if m not in rows[-1][1])
        else:
            rows.append(([l], mates))
    used = [m for _, ms in rows for m in ms]
    if sorted(map(id, used)) != sorted(map(id, col2)) or len(set(map(id, used))) != len(used):
        raise SystemExit(f'ν. {law}/{year}: {key}: a second-column cell of the table has no single row')
    out = [N.P.tidy_para(N.join_lines([l['t'] for l in a] + [m['t'] for m in sorted(b, key=lambda m: m['y0'])]))
           for a, b in rows]
    if not out[-1].endswith('»'):
        raise SystemExit(f'ν. {law}/{year}: {key}: the last row of the table does not close the quotation: {out[-1]}')
    units = dict(units)
    units[key] = units[key] + out
    P5.UNCLOSED[:] = [u for u in P5.UNCLOSED if not u.startswith(f'{key}: ')]
    TABLE_NOTES.append(f'ν. {law}/{year}: the table in {key} is set in small type with no rules; it is read row by row '
                       f'({len(out)} rows), each row one line: the cell of the first column, then the number of posts.')
    return units


def signed(year: int, num: int) -> str | None:
    try:
        return N.signed(year, num)
    except StopIteration:  # the signature line is not a paragraph of its own: read it from the raw text layer
        import parse_n3471 as T
        return T.signed(year, num)


def single_part(part_name: str, slug: str, y: int, n: int, law: int, desc: str) -> tuple[dict, str]:
    """The part for one law as published (its only version), and a one-line summary. parse_multi.py builds on it."""
    if True:
        key = f'n-{law}-{y}'
        P5.UNCLOSED.clear()
        P5.CLEANED.clear()
        LATIN_KEPT.clear()
        LATIN_ANNEX.clear()
        P5.UNOPENED.clear()
        TABLE_NOTES.clear()
        P5.UNOPENED_FIX = law in UNOPENED_LAWS
        try:
            units, end = body(y, n, law)
        finally:
            P5.UNOPENED_FIX = False
        units = small_table(law, y, n, units)
        joined = None
        if law in PROMULGATION_JOINED:
            last = list(units)[-1]
            if not units[last][-1].endswith(PROMULGATION):
                raise SystemExit(f'ν. {law}/{y}: the promulgation formula is not joined to {last} as expected')
            units = dict(units)
            units[last] = units[last][:-1] + [units[last][-1][:-len(PROMULGATION)]]
            joined = last
        if N.law_number(y, n) != law:
            raise SystemExit(f'Α΄ {n}/{y} is not ν. {law}/{y}')
        pub = N.masthead(y, n)
        annex_units, gaps = annex(y, n, int(list(units)[-1].split('-')[1]))
        last_art = list(units)[-1]
        lines = [l for l in units[last_art]
                 if re.match(r'^(\d+\. (?:[α-ω]\. )?)?(Με την επιφύλαξη ([^,]*,( και [^,]*,)?|των παρ\. (\d+, )+\d+ και \d+,?|της παρ\. \d+) |Τηρουμένων των διατάξεων του άρθρου 54 του Συντάγματος, )?([Ηη] ισχύς|[Ηη] έναρξη ισχύος|[Οο] παρών (νόμος )?ισχύει|Οι διατάξεις του παρόντος τίθενται σε ισχύ)', l)]
        retro = None
        if law in CLAUSE_LATER_PAR and CLAUSE_LATER_PAR[law] in lines:
            lines = [CLAUSE_LATER_PAR[law]] + [l for l in lines if l != CLAUSE_LATER_PAR[law]]
        if lines and not re.search(r'από την? δημοσίευσ', lines[0]):
            m = RETRO_RE.match(lines[0])
            if m and len(lines) == 1:
                day = f'{m.group(5)}-{int(m.group(4)):02d}-{int(m.group(3)):02d}'
                if day < pub:
                    retro = day
        if not lines or not (retro or re.search(r'από την? δημοσίευσ', lines[0])):  # 5215: «από την δημοσίευσή του»
            raise SystemExit(f'ν. {law}/{y}: the last article ({last_art}) does not start the law on publication')
        clause = ' '.join(lines)
        laws = {key: {'label': f'ν. {law}/{y}', 'kind': 'law', 'title': N.law_title(y, n), 'enacted': signed(y, n),
                      'published': pub, 'url': FL.fek_url(y, n), 'temporary_until': None, 'restores': None,
                      'note': None}}
        version = {'from': pub, 'source_url': FL.fek_url(y, n), 'sha256': N.sha(FL.fek_url(y, n)),
                   'units': {**N.as_units(units), **annex_units},
                   'note': f'ν. {law}/{y} as published in ΦΕΚ Α΄ {n}/{pub[:4]}, in force on publication.' if not retro
                   else f'ν. {law}/{y} as published in ΦΕΚ Α΄ {n}/{pub[:4]}, dated from publication (its stated start, '
                        f'{retro}, is earlier).'}
        part = {
            'laws': laws,
            'sources': [{
                'name': f'Εφημερίδα της Κυβερνήσεως (ΦΕΚ), Εθνικό Τυπογραφείο: Α΄ {n}/{y} (ν. {law}/{y})',
                'url': FL.fek_url(y, n), 'retrieved': RETRIEVED.get(law, '2026-10-30'), 'requests': 1,
                'licence': 'Official legislative texts are not protected by copyright (ν. 2121/1993, άρθρο 2 παρ. 5). '
                           'Attribution: Εφημερίδα της Κυβερνήσεως, Εθνικό Τυπογραφείο (www.et.gr).',
                'notes': 'Issue with a text layer; issue number, date and law number checked against the issue.'}],
            'acts': [{'slug': slug, 'short': f'ν. {law}/{y}', 'title': laws[key]['title'], 'url': FL.fek_url(y, n),
                      'first_law': key, 'earlier_laws': [], 'versions': [version]}],
            'applies': [],
            'decisions': [
                f'ν. {law}/{y} ({desc}) is given as published in ΦΕΚ Α΄ {n}/{y}, its only version: no later law '
                f'amends it. ' + (NOTES_8[law] if law in NOTES_8 else
                                  SCAN_NOTE + (' ' + (GAP_NOTE_8 if RETRIEVED[law] == '2026-11-02' else GAP_NOTE)
                                               if law in RETRIEVED else '')),
                f'ν. {law}/{y} is dated {pub}, the date on the issue\'s masthead: its commencement article '
                f'({last_art}) reads «{clause}». Provisions it starts later are shown from publication.' if not retro
                else f'ν. {law}/{y} is dated {pub}, the date on the issue\'s masthead (its publication): its commencement '
                     f'article ({last_art}) reads «{clause}», a start before publication. By the rule for retroactive '
                     f'starts used across this corpus, the law is dated from its publication day and the stated day, '
                     f'{retro}, is recorded here and not as a version.',
                *([f'ν. {law}/{y}: ' + '; '.join(P5.UNCLOSED) + ' (in the issue text layer); the next '
                    'article of the law itself closes it.'] if P5.UNCLOSED else []),
                *([f'ν. {law}/{y}: ' + '; '.join(P5.UNOPENED) + ': the issue prints no opening « for that '
                   'quotation, so its text is read as quoted up to that closing ».'] if P5.UNOPENED else []),
                *([f'ν. {law}/{y}: ' + '; '.join(f'{k}: a table header line reads «{l}» in Latin capitals in the issue '
                                                 '(the abbreviation of «αύξων αριθμός»); kept as printed'
                                                 for k, l in LATIN_KEPT)] if LATIN_KEPT else []),
                *TABLE_NOTES,
                *([f'ν. {law}/{y}: the issue sets the promulgation formula («{PROMULGATION.strip()}») on the same line '
                   f'as the last paragraph of {joined}; it is not part of the article and is left out.'] if joined else []),
                *([f'ν. {law}/{y}: cleaned line ends (the end of the promulgation formula joined to the text): '
                    + '; '.join(P5.CLEANED)] if P5.CLEANED else []),
                *([f'ν. {law}/{y}: the Annex (ΠΑΡΑΡΤΗΜΑ) is one unit, `parartima`, read line by line from the issue text layer '
                   '(one column).'] if annex_units else []),
                *([f'ν. {law}/{y}: {len(gaps)} line(s) of the Annex are set in a font whose text layer maps to other '
                   f'characters; each reads «{GAP}» (no OCR).'] if gaps else []),
                *([f'ν. {law}/{y}: {len(LATIN_ANNEX)} line(s) of the Annex are printed in Latin script (names and '
                   'terms as the issue gives them); each is kept as printed, on a line of its own.']
                  if LATIN_ANNEX else []),
                'Units are articles (art-NNN), as in the other Greek parts: the headings that open an article, '
                '"Άρθρο N", its title, then one paragraph or item per line. Annexes and signatures are not units.',
            ],
            'ai_use': [f'ν. {law}/{y} part: none. No model wrote or altered legal text; a model (Claude) wrote '
                       'parse_single.py, which reads every word from the Gazette PDF.'],
        }
        return part, f'{part_name}: ν. {law}/{y}, {len(units)} articles, from {pub}; clause in {last_art}: {clause[:90]}'


# GR-14: laws whose commencement article starts most of the law on a later day and names the articles in force on
# publication (as for ν. 3471/2006 in parse_n3471.py): law -> (later day, the clause's own words (checked in the
# issue), articles in force on publication, why the commencement article itself is among them)
SPLIT = {
    4800: ('2021-09-16',
           'Η ισχύς του παρόντος αρχίζει από τις 16.9.2021, εξαιρουμένων των άρθρων 4, 16, 17, 20, 21, 22 και του '
           'Κεφαλαίου Ζ’, η ισχύς των οποίων αρχίζει από τη δημοσίευση του παρόντος.',
           ['art-004', 'art-016', 'art-017', 'art-020', 'art-021', 'art-022', 'art-023', 'art-024', 'art-025',
            'art-026', 'art-027', 'art-028', 'art-029', 'art-030'],
           'arts. 4, 16, 17, 20, 21 and 22 and Chapter Ζ’ (arts. 23-29) are in force on publication; art. 30 (Chapter '
           'Η’, the commencement article) is shown from publication too, since it is the provision that starts '
           'those articles on that day'),
}


def split_part(part: dict, law: int, y: int, n: int) -> tuple[dict, str]:
    """A single-version part whose law starts in two steps (SPLIT): the first version holds only the articles in
    force on publication, the second, on the later day, adds every other article, credited to the law itself."""
    day, clause, early, why = SPLIT[law]
    act = part['acts'][0]
    v = act['versions'][0]
    pub = v['from']
    flat = re.sub(r'\s+', ' ', ' '.join(u['text'] for k, u in v['units'].items() if k == early[-1]))
    if clause not in flat:
        raise SystemExit(f'ν. {law}/{y}: the commencement clause was not found as expected in {early[-1]}')
    missing = [k for k in early if k not in v['units']]
    if missing:
        raise SystemExit(f'ν. {law}/{y}: no such articles {missing}')
    later = [k for k in v['units'] if k not in early]
    if any(not k.startswith('art-') for k in later):
        raise SystemExit(f'ν. {law}/{y}: units other than articles {[k for k in later if not k.startswith("art-")]}')
    key = f'n-{law}-{y}'
    d0 = f'{int(day[8:])}.{int(day[5:7])}.{day[:4]}'
    v1 = {**{k: x for k, x in v.items() if k != 'units' and k != 'note'},
          'units': {k: x for k, x in v['units'].items() if k in early},
          'note': f'ν. {law}/{y} as published in ΦΕΚ Α΄ {n}/{pub[:4]}: only the articles its commencement article '
                  f'puts in force on publication ({", ".join(str(int(k[4:])) for k in early)}); the rest of the law '
                  f'follows on {d0}.'}
    v2 = {'from': day, 'source_url': v['source_url'], 'sha256': v['sha256'],
          'changes': {k: v['units'][k] for k in later}, 'credits': {k: [key] for k in later},
          'note': f'The rest of ν. {law}/{y} ({len(later)} articles) takes effect on {d0} (its commencement article).'}
    act['versions'] = [v1, v2]
    dec = part['decisions']
    i = next(i for i, x in enumerate(dec) if x.startswith(f'ν. {law}/{y} is dated '))
    dec[i] = (f'ν. {law}/{y} starts in two steps, by its own commencement article ({early[-1]}): «{clause}» So the '
              f'first version ({pub}, publication, the date on the issue\'s masthead) holds only the articles in force '
              f'then: {why}. The other {len(later)} articles are added on {day}, credited to the law itself.')
    dec[0] = dec[0].replace('its only version: no later law amends it', 'in two versions (its own two start days): '
                            'no later law amends it')
    return part, f'split: {len(v1["units"])} articles from {pub}, {len(later)} from {day}'


def write_part(part_name: str, part: dict) -> Path:
    out = Path(os.environ.get('GR_OUTDIR', HERE / 'corpus.d')) / f'{part_name}.json'
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(part, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    os.replace(tmp, out)
    return out


def main() -> None:
    for part_name, slug, (y, n), law, desc in LAWS:
        part, line = single_part(part_name, slug, y, n, law, desc)
        if law in SPLIT:
            part, more = split_part(part, law, y, n)
            line += '; ' + more
        write_part(part_name, part)
        print(line)


if __name__ == '__main__':
    main()
