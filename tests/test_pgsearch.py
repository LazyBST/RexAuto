from ingest import apply as ap, parse, pgsearch


def test_search_by_part_number_description_and_make(conn, small_pdf, cached_parse):
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "t")["batch_id"]
    parse.parse_batch(conn, b, "t", parse_fn=cached_parse)
    ap.apply_batch(conn, b, "t")
    r = pgsearch.search(conn, "MB 0301-2014")  # formatting-insensitive part number
    assert r["total"] >= 1 and r["hits"][0]["part_no"] == "MB03012014"
    assert pgsearch.search(conn, "tata dual brake valve")["total"] > 0
    assert pgsearch.search(conn, "tml dual brake valve")["total"] == pgsearch.search(conn, "tata dual brake valve")["total"]
    only = pgsearch.search(conn, "valve", {"make": "Tata"})
    assert all("Tata" in (h["oem_name"] or "") for h in only["hits"])
    assert pgsearch.search(conn, "zzzzqq")["total"] == 0
    assert pgsearch.product(conn, r["hits"][0]["id"])["part_no"] == "MB03012014"
