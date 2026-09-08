"""Synthetic mutation/red-team coverage for F.16 explicit item counts."""
from pb_explicit_item_count_extractor import extract_explicit_item_counts


def _by_tag(text: str):
    return {item.tag: item for item in extract_explicit_item_counts(text)}


def test_count_before_item_is_extracted_exactly():
    rows = _by_tag("7 No. 89mm dia SHS pillars")
    assert rows["verandah_pillars"].quantity == 7
    assert rows["verandah_pillars"].trade_type == "structure"


def test_item_before_count_is_extracted_exactly():
    rows = _by_tag("Masonry piers — 16 Nos")
    assert rows["masonry_piers"].quantity == 16


def test_changing_count_changes_output_exactly():
    assert _by_tag("Steel columns: 9 No.")["structural_columns"].quantity == 9
    assert _by_tag("Steel columns: 14 No.")["structural_columns"].quantity == 14


def test_drawing_tags_are_preserved_for_openings():
    rows = _by_tag("Steel casement windows W7 - 11 Nos\n4 No flush doors D3")
    assert rows["W7"].quantity == 11
    assert rows["W7"].trade_type == "windows"
    assert rows["D3"].quantity == 4
    assert rows["D3"].trade_type == "doors"


def test_removing_no_marker_removes_prediction():
    assert extract_explicit_item_counts("13 steel columns at 2.7m centres") == []


def test_dimensions_and_heights_are_not_misread_as_counts():
    assert extract_explicit_item_counts("300 x 300mm masonry piers, 4,500mm high") == []


def test_hardware_fitting_count_is_not_misread_as_a_door_count():
    # Real false positive found against a live project PDF: a door spec
    # note's hinge count ("3 nos. butt hinges") was being read as "3 No.
    # doors". The real PyMuPDF text block was itself truncated to
    # "...batten door with 3 nos. butt" (the word "hinges" fell into a
    # separate block), so "butt" alone must be enough to disqualify the
    # clause.
    assert extract_explicit_item_counts(
        "1,000mm x 2,100mm timber\nbatten door with 3 nos. butt\n"
    ) == []
    assert extract_explicit_item_counts("Door complete with 4 No. butt hinges") == []
    assert extract_explicit_item_counts("Window ironmongery: 2 No. fasteners") == []


def test_two_counts_in_one_clause_fail_closed():
    assert extract_explicit_item_counts("7 No. columns plus 3 No. spare columns") == []


def test_two_item_classes_in_one_clause_fail_closed():
    assert extract_explicit_item_counts("12 No. combined columns and doors") == []


def test_conflicting_duplicate_notes_fail_closed():
    assert extract_explicit_item_counts("Steel columns 8 No.\nSteel columns 9 No.") == []


def test_repeated_identical_note_is_deduplicated():
    rows = extract_explicit_item_counts("Roof trusses 17 Nos\nRoof trusses 17 Nos")
    assert len(rows) == 1
    assert rows[0].tag == "roof_trusses"
    assert rows[0].quantity == 17


def test_unrelated_numbers_do_not_affect_explicit_count():
    rows = _by_tag("Drawing 2029 scale 1:75; 6 No. concrete pillars")
    assert rows["verandah_pillars"].quantity == 6


def test_no_project_or_expected_quantity_inputs_exist():
    import inspect
    import pb_explicit_item_count_extractor as module

    source = inspect.getsource(module)
    assert "KSTVET" not in source
    assert "Murera" not in source
    assert "expected_quantity" not in source
    assert "benchmark_id" not in source
