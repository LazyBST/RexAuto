"""Hard rule: no discount / dealer rate / trade cut / margin / net price anywhere we store or emit."""
import json
import re

import pytest

from ingest import apply as ap, index, parse, report
from ingest.profiles import uno_minda
from ingest.profiles.base import PRODUCT_FIELDS

from ingest.rules import bad_name  # noqa: E402


def test_whitelist_has_no_forbidden_names():
    assert not [f for f in PRODUCT_FIELDS if bad_name(f)]


def test_schema_has_no_forbidden_columns(conn):
    cur = conn.cursor()
    cur.execute("select table_name, column_name from information_schema.columns where table_schema='public'")
    assert not [(t, c) for t, c in cur.fetchall() if bad_name(c)]


def test_profile_never_reads_the_skipped_column(small_pdf, monkeypatch):
    """Every text lookup the profile makes must stay clear of the trade-discount column's x-range."""
    calls = []
    orig = uno_minda.UnoMindaProfile._cell_text

    def spy(chars, bbox, used=None):
        calls.append((bbox, [c for c in chars]))
        return orig(chars, bbox, used)

    monkeypatch.setattr(uno_minda.UnoMindaProfile, "_cell_text", staticmethod(spy))
    uno_minda.UnoMindaProfile().parse(str(small_pdf))
    assert calls
    skip_lo, skip_hi = 502.9, 529.0
    for bbox, chars in calls:
        assert bbox[2] <= skip_lo + 0.5 or bbox[0] >= skip_hi - 0.5, f"lookup {bbox} overlaps the skipped column"
        for c in chars:  # the chars handed to the lookups were pre-filtered
            assert not (skip_lo <= (c["x0"] + c["x1"]) / 2 <= skip_hi)


def test_profile_output_only_whitelisted(parsed_small):
    for r in parsed_small.rows:
        assert set(r.data) <= PRODUCT_FIELDS


def test_staging_index_csv_and_audit_clean(conn, small_pdf, cached_parse):
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, b, "t", parse_fn=cached_parse)
    ap.apply_batch(conn, b, "t")
    cur = conn.cursor()
    cur.execute("select distinct jsonb_object_keys(data) from batch_rows")
    assert not [k for (k,) in cur.fetchall() if bad_name(k)]
    cur.execute("select distinct jsonb_object_keys(details) from audit_events")
    assert not [k for (k,) in cur.fetchall() if bad_name(k)]
    cur.execute("select distinct jsonb_object_keys(after) from change_log where after is not null")
    assert not [k for (k,) in cur.fetchall() if bad_name(k)]
    header = report.flagged_csv(conn, b).splitlines()[0].split(",")
    assert not [h for h in header if bad_name(h)]
    cur.execute("select id from products")
    docs = index.documents(conn, [r[0] for r in cur.fetchall()])
    assert docs and not [k for d in docs for k in d if bad_name(k)]


def test_archived_copy_is_redacted_and_parses_identically(conn, small_pdf, parsed_small, monkeypatch):
    monkeypatch.setenv("REDACT_ON_UPLOAD", "1")
    import pdfplumber
    from ingest.storage import get_storage
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    cur = conn.cursor()
    cur.execute("select stored_path, redacted, stored_sha256, file_sha256 from import_batches where id=%s", (b,))
    path, redacted, stored_sha, up_sha = cur.fetchone()
    assert redacted and stored_sha != up_sha
    archived = get_storage().local_path(path)
    with pdfplumber.open(archived) as pdf:
        for page in pdf.pages:
            text = " ".join(c["text"] for c in page.chars if 503 <= (c["x0"] + c["x1"]) / 2 <= 529)
            assert "%" not in text and "TD" not in text
    again = uno_minda.UnoMindaProfile().parse(str(archived))
    assert [(r.data, r.flags) for r in again.rows] == [(r.data, r.flags) for r in parsed_small.rows]


@pytest.mark.parametrize("name", ["discount_pct", "td_pct", "dealer_price", "trade_cut", "net_price", "margin", "scheme_amt",
                                  "cut_pct", "distributor_rate", "dealer_rate", "cd_pct", "ndp", "dp", "wholesale_price",
                                  "purchase_price", "landing_cost", "cost_price", "TDPercent", "tradeDiscount", "tdpct",
                                  "dealerrate", "disc", "discount%"])
def test_every_plausible_discount_name_would_fail_the_build(name):
    assert bad_name(name)


@pytest.mark.parametrize("name", ["gst_pct", "mrp", "mrp_prev", "part_no", "price_basis", "pack_qty", "price_effective_from",
                                  "attributes", "locked_fields", "image_url", "stock_status"])
def test_real_columns_are_not_flagged(name):
    assert not bad_name(name)


def test_every_real_column_and_attribute_key_is_clean(conn):
    from ingest.profiles.base import ATTRIBUTE_KEYS, CHILD_FIELDS
    cur = conn.cursor()
    cur.execute("select table_name, column_name from information_schema.columns where table_schema='public'")
    assert not [(t, c) for t, c in cur.fetchall() if bad_name(c)]
    assert not [k for k in ATTRIBUTE_KEYS | {f for v in CHILD_FIELDS.values() for f in v} if bad_name(k)]
