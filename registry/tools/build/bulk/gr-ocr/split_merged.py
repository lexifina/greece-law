"""One-off repair (coordinator 11-11: never overwrite GR-A's text-layer file): the first GR-OCR runs merged OCR pages
into text/<s>/<y>/<id>.json.gz for partial text layers. Split each such file back into
  <id>.json.gz      GR-A's text-layer content as GR-A wrote it (key order, page_info, lines without OCR lines)
  <id>.ocr.json.gz  the OCR pages only (GR-OCR format)
and record ocr_pages_done in meta.

    python -X utf8 -I split_merged.py [--dry]
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from runner import SRC, write_atomic  # noqa: E402

OCR_KEYS = ('ocr_engine', 'ocr_recipe', 'note', 'ocr_line_order')


def main(dry: bool) -> None:
    n = 0
    for mp in sorted((SRC / 'meta').glob('*/*/*.json')):
        m = json.loads(mp.read_text(encoding='utf-8'))
        if not m.get('ocr_done') or m.get('text_layer') != 'partial':
            continue
        tp = SRC / 'text' / m['series'] / str(m['year']) / f"{m['id']}.json.gz"
        if not tp.exists():
            continue
        with gzip.open(tp, 'rb') as f:
            d = json.loads(f.read().decode('utf-8'))
        if not str(d.get('text_source', '')).startswith('text layer + '):
            continue
        ocr_pages = sorted(pi['page'] for pi in d['page_info'] if pi.get('ocr'))
        label = d['text_source'][len('text layer + '):]
        legacy = set(m.get('legacy_font_pages') or [])
        base_info = []
        for pi in d['page_info']:
            if pi.get('ocr'):
                base_info.append({'page': pi['page'], 'w': pi['w'], 'h': pi['h'], 'text': False,
                                  'legacy': pi['page'] in legacy})
            else:
                base_info.append({k: v for k, v in pi.items() if k != 'text_source'})
        base = {'id': d['id'], 'series': d['series'], 'year': d['year'], 'number': d['number'],
                'text_source': 'text layer', 'reader': d['reader'], 'sha256': d['sha256'], 'pages': d['pages'],
                'page_info': base_info, 'lines': [L for L in d['lines'] if 'conf' not in L]}
        ocr_doc = {'id': d['id'], 'series': d['series'], 'year': d['year'], 'number': d['number'],
                   'text_source': label, 'reader': None, 'sha256': d['sha256'], 'pages': d['pages'],
                   'ocr_pages': ocr_pages,
                   'page_info': [{**pi} for pi in d['page_info'] if pi.get('ocr')],
                   'lines': [L for L in d['lines'] if 'conf' in L],
                   **{k: d[k] for k in OCR_KEYS if k in d}}
        n += 1
        print(m['id'], len(base['lines']), 'text-layer lines,', len(ocr_doc['lines']), 'OCR lines on', len(ocr_pages),
              'pages')
        if dry:
            continue
        write_atomic(tp.with_name(f"{m['id']}.ocr.json.gz"), ocr_doc, gz=True)
        write_atomic(tp, base, gz=True)
        cur = json.loads(mp.read_text(encoding='utf-8'))
        cur['ocr_pages_done'] = sorted(set(cur.get('ocr_pages_done') or []) | set(ocr_pages))
        cur['ocr_text_file'] = f"text/{m['series']}/{m['year']}/{m['id']}.ocr.json.gz"
        write_atomic(mp, cur, indent=1)
    print(n, 'files split' + (' (dry run)' if dry else ''))


if __name__ == '__main__':
    main('--dry' in sys.argv)
