from ingest.normalize import norm_part, to_number


def test_norm_part():
    assert norm_part("MB 0401-5028") == "MB04015028"
    assert norm_part("h4/h19-5055") == "H4H195055"
    assert norm_part(None) == ""


def test_to_number():
    assert to_number("₹1,296") == 1296
    assert to_number("12.50") == 12.5
    assert to_number("NA") is None
    assert to_number("") is None
