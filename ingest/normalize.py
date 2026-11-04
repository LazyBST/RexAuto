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
