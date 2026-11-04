import pytest

from ingest.profiles import uno_minda


def ch(t, x, top):
    return {"text": t, "x0": x, "x1": x + 4, "top": top, "bottom": top + 5}


def test_two_printed_lines_in_one_cell_are_read_line_by_line():
    # "WIRE" on line 1, "KEY" on line 2 at overlapping x positions must not interleave
    chars = [ch("W", 10, 100), ch("I", 15, 100), ch("R", 20, 100), ch("E", 25, 100),
             ch("K", 10, 106), ch("E", 15, 106), ch("Y", 20, 106)]
    text = uno_minda.UnoMindaProfile._cell_text(chars, (0, 95, 60, 115))
    assert text == "WIRE KEY"
