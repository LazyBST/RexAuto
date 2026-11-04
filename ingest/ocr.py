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


def ocr_png(png: bytes, drop=None, tag="", cache=True):
    """OCR one page image. `drop(words) -> words` removes words BEFORE anything is cached or returned, so material that must
    never be stored (e.g. a dealer-rate column) does not reach disk through the cache; `tag` keeps filtered and unfiltered
    results apart."""
    key = hashlib.sha256(png).hexdigest() + (("-" + tag) if tag else "")
    cached = CACHE / f"{key}.json"
    if cache and cached.exists():
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
    if drop:
        words = drop(words)
    for w in words:
        w["cx"], w["cy"] = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
    if cache:
        cached.write_text(json.dumps(words))
    return words


def _raw(png: bytes):
    """Words straight from the engine (nothing cached, nothing dropped)."""
    key = hashlib.sha256(png).hexdigest()
    _ensure_binary()
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / f"{key}.tmp.png"
    tmp.write_bytes(png)
    try:
        out = subprocess.run([str(BIN), str(tmp)], capture_output=True, text=True, check=True)
    finally:
        tmp.unlink(missing_ok=True)
    return _split_glued(json.loads(out.stdout))


def ocr_tiled(page, dpi=DPI, drop=None, tag="", cache=True):
    """OCR the whole page, then its left and right parts again (with an overlap) and merge. The engine sometimes leaves a
    column of numbers out of a full-page read; a narrower view brings them back. Same word seen twice -> kept once."""
    full_png = render(page, dpi)
    key = hashlib.sha256(full_png).hexdigest() + "-tiled" + (("-" + tag) if tag else "")
    cached = CACHE / f"{key}.json"
    if cache and cached.exists():
        return json.loads(cached.read_text())
    words = _raw(full_png)
    k, rect = dpi / 72, page.rect
    for x0, x1 in ((0.0, 0.58), (0.42, 1.0)):
        clip = fitz.Rect(rect.x0 + x0 * rect.width, rect.y0, rect.x0 + x1 * rect.width, rect.y1)
        for w in _raw(page.get_pixmap(dpi=dpi, clip=clip).tobytes("png")):
            w["x"] += (clip.x0 - rect.x0) * k
            w["y"] += (clip.y0 - rect.y0) * k
            # keep a tile word only if nothing from the first read sits where it is (whatever that read made of the text)
            if not any(abs((v["x"] + v["w"] / 2) - (w["x"] + w["w"] / 2)) < max(v["w"], w["w"]) / 2 + 3
                       and abs((v["y"] + v["h"] / 2) - (w["y"] + w["h"] / 2)) < max(v["h"], w["h"]) / 2 for v in words):
                words.append(w)
    if drop:
        words = drop(words)
    for w in words:
        w["cx"], w["cy"] = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
    if cache:
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(words))
    return words


def ocr_page(pdf_path, page_index, dpi=DPI, drop=None, tag="", tiled=False):
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    if tiled:
        return ocr_tiled(page, dpi, drop=drop, tag=tag), page.rect
    return ocr_png(render(page, dpi), drop=drop, tag=tag), page.rect
