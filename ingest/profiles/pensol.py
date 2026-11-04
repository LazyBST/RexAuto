"""Pensol Industries "AUTOMOTIVE DEALERS PRICE LIST" (effective 01-04-2026): lubricants, per pack.

The sheet is a scan: only page 2 carries a text layer (page 1 is a picture and is reported as needing OCR).
Two panels per page, each: PRODUCT | PACKING | RATE | MRP PER PC.  The RATE column is the dealer rate:
it is excluded by position BEFORE any text is read and never stored. Only MRP per pack is kept.
Product names and their specification lines do not sit on the same row as their pack lines, so each pack is
attached to the nearest product name above it; every row is therefore marked for review.
"""
import re

import pdfplumber

from .. import normalize as nz
from .base import PageStat, ParsedRow, ParseResult

NAME = "pensol"
BRAND_SLUG = "pensol"
PARSER_VERSION = "pensol/1.0"

MIN_WORDS_FOR_TEXT_LAYER = 30
# panel x-ranges in points: (product, packing, rate (never read), mrp)
PANELS = [((40, 195), (195, 249), (249, 288), (288, 317)), ((317, 426), (426, 478), (478, 511), (511, 565))]
MAX_UNRELIABLE = 0.05  # tolerated share of pack lines without a readable product / MRP
NAME_LIFT = 9  # a product name sits up to this many points below its first pack line
PACK_RE = re.compile(r"(LTR|LIR|KG|ML|GM|PCH|JAR|BKT|DRM|DRUM|DRN)", re.I)
SECTION_CATEGORY = {"PASSENGER CAR MOTOR OILS": ("Engine Oils - Passenger Car", "CAR"), "CNG ENGINE OILS": ("Engine Oils - CNG", "CAR"),
                    "TWO WHEELER OILS": ("Engine Oils - Two Wheeler", "OTHER"), "GEAR / TRANSMISSION OILS": ("Gear & Transmission Oils", "OTHER"),
                    "COOLANTS": ("Coolants", "OTHER")}


class PensolProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def parse(self, pdf_path):
        rows, pages = [], []
        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                stat = PageStat(page=pno, words=len(page.extract_words()))
                pages.append(stat)
                if stat.words < MIN_WORDS_FOR_TEXT_LAYER:
                    stat.needs_ocr, stat.note = True, "no usable text layer (scanned image)"
                    continue
                self._page(page, pno, stat, rows)
        return ParseResult(rows=rows, pages=pages)

    @staticmethod
    def _clean_page(page):
        """Characters of the page minus everything inside a RATE column."""
        gone = [p[2] for p in PANELS]
        return [c for c in page.chars if c["text"].strip()
                and not any(lo <= (c["x0"] + c["x1"]) / 2 < hi for lo, hi in gone)]

    def _page(self, page, pno, stat, rows):
        text = page.extract_text() or ""
        if "PACKING" not in text.upper() or "MRP" not in text.upper():
            stat.unrecognised, stat.note = True, "price table headers not found"
            return
        chars = self._clean_page(page)
        terms = [c["top"] for c in chars if False]
        words = page.extract_words()
        stop = min([w["top"] for w in words if w["text"].upper().startswith("TERMS")] or [page.height])
        top = max([w["bottom"] for w in words if w["text"].upper() == "PC." and w["top"] < 140] or [120])
        page_rows = []
        for cols in PANELS:
            self._panel(chars, cols, top, stop, pno, stat, page_rows)
        bad = sum(1 for r in page_rows if "no_product_name" in r.flags or "bad_mrp" in r.flags)
        if not page_rows or bad / len(page_rows) > MAX_UNRELIABLE:
            # The scan's text layer cannot tell which product a pack line belongs to; publishing guesses would put
            # prices on the wrong products. Report the page for OCR instead.
            stat.needs_ocr, stat.rows = True, 0
            stat.note = (f"text layer unreliable: {bad} of {len(page_rows)} pack lines could not be matched to a product; "
                         "page needs OCR, nothing was imported")
            return
        rows.extend(page_rows)
        stat.rows = len(page_rows)

    @staticmethod
    def _lines(chars, lo, hi, top, stop):
        sel = sorted((c for c in chars if lo <= (c["x0"] + c["x1"]) / 2 < hi and top <= c["top"] < stop), key=lambda c: c["top"])
        lines, cur = [], []
        for c in sel:
            if cur and c["top"] - cur[-1]["top"] > 3.5:
                lines.append(cur)
                cur = []
            cur.append(c)
        if cur:
            lines.append(cur)
        return lines

    @staticmethod
    def _txt(cs, lo, hi):
        hit = sorted((c for c in cs if lo <= (c["x0"] + c["x1"]) / 2 < hi), key=lambda c: c["x0"])
        out, prev = [], None
        for c in hit:
            if prev is not None and c["x0"] - prev["x1"] > 1.5:
                out.append(" ")
            out.append(c["text"])
            prev = c
        return nz.clean_text("".join(out))

    def _panel(self, chars, cols, top, stop, pno, stat, rows):
        (plo, phi), (klo, khi), _rate, (mlo, mhi) = cols
        events = []  # (sort_y, kind, payload)
        for line in self._lines(chars, plo, mhi, top, stop):
            y = sum(c["top"] for c in line) / len(line)
            prod, pack, mrp = self._txt(line, plo, phi), self._txt(line, klo, khi), self._txt(line, mlo, mhi)
            if pack and PACK_RE.search(pack):
                events.append((y, 2, (pack, mrp, y)))
                stat.rows += 0
            if prod:
                up = prod.upper()
                if up.startswith("PENSOL") and not up.startswith("PENSOL )"):
                    events.append((y - NAME_LIFT, 0, prod))
                elif re.fullmatch(r"[A-Z0-9 /&.\-]{6,}", prod) and not re.match(r"(SAE|API)", up):
                    events.append((y - NAME_LIFT, 1, prod))
                else:
                    events.append((y, 3, prod))
        events.sort(key=lambda e: (e[0], e[1]))
        cur = None
        section = ("Lubricants", "OTHER")
        for _, kind, payload in events:
            if kind == 1:
                section = SECTION_CATEGORY.get(payload.upper().strip(), (payload.title(), "OTHER"))
                cur = None
            elif kind == 0:
                cur = {"name": payload, "specs": [], "section": section}
            elif kind == 3 and cur is not None:
                cur["specs"].append(payload)
            elif kind == 2:
                rows.append(self._build(pno, len(rows) + 1, cur, payload[0], payload[1]))
                stat.rows += 1

    def _build(self, pno, n, prod, pack, mrp_txt):
        flags = ["check_alignment"]
        mrp = nz.to_number(mrp_txt)
        if mrp is None:
            flags.append("no_mrp" if mrp_txt.upper() in ("", "NA", "N/A") else "bad_mrp")
        if prod is None:
            flags.append("no_product_name")
            name, specs, (cat, seg) = "UNKNOWN PRODUCT", [], ("Lubricants", "OTHER")
        else:
            name, specs, (cat, seg) = prod["name"], prod["specs"], prod["section"]
        pack = re.sub(r"\s+", " ", pack).strip()
        data = {
            "part_no": nz.clean_text(name), "part_no_norm": nz.norm_part(name), "description": nz.clean_text(name + " " + " ".join(specs)),
            "category": cat, "segment": seg, "oem_name": None, "oem_raw": None, "application": " ".join(specs) or None,
            "variant_label": pack, "mrp": mrp, "mrp_prev": None, "price_basis": "incl_tax", "gst_pct": None, "hsn": None,
            "moq": None, "pack_qty": None, "unit": "pack", "image_url": None, "needs_review": True,
            "review_note": "product/pack match read from a scanned page by position; please verify",
            "source_page": pno, "source_row": n,
        }
        if not data["part_no_norm"]:
            flags.append("missing_part_no")
        return ParsedRow(page=pno, row_no=n, data=data, flags=flags)
