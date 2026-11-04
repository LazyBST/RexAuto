"""Meko visual catalogue ("CATALOGUE 2026"): every page is a picture of product cards (model code, photo, application,
REF. NOS.). It is read with local OCR for the model codes and PyMuPDF for the embedded photos. This profile only ENRICHES
products that already exist from the price list: it sets image_url by model code, never inserts a product, and never
touches price or any other field (rows carry update_only). Codes with no matching product are reported as unmatched.
"""
import hashlib
import re

import fitz

from .. import normalize as nz
from ..ocr import ocr_page
from ..storage import get_storage
from .base import PageStat, ParsedRow, ParseResult

NAME = "meko_catalogue"
BRAND_SLUG = "meko"
PARSER_VERSION = "meko_catalogue/1.0"

PT = 72 / 250  # OCR pixels (250 dpi) -> PDF points
CODE_RE = re.compile(r"^M-?\d{2,5}$", re.I)
SUFFIX_RE = re.compile(r"^(?:[A-Z]{1,3}|\(?[A-Z]\)?|\(Z\))$")


class MekoCatalogueProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def parse(self, pdf_path):
        doc = fitz.open(pdf_path)
        rows, pages = [], []
        store = get_storage()
        for pno, page in enumerate(doc, start=1):
            stat = PageStat(page=pno)
            pages.append(stat)
            words, _ = ocr_page(pdf_path, pno - 1)
            stat.words = len(words)
            if len(words) < 20:
                stat.note = "no product cards (cover / photo page)"
                continue
            photos = self._photos(doc, page)
            heads = self._headings(words)
            if not heads:
                stat.note = "no model codes found"
                continue
            if not photos:
                stat.note = "model codes found but no separate photos"
                continue
            used = set()
            for code, hx, hy in heads:
                cand = [p for p in photos if p["y0"] >= hy - 2 and p["x0"] - 70 <= hx <= p["x1"] and p["y0"] - hy < 170 and id(p) not in used]
                if not cand:
                    continue
                best = min(cand, key=lambda p: p["y0"] - hy)
                used.add(id(best))
                url = self._save(store, best["bytes"], best["ext"])
                rows.append(ParsedRow(page=pno, row_no=len(rows) + 1, flags=[], data={
                    "part_no_norm": nz.norm_part(code), "variant_label": "", "image_url": url, "update_only": True,
                    "part_no": code,
                }))
                stat.rows += 1
        return ParseResult(rows=rows, pages=pages)

    @staticmethod
    def _headings(words):
        """Model codes are printed large: take 'M-513' (+ a short suffix such as MD / CA / A on the same line)."""
        hs = sorted(w["h"] for w in words)
        median = hs[len(hs) // 2]
        out = []
        for w in words:
            if CODE_RE.match(w["t"]) and w["h"] > 1.25 * median:
                code = w["t"].upper() if "-" in w["t"] else "M-" + w["t"][1:]
                suffix = [v for v in words if abs(v["cy"] - w["cy"]) < w["h"] * 0.5 and 0 < v["x"] - (w["x"] + w["w"]) < w["h"] * 3
                          and v["h"] > 1.25 * median and SUFFIX_RE.match(v["t"])]
                if suffix:
                    code += " " + min(suffix, key=lambda v: v["x"])["t"].strip("()")
                out.append((code, w["x"] * PT, w["cy"] * PT))
        return out

    @staticmethod
    def _photos(doc, page):
        out = []
        for info in page.get_image_info(xrefs=True):
            x0, y0, x1, y1 = info["bbox"]
            w, h = x1 - x0, y1 - y0
            if not (60 <= w <= 230 and 50 <= h <= 200) or y0 < 75 or not info.get("xref"):
                continue
            try:
                img = doc.extract_image(info["xref"])
            except Exception:
                continue
            if not img or img["width"] < 120:
                continue
            data, ext = img["image"], img["ext"].lower()
            if ext not in ("jpg", "jpeg", "png"):
                pix = fitz.Pixmap(doc, info["xref"])
                if pix.n > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                data, ext = pix.tobytes("jpeg"), "jpg"
            out.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "bytes": data, "ext": "jpg" if ext == "jpeg" else ext})
        return out

    @staticmethod
    def _save(store, data, ext):
        name = hashlib.sha256(data).hexdigest()[:20] + "." + ext
        store.put(f"images/meko/{name}", data)
        return f"/img/meko/{name}"
