"""Local OCR through Apple's Vision framework (tools/ocr.swift, compiled on first use; nothing leaves this Mac).
Pages are rendered with PyMuPDF and the recognised words come back with pixel boxes. Results are cached by the
hash of the page image, so a re-parse (resync) of the same file does not run OCR again."""
import hashlib
import json
import subprocess
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "data" / "bin" / "ocr"
SRC = ROOT / "tools" / "ocr.swift"
CACHE = ROOT / "data" / "ocr_cache"
DPI = 250


def _ensure_binary():
    if not BIN.exists() or BIN.stat().st_mtime < SRC.stat().st_mtime:
        BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", str(SRC), "-o", str(BIN)], check=True)


def render(page, dpi=DPI):
    return page.get_pixmap(dpi=dpi).tobytes("png")


def _split_glued(words):
    """Vision sometimes returns one 'word' spanning a column border ('7910|OTHER', '1132PENSOL'): cut it at the
    border, sharing the box in proportion to the characters, so each part lands in its own column."""
    import re
    out = []
    for w in words:
        t = w["t"]
        parts = [p for p in re.split(r"\||(?<=\d)(?=[A-Z]{3,})", t) if p]
        if len(parts) <= 1:
            w["t"] = t.strip("|")
            out.append(w)
            continue
        x, total = w["x"], sum(len(p) for p in parts)
        for p in parts:
            pw = w["w"] * len(p) / total
            out.append({**w, "t": p, "x": x, "w": pw})
            x += pw
    return out


def ocr_png(png: bytes):
    key = hashlib.sha256(png).hexdigest()
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    _ensure_binary()
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / f"{key}.png"
    tmp.write_bytes(png)
    try:
        out = subprocess.run([str(BIN), str(tmp)], capture_output=True, text=True, check=True)
    finally:
        tmp.unlink(missing_ok=True)
    words = _split_glued(json.loads(out.stdout))
    for w in words:
        w["cx"], w["cy"] = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
    cached.write_text(json.dumps(words))
    return words


def ocr_page(pdf_path, page_index, dpi=DPI):
    doc = fitz.open(pdf_path)
    return ocr_png(render(doc[page_index], dpi)), doc[page_index].rect
