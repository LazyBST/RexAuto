"""Car International (CI) PRICE LIST Feb-26.

Grid: PART NO | DESCRIPTION | NEW LIST (price) | UNIT | HSN | RATE.  The last column is the GST rate (18%), not a
dealer rate, and goes to gst_pct.  There is no vehicle column: make and model are looked up from keywords in the
description (data/config/vehicle_keywords.csv). Rows with no recognised vehicle are flagged, never guessed.
A printed pair of numbers ("141/1203") stays as printed in part_no; both numbers are searchable.
"""
import re

import pdfplumber

from .. import normalize as nz
from .base import PageStat, ParsedRow, ParseResult

NAME = "car_international"
BRAND_SLUG = "car-international"
PARSER_VERSION = "car_international/1.0"

MIN_WORDS_FOR_TEXT_LAYER = 30
GAP_AS_SPACE = 1.0
CATEGORIES = [  # first match wins, matched against the upper-cased description
    (r"FILTER", "Filters"),
    (r"\bW\.?\s?R\.?\b|REGULATOR", "Window Regulators"),
    (r"MIRROR|ORVM|\bRVM\b", "Mirrors"),
    (r"WIPER", "Wipers"),
    (r"LOCK|KEY|LATCH|STRIKER", "Locks & Keys"),
    (r"HANDLE|\bO\.?\s?H\.?\b|KNOB", "Handles & Knobs"),
    (r"CABLE|WIRE", "Cables"),
    (r"SWITCH|SENSOR|RELAY|CONNECTOR|\bMOTOR\b", "Switches & Sensors"),
    (r"HINGE|STOPPER|SHOCKER|SPRING|BRACKET|HOOK|CHANNEL", "Hinges, Stoppers & Brackets"),
    (r"BONNET|DICKY|DICKEY|BAGGAGE|CANOPY|GRILL|BUMPER|DOOR|CABIN|GLASS|PLATE|TANK|COVER", "Body Parts"),
    (r"CLUTCH|BRAKE|GEAR|STEERING|WHEEL|SHOE|BELT", "Mechanical Parts"),
    (r"LAMP|LIGHT|BLINKER|INDICATOR", "Lamps"),
]


class CarInternationalProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def parse(self, pdf_path):
        kws = []
        for r in nz.load_csv("vehicle_keywords.csv"):
            kws.append((re.compile(r"(?<![A-Z0-9])" + re.escape(r["keyword"].upper()) + r"(?![A-Z0-9])"), r["keyword"].upper(),
                        r["make"], r["segment"]))
        rows, pages = [], []
        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                stat = PageStat(page=pno, words=len(page.extract_words()))
                pages.append(stat)
                if stat.words < MIN_WORDS_FOR_TEXT_LAYER:
                    stat.needs_ocr, stat.note = True, "no usable text layer"
                    continue
                self._page(page, pno, stat, rows, kws)
        self._label_repeats(rows)
        return ParseResult(rows=rows, pages=pages)

    @staticmethod
    def _label_repeats(rows):
        """The same part number printed for two different parts: keep both, told apart by the words that differ
        (e.g. 'FUEL' vs 'AIR'). If that cannot separate them, validation holds the later ones."""
        groups = {}
        for r in rows:
            groups.setdefault(r.data["part_no_norm"], []).append(r)
        for g in (g for g in groups.values() if len(g) > 1):
            toks = [re.sub(r"[^A-Z0-9/ ]", " ", (r.data["description"] or "").upper()).split() for r in g]
            common = set.intersection(*(set(t) for t in toks))
            labels = [" ".join(t for t in ts if t not in common)[:40] for ts in toks]
            if all(labels) and len(set(labels)) == len(labels):
                for r, lab in zip(g, labels):
                    r.data["variant_label"] = lab
                    r.flags.append("variant_inferred")

    @staticmethod
    def _text(chars, bbox):
        x0, top, x1, bottom = bbox
        hit = sorted((c for c in chars if x0 <= (c["x0"] + c["x1"]) / 2 < x1 and top <= (c["top"] + c["bottom"]) / 2 <= bottom),
                     key=lambda c: (round(c["top"] / 3), c["x0"]))
        out, prev = [], None
        for c in hit:
            if prev is not None and (abs(c["top"] - prev["top"]) > 3 or c["x0"] - prev["x1"] > GAP_AS_SPACE):
                out.append(" ")
            out.append(c["text"])
            prev = c
        return nz.clean_text("".join(out))

    def _page(self, page, pno, stat, rows, kws):
        tables = page.find_tables()
        if not tables:
            stat.unrecognised, stat.note = True, "table grid not recognised"
            return
        trs = tables[0].rows
        if not trs or any(len(r.cells) != 6 for r in trs):
            stat.unrecognised, stat.note = True, "unexpected column count"
            return
        xs = [(29, 77), (77, 403), (403, 443), (443, 473), (473, 518), (518, 558)]
        full = next((r.cells for r in trs if all(c is not None for c in r.cells)), None)
        if full:
            xs = [(c[0], c[2]) for c in full]
        chars = page.chars
        for r in trs:
            live = [c for c in r.cells if c is not None]
            top, bottom = min(c[1] for c in live), max(c[3] for c in live)
            tx = [self._text(chars, (a, top, b, bottom)) for a, b in xs]
            if not tx[0] or tx[0].upper() == "PART NO":
                continue  # title / header rows
            rows.append(self._build(pno, len(rows) + 1, tx, kws))
            stat.rows += 1

    @staticmethod
    def _category(desc):
        d = desc.upper()
        for rx, cat in CATEGORIES:
            if re.search(rx, d):
                return cat
        return "Other Parts"

    def _build(self, pno, n, tx, kws):
        part, desc, price, unit, hsn_raw, gst_raw = tx
        flags = []
        mrp = nz.to_number(price)
        if mrp is None:
            flags.append("bad_mrp")
        hsn = re.sub(r"\D", "", hsn_raw)
        if not 6 <= len(hsn) <= 8 or hsn_raw.endswith("+"):
            flags.append("bad_hsn")
            hsn = hsn or None
        gst = nz.to_number(gst_raw.replace("%", ""))
        d = desc.upper()
        found = [(k, m, s) for rx, k, m, s in kws if rx.search(d)]
        makes = list(dict.fromkeys(m for _, m, _ in found if m))
        models = list(dict.fromkeys(k.title() for k, m, _ in found if m and k != m.upper()))
        segs = [s for _, _, s in found if s]
        segment = next((s for s in ("HCV", "LCV", "CAR", "OTHER") if s in segs), "OTHER")
        if not makes and re.search(r"(?<![A-Z0-9])VAN(?![A-Z0-9])", d) and not segs:
            # "VAN" with no other vehicle named: the Maruti vans (Omni / Eeco) are what these catalogue lines mean
            makes, segment = ["Maruti Suzuki"], "CAR"
            flags.append("vehicle_guess")
        elif not found:
            flags.append("no_vehicle_detected")
        data = {
            "part_no": part, "part_no_norm": nz.norm_part(part), "description": desc or None,
            "category": self._category(desc), "segment": segment, "oem_name": " / ".join(makes) or None,
            "oem_raw": None, "application": ", ".join(models) or None, "variant_label": "", "mrp": mrp, "mrp_prev": None,
            "price_basis": "unknown", "gst_pct": gst, "hsn": hsn, "moq": None, "pack_qty": None,
            "unit": unit.lower() or None, "image_url": None, "needs_review": False, "review_note": None,
            "source_page": pno, "source_row": n,
        }
        if not part:
            flags.append("missing_part_no")
        return ParsedRow(page=pno, row_no=n, data=data, flags=flags)
