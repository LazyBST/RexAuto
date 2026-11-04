"""One vocabulary across brands, applied to every parsed batch before it is staged (so resync keeps it consistent).
Mappings live in data/config/make_canonical.csv and category_canonical.csv; an empty canonical value means "no make"."""
from . import normalize as nz


def _load(name):
    return {r["variant"].strip(): r["canonical"].strip() for r in nz.load_csv(name)}


def canon_makes(value, table):
    parts, universal = [], False
    for p in (x.strip() for x in (value or "").split(" / ")):
        if not p:
            continue
        if p == "Universal":
            universal = True
        p = table.get(p, p)
        if p and p not in parts:
            parts.append(p)
    return (" / ".join(parts) or None), universal


def apply(rows):
    makes, cats = _load("make_canonical.csv"), _load("category_canonical.csv")
    for r in rows:
        d = r.data
        if "oem_name" in d:
            d["oem_name"], universal = canon_makes(d["oem_name"], makes)
            if universal:
                d["attributes"] = {**(d.get("attributes") or {}), "universal": True}
        if "category" in d:
            d["category"] = cats.get(d["category"], d["category"]) if d["category"] else "Uncategorised"
        if d.get("variant_label"):
            d["variant_label"] = d["variant_label"].strip()
        if d.get("part_no"):
            d["part_no"] = d["part_no"].strip()
