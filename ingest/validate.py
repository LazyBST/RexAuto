"""Batch-level validation. Flags rows; never drops them. Hard flags keep a row in staging only."""
import statistics
from collections import defaultdict

from .profiles.base import ATTRIBUTE_KEYS, CHILD_FIELDS, EXTRA_FIELDS, HARD_FLAGS, PRODUCT_FIELDS, REF_FIELDS  # noqa: F401

OUTLIER_FACTOR = 10
MIN_CATEGORY_SIZE = 10


def assert_whitelisted(row):
    extra = set(row.data) - PRODUCT_FIELDS - EXTRA_FIELDS
    if extra:
        raise ValueError(f"profile emitted non-whitelisted fields {sorted(extra)}; refusing to stage")
    for kind, allowed in CHILD_FIELDS.items():
        for child in row.data.get(kind) or []:
            if set(child) - allowed:
                raise ValueError(f"profile emitted non-whitelisted {kind} fields {sorted(set(child) - allowed)}")
    bad = set(row.data.get("attributes") or {}) - ATTRIBUTE_KEYS
    if bad:
        raise ValueError(f"profile emitted non-whitelisted attribute keys {sorted(bad)}")


def validate(rows, pages):
    """Mutates row.flags. Returns batch-level findings (serial gaps, thin pages)."""
    for r in rows:
        assert_whitelisted(r)

    seen = {}
    for r in rows:
        if "missing_part_no" in r.flags or not r.data["part_no_norm"]:
            continue
        key = (r.data["part_no_norm"], r.data.get("variant_label") or "")
        if key in seen:
            r.flags.append("duplicate_in_batch")
        else:
            seen[key] = r

    by_cat = defaultdict(list)
    for r in rows:
        if r.data.get("mrp") and r.data.get("category"):
            by_cat[r.data["category"]].append(r.data["mrp"])
    medians = {c: statistics.median(v) for c, v in by_cat.items() if len(v) >= MIN_CATEGORY_SIZE}
    for r in rows:
        m = medians.get(r.data.get("category"))
        if m and r.data.get("mrp") and r.data["mrp"] > OUTLIER_FACTOR * m:
            r.flags.append("mrp_outlier")

    findings = {"serial_gaps": [], "thin_pages": []}
    serials = [r.data["source_row"] for r in rows if r.data.get("source_row")]
    for a, b in zip(serials, serials[1:]):
        if b != a + 1:
            findings["serial_gaps"].append([a, b])
    counts = [p.rows for p in pages if p.rows]
    if counts:
        med = statistics.median(counts)
        findings["thin_pages"] = [{"page": p.page, "rows": p.rows} for p in pages
                                  if not p.needs_ocr and not p.unrecognised and p.rows < 0.5 * med]
    return findings
