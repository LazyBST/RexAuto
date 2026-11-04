from dataclasses import dataclass, field

# The ONLY keys a profile may emit. Anything else is a bug and aborts the parse.
PRODUCT_FIELDS = frozenset({
    "part_no", "part_no_norm", "description", "category", "segment", "oem_name", "oem_raw",
    "application", "variant_label", "mrp", "mrp_prev", "price_basis", "gst_pct", "hsn", "moq",
    "pack_qty", "unit", "image_url", "needs_review", "review_note", "source_page", "source_row",
})

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
