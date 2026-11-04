"""Pensol Industries "AUTOMOTIVE DEALERS PRICE LIST" (effective 01-04-2026): lubricants, one row per pack.

The sheet is a scan, so it is read with local OCR (ingest/ocr.py, Apple Vision) and then by position.
Two panels per page, each: PRODUCT | PACKING | RATE | MRP PER PC.  RATE is the dealer rate: the words in that
column are discarded straight after OCR, before any row is built, and are never stored. Only MRP per piece is kept.
Names are matched to their pack lines by position; prices are cross-checked per litre inside each product so a
misread digit shows up as a flag. Every row carries an `ocr` flag; low-confidence ones are marked for review.
"""
import re
import statistics

import fitz

from .. import normalize as nz
from ..ocr import ocr_page, ocr_tiled
from .base import PageStat, ParsedRow, ParseResult

NAME = "pensol"
BRAND_SLUG = "pensol"
PARSER_VERSION = "pensol/2.0-ocr"

PACK_RE = re.compile(r"(LTR|LIR|KG|ML|GM|PCH|JAR|BKT|DRM|DRUM|DRN|TUB)", re.I)
NAME_LIFT = 24          # a product name sits up to this many pixels below its first pack line (250 dpi, scans drift)
ROW_TOL = 16
ALIGN_TOL = 14
LOW_CONF = 0.6
SECTIONS = {
    "HEAVY DUTY DIESEL ENGINE OILS": ("Engine Oils - Heavy Duty Diesel", "HCV"),
    "PASSENGER CAR MOTOR OILS": ("Engine Oils - Passenger Car", "CAR"),
    "CNG ENGINE OILS": ("Engine Oils - CNG", "CAR"),
    "TWO WHEELER OILS": ("Engine Oils - Two Wheeler", "OTHER"),
    "TRACTOR AND PUMPSET OILS": ("Engine Oils - Tractor & Pumpset", "TRACTOR"),
    "GEAR / TRANSMISSION OILS": ("Gear & Transmission Oils", "OTHER"),
    "APLR SERIES GREASES": ("Greases", "OTHER"), "OTHER GREASES": ("Greases", "OTHER"),
    "HYDRAULIC OILS": ("Hydraulic Oils", "OTHER"), "BRAKE FLUIDS": ("Brake Fluids", "OTHER"), "COOLANTS": ("Coolants", "OTHER"),
}


def rate_bands(words):
    """x-ranges of the two RATE (dealer rate) columns, located from the PACKING headers; [] if the page has no two headers."""
    heads = sorted((w["x"] for w in words if w["t"] == "PACKING"))
    return [(p + 150, p + 280) for p in heads] if len(heads) == 2 else []


def drop_rate_column(words):
    """Remove every word inside a RATE column. Applied inside the OCR layer, before the result is cached."""
    bands = rate_bands(words)
    return [w for w in words if not any(lo <= w["x"] + w["w"] / 2 < hi for lo, hi in bands)]


def redact_scan(data, dpi=250):
    """Blank the dealer RATE column in the scanned pages themselves: the pixels of that strip are cleared in the page image
    and the image is stored again at its original resolution, so the archived original no longer contains the column.
    Fails closed: each page is re-read with OCR and must show no number in a RATE band."""
    import fitz
    from ..ocr import ocr_png, render
    doc = fitz.open(stream=data, filetype="pdf")
    k = 72 / dpi
    bands = {}
    for i, page in enumerate(doc):
        words = ocr_tiled(page, dpi, drop=drop_rate_column, tag="no-rate")           # cached WITHOUT the rate words
        heads = sorted(w["x"] for w in words if w["t"] == "PACKING")
        if len(heads) != 2:
            raise RuntimeError(f"redaction: page {i + 1} does not show two PACKING headers")
        top = min(w["y"] for w in words if w["t"] == "PACKING") - 15
        bands[i] = [fitz.Rect((p + 150) * k, top * k, (p + 280) * k, page.rect.height - 5) for p in heads]
        infos = [x for x in page.get_image_info(xrefs=True) if x.get("xref")]
        if len(infos) != 1:
            raise RuntimeError(f"redaction: page {i + 1} has {len(infos)} images, expected one scan")
        info = infos[0]
        pix = fitz.Pixmap(doc, info["xref"])
        if pix.alpha or pix.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)
        bx0, by0, bx1, by1 = info["bbox"]
        sx, sy = pix.width / (bx1 - bx0), pix.height / (by1 - by0)
        for r in bands[i]:
            pix.set_rect(fitz.IRect(int((r.x0 - bx0) * sx), int((r.y0 - by0) * sy), int((r.x1 - bx0) * sx), int((r.y1 - by0) * sy)),
                         (255,) * pix.n)
        page.replace_image(info["xref"], pixmap=pix)
    out = doc.tobytes(garbage=1, deflate=True)
    check = fitz.open(stream=out, filetype="pdf")
    for i, page in enumerate(check):
        words = ocr_tiled(page, dpi, cache=False)                                      # never cached: it is a check
        left = [w for w in words if any(r.x0 / k <= w["x"] + w["w"] / 2 < r.x1 / k and w["y"] > r.y0 / k + 40 for r in bands[i])
                and any(ch.isdigit() for ch in w["t"])]
        if left:
            raise RuntimeError(f"redaction failed on page {i + 1}: {len(left)} numbers remain in the RATE column")
    return out


def _lines(words, tol=ROW_TOL):
    out, cur = [], []
    for w in sorted(words, key=lambda w: w["cy"]):
        if cur and w["cy"] - cur[-1]["cy"] > tol:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def clean_pack(txt):
    """Fix the usual OCR slips in a pack description without changing its meaning."""
    t = nz.clean_text(txt).strip("|/ ")
    t = re.sub(r"^[AÀ]\s*X", "4X", t)                       # '4' read as 'A'
    t = re.sub(r"(?<=\d)\s*[BS](?=\d)", "8", t)             # '8' read as B/S inside a number
    t = re.sub(r"\bB(?=0{2}\b)", "8", t)                    # 'B00 ML' -> '800 ML'
    t = re.sub(r"^B(?=\s?\d\s*(LTR|KG))", "8", t)          # 'B 5 LTR' -> '8 5 LTR'
    t = re.sub(r"(\d)\s(\d)(?=\s*(LTR|LIR|KG)\b)", r"\1.\2", t)   # '7 5 LTR' -> '7.5 LTR'
    t = re.sub(r"(X\s*\d)\s(\d)(?=\s*(LTR|LIR|KG)\b)", r"\1.\2", t)
    t = re.sub(r"\bLIR\b", "LTR", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def clean_name(txt):
    t = nz.clean_text(txt).lstrip("|/ ")
    t = re.sub(r"\b[B8]OW\b", "80W", t)       # '80W' read as 'BOW'
    t = re.sub(r"\bSW\b(?=\s*\d)", "5W", t)  # '5W 40' read as 'SW 40'
    t = re.sub(r"\b(80W|85W|75W)\s30\b", r"\1 90", t)   # gear grade '90' read as '30'
    return t


def _text(ws):
    return nz.clean_text(" ".join(w["t"] for w in sorted(ws, key=lambda w: w["x"])))


class PensolProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def redact(self, data):
        return redact_scan(data)

    def parse(self, pdf_path):
        n_pages = len(fitz.open(pdf_path))
        rows, pages, carry, eff = [], [], {}, None
        for pno in range(1, n_pages + 1):
            stat = PageStat(page=pno)
            pages.append(stat)
            words, _ = ocr_page(pdf_path, pno - 1, drop=drop_rate_column, tag="no-rate", tiled=True)
            stat.words = len(words)
            if len(words) < 30:
                stat.needs_ocr, stat.note = True, "nothing recognised even with OCR"
                continue
            if pno == 1:
                eff = nz.find_date(" ".join(w["t"] for w in words))
            self._page(words, pno, stat, rows, carry)
        self._price_check(rows)
        nz.stamp(rows, eff)
        return ParseResult(rows=rows, pages=pages)

    def _page(self, words, pno, stat, rows, carry):
        heads = sorted((w for w in words if w["t"] == "PACKING"), key=lambda w: w["x"])
        if len(heads) != 2:
            stat.unrecognised, stat.note = True, f"expected 2 PACKING headers, found {len(heads)}"
            return
        px0 = [h["x"] for h in heads]
        # RATE (dealer rate) words are dropped here, before anything else looks at the page
        rate = [(p + 150, p + 280) for p in px0]
        words = [w for w in words if not any(lo <= w["cx"] < hi for lo, hi in rate)]
        top = max(h["cy"] for h in heads) + 45
        terms = [w["cy"] for w in words if w["t"].upper().startswith("TERMS")]
        stop = min(terms) if terms else 10 ** 6
        words = [w for w in words if top <= w["cy"] < stop]
        for i, p in enumerate(px0):
            prod_lo = 0 if i == 0 else px0[0] + 392
            self._panel(words, i, prod_lo, p - 60, (p - 60, p + 150), (p + 280, p + 392), pno, stat, rows, carry)

    def _panel(self, words, idx, prod_lo, prod_hi, pack_band, mrp_band, pno, stat, rows, carry):
        band = lambda lo, hi: [w for w in words if lo <= w["cx"] < hi]
        events = []
        for ln in _lines(band(prod_lo, prod_hi)):
            cy, txt = sum(w["cy"] for w in ln) / len(ln), _text(ln)
            up = txt.upper()
            if up.lstrip("|/ ").startswith("PENSOL"):
                events.append((cy - NAME_LIFT, 0, (clean_name(txt), cy)))
            elif up in SECTIONS or (txt == txt.upper() and re.search(r"[A-Z]{3}", txt) and not re.match(r"(SAE|API|DOT|\()", up)
                                     and len(txt.split()) >= 2 and not any(ch.isdigit() for ch in txt)):
                events.append((cy - NAME_LIFT, 1, txt))
            else:
                events.append((cy, 3, txt))
        mrp_words = band(*mrp_band)
        for ln in _lines(band(*pack_band)):
            txt = _text(ln)
            if not PACK_RE.search(txt) or not re.search(r"\d", txt):
                continue
            cy = sum(w["cy"] for w in ln) / len(ln)
            cand = [w for w in mrp_words if abs(w["cy"] - cy) < ROW_TOL and re.fullmatch(r"\d{1,6}|N/?A", w["t"].upper())]
            m = min(cand, key=lambda w: abs(w["cy"] - cy)) if cand else None
            conf = min([w["c"] for w in ln] + ([m["c"]] if m else [0.0]))
            events.append((cy, 2, (clean_pack(txt), m["t"] if m else "", conf)))
        events.sort(key=lambda e: (e[0], e[1]))
        cur, section = None, carry.get(idx, ("Lubricants", "OTHER"))
        groups = []
        for ey, kind, payload in events:
            if kind == 1:
                section = SECTIONS.get(payload.upper().strip(), (payload.title(), "OTHER"))
                cur = None
            elif kind == 0:
                cur = {"name": payload[0], "name_cy": payload[1], "specs": [], "section": section, "first_cy": None, "rows": []}
                groups.append(cur)
            elif kind == 3 and cur is not None:
                cur["specs"].append(clean_name(payload))
            elif kind == 2:
                row = self._build(pno, len(rows) + 1, cur, *payload)
                rows.append(row)
                stat.rows += 1
                if cur is not None:
                    cur["rows"].append(row)
                    if cur["first_cy"] is None:
                        cur["first_cy"] = ey
        for g in groups:  # the spec lines (SAE grade, API class) belong to every pack of the product, not only the later ones
            full = nz.clean_text(g["name"] + " " + " ".join(g["specs"]))
            for r in g["rows"]:
                r.data["description"] = full
                r.data["attributes"] = {"section": g["section"][0], "pack_raw": r.data["variant_label"]}
        for g in groups:  # a name far from its first pack line is an uncertain match: say so
            if g["first_cy"] is not None and abs(g["first_cy"] - g["name_cy"]) > ALIGN_TOL:
                for r in g["rows"]:
                    r.flags.append("check_alignment")
                    r.data["needs_review"] = True
                    r.data["review_note"] = "product name sits far from its first pack line on the scan; please verify the match"
        carry[idx] = section

    def _build(self, pno, n, prod, pack, mrp_txt, conf):
        flags = ["ocr"]
        mrp = nz.to_number(mrp_txt)
        if mrp is None:
            flags.append("no_mrp" if mrp_txt.upper() in ("NA", "N/A") else "bad_mrp")
        if prod is None:
            flags.append("no_product_name")
            name, specs, (cat, seg) = "UNKNOWN PRODUCT", [], ("Lubricants", "OTHER")
        else:
            name, specs, (cat, seg) = prod["name"], prod["specs"], prod["section"]
        low = conf < LOW_CONF
        if low:
            flags.append("low_ocr_confidence")
        data = {
            "part_no": nz.clean_text(name), "part_no_norm": nz.norm_part(name),
            "description": nz.clean_text(name + " " + " ".join(specs)), "category": cat, "segment": seg, "oem_name": None,
            "oem_raw": None, "application": None, "variant_label": pack, "mrp": mrp, "mrp_prev": None, "gst_pct": None, "hsn": None, "moq": None, "pack_qty": None, "unit": "pack",
            "image_url": None, "needs_review": low, "review_note": "read by OCR with low confidence" if low else None,
            "source_page": pno, "source_row": n,
        }
        if not data["part_no_norm"]:
            flags.append("missing_part_no")
        return ParsedRow(page=pno, row_no=n, data=data, flags=flags)

    @staticmethod
    def _litres(pack):
        """Volume of ONE piece: '4X5 LTR JAR' -> 5, '20 LTR BKT' -> 20, '20X500 ML JAR' -> 0.5."""
        s = pack.upper().replace(",", ".")
        m = re.search(r"(?:\d+\s*[X]\s*)?(\d+(?:\.\d+)?)\s*(LTR|LIR|L|ML|KG|GM)\b", s)
        if not m:
            return None
        v = float(m.group(1))
        return v / 1000 if m.group(2) in ("ML", "GM") else v

    def _price_check(self, rows):
        groups = {}
        for r in rows:
            v = self._litres(r.data["variant_label"])
            if r.data["mrp"] and v:
                groups.setdefault(r.data["part_no_norm"], []).append((r, r.data["mrp"] / v))
        for g in groups.values():
            if len(g) >= 3:
                med = statistics.median(p for _, p in g)
                for r, p in g:
                    if p > 1.9 * med or p < 0.5 * med:
                        # OCR often drops a decimal point in the pack size ('75 LTR' for '7.5 LTR', '4X25' for '4X2.5')
                        v = self._litres(r.data["variant_label"])
                        if v and 0.7 * med <= r.data["mrp"] / (v / 10) <= 1.4 * med:
                            r.data["variant_label"] = self._with_decimal(r.data["variant_label"])
                            r.flags.append("pack_decimal_fixed")
                            r.data["needs_review"], r.data["review_note"] = True, "pack size had its decimal point restored from the price"
                        else:
                            r.flags.append("price_per_litre_outlier")

    @staticmethod
    def _with_decimal(pack):
        """'75 LTR BKT' -> '7.5 LTR BKT', '4 X25 LTR JAR' -> '4 X2.5 LTR JAR' (volume of one piece gets a decimal point)."""
        return re.sub(r"(\d)(\d)(?=\s*(LTR|KG|L)\b)", r"\1.\2", pack, count=1)
