from pathlib import Path

import pytest

from ingest import apply as ap, parse, rollback
from ingest.profiles import get_profile
from ingest.profiles.base import HARD_FLAGS
from ingest.snapshot import snapshot
from ingest.validate import validate

SAMPLE = Path("/Users/ayusharora/Downloads/original/NEW PRICE LIST 2026 WHSN.pdf")
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="Car International sample PDF not available")


@pytest.fixture(scope="module")
def res():
    r = get_profile("car_international").parse(str(SAMPLE))
    validate(r.rows, r.pages)
    return r


def row(res, part, nth=0):
    return [r for r in res.rows if r.data["part_no"] == part][nth]


def test_row_count_and_every_page_parsed(res):
    assert len(res.rows) == 4640 and len(res.pages) == 80 and all(p.rows > 30 for p in res.pages)


def test_basic_fields_and_gst_is_not_a_dealer_rate(res):
    d = row(res, "101").data
    assert (d["mrp"], d["unit"], d["hsn"], d["gst_pct"]) == (25, "pcs", "87089900", 18)
    assert d["category"] == "Handles & Knobs" or d["category"] == "Window Regulators"


def test_vehicle_keywords_give_make_and_flag_the_rest(res):
    d = row(res, "1088/8158").data
    assert d["oem_name"] == "Maruti Suzuki" and "Alto" in d["application"]
    assert "no_vehicle_detected" in row(res, "101").flags


def test_pair_part_numbers_stay_searchable_as_printed(res):
    d = row(res, "1172/1206").data
    assert d["part_no_norm"] == "11721206"


def test_bad_hsn_flagged_not_dropped(res):
    assert "bad_hsn" in row(res, "1172/1206").flags and row(res, "1172/1206").data["hsn"] is None


def test_repeated_part_number_for_different_parts_keeps_both_with_labels(res):
    a, b = row(res, "21153A", 0), row(res, "21153A", 1)
    assert a.data["variant_label"] != b.data["variant_label"] and "variant_inferred" in b.flags
    assert "FUEL" in a.data["variant_label"] and not [r for r in res.rows if HARD_FLAGS & set(r.flags)]


def test_apply_delete_roundtrip(conn):
    conn.cursor().execute("insert into brands(name, slug) values ('Car International','car-international')")
    conn.commit()
    before = snapshot(conn)
    b = parse.upload_batch(conn, "car-international", "car_international", SAMPLE, "t")["batch_id"]
    parse.parse_batch(conn, b, "t")
    out = ap.apply_batch(conn, b, "t")
    assert out["inserted"] == 4640 and out["held"] == 0
    rollback.delete_batch(conn, b, "t", confirm=SAMPLE.name)
    assert snapshot(conn) == before
