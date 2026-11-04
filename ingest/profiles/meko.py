"""Meko "PRICE LIST 2026": assembly water pump tables (S.No | PART No | MRP | application | REF. NOS.).

Uses PyMuPDF only (pdfplumber/pdfminer cannot open some of these pages). Pages that do not hold this table
(index, bearing-housing lists, "Z series" cards, kits, impellers, brochure pages) are reported as unrecognised
layout and skipped, never guessed. REF. NOS. are OEM numbers and become cross references.
"""
import re

import fitz

from .. import normalize as nz
from .base import PageStat, ParsedRow, ParseResult

NAME = "meko"
BRAND_SLUG = "meko"
PARSER_VERSION = "meko/1.0"

X_PART, X_MRP, X_DESC, X_REF = 44, 105, 146, 457
MIN_WORDS = 30
HCV = ["TATA", "BHARAT", "BENZ", "LEYLAND", "EICHER", "VOLVO", "MAN", "MITSUBISHI", "CUMMINS", "JBM", "HINO"]
TRACTOR = ["TRACTOR", "SWARAJ", "SONALIKA", "ZETOR", "ESCORTS", "FARMTRAC", "POWERTRAC", "STEELTRAC", "MASSEY", "PERKINS",
           "NEW HOLLAND", "JOHN DEERE", "DEUTZ", "KUBOTA", "CAPTAIN", "ACE"]
CAR = ["MARUTI", "HYUNDAI", "TOYOTA", "HONDA", "CHEVROLET", "NISSAN", "AMBASSADOR", "VOLKSWAGEN", "ISUZU"]


class MekoProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def parse(self, pdf_path):
        keys = self._make_keys()
        rows, pages = [], []
        doc = fitz.open(pdf_path)
        for pno, page in enumerate(doc, start=1):
            words = self._words(page)
            stat = PageStat(page=pno, words=len(words))
            pages.append(stat)
            if len(words) < MIN_WORDS:
                stat.needs_ocr, stat.note = True, "no usable text layer"
                continue
            self._page(words, pno, stat, rows, keys)
            if stat.unrecognised and self._page_z(page.get_text("text"), pno, stat, rows, keys):
                stat.unrecognised, stat.note = False, "Z-series cards"
        return ParseResult(rows=rows, pages=pages)

    def _page_z(self, text, pno, stat, rows, keys):
        """'Z series' pump cards: 'M-525 (Z) / Price : 8570 / <application> / REF : <numbers>' repeated per card."""
        pat = re.compile(r"(M-\s?\d+(?:\s[A-Z]{1,3})?)\s*\(Z\)\s*Price\s*:\s*(\d+)\s*(.*?)(?=M-\s?\d+(?:\s[A-Z]{1,3})?\s*\(Z\)|\Z)", re.S)
        found = pat.findall(text)
        if len(found) < 2:
            return False
        for n, (code, price, rest) in enumerate(found, start=1):
            app, _, ref = re.split(r"(REF\s*:)", rest, maxsplit=1) if re.search(r"REF\s*:", rest) else (rest, "", "")
            app = nz.clean_text(re.sub(r"\bZ\s*\d*\b|SERIES PUMPS", " ", app))
            refs = [{"ref_type": "oem", "ref_brand": None, "ref_part_no": t.strip(" ."), "note": None}
                    for t in re.split(r"[/\n,]+", ref) if nz.norm_part(t) and len(t.strip()) <= 24 and not re.search(r"[a-z]{3}", t)]
            part = re.sub(r"\s+", " ", code.replace("M- ", "M-")) + " (Z)"
            data = {
                "part_no": part, "part_no_norm": nz.norm_part(part), "description": "Water pump assembly (Z series)",
                "category": "Water Pumps", "segment": "HCV", "oem_name": self._find_make(app.upper(), keys), "oem_raw": None,
                "application": app or None, "variant_label": "", "mrp": nz.to_number(price), "mrp_prev": None,
                "price_basis": "unknown", "gst_pct": None, "hsn": None, "moq": None, "pack_qty": None, "unit": None,
                "image_url": None, "needs_review": False, "review_note": None, "source_page": pno,
                "source_row": 9000 + len(rows) + 1, "cross_refs": refs,
            }
            rows.append(ParsedRow(page=pno, row_no=data["source_row"], data=data, flags=[] if refs else ["no_ref_numbers"]))
            stat.rows += 1
        return True

    @staticmethod
    def _words(page):
        """Words rebuilt from characters, dropping characters printed twice on top of each other (some pages
        carry every text object twice, which otherwise doubles each row and glues digits like 28412841)."""
        chars = []
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    for c in span["chars"]:
                        chars.append((c["bbox"][0], c["bbox"][1], c["bbox"][2], c["bbox"][3], c["c"]))
        chars.sort(key=lambda c: c[1])
        lines, cur_line = [], []
        for c in chars:  # cluster characters into text lines first, then read each line left to right
            if cur_line and c[1] - cur_line[0][1] > 2.5:
                lines.append(cur_line)
                cur_line = []
            cur_line.append(c)
        if cur_line:
            lines.append(cur_line)
        words = []
        for line in lines:
            line.sort(key=lambda c: c[0])
            kept = []
            for c in line:
                if any(k[4] == c[4] and abs(k[1] - c[1]) < 1.2 and 0 <= c[0] - k[0] < 0.75 * max(k[2] - k[0], 1.0) or
                       k[4] == c[4] and abs(k[0] - c[0]) < 1.2 and abs(k[1] - c[1]) < 1.2 for k in kept[-6:]):
                    continue
                kept.append(c)
            cur = []
            for c in kept:
                if c[4].isspace() or (cur and c[0] - cur[-1][2] > 1.6):
                    if cur:
                        words.append((min(x[0] for x in cur), min(x[1] for x in cur), max(x[2] for x in cur),
                                      max(x[3] for x in cur), "".join(x[4] for x in cur)))
                    cur = []
                    if c[4].isspace():
                        continue
                cur.append(c)
            if cur:
                words.append((min(x[0] for x in cur), min(x[1] for x in cur), max(x[2] for x in cur),
                              max(x[3] for x in cur), "".join(x[4] for x in cur)))
        return words

    @staticmethod
    def _make_keys():
        keys = {}
        for r in nz.load_csv("vehicle_keywords.csv"):
            if r["make"]:
                keys[r["keyword"].upper()] = r["make"]
        for r in nz.load_csv("make_aliases.csv"):
            keys.setdefault(r["raw"].upper().strip("."), r["make"])
        return keys

    def _page(self, words, pno, stat, rows, keys):
        words = sorted(words, key=lambda w: (w[1], w[0]))
        has_header = any(w[4] == "REF." for w in words)
        anchors = []  # (y, sno, part words)
        for w in words:
            if w[0] < X_PART - 8 and re.fullmatch(r"\d{1,4}", w[4]):
                nxt = [v for v in words if abs(v[1] - w[1]) < 3 and X_PART - 4 <= v[0] < X_MRP and re.match(r"M(-|$|\d)", v[4].upper())]
                if nxt:
                    anchors.append((w[1], w[4]))
        if not has_header or len(anchors) < 3:
            if not self._page_kits(words, pno, stat, rows, keys):
                stat.unrecognised, stat.note = True, "not an assembly water pump price table"
            return
        # centred text lines that are neither title nor header nor row text = section (vehicle group) titles
        lines = {}
        for w in words:
            lines.setdefault(round(w[1] / 3), []).append(w)
        sections = []  # (y, title)
        for k, ws in sorted(lines.items()):
            ws.sort(key=lambda w: w[0])
            txt = " ".join(w[4] for w in ws)
            y = ws[0][1]
            centre = (ws[0][0] + ws[-1][2]) / 2
            if y < 60 or not 255 <= centre <= 340 or 146 <= ws[0][0] <= 158 or any(w[0] < 90 for w in ws) or ws[0][0] > 330:
                continue
            if re.search(r"S\.|REF|NOS|MRP|PART|ASSEMBLY|WATER|PUMP|Disclaimer|AUTOMOBILES|COMPONENTS", txt) or re.search(r"\d", txt):
                continue
            if ws[-1][2] > 470:
                continue
            sections.append((y, txt))
        sec_ys = [y for y, _ in sections]
        bounds = [a[0] for a in anchors]
        cuts = sorted(set(bounds + sec_ys))
        title = " ".join(w[4] for w in sorted(words, key=lambda w: w[0]) if w[1] < 60 and w[4].isalpha() and w[3] - w[1] > 6)
        page_rows = []
        for i, (ay, sno) in enumerate(anchors):
            end = min([c for c in cuts if c > ay + 1] + [10 ** 6])
            if end == 10 ** 6:
                end = ay + 120
            band = [w for w in words if ay - 2 <= w[1] < end - 2]
            part = " ".join(w[4] for w in sorted(band, key=lambda w: w[0]) if X_PART - 4 <= w[0] < X_MRP and abs(w[1] - ay) < 3)
            mrp_txt = " ".join(w[4] for w in sorted(band, key=lambda w: w[0]) if X_MRP <= w[0] < X_DESC and abs(w[1] - ay) < 3)
            desc = " ".join(w[4] for w in sorted(band, key=lambda w: (round(w[1] / 3), w[0])) if X_DESC <= w[0] < X_REF)
            ref = " ".join(w[4] for w in sorted(band, key=lambda w: (round(w[1] / 3), w[0])) if w[0] >= X_REF)
            sec = next((t for y, t in reversed(sections) if y < ay), None)
            page_rows.append(self._build(pno, sno, part, mrp_txt, desc, ref, sec, keys, title))
        bad = sum(1 for r in page_rows if "bad_mrp" in r.flags)
        if page_rows and bad / len(page_rows) > 0.10:
            if self._page_kits(words, pno, stat, rows, keys):
                return
            stat.unrecognised, stat.note = True, f"columns differ from the water pump table ({bad} of {len(page_rows)} rows have no readable MRP)"
            return
        rows.extend(page_rows)
        stat.rows += len(page_rows)

    def _page_kits(self, words, pno, stat, rows, keys):
        """Repair-kit / impeller tables: S.No | PART No | MRP | application (no REF. NOS. column)."""
        K_PART, K_MRP, K_DESC = 60, 125, 183
        anchors = []
        for w in words:
            if w[0] < K_PART - 2 and re.fullmatch(r"\d{4}", w[4]):
                if any(abs(v[1] - w[1]) < 3 and K_PART <= v[0] < K_MRP and re.match(r"M(-|$|\d)", v[4].upper()) for v in words):
                    anchors.append((w[1], w[4]))
        if len(anchors) < 3:
            return False
        lines = {}
        for w in words:
            lines.setdefault(round(w[1] / 3), []).append(w)
        banners = []  # (y, kind, text)
        for k, ws in sorted(lines.items()):
            ws.sort(key=lambda w: w[0])
            txt = " ".join(w[4] for w in ws)
            if ws[0][1] < 60 or re.search(r"\d", txt) or len(ws) < 2:
                continue
            if "DIVISION" in txt.upper():
                banners.append((ws[0][1], "div", txt))
            elif re.search(r"KITS|IMPELLERS", txt.upper()) and ws[0][0] > 100:
                banners.append((ws[0][1], "sub", txt))
        cuts = sorted(set([a[0] for a in anchors] + [b[0] for b in banners]))
        page_rows = []
        for ay, sno in anchors:
            end = min([c for c in cuts if c > ay + 1] + [ay + 40])
            band = [w for w in words if ay - 2 <= w[1] < end - 2]
            part = re.sub(r"^M\s+(?=\d)", "M-", nz.clean_text(" ".join(w[4] for w in sorted(band, key=lambda w: w[0]) if K_PART <= w[0] < K_MRP and abs(w[1] - ay) < 3)))
            mrp = nz.to_number(" ".join(w[4] for w in sorted(band, key=lambda w: w[0]) if K_MRP <= w[0] < K_DESC and abs(w[1] - ay) < 3))
            app = nz.clean_text(" ".join(w[4] for w in sorted(band, key=lambda w: (round(w[1] / 3), w[0])) if w[0] >= K_DESC))
            sub = next((t for y, k, t in reversed(banners) if k == "sub" and y < ay), "")
            div = next((t for y, k, t in reversed(banners) if k == "div" and y < ay), "")
            flags = [] if mrp is not None else ["bad_mrp"]
            up = (div + " " + sub).upper()
            kind = "Impellers" if "IMPELLER" in up and "KIT" not in up else "Kits"
            seg = "TRACTOR" if "TRACTOR" in up else "HCV" if "MOTOR VEHICLE" in up else "OTHER"
            data = {
                "part_no": part, "part_no_norm": nz.norm_part(part), "description": nz.clean_text(sub).capitalize() or "Water pump kit",
                "category": "Water Pump " + kind, "segment": seg, "oem_name": self._find_make(app.upper(), keys),
                "oem_raw": div or None, "application": app or None, "variant_label": "", "mrp": mrp, "mrp_prev": None,
                "price_basis": "unknown", "gst_pct": None, "hsn": None, "moq": None, "pack_qty": None, "unit": None,
                "image_url": None, "needs_review": False, "review_note": None, "source_page": pno, "source_row": int(sno),
                "cross_refs": [],
            }
            if not part:
                flags.append("missing_part_no")
            page_rows.append(ParsedRow(page=pno, row_no=int(sno), data=data, flags=flags))
        bad = sum(1 for r in page_rows if "bad_mrp" in r.flags)
        if bad / len(page_rows) > 0.10:
            return False
        rows.extend(page_rows)
        stat.rows += len(page_rows)
        stat.note = "repair-kit / impeller table"
        return True

    @staticmethod
    def _find_make(text, keys):
        for k in sorted(keys, key=len, reverse=True):
            if re.search(r"(?<![A-Z0-9])" + re.escape(k) + r"(?![A-Z0-9])", text):
                return keys[k]
        return None

    def _build(self, pno, sno, part, mrp_txt, desc, ref, sec, keys, title_line=""):
        flags = []
        part = re.sub(r"^M\s+(?=\d)", "M-", nz.clean_text(part))
        mrp = nz.to_number(mrp_txt)
        if mrp is None:
            flags.append("bad_mrp")
        if not part:
            flags.append("missing_part_no")
        app = nz.clean_text(desc)
        refs = []
        for token in re.split(r"\s*[/,]\s*", nz.clean_text(ref)):
            token = token.strip(" .")
            if token and nz.norm_part(token):
                refs.append({"ref_type": "oem", "ref_brand": None, "ref_part_no": token, "note": None})
        if not refs:
            flags.append("no_ref_numbers")
        title = (sec or "").upper()
        make = self._find_make(title, keys) or (None if sec else self._find_make(app.upper(), keys))
        if sec is None:
            flags.append("no_section")
        seg = "TRACTOR" if any(t in title for t in TRACTOR) else "HCV" if any(t in title for t in HCV) else \
            "CAR" if any(t in title for t in CAR) else "OTHER"
        up = title_line.upper()
        if "WATER PUMP" in up or not up:
            desc_title, category = "Water pump assembly", "Water Pumps"
        else:
            desc_title, category = up.capitalize(), "Bearing Housing & Fan Assemblies"
        data = {
            "part_no": part, "part_no_norm": nz.norm_part(part), "description": desc_title,
            "category": category, "segment": seg, "oem_name": make, "oem_raw": sec, "application": app or None,
            "variant_label": "", "mrp": mrp, "mrp_prev": None, "price_basis": "unknown", "gst_pct": None, "hsn": None,
            "moq": None, "pack_qty": None, "unit": None, "image_url": None, "needs_review": False, "review_note": None,
            "source_page": pno, "source_row": int(sno), "cross_refs": refs,
        }
        return ParsedRow(page=pno, row_no=int(sno), data=data, flags=flags)
