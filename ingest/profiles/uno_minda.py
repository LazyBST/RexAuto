"""Uno Minda "MASTER PRICE LIST" (4WH SEGMENTS, WEF APR'26).

Table with a text layer and cell borders. Columns, by index:
 0 S.No  1 PART NO  2 P'GROUP  3 DESCRIPTION  4 CLASS  5 SEGMENT  6 PRODUCT TYPE  7 OEM
 8 APPLICATION  9 NPD STATUS  10 MOQ  11 GST%  12 <trade discount, NEVER READ>  13 HSN  14 MRP

The trade-discount column is excluded by whitelist: words that sit in that column's x-range are
discarded before any row is built, and no code path ever reads their text.
"""
import io
import re

import pdfplumber

from .. import normalize as nz
from .base import PageStat, ParsedRow, ParseResult

NAME = "uno_minda"
BRAND_SLUG = "uno-minda"
PARSER_VERSION = "uno_minda/1.0"

SKIP_COL = 12  # trade-discount column: geometry only, text is never read
COLS = {
    0: "sno", 1: "part_no", 2: "pgroup", 3: "description", 4: "class", 5: "segment",
    6: "ptype", 7: "oem", 8: "application", 9: "npd", 10: "moq", 11: "gst", 13: "hsn", 14: "mrp",
}
# header sanity: column index -> token that must appear in that header cell
HEADER_CHECK = {1: "PART", 2: "GROUP", 3: "DESC", 7: "OEM", 8: "APPLIC", 10: "MOQ", 11: "GST", 13: "HSN", 14: "MRP"}
MIN_WORDS_FOR_TEXT_LAYER = 30
PGROUP_TEXT_START = 82.0
GAP_AS_SPACE = 1.0
SEGMENTS = {"HCV": "HCV", "CAR": "CAR", "TTR": "TRACTOR", "LCV": "LCV"}
SEGMENT_GUESSES = {"4WH": "CAR"}  # the segment cell repeats the CLASS value on some rows; these are mostly car parts


class UnoMindaProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def __init__(self):
        self._ctx = None

    def redact(self, data):
        """Return the PDF with the trade-discount column physically removed (text deleted, grid lines kept).
        The column's x-range is read once from the table grid, then the whole strip is cleared on every page; a page whose
        header does not show the column where expected gets its own grid lookup. Fails closed: raises if any text is left."""
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        band = None
        for page in doc:
            tabs = page.find_tables().tables
            geo = next((r.cells[SKIP_COL] for r in tabs[0].rows if len(r.cells) > SKIP_COL and r.cells[SKIP_COL]), None) if tabs else None
            if geo:
                band = (geo[0] + 0.2, geo[2] - 0.2)
                break
        if band is None:
            raise RuntimeError("redaction: could not locate the discount column")
        zones = {}
        for i, page in enumerate(doc):
            rect = fitz.Rect(band[0], 40, band[1], page.rect.height - 15)
            if not any(w[4].upper().startswith("TD") for w in page.get_text("words", clip=rect)):   # header not where expected
                tabs = page.find_tables().tables
                geo = next((r.cells[SKIP_COL] for r in tabs[0].rows if len(r.cells) > SKIP_COL and r.cells[SKIP_COL]), None) if tabs else None
                if not geo:
                    raise RuntimeError(f"redaction: discount column not found on page {i + 1}")
                rect = fitz.Rect(geo[0] + 0.2, 40, geo[2] - 0.2, page.rect.height - 15)
            zones[i] = rect
            page.add_redact_annot(rect, fill=False)
            page.apply_redactions(images=0, graphics=0, text=0)
        out = doc.tobytes(garbage=1, deflate=True)
        check = fitz.open(stream=out, filetype="pdf")
        for i, rect in zones.items():
            left = check[i].get_text("words", clip=rect)
            if left:
                raise RuntimeError(f"redaction failed on page {i + 1}: {len(left)} words remain")
        return out

    def _load_config(self):
        aliases, self._guessed = nz.load_aliases()
        cats = {r["source_code"].strip().upper(): r["category"]
                for r in nz.load_csv("category_map.csv") if r["brand_slug"] == BRAND_SLUG}
        return aliases, cats

    def parse(self, pdf_path):
        aliases, cats = self._load_config()
        rows, pages, eff = [], [], None
        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                stat = PageStat(page=pno)
                if pno == 1:
                    eff = nz.date_after(page.extract_text(), "WEF")
                pages.append(stat)
                words = page.extract_words(x_tolerance=1.5, y_tolerance=2)
                stat.words = len(words)
                if len(words) < MIN_WORDS_FOR_TEXT_LAYER:
                    stat.needs_ocr = True
                    stat.note = "no usable text layer"
                    continue
                self._parse_page(page, pno, page.chars, stat, rows, aliases, cats)
        nz.stamp(rows, eff)
        return ParseResult(rows=rows, pages=pages)

    def _parse_page(self, page, pno, chars, stat, rows, aliases, cats):
        tables = page.find_tables()
        if not tables or len(tables[0].rows) < 2 or any(len(r.cells) != 15 for r in tables[0].rows):
            stat.unrecognised, stat.note = True, "table grid not recognised"
            return
        trs = tables[0].rows
        # geometry only: find the skipped column's x-range and drop its characters before ANY text lookup
        geo = next((r.cells[SKIP_COL] for r in trs if r.cells[SKIP_COL] is not None), None)
        if geo is None:
            stat.unrecognised, stat.note = True, "table grid not recognised"
            return
        chars = [c for c in chars if not (geo[0] <= (c["x0"] + c["x1"]) / 2 <= geo[2])]
        hdr_idx = next((i for i, r in enumerate(trs) if r.cells[0] is not None and r.cells[1] is not None
                        and re.fullmatch(r"S\.?\s*NO\.?", self._cell_text(chars, r.cells[0]).upper())), None)
        if hdr_idx is None:
            stat.unrecognised, stat.note = True, "header row not found"
            return
        hdr = trs[hdr_idx]
        for ci, tok in HEADER_CHECK.items():
            if hdr.cells[ci] is None or tok not in self._cell_text(chars, hdr.cells[ci]).upper():
                stat.unrecognised, stat.note = True, f"header mismatch in column {ci}"
                return


        # the column grid comes from the header row; each data row only supplies its y-band
        colx = {ci: (hdr.cells[ci][0], hdr.cells[ci][2]) for ci in COLS}
        # long part numbers overflow into the P'GROUP cell; the group text itself always starts at x~83
        colx[1] = (colx[1][0], PGROUP_TEXT_START)
        colx[2] = (PGROUP_TEXT_START, colx[2][1])
        used = set()
        skipped = 0
        for r in trs[hdr_idx + 1:]:
            live = [c for c in r.cells if c is not None]
            if not live:
                continue
            top, bottom = min(c[1] for c in live), max(c[3] for c in live)
            band = [c for c in chars if top <= (c["top"] + c["bottom"]) / 2 <= bottom]
            cells = {key: self._cell_text(band, (colx[ci][0], top, colx[ci][1], bottom), used)
                     for ci, key in COLS.items()}
            if not cells["sno"].isdigit():
                skipped += 1  # footer / blank line inside the grid, not a product row
                continue
            rows.append(self._build(pno, cells, aliases, cats))
            stat.rows += 1
        notes = []
        if skipped:
            notes.append(f"{skipped} non-product grid rows skipped")
        # words inside the table body that landed in no cell: report, never drop silently
        top = trs[hdr_idx + 1].cells[0][1] if trs[hdr_idx + 1].cells[0] else 0
        orphans = [c for c in chars if id(c) not in used and c["top"] >= top - 1 and c["text"].strip()
                   and c["x0"] >= tables[0].bbox[0] - 1 and c["x1"] <= tables[0].bbox[2] + 1
                   and c["bottom"] <= tables[0].bbox[3] + 1]
        if orphans:
            notes.append(f"{len(orphans)} characters outside any column: " + "".join(c["text"] for c in orphans[:12]))
        stat.note = "; ".join(notes)

    @staticmethod
    def _cell_text(chars, bbox, used=None):
        """Text of the characters whose centre lies in bbox; a visible gap between characters becomes a space."""
        x0, top, x1, bottom = bbox
        hit = [c for c in chars
               if x0 <= (c["x0"] + c["x1"]) / 2 < x1 and top <= (c["top"] + c["bottom"]) / 2 <= bottom]
        # a cell can hold several printed lines: read line by line (top to bottom), each left to right
        hit.sort(key=lambda c: c["top"])
        lines, cur = [], []
        for c in hit:
            if cur and c["top"] - cur[0]["top"] > 2.5:
                lines.append(cur)
                cur = []
            cur.append(c)
        if cur:
            lines.append(cur)
        hit = [c for ln in lines for c in sorted(ln, key=lambda c: c["x0"])]
        if used is not None:
            used.update(id(c) for c in hit)
        out, prev = [], None
        for c in hit:
            if prev is not None and (c["top"] - prev["top"] > 2.5 or c["x0"] - prev["x1"] > GAP_AS_SPACE) and not c["text"].isspace():
                out.append(" ")
            out.append(c["text"])
            prev = c
        return nz.clean_text("".join(out))

    def _build(self, pno, c, aliases, cats):
        flags = []
        part_no = c["part_no"]
        mrp_raw = c["mrp"]
        mrp = nz.to_number(mrp_raw)
        if not part_no:
            flags.append("missing_part_no")
        elif len(part_no) > 18:
            flags.append("long_part_no")
        if mrp is None and mrp_raw.upper() not in ("", "NA", "N/A", "-"):
            flags.append("bad_mrp")
        elif mrp is None:
            flags.append("no_mrp")

        oem_raw = c["oem"]
        oem_name = self._map_oem(oem_raw, aliases)
        if oem_raw not in ("", "-") and oem_name is None:
            flags.append("unknown_oem")
        elif oem_name and self._uses_guess(oem_raw):
            flags.append("oem_guess")
        pgroup = c["pgroup"].upper()
        category = cats.get(pgroup)
        if category is None:
            flags.append("unknown_pgroup")
        seg = SEGMENTS.get(c["segment"].upper())
        if seg is None and c["segment"].upper() in SEGMENT_GUESSES:
            seg = SEGMENT_GUESSES[c["segment"].upper()]
            flags.append("segment_guess")
        elif seg is None:
            seg = "OTHER"
            flags.append("unknown_segment")
        hsn = re.sub(r"\D", "", c["hsn"])
        if not 6 <= len(hsn) <= 8:
            flags.append("bad_hsn")
        gst = nz.to_number(c["gst"].replace("%", ""))
        moq = nz.to_number(c["moq"])

        desc = c["description"]
        if not desc and c["application"]:           # the source row has an empty DESCRIPTION cell: show what it is used for
            desc = c["application"]
            flags.append("description_from_application")
        clipped = self._looks_clipped(desc)
        if clipped:
            flags.append("clipped_description")

        data = {
            "part_no": part_no,
            "part_no_norm": nz.norm_part(part_no),
            "description": desc or None,
            "category": category,
            "segment": seg,
            "oem_name": oem_name,
            "oem_raw": oem_raw or None,
            "application": c["application"] or None,
            "variant_label": "",
            "mrp": mrp,
            "mrp_prev": None,
            "price_basis": nz.price_basis(BRAND_SLUG),
            "gst_pct": gst,
            "hsn": hsn or None,
            "moq": int(moq) if moq is not None else None,
            "pack_qty": None,
            "unit": None,
            "image_url": None,
            "attributes": {k: v for k, v in {"pgroup": c["pgroup"], "class": c["class"], "product_type": c["ptype"],
                                              "npd_status": c["npd"]}.items() if v},
            "needs_review": bool(clipped),
            "review_note": "description looks clipped in the source" if clipped else None,
            "source_page": pno,
            "source_row": int(c["sno"]) if c["sno"].isdigit() else None,
        }
        return ParsedRow(page=pno, row_no=data["source_row"] or 0, data=data, flags=flags)

    def _uses_guess(self, raw):
        parts = [raw.upper().strip()] + [p.strip() for p in re.split(r"[/,&]", raw.upper()) if p.strip()]
        return any(p in getattr(self, "_guessed", ()) or p.strip(".") in getattr(self, "_guessed", ()) for p in parts)

    @staticmethod
    def _map_oem(raw, aliases):
        """'TTA./ VECV/ ASLY' -> 'Tata / Eicher / Ashok Leyland'. Any unmapped part -> None (flagged)."""
        whole = aliases.get(raw.upper().strip())
        if whole:
            return whole
        parts = [p.strip() for p in re.split(r"[/,]", raw.upper()) if p.strip()]
        if not parts:
            return None
        mapped = [aliases.get(p) or aliases.get(p.strip(".")) for p in parts]
        if not all(mapped):
            return None
        return " / ".join(dict.fromkeys(mapped))

    @staticmethod
    def _looks_clipped(desc):
        if not desc:
            return False
        if desc.count("(") > desc.count(")") or desc.count("[") > desc.count("]"):
            return True
        return desc[-1] in "-,/&+" 
