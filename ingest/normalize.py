import csv
import re
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "data" / "config"


def norm_part(s):
    """Part number as printed -> UPPER, only A-Z0-9."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def to_number(s):
    """'₹1,296.00' -> 1296.0 ; '' / 'NA' / junk -> None."""
    if s is None:
        return None
    t = re.sub(r"[₹,\s]", "", str(s))
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    return float(t) if "." in t else int(t)


def clean_text(s):
    return re.sub(r"\s+", " ", s or "").strip()


def load_csv(name):
    with open(CONFIG_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_aliases():
    """(map, guessed): raw code -> make, and the set of raw codes that come from the guess file
    (data/config/make_aliases_guess.csv: best guesses waiting for the owner's confirmation)."""
    amap, guessed = {}, set()
    for r in load_csv("make_aliases.csv"):
        amap[r["raw"].strip().upper()] = r["make"]
    try:
        for r in load_csv("make_aliases_guess.csv"):
            k = r["raw"].strip().upper()
            if k not in amap:
                amap[k] = r["make"]
                guessed.add(k)
    except FileNotFoundError:
        pass
    return amap, guessed


_MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def find_date(text):
    """First 'effective from' style date in a header text, as ISO yyyy-mm-dd, or None.
    Understands 01-04-2026 / 01.04.26 / 01 / 01 / 2026, 01-April-2026, APR'26 / Feb-26, APRIL 01, 2026."""
    import re
    t = re.sub(r"\s+", " ", text or "")
    m = re.search(r"\b(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2,4})\b", t)
    if m:
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        y += 2000 if y < 100 else 0
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b(\d{1,2})\s*[-. ]\s*([A-Za-z]{3,9})\s*[-. ]+\s*(\d{4})\b", t)
    if m and m[2][:3].upper() in _MONTHS:
        return f"{int(m[3]):04d}-{_MONTHS[m[2][:3].upper()]:02d}-{int(m[1]):02d}"
    m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", t)
    if m and m[1][:3].upper() in _MONTHS:
        return f"{int(m[3]):04d}-{_MONTHS[m[1][:3].upper()]:02d}-{int(m[2]):02d}"
    m = re.search(r"\b([A-Za-z]{3})['\- ]\s?(\d{2})\b", t)
    if m and m[1].upper() in _MONTHS:
        return f"20{m[2]}-{_MONTHS[m[1].upper()]:02d}-01"
    return None


def date_after(text, marker, span=48):
    """find_date() restricted to the text right after `marker` (e.g. 'WEF'), so unrelated dates are not picked up."""
    t = text or ""
    i = t.upper().find(marker.upper())
    return find_date(t[i:i + span]) if i >= 0 else None


def stamp(rows, iso):
    """Give every priced row the price list's effective date."""
    if iso:
        for r in rows:
            if "mrp" in r.data and not r.data.get("update_only"):
                r.data["price_effective_from"] = iso


def price_basis(brand_slug):
    """'incl_tax' | 'ex_tax' | 'unknown' for a brand, from data/config/price_basis.csv (owner-maintained)."""
    for r in load_csv("price_basis.csv"):
        if r["brand_slug"] == brand_slug:
            return r["basis"]
    return "unknown"
