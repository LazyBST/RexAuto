"""The never-stored rule: no discount, dealer rate, trade cut, margin or net price is ever stored. One definition of
"a forbidden name", used by the tests and by the post-load verify command."""
import re

FORBIDDEN = {"discount", "disc", "td", "rate", "dealer", "trade", "margin", "net", "scheme", "cut", "distributor",
             "cd", "ndp", "dp", "wholesale", "purchase", "landing", "cost"}
STRONG = ("discount", "dealer", "margin", "scheme", "wholesale", "purchase", "landing", "distributor", "tradedisc", "dealerrate")
ALLOWED = {"gst_pct"}      # GST % is a tax rate, not a dealer rate


def bad_name(name):
    if name in ALLOWED:
        return False
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()      # camelCase -> camel_case
    if FORBIDDEN & set(re.split(r"[^a-z0-9]+", spaced)):
        return True
    flat = re.sub(r"[^a-z0-9]", "", spaced)
    return any(s in flat for s in STRONG) or bool(re.fullmatch(r"(td|cd|dp|ndp)(pct|percent|perc|amt|val)?", flat))
