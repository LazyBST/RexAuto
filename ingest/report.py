import csv
import io
import json
from collections import Counter

from .db import cursor


def batch_report(conn, batch_id):
    cur = cursor(conn)
    cur.execute("""select b.*, br.name as brand from import_batches b join brands br on br.id=b.brand_id
                   where b.id=%s""", (batch_id,))
    b = cur.fetchone()
    if b is None:
        raise SystemExit("no such batch")
    cur.execute("""select page, count(*) n, min((data->>'source_row')::int) first_no, max((data->>'source_row')::int) last_no
                   from batch_rows where batch_id=%s group by page order by page""", (batch_id,))
    pages = cur.fetchall()
    cur.execute("select flags, page, row_no, data->>'part_no' part_no, data->>'description' descr, data->>'oem_raw' oem "
                "from batch_rows where batch_id=%s and cardinality(flags) > 0 order by id", (batch_id,))
    flagged = cur.fetchall()
    by_reason = {}
    for r in flagged:
        for f in r["flags"]:
            by_reason.setdefault(f, []).append(r)
    cur.execute("select run_type, started_at, finished_at, inserted, updated, unchanged, removed, status "
                "from sync_runs where batch_id=%s order by started_at", (batch_id,))
    runs = cur.fetchall()
    return {"batch": b, "pages": pages, "by_reason": by_reason, "runs": runs, "notes": json.loads(b["notes"] or "{}")}


def render(rep):
    b = rep["batch"]
    out = [f"BATCH {b['id']}", f"  file      {b['original_filename']}  ({b['file_size_bytes']:,} bytes, {b['page_count']} pages)",
           f"  brand     {b['brand']}   profile {b['profile']}   parser {b['parser_version']}",
           f"  uploaded  {b['uploaded_at']:%Y-%m-%d %H:%M:%S %Z} by {b['uploaded_by']}   sha256 {b['file_sha256'][:16]}…",
           f"  status    {b['status']}   parse time {b['parse_seconds']}s",
           f"  rows      extracted {b['rows_extracted']}   flagged {b['rows_flagged']}   "
           f"inserted {b['rows_inserted']}  updated {b['rows_updated']}  unchanged {b['rows_unchanged']}  removed {b['rows_removed']}",
           f"  pages needing OCR (skipped): {b['pages_needing_ocr'] or 'none'}",
           f"  pages with unrecognised layout: {b['pages_unrecognised'] or 'none'}", "", "ROWS PER PAGE"]
    line = []
    for p in rep["pages"]:
        line.append(f"p{p['page']:>2}: {p['n']:>3} (#{p['first_no']}–{p['last_no']})")
    for i in range(0, len(line), 3):
        out.append("  " + "   ".join(line[i:i + 3]))
    n = rep["notes"]
    out += ["", "BATCH-LEVEL CHECKS",
            f"  serial-number gaps: {n.get('serial_gaps') or 'none'}",
            f"  pages with far fewer rows than the median: {n.get('thin_pages') or 'none'}",
            f"  page notes: {n.get('page_notes') or 'none'}", "", "FLAGGED ROWS BY REASON"]
    for reason, rows in sorted(rep["by_reason"].items(), key=lambda kv: -len(kv[1])):
        ex_ = ", ".join(f"{r['part_no'] or '∅'}" for r in rows[:4])
        out.append(f"  {reason:<22}{len(rows):>5}   e.g. {ex_}")
    if rep["runs"]:
        out += ["", "SYNC RUNS"]
        for r in rep["runs"]:
            out.append(f"  {r['run_type']:<8} {r['started_at']:%H:%M:%S}  +{r['inserted']} ~{r['updated']} ={r['unchanged']} -{r['removed']}  {r['status']}")
    return "\n".join(out)


def flagged_csv(conn, batch_id):
    cur = cursor(conn)
    cur.execute("select page, row_no, flags, data from batch_rows where batch_id=%s and cardinality(flags)>0 order by id", (batch_id,))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["page", "serial_no", "flags", "part_no", "description", "oem_raw", "application", "mrp"])
    for r in cur.fetchall():
        d = r["data"]
        w.writerow([r["page"], r["row_no"], "|".join(r["flags"]), d.get("part_no"), d.get("description"),
                    d.get("oem_raw"), d.get("application"), d.get("mrp")])
    return buf.getvalue()
