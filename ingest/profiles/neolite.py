"""Neolite "PRICE LIST - AFTER MARKET" (w.e.f. 01-April-2026).

Table: Product Code | Description | Unit | Std Pkg | MRP till 31.03.2026 | Revised MRP.
Between product rows sit section rows naming the vehicle group the following products fit
("MSZ 8-00 (New)", "TAL TRUK/BUS", "BEACON LIGHTS" ...). A code listed under several sections is ONE product whose
`application` lists every section; a code repeated with a different description or price is kept as a separate
row and flagged duplicate (held), never merged by guesswork.
"""
import difflib
import re

import pdfplumber

from .. import normalize as nz
from .base import PageStat, ParsedRow, ParseResult

NAME = "neolite"
BRAND_SLUG = "neolite"
PARSER_VERSION = "neolite/1.0"

MIN_WORDS_FOR_TEXT_LAYER = 30
GAP_AS_SPACE = 1.0
SWING = 0.40
CAR_MAKES = {"Maruti Suzuki", "Hyundai", "Fiat", "Chevrolet", "Ford", "Volkswagen", "Hindustan Motors", "Premier", "Toyota"}
TRACTOR_MAKES = {"Massey Ferguson", "Farmtrac", "Escorts", "Sonalika"}
CATEGORIES = [  # first match wins; matched against the description
    (r"\b(H\.?\s?L\.?|HEAD\s?LAMP|HEADLIGHT)\b", "Head Lamps"),
    (r"\b(T\.?\s?L\.?|TAIL)\b", "Tail Lamps"),
    (r"\b(S\.?\s?L\.?|SIDE)\b", "Side Lamps"),
    (r"\b(IND\.?|INDICATOR|BLINKER)\b", "Indicators"),
    (r"HORN", "Horns"),
    (r"MIRROR", "Mirrors"),
    (r"NUMBER PLATE", "Number Plate Lamps"),
    (r"BEACON|ROOF|FOG|SPOT|DRIVING|AUXILL|BRAKE LIGHT|BREAK LIGHT", "Auxiliary Lamps"),
]


class NeoliteProfile:
    name = NAME
    brand_slug = BRAND_SLUG
    parser_version = PARSER_VERSION

    def parse(self, pdf_path):
        aliases = {self._key(r["raw"]): r["make"] for r in nz.load_csv("make_aliases.csv")}
        rows, pages = [], []
        state = {"section": None, "n": 0, "unmapped": set(), "notes": []}
        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                stat = PageStat(page=pno, words=len(page.extract_words()))
                pages.append(stat)
                if stat.words < MIN_WORDS_FOR_TEXT_LAYER:
                    stat.needs_ocr, stat.note = True, "no usable text layer"
                    continue
                self._page(page, pno, stat, rows, aliases, state)
        merged = self._merge(rows, pages)
        if state["unmapped"] and pages:
            pages[0].note = (pages[0].note + "; " if pages[0].note else "") + \
                "sections with no recognised make (check make_aliases.csv): " + ", ".join(sorted(state["unmapped"]))
        if state["notes"] and pages:
            pages[0].note = (pages[0].note + "; " if pages[0].note else "") + \
                "packing note lines not attached to a row (pack_qty left blank): " + " / ".join(state["notes"])
        if merged:
            pages[-1].note = (pages[-1].note + "; " if pages[-1].note else "") + \
                f"{merged} repeated listings under other sections merged into their product"
        for p in pages:
            p.rows = sum(1 for r in rows if r.page == p.page)
        return ParseResult(rows=rows, pages=pages)

    @staticmethod
    def _key(s):
        return re.sub(r"[^A-Z0-9]", "", s.upper())

    @staticmethod
    def _text(chars, bbox):
        x0, top, x1, bottom = bbox
        hit = sorted((c for c in chars if x0 <= (c["x0"] + c["x1"]) / 2 < x1 and top <= (c["top"] + c["bottom"]) / 2 <= bottom),
                     key=lambda c: c["x0"])
        out, prev = [], None
        for c in hit:
            if prev is not None and c["x0"] - prev["x1"] > GAP_AS_SPACE:
                out.append(" ")
            out.append(c["text"])
            prev = c
        return nz.clean_text("".join(out))

    def _page(self, page, pno, stat, rows, aliases, st):
        tables = page.find_tables()
        if not tables:
            stat.unrecognised, stat.note = True, "table grid not recognised"
            return
        trs = tables[0].rows
        full = next((r.cells for r in trs if len(r.cells) == 6 and all(c is not None for c in r.cells)), None)
        if full is None:
            stat.unrecognised, stat.note = True, "no complete grid row found"
            return
        xs = [(c[0], c[2]) for c in full]
        chars = page.chars
        tb = tables[0].bbox
        body = sorted((c for c in chars if tb[0] - 1 <= c["x0"] and c["x1"] <= tb[2] + 1 and tb[1] <= c["top"] <= tb[3] and c["text"].strip()),
                      key=lambda c: c["top"])
        lines, cur = [], []
        for c in body:  # text lines, whatever the grid says: a tall grid row can hold several printed lines
            if cur and c["top"] - cur[-1]["top"] > 2.5:
                lines.append(cur)
                cur = []
            cur.append(c)
        if cur:
            lines.append(cur)
        for line in lines:
            top, bottom = min(c["top"] for c in line) - 0.5, max(c["bottom"] for c in line) + 0.5
            tx = [self._text(line, (a, top, b, bottom)) for a, b in xs]
            code = tx[0]
            if code.upper().startswith("PRODUCT CODE") or "MRP" in " ".join(tx).upper() and not nz.to_number(tx[5]):
                continue
            if not any(tx) or re.search(r"\d\d\.\d\d\.\d{4}", " ".join(tx)):
                continue
            mrp_prev, mrp = nz.to_number(tx[4]), nz.to_number(tx[5])
            if code and (mrp is not None or mrp_prev is not None or tx[1]):
                rows.append(self._build(pno, st, tx, aliases))
            elif not code:
                title = self._text(line, (xs[0][0], top, xs[-1][1], bottom))
                if title.upper().startswith("PRICE LIST"):
                    continue
                if re.search(r"\bpcs?\.?\s+each\b|\bper box\b", title, re.I):  # wrapped packing note, not a section
                    st["notes"].append(title)
                    continue
                st["section"] = self._section(title, aliases)
                if st["section"]["make"] is None and not st["section"]["generic"]:
                    st["unmapped"].add(title)

    def _section(self, title, aliases):
        make, rest = None, title
        for n in (1, 2):
            parts = re.split(r"[\s/]+", title, maxsplit=n)
            k = self._key("".join(parts[:n]))
            if len(parts) > n - 1 and k in aliases:
                make, rest = aliases[k], (parts[n] if len(parts) > n else "")
                break
        generic = bool(re.search(r"LIGHTS?|LAMPS?|HORNS?|ITEMS|RANGE|TRACTOR", title.upper()))
        label = f"{make} {rest}".strip() if make else title
        return {"title": title, "make": make, "label": label, "generic": generic}

    @staticmethod
    def _category(desc):
        for rx, cat in CATEGORIES:
            if re.search(rx, desc.upper()):
                return cat
        return "Lamps & Accessories"

    def _build(self, pno, st, tx, aliases):
        flags = []
        code = tx[0]
        desc, unit_raw = tx[1], tx[2]
        mrp_prev, mrp = nz.to_number(tx[4]), nz.to_number(tx[5])
        if mrp is None:
            flags.append("bad_mrp")
        if not code:
            flags.append("missing_part_no")
        if mrp is not None and mrp_prev:
            if abs(mrp - mrp_prev) / mrp_prev > SWING:
                flags.append("mrp_swing")
            if mrp < mrp_prev:
                flags.append("mrp_decreased")
        pack = nz.to_number(re.sub(r"[^\d.]", "", tx[3]) or None)
        sec = st["section"]
        st["n"] += 1
        data = {
            "part_no": code, "part_no_norm": nz.norm_part(code), "description": desc or None,
            "category": self._category(desc), "segment": self._segment(sec), "oem_name": sec["make"] if sec else None,
            "oem_raw": None, "application": sec["label"] if sec else None, "variant_label": "", "mrp": mrp,
            "mrp_prev": mrp_prev, "price_basis": "unknown", "gst_pct": None, "hsn": None, "moq": None,
            "pack_qty": int(pack) if pack else None, "unit": unit_raw.lower() or None, "image_url": None,
            "needs_review": False, "review_note": None, "source_page": pno, "source_row": st["n"],
        }
        if sec is None:
            flags.append("no_section")
        row = ParsedRow(page=pno, row_no=st["n"], data=data, flags=flags)
        row._sections = [sec] if sec else []
        return row

    @staticmethod
    def _segment(sec):
        if not sec:
            return "OTHER"
        t = sec["title"].upper()
        if sec["make"] in CAR_MAKES:
            return "CAR"
        if sec["make"] in TRACTOR_MAKES or "TRACTOR" in t:
            return "TRACTOR"
        if "TRUK" in t or "BUS" in t:
            return "HCV"
        return "OTHER"

    @staticmethod
    def _same_description(a, b):
        """Wording differs between sections ("W/BULB" vs "WITH BULB"); sizes and voltages must not."""
        na, nb = (re.sub(r"[^A-Z0-9 ]", " ", (x or "").upper()) for x in (a, b))
        digits = lambda t: sorted(w for w in t.split() if re.search(r"\d", w))
        if digits(na) != digits(nb):
            return False
        return difflib.SequenceMatcher(None, " ".join(na.split()), " ".join(nb.split())).ratio() >= 0.75

    def _merge(self, rows, pages):
        """Same code + same prices under several sections -> one product with many applications (other wording of its
        description is kept in review_note). Same code but a different price (W/P vs W/O/P) -> kept apart, told apart by a
        variant label made from the words that differ; if that is not possible both stay and validation holds them."""
        seen, merged, keep = {}, 0, []
        for r in rows:
            d = r.data
            twin = next((f for f in seen.get(d["part_no_norm"], [])
                         if all(f.data[x] == d[x] for x in ("mrp", "mrp_prev"))), None)
            if twin:
                merged += 1
                if not self._same_description(twin.data["description"], d["description"]):
                    alts = twin.__dict__.setdefault("_alts", [])
                    if d["description"] not in alts:
                        alts.append(d["description"])
                for sec in r._sections:
                    if sec not in twin._sections:
                        twin._sections.append(sec)
                continue
            seen.setdefault(d["part_no_norm"], []).append(r)
            keep.append(r)
        for group in seen.values():
            if len(group) > 1:
                self._label_variants(group)
        for r in keep:
            alts = getattr(r, "_alts", None)
            if alts:
                r.data["needs_review"] = True
                r.data["review_note"] = "same code and price listed with other wording: " + " | ".join(alts)[:300]
                r.flags.append("alt_descriptions")
            secs = r._sections
            if secs:
                r.data["application"] = "; ".join(dict.fromkeys(s["label"] for s in secs))
                makes = list(dict.fromkeys(s["make"] for s in secs if s["make"]))
                r.data["oem_name"] = " / ".join(makes) or None
                segs = {self._segment(s) for s in secs}
                r.data["segment"] = segs.pop() if len(segs) == 1 else "OTHER"
        rows[:] = keep
        for i, r in enumerate(rows, 1):  # listing order of the products that remain
            r.data["source_row"], r.row_no = i, i
        return merged

    @staticmethod
    def _label_variants(group):
        toks = [[t for t in re.sub(r"[^A-Z0-9/ ]", " ", (r.data["description"] or "").upper()).split()] for r in group]
        common = set.intersection(*(set(t) for t in toks))
        labels = [" ".join(t for t in ts if t not in common)[:40] for ts in toks]
        if all(labels) and len(set(labels)) == len(labels):
            for r, lab in zip(group, labels):
                r.data["variant_label"] = lab
                r.flags.append("variant_inferred")
