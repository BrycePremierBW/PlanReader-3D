"""tests/learning_ledger/test_error_taxonomy_and_ledger.py — Tests for error taxonomy and learning ledger."""
import json
import math
from pathlib import Path
import pytest

from pb_takeoff_learning_ledger import (
    AIDraftTakeoffRow,
    ErrorTaxonomy,
    LearningLedgerEntry,
    TakeoffLearningLedger,
)


def test_error_taxonomy_categories():
    assert len(ErrorTaxonomy) == 16
    assert ErrorTaxonomy.SCALE_ERROR.value == "scale_error"
    assert ErrorTaxonomy.PROJECT_MISMATCH.value == "project_mismatch"
    assert ErrorTaxonomy.OPENING_MISSED.value == "opening_missed"
    assert ErrorTaxonomy.WRONG_DIMENSION_SELECTED.value == "wrong_dimension_selected"


def test_ai_draft_takeoff_row_invariants():
    row = AIDraftTakeoffRow(
        draft_id="draft_01",
        section="Internal walls",
        location="Unit 1",
        substrate="Plasterboard",
        finish_tag="PB01",
        element="Internal Wall",
        unit="m2",
        detected_quantity=45.2,
        confidence=0.78,
        source_page="Page 3",
        source_region=(100.0, 150.0, 300.0, 450.0),
        reasoning_summary="Detected from vector linework boundary and OCR text tag PB01",
        uncertainty_flags=["unverified_height", "scaled_linework"],
        requires_review=True,
    )
    d = row.to_dict()
    assert d["detected_quantity"] == 45.2
    assert d["confidence"] == 0.78
    assert d["authority_status"] == "provisional"
    assert d["requires_review"] is True

    # Negative quantity rejected
    with pytest.raises(ValueError, match="non-negative finite number"):
        AIDraftTakeoffRow(
            draft_id="draft_bad",
            section="Internal",
            location="Unit 1",
            substrate="Plasterboard",
            finish_tag="PB01",
            element="Wall",
            unit="m2",
            detected_quantity=-5.0,
            confidence=0.8,
            source_page="P1",
            source_region=(0, 0, 10, 10),
            reasoning_summary="",
        )

    # Invalid confidence rejected
    with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
        AIDraftTakeoffRow(
            draft_id="draft_bad",
            section="Internal",
            location="Unit 1",
            substrate="Plasterboard",
            finish_tag="PB01",
            element="Wall",
            unit="m2",
            detected_quantity=10.0,
            confidence=1.5,
            source_page="P1",
            source_region=(0, 0, 10, 10),
            reasoning_summary="",
        )


def test_takeoff_learning_ledger_operations(tmp_path):
    ledger = TakeoffLearningLedger()

    # Record 3 corrections
    e1 = ledger.record_correction(
        entry_id="corr_1",
        benchmark_or_job_id="school_rd_60_62",
        object_id="W_101",
        object_type="wall",
        planreader_measured_value=16.2,
        user_corrected_value=18.0,
        source_page="WD-02",
        error_reason=ErrorTaxonomy.WRONG_DIMENSION_SELECTED.value,
        confidence_before=0.65,
        confidence_after=1.0,
    )
    assert e1.entry_id == "corr_1"

    ledger.record_correction(
        entry_id="corr_2",
        benchmark_or_job_id="school_rd_60_62",
        object_id="W_102",
        object_type="wall",
        planreader_measured_value=12.0,
        user_corrected_value=14.5,
        source_page="WD-02",
        error_reason=ErrorTaxonomy.OPENING_MISSED.value,
    )
    ledger.record_correction(
        entry_id="corr_3",
        benchmark_or_job_id="lago_britinya",
        object_id="W_LAGO",
        object_type="wall",
        planreader_measured_value=30.0,
        user_corrected_value=35.0,
        source_page="CD3001",
        error_reason=ErrorTaxonomy.OPENING_MISSED.value,
    )

    top_errors = ledger.get_top_error_reasons(limit=2)
    assert len(top_errors) == 2
    # OPENING_MISSED has 2 occurrences
    assert top_errors[0] == (ErrorTaxonomy.OPENING_MISSED.value, 2)
    assert top_errors[1] == (ErrorTaxonomy.WRONG_DIMENSION_SELECTED.value, 1)

    # Persistence to file
    ledger_file = tmp_path / "learning_ledger.json"
    ledger.save_to_file(ledger_file)
    assert ledger_file.exists()

    loaded = TakeoffLearningLedger.load_from_file(ledger_file)
    assert len(loaded.entries) == 3
    assert loaded.entries[0].object_id == "W_101"
