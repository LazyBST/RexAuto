from dataclasses import dataclass, field

# The ONLY keys a profile may emit. Anything else is a bug and aborts the parse.
PRODUCT_FIELDS = frozenset({
    "part_no", "part_no_norm", "description", "category", "segment", "oem_name", "oem_raw",
    "application", "variant_label", "mrp", "mrp_prev", "price_basis", "gst_pct", "hsn", "moq",
    "pack_qty", "unit", "image_url", "needs_review", "review_note", "source_page", "source_row",
    "attributes", "price_effective_from",
})

# Keys allowed inside products.attributes (source-specific extras that have no column of their own).
# Deliberately a closed list: a new key is a reviewed code change, and none may name a discount / dealer / net price.
ATTRIBUTE_KEYS = frozenset({"pgroup", "class", "product_type", "npd_status", "group_no", "position", "pcs_per_set",
                            "sections", "universal", "pack_raw", "section"})

# Optional staged keys holding a product's child rows. Each is only managed when a profile emits it; profiles that never
# emit it leave the existing child rows untouched. Allowed inner keys per child kind:
CHILD_FIELDS = {
    "cross_refs": frozenset({"ref_type", "ref_brand", "ref_part_no", "note", "direction"}),
    "images": frozenset({"url", "kind", "sort", "caption"}),
    "fitments": frozenset({"make", "model", "variant", "year_from", "year_to", "engine", "note"}),
}
EXTRA_FIELDS = frozenset(CHILD_FIELDS) | {"update_only"}
# "update_only": True marks an enrichment row (e.g. photos from a catalogue): it carries the identifying keys plus only the
# fields to set; it never inserts a product and never touches fields it does not carry.
REF_FIELDS = CHILD_FIELDS["cross_refs"]

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
