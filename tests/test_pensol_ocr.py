import shutil
from pathlib import Path

import pytest

from ingest.profiles import get_profile
from ingest.profiles import pensol as pensol_mod
from ingest.validate import validate

SAMPLE = Path("/Users/ayusharora/Downloads/original/Automotive Dealer Price List W.e.f. 01-04-2026.pdf")
pytestmark = pytest.mark.skipif(not SAMPLE.exists() or not shutil.which("swiftc"), reason="needs the sample PDF and swiftc")


@pytest.fixture(scope="module")
def res():
    r = get_profile("pensol").parse(str(SAMPLE))
    validate(r.rows, r.pages)
    return r


def find(res, name, pack_start):
    return next(r for r in res.rows if r.data["part_no"] == name and r.data["variant_label"].startswith(pack_start))


def test_both_scanned_pages_are_read(res):
    assert [p.page for p in res.pages if p.needs_ocr or p.unrecognised] == []
    assert len(res.rows) == 205 and all("ocr" in r.flags for r in res.rows)


def test_mrp_per_pack_is_read_from_the_mrp_column_not_the_dealer_rate(res):
    assert find(res, "PENSOL URANUS PLUS", "21 LTR").data["mrp"] == 9776      # its RATE is 7251
    assert find(res, "PENSOL PXT DIESEL", "7 LTR").data["mrp"] == 2982         # its RATE is 2212
    assert find(res, "PENSOL DIAMOND EX 36000", "20 LTR").data["mrp"] == 7979  # its RATE is 5918


def test_na_means_no_mrp_not_zero(res):
    d = find(res, "PENSOL URANUS PLUS", "26 LTR")
    assert d.data["mrp"] is None and "no_mrp" in d.flags


def test_rate_column_words_never_reach_the_row_builder(monkeypatch):
    seen = []
    orig = pensol_mod.PensolProfile._panel

    def spy(self, words, idx, *a, **k):
        seen.append(list(words))
        return orig(self, words, idx, *a, **k)
    monkeypatch.setattr(pensol_mod.PensolProfile, "_panel", spy)
    get_profile("pensol").parse(str(SAMPLE))
    all_words = [w for ws in seen for w in ws]
    # 12120 / 7251 / 8909 are printed only in the RATE column of page 1 / 2
    assert not [w for w in all_words if w["t"] in ("8909", "7251", "12120")]


def test_prices_and_variants_land_on_the_right_product(res):
    assert find(res, "PENSOL APLR 30000", "18 KG").data["mrp"] == 9360
    assert find(res, "PENSOL HDBF CRIMSON PLUS", "40X250").data["mrp"] == 207
    assert find(res, "PENSOL GEAR REGULAR 140", "20 LTR").data["mrp"] == 7725
    assert find(res, "PENSOL T.S.O. (NEW)", "8.5").data["mrp"] == 4104


def test_archived_pensol_scan_has_no_rate_column_and_still_reads(tmp_path):
    from ingest.profiles.pensol import PensolProfile, rate_bands
    from ingest.ocr import ocr_png, render
    import fitz
    p = PensolProfile()
    red = p.redact(SAMPLE.read_bytes())                      # raises if any number is left in a RATE band
    out = tmp_path / "pensol_redacted.pdf"
    out.write_bytes(red)
    doc = fitz.open(out)
    for page in doc:                                         # independent re-check with unfiltered OCR, not cached
        words = ocr_png(render(page), cache=False)
        bands = rate_bands(words) or [(p + 150, p + 280) for p in sorted(w["x"] for w in words if w["t"] == "PACKING")]
        assert bands and not [w for w in words if any(lo <= w["x"] + w["w"] / 2 < hi for lo, hi in bands) and w["y"] > 560
                              and any(c.isdigit() for c in w["t"])]
    assert len(p.parse(str(out)).rows) >= 195                # the archived copy is still readable


def test_spec_lines_reach_every_pack_of_the_product(res):
    rows = [r.data for r in res.rows if r.data["part_no"] == "PENSOL PXT DIESEL"]
    assert len(rows) == 4 and all("SAE 15W 40" in d["description"] for d in rows)
    first = [r.data["description"] for r in res.rows if r.data["part_no"] == "PENSOL URANUS PLUS"]
    assert first and all("SAE 15W 40" in d for d in first)          # the first rows used to lack the grade


def test_dealer_rate_column_is_never_written_to_the_ocr_cache(res):
    import json
    from ingest.ocr import CACHE
    checked = 0
    for f in CACHE.glob("*.json"):
        words = json.loads(f.read_text())
        heads = sorted(w["x"] for w in words if w["t"] == "PACKING")
        if len(heads) != 2:
            continue
        checked += 1
        bands = [(p + 150, p + 280) for p in heads]
        leaked = [w for w in words if any(lo <= w["x"] + w["w"] / 2 < hi for lo, hi in bands)]
        assert not leaked, f"{f.name} holds {len(leaked)} words from the RATE column"
    assert checked >= 2
