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
