from dataclasses import dataclass, field

# The ONLY keys a profile may emit. Anything else is a bug and aborts the parse.
PRODUCT_FIELDS = frozenset({
    "part_no", "part_no_norm", "description", "category", "segment", "oem_name", "oem_raw",
    "application", "variant_label", "mrp", "mrp_prev", "price_basis", "gst_pct", "hsn", "moq",
    "pack_qty", "unit", "image_url", "needs_review", "review_note", "source_page", "source_row",
})

# Optional staged key holding the product's cross references (OEM / competitor numbers):
#   [{"ref_type": "oem", "ref_brand": None, "ref_part_no": "2525 2010 0103", "note": None}, ...]
# Only managed when a profile emits it; profiles that never emit it leave existing cross refs untouched.
EXTRA_FIELDS = frozenset({"cross_refs", "update_only"})
# "update_only": True marks an enrichment row (e.g. photos from a catalogue): it carries the identifying keys plus only the
# fields to set; it never inserts a product and never touches fields it does not carry.
REF_FIELDS = frozenset({"ref_type", "ref_brand", "ref_part_no", "note"})

# hard flags: row is held in staging and never applied
HARD_FLAGS = frozenset({"missing_part_no", "bad_mrp", "duplicate_in_batch"})


@dataclass
class ParsedRow:
    page: int
    row_no: int
    data: dict
    flags: list = field(default_factory=list)


@dataclass
class PageStat:
    page: int
    rows: int = 0
    words: int = 0
    needs_ocr: bool = False
    unrecognised: bool = False
    note: str = ""


@dataclass
class ParseResult:
    rows: list
    pages: list
