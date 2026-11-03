"""The text layer of a ΦΕΚ issue PDF as positioned lines, the input of parse_acts.py.

    python -X utf8 fek_text.py <issue.pdf> <out.json.gz>

Output (gzip JSON): {"v": 2, "sha256": <sha256 of the PDF bytes>, "pages": [{"w", "h", "lines": [[x0, y0, x1, y1,
size, bold, text], ...], "img": [[x0, y0, x1, y1], ...]}]}; "img" lists the page's images larger than 2000 pt². One entry per text line PyMuPDF finds, in its order; text is the raw text layer (no
decoding: issues before about 2005 hold Windows-1253 bytes, which parse_acts.py maps back). No OCR: a scanned page
gives no lines.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys


def dump_pdf_bytes(data: bytes) -> dict:
    import fitz  # PyMuPDF
    doc = fitz.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        lines, imgs = [], []
        for im in page.get_image_info():
            x0, y0, x1, y1 = im["bbox"]
            if (x1 - x0) * (y1 - y0) > 2000:
                imgs.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
        for b in page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"]]
                text = "".join(s["text"] for s in spans)
                if not text.strip():
                    continue
                n = sum(len(s["text"].strip()) for s in spans) or 1
                bold = sum(len(s["text"].strip()) for s in spans if s["flags"] & 16 or "Bold" in s["font"]) * 2 > n
                size = max(s["size"] for s in spans if s["text"].strip())
                x0, y0, x1, y1 = l["bbox"]
                lines.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), round(size, 1), int(bold), text])
        pages.append({"w": round(page.rect.width, 1), "h": round(page.rect.height, 1), "lines": lines, "img": imgs})
    return {"v": 2, "sha256": hashlib.sha256(data).hexdigest(), "pages": pages}


def write_dump(d: dict, out: str) -> None:
    tmp = out + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    import os
    os.replace(tmp, out)


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    write_dump(dump_pdf_bytes(data), sys.argv[2])
