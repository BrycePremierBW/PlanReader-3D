"""Mutation coverage for contextual WD/DR opening-tag conventions."""
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def test_contextual_opening_tags_are_counted_and_normalized() -> None:
    text = (
        "MILD STEEL CASEMENT WINDOWS\n"
        "WD-03 (Mild Steel Side Hung) WD-03 (Mild Steel Side Hung)\n"
        "WD-07 (Mild Steel Top Hung)\n"
        "DR-02 (Steel Casement)"
    )

    assert GenericPlanReaderExtractor._contextual_opening_tag_counts(text) == {
        "W3": ("windows", 2),
        "W7": ("windows", 1),
        "D2": ("doors", 1),
    }


def test_ambiguous_wd_abbreviation_fails_closed_without_window_scope() -> None:
    text = "JOINERY DETAILS WD-03 (Wood Door Side Hung)"

    assert GenericPlanReaderExtractor._contextual_opening_tag_counts(text) == {}
