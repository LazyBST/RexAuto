"""Fras-le "XTRA LIFE" non-asbestos brake linings (w.e.f. 01-04-2026).

Grid with merged cells: Sr.No and Vehicle Application are one tall cell spanning every variant row of a group
(STD / OS-1 / OS-2 ...). Rows are read from the grid; a group's Sr.No + application are carried down to its rows.
Columns by index: 0 Sr.No  1 OEM  2 Segment  3 New Part No  4 Vehicle Application  5 Front/Rear
                  6 pcs per set  7 std packing (sets)  8 MRP   (prices exclude GST; HSN 68138100)
"""
import re

import pdfplumber

from .. import normalize as nz
from .base import PageStat, ParsedRow, ParseResult

NAME = "fras_le"
BRAND_SLUG = "fras-le"
PARSER_VERSION = "fras_le/1.0"

MIN_WORDS_FOR_TEXT_LAYER = 30
GAP_AS_SPACE = 1.0
SEGMENTS = {"HCV": "HCV", "LCV": "LCV", "CAR": "CAR", "TTR": "TRACTOR"}
POSITIONS = {"F": "Front", "R": "Rear", "F/R": "Front & Rear"}
PART_RE = re.compile(r"^(?P<part>.+?)\s*\((?P<var>[^)]*)\)\s*(?P<tail>.*)$")


class FrasLeProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def parse(self, pdf_path):
        aliases, self._guessed = nz.load_aliases()
        rows, pages = [], []
        state = {"group": None, "app": "", "n": 0, "groups_seen": []}
        with pdfplumber.open(pdf_path) as pdf:
            hsn = self._hsn(pdf)
            for pno, page in enumerate(pdf.pages, start=1):
                stat = PageStat(page=pno, words=len(page.extract_words()))
                pages.append(stat)
                if stat.words < MIN_WORDS_FOR_TEXT_LAYER:
                    stat.needs_ocr, stat.note = True, "no usable text layer"
                    continue
                self._page(page, pno, stat, rows, aliases, state, hsn)
        seen = state["groups_seen"]
        if seen and seen != list(range(seen[0], seen[0] + len(seen))):
            pages[0].note = (pages[0].note + "; " if pages[0].note else "") + f"group numbers not consecutive: {seen}"
        return ParseResult(rows=rows, pages=pages)

    @staticmethod
    def _hsn(pdf):
        text = pdf.pages[0].extract_text() or ""
        m = re.search(r"HSN\s*CODE\s*-?\s*([\d ]{6,12})", text)
        return re.sub(r"\D", "", m.group(1)) if m else None

    @staticmethod
    def _text(chars, bbox):
        x0, top, x1, bottom = bbox
        hit = sorted((c for c in chars if x0 <= (c["x0"] + c["x1"]) / 2 < x1 and top <= (c["top"] + c["bottom"]) / 2 <= bottom),
                     key=lambda c: (round(c["top"] / 3), c["x0"]))
        out, prev = [], None
        for c in hit:
            if prev is not None:
                if abs(c["top"] - prev["top"]) > 3 or c["x0"] - prev["x1"] > GAP_AS_SPACE:
                    out.append(" ")
            out.append(c["text"])
            prev = c
        return nz.clean_text("".join(out))

    def _page(self, page, pno, stat, rows, aliases, st, hsn):
        tables = [t for t in page.find_tables() if len(t.rows) > 5]
        if not tables:
            stat.unrecognised, stat.note = True, "table grid not recognised"
            return
        chars = page.chars
        trs = tables[0].rows
        first = True
        for r in trs:
            c = r.cells
            if len(c) != 9:
                stat.unrecognised, stat.note = True, "unexpected column count"
                return
            if c[1] is None or c[3] is None:
                continue
            part_cell = self._text(chars, c[3])
            if not part_cell or part_cell.upper().startswith("NEW PART"):
                continue
            if c[0] is not None:  # first row of a merged group: read the tall cells
                sno = self._text(chars, c[0])
                st["group"] = int(sno) if sno.isdigit() else None
                st["app"] = self._text(chars, c[4]) if c[4] is not None else ""
                if st["group"] is not None:
                    st["groups_seen"].append(st["group"])
                cont = False
            else:
                cont = first  # page starts mid-group
            first = False
            st["n"] += 1
            t = {k: self._text(chars, c[i]) for k, i in (("oem", 1), ("seg", 2), ("fr", 5), ("pcs", 6), ("pack", 7), ("mrp", 8))}
            row = self._build(pno, st, part_cell, t, aliases, hsn)
            if cont:
                row.flags.append("group_continued_from_previous_page")
            rows.append(row)
            stat.rows += 1

    def _build(self, pno, st, part_cell, t, aliases, hsn):
        flags = []
        m = PART_RE.match(part_cell)
        if m:
            part_no, variant = m.group("part").strip(), m.group("var").strip().rstrip(".").upper()
            if m.group("tail"):  # e.g. "AFF/XL/TBS6 (STD.) 10 HOLE": the suffix belongs to the part number
                part_no = f"{part_no} {m.group('tail').strip()}"
        else:
            part_no, variant = part_cell, ""
            flags.append("no_variant_in_part_no")
        mrp = nz.to_number(t["mrp"].replace("₹", ""))
        if not part_no:
            flags.append("missing_part_no")
        if mrp is None:
            flags.append("bad_mrp")
        oem_raw = t["oem"]
        oem_name = aliases.get(oem_raw.upper())
        if oem_raw and oem_name is None:
            flags.append("unknown_oem")
        elif oem_name and oem_raw.upper() in self._guessed:
            flags.append("oem_guess")
        seg = SEGMENTS.get(t["seg"].upper())
        if seg is None:
            seg = "OTHER"
            flags.append("unknown_segment")
        if t["fr"] not in POSITIONS:
            flags.append("unknown_position")
        pcs, pack = nz.to_number(t["pcs"]), nz.to_number(t["pack"])
        if pcs is None or pack is None:
            flags.append("bad_pack_info")
        if not st["app"]:
            flags.append("no_application")
        desc = "Brake lining set, " + POSITIONS.get(t["fr"], t["fr"]).lower() + (f", {int(pcs)} pcs per set" if pcs else "")
        data = {
            "part_no": part_no, "part_no_norm": nz.norm_part(part_no), "description": desc, "category": "Brake Linings",
            "segment": seg, "oem_name": oem_name, "oem_raw": oem_raw or None, "application": st["app"] or None,
            "variant_label": variant, "mrp": mrp, "mrp_prev": None, "price_basis": "ex_tax", "gst_pct": None,
            "hsn": hsn, "moq": None, "pack_qty": int(pack) if pack else None, "unit": "set", "image_url": None,
            "needs_review": False, "review_note": None, "source_page": pno, "source_row": st["n"],
        }
        return ParsedRow(page=pno, row_no=st["n"], data=data, flags=flags)
