"""Things that are expensive to change after the hosted database is loaded: child tables, hand-edit locks, attributes."""
import copy

import pytest

from ingest import apply as ap, parse, rollback
from ingest.db import cursor
from ingest.profiles.base import ATTRIBUTE_KEYS
from ingest.snapshot import snapshot


def with_children(parsed, n=3):
    def fn(_path):
        res = copy.deepcopy(parsed)
        for i, r in enumerate(res.rows[:n]):
            r.data["images"] = [{"url": f"/img/x{i}a.jpg", "kind": "photo", "sort": 0}, {"url": f"/img/x{i}b.jpg", "kind": "diagram", "sort": 1}]
            r.data["fitments"] = [{"make": "Tata", "model": "1612", "year_from": 2008, "year_to": 2015, "engine": "697"}]
            r.data["attributes"] = {"pcs_per_set": 8}
        return res
    return fn


def test_images_fitments_attributes_roundtrip(conn, small_pdf, parsed_small, cached_parse):
    base = snapshot(conn)
    a = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, a, "t", parse_fn=cached_parse)
    ap.apply_batch(conn, a, "t")
    after_a = snapshot(conn)
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, b, "t", parse_fn=with_children(parsed_small))
    prev = ap.preview(conn, b)
    assert prev["update"] == 3 and {"images", "fitments", "attributes"} <= set(prev["sample_updates"][0]["changes"])
    ap.apply_batch(conn, b, "t")
    cur = cursor(conn)
    cur.execute("select count(*) n from product_images"); assert cur.fetchone()["n"] == 6
    cur.execute("select count(*) n from fitments where year_from = 2008"); assert cur.fetchone()["n"] == 3
    # an unchanged re-apply of the same file changes nothing
    parse.parse_batch(conn, b, "t", parse_fn=with_children(parsed_small))
    assert ap.preview(conn, b)["update"] == 0
    rollback.delete_batch(conn, b, "t", confirm="um_small.pdf")
    assert snapshot(conn) == after_a            # children and attributes come back exactly as they were
    rollback.delete_batch(conn, a, "t", confirm="um_small.pdf")
    assert snapshot(conn) == base


def test_hand_edited_fields_survive_a_resync(conn, small_pdf, parsed_small, cached_parse):
    a = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, a, "t", parse_fn=cached_parse)
    ap.apply_batch(conn, a, "t")
    cur = cursor(conn)
    part = parsed_small.rows[0].data["part_no"]
    cur.execute("update products set mrp = 1111, locked_fields = array['mrp'] where part_no = %s", (part,))
    conn.commit()

    def newer(_path):
        res = copy.deepcopy(parsed_small)
        res.rows[0].data["mrp"] = 9999                   # the file now says something else about the locked field
        res.rows[0].data["description"] = "NEW WORDING"  # ... and about an unlocked one
        return res
    parse.parse_batch(conn, a, "t", parse_fn=newer)
    prev = ap.preview(conn, a)
    assert prev["update"] == 1 and list(prev["sample_updates"][0]["changes"]) == ["description"]
    ap.apply_batch(conn, a, "t")
    cur.execute("select mrp, description from products where part_no = %s", (part,))
    r = cur.fetchone()
    assert float(r["mrp"]) == 1111 and r["description"] == "NEW WORDING"


def test_history_cannot_be_truncated(conn):
    cur = conn.cursor()
    for t in ("audit_events", "change_log"):
        with pytest.raises(Exception):
            cur.execute(f"truncate {t}")
        conn.rollback()


def test_children_of_hidden_products_are_not_public(conn, small_pdf, cached_parse):
    a = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, a, "t", parse_fn=cached_parse)
    ap.apply_batch(conn, a, "t")
    cur = conn.cursor()
    cur.execute("select definition from pg_policies where tablename in ('cross_refs','product_images','fitments')") if False else None
    cur.execute("select tablename, qual from pg_policies where schemaname='public' and tablename in ('cross_refs','product_images','fitments')")
    rows = cur.fetchall()
    assert len(rows) == 3 and all("published" in q for _, q in rows)


def test_attribute_keys_never_name_a_discount():
    import re
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from test_never_stored import bad_name
    assert not [k for k in ATTRIBUTE_KEYS if bad_name(k)]


def test_variant_labels_are_trimmed_by_the_pipeline(conn, small_pdf, parsed_small):
    def fn(_path):
        res = copy.deepcopy(parsed_small)
        res.rows[0].data["variant_label"] = "OS-1  "
        return res
    a = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, a, "t", parse_fn=fn)
    ap.apply_batch(conn, a, "t")
    cur = cursor(conn)
    cur.execute("select count(*) n from products where variant_label <> btrim(variant_label)")
    assert cur.fetchone()["n"] == 0


def test_gst_basis_is_a_toggle_on_the_batch_and_needs_no_resync(conn, small_pdf, cached_parse):
    from ingest import pgsearch
    a = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, a, "t", parse_fn=cached_parse)
    ap.apply_batch(conn, a, "t")
    cur = cursor(conn)
    cur.execute("select price_includes_gst from import_batches where id=%s", (a,))
    assert cur.fetchone()["price_includes_gst"] is None                      # not known yet
    snap = snapshot(conn)
    hit = lambda: pgsearch.search(conn, "MB03012014")["hits"][0]["price_basis"]
    assert hit() == "unknown"
    assert parse.set_price_includes_gst(conn, "t", True, batch_id=a) == 1
    assert hit() == "incl_tax"
    parse.set_price_includes_gst(conn, "t", False, brand_slug="uno-minda")
    assert hit() == "ex_tax"
    parse.set_price_includes_gst(conn, "t", None, batch_id=a)
    assert hit() == "unknown"
    assert snapshot(conn) == snap                                             # no product row was touched
    cur.execute("select count(*) n from audit_events where event_type='price_basis_changed'")
    assert cur.fetchone()["n"] == 3
    cur.execute("select count(*) n from products where mrp is not null and mrp_batch_id is null")
    assert cur.fetchone()["n"] == 0
