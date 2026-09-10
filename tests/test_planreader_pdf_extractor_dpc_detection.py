"""Regression: damp-proof-course (DPC) detection must not depend on periods.

Found via a real benchmark drawing (tenders_ke_ghazi_science_lab): the source
PDF's own construction notes read "dpc (dam proof course) to be laid under
all walls" -- no periods around the abbreviation, and a genuine spelling typo
("dam" not "damp") in the spelled-out form. The previous detection
(``"d.p.c" in norm_pg or "damp proof course" in norm_pg``) required an exact
match on either the punctuated abbreviation or the correctly-spelled phrase,
so it matched neither and the entire damp_proof_course quantity was silently
dropped (missed_in_extraction) rather than computed.

This is a generic robustness fix, not a benchmark-specific one: "DPC" is a
standard architectural abbreviation real drawings write inconsistently
("D.P.C.", "d.p.c", "DPC", "d p c"), mirroring the flexible punctuation
pattern ``_has_dpm_specification`` already used for "DPM". The genuine
"dam"/"damp" spelling typo is NOT special-cased -- the fix only closes the
punctuation gap, which is what actually generalizes across drawings.
"""
from __future__ import annotations

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor

_EXTRACTOR = GenericPlanReaderExtractor()


def test_bare_dpc_without_periods_is_recognized() -> None:
    assert _EXTRACTOR._has_dpc_specification("dpc to be laid under all walls")


def test_real_ghazi_drawing_note_with_typo_is_recognized() -> None:
    """The exact real-world text that originally slipped through: no periods
    around the abbreviation, and a genuine "dam"/"damp" typo in the spelled-out
    form. Only the punctuation gap is being fixed here -- matching is via the
    bare "dpc" abbreviation, not by special-casing the typo."""
    note = "06. dpc (dam proof course) to be laid under all walls and should be minimum 150mm above ground level."
    assert _EXTRACTOR._has_dpc_specification(note)


def test_punctuated_abbreviation_still_recognized() -> None:
    assert _EXTRACTOR._has_dpc_specification("d.p.c. to all external walls")


def test_spaced_out_abbreviation_is_recognized() -> None:
    assert _EXTRACTOR._has_dpc_specification("d p c below damp course level")


def test_correctly_spelled_phrase_still_recognized() -> None:
    assert _EXTRACTOR._has_dpc_specification("3. dpc denotes damp proof course to be of approved bitumious felt")


def test_unrelated_text_does_not_match() -> None:
    assert not _EXTRACTOR._has_dpc_specification("just some random architectural note")


def test_similar_but_unrelated_abbreviation_does_not_false_positive() -> None:
    """"dpc" is word-boundary anchored -- it must not match as a substring of
    an unrelated longer token."""
    assert not _EXTRACTOR._has_dpc_specification("the dpcm module handles something unrelated")


def test_dpm_and_dpc_are_still_distinguished() -> None:
    """DPC (course, in walls) and DPM (membrane, under slabs) are different
    measured items -- confirming this fix does not conflate the two existing
    independent detectors."""
    dpm_only_note = "500 gauge polythene dpm under ground floor concrete slab"
    assert _EXTRACTOR._has_dpm_specification(dpm_only_note)
    assert not _EXTRACTOR._has_dpc_specification(dpm_only_note)

    dpc_only_note = "dpc to be laid under all walls, minimum 150mm above ground"
    assert _EXTRACTOR._has_dpc_specification(dpc_only_note)
    assert not _EXTRACTOR._has_dpm_specification(dpc_only_note)
