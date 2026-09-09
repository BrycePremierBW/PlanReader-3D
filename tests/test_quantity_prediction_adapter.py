from __future__ import annotations

import ast
import inspect

import pytest

import pb_quantity_prediction_adapter
from pb_migration_contracts import QuantityEvidence
from pb_planreader_pdf_extractor import ExtractedPrediction
from pb_quantity_prediction_adapter import (
    PredictionProjectionAmbiguityError,
    PredictionSourceTrace,
    prediction_unit,
    quantities_to_prediction_dicts,
    quantity_evidence_to_extracted_prediction,
    quantity_evidence_to_prediction_dict,
)


def _quantity(
    quantity_id: str = "q1",
    semantic_key: str = "W1",
    value: float | None = 2.0,
    *,
    unit: str = "ea",
    family: str = "opening_count",
    abstained: bool = False,
    metadata=None,
) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id=quantity_id,
        family=family,
        semantic_key=semantic_key,
        value=value,
        unit=unit,
        evidence_ids=("ev1",) if not abstained else (),
        authority="schedule_extracted" if not abstained else "provisional",
        status="firm" if not abstained else "blocked",
        confidence=0.97 if not abstained else 0.0,
        abstained=abstained,
        blocking_reasons=("insufficient_evidence",) if abstained else (),
        formula="count_instances" if not abstained else "",
        formula_version="1" if not abstained else "",
        metadata=metadata or {},
    )


def test_unit_projection_is_generic_only() -> None:
    assert prediction_unit("ea") == "NO"
    assert prediction_unit("each") == "NO"
    assert prediction_unit("m2") == "SM"
    assert prediction_unit("m²") == "SM"
    assert prediction_unit("m") == "M"
    assert prediction_unit("lm") == "M"
    assert prediction_unit("m3") == "M3"
    assert prediction_unit("custom") == "custom"


def test_prediction_dict_preserves_quantity_and_provenance_without_guessing_page() -> None:
    quantity = _quantity(metadata={"description": "Explicit W1 count", "trade_type": "windows"})
    projected = quantity_evidence_to_prediction_dict(quantity)
    assert projected is not None
    assert projected["tag"] == "W1"
    assert projected["trade_type"] == "windows"
    assert projected["description"] == "Explicit W1 count"
    assert projected["quantity"] == 2.0
    assert projected["unit"] == "NO"
    assert projected["source_page"] is None
    assert projected["sheet_number"] is None
    assert projected["metadata"]["quantity_id"] == "q1"
    assert projected["metadata"]["evidence_ids"] == ["ev1"]
    assert projected["metadata"]["formula"] == "count_instances"


def test_explicit_source_trace_projects_page_sheet_dimensions_and_bbox() -> None:
    trace = PredictionSourceTrace(
        source_page=7,
        sheet_number="A-07",
        dimensions=(1.2, 1.5),
        bounding_box=(10, 20, 30, 40),
        description="Window W1 from schedule",
        metadata={"trace_authority": "native_schedule"},
    )
    projected = quantity_evidence_to_prediction_dict(_quantity(), trace=trace)
    assert projected is not None
    assert projected["source_page"] == 7
    assert projected["sheet_number"] == "A-07"
    assert projected["dimensions"] == [1.2, 1.5]
    assert projected["bounding_box"] == [10.0, 20.0, 30.0, 40.0]
    assert projected["description"] == "Window W1 from schedule"
    assert projected["metadata"]["source_trace_metadata"]["trace_authority"] == "native_schedule"


def test_source_trace_rejects_invalid_page_bbox_and_nonfinite_geometry() -> None:
    with pytest.raises(ValueError):
        PredictionSourceTrace(source_page=0)
    with pytest.raises(ValueError):
        PredictionSourceTrace(source_page=-1)
    with pytest.raises(ValueError):
        PredictionSourceTrace(bounding_box=(10, 20, 5, 40))
    with pytest.raises(ValueError):
        PredictionSourceTrace(dimensions=(1.0, float("nan")))


def test_abstention_emits_no_prediction_not_a_zero() -> None:
    quantity = _quantity(value=None, abstained=True)
    assert quantity_evidence_to_prediction_dict(quantity) is None
    assert quantities_to_prediction_dicts([quantity]) == []


def test_bundle_projection_fails_closed_on_duplicate_emitted_semantic_key() -> None:
    first = _quantity(quantity_id="q1", semantic_key="W1", value=2)
    second = _quantity(quantity_id="q2", semantic_key="W1", value=3)
    with pytest.raises(PredictionProjectionAmbiguityError):
        quantities_to_prediction_dicts([first, second])


def test_duplicate_abstention_does_not_suppress_one_real_emission() -> None:
    abstained = _quantity(quantity_id="q0", semantic_key="W1", value=None, abstained=True)
    emitted = _quantity(quantity_id="q1", semantic_key="W1", value=2)
    projected = quantities_to_prediction_dicts([abstained, emitted])
    assert len(projected) == 1
    assert projected[0]["quantity"] == 2.0


def test_extracted_prediction_requires_real_source_page_trace() -> None:
    quantity = _quantity()
    with pytest.raises(ValueError):
        quantity_evidence_to_extracted_prediction(
            quantity,
            trace=PredictionSourceTrace(),
        )

    prediction = quantity_evidence_to_extracted_prediction(
        quantity,
        trace=PredictionSourceTrace(source_page=3, sheet_number="A3"),
    )
    assert isinstance(prediction, ExtractedPrediction)
    assert prediction.tag == "W1"
    assert prediction.quantity == 2.0
    assert prediction.unit == "NO"
    assert prediction.source_page == 3
    assert prediction.sheet_number == "A3"


def test_extracted_prediction_abstention_returns_none_even_with_trace() -> None:
    quantity = _quantity(value=None, abstained=True)
    assert quantity_evidence_to_extracted_prediction(
        quantity,
        trace=PredictionSourceTrace(source_page=1),
    ) is None


def test_projection_api_has_no_gold_or_benchmark_inputs() -> None:
    for func in (
        quantity_evidence_to_prediction_dict,
        quantities_to_prediction_dicts,
        quantity_evidence_to_extracted_prediction,
    ):
        params = {name.lower() for name in inspect.signature(func).parameters}
        assert "benchmark_id" not in params
        assert "expected" not in params
        assert "expected_quantity" not in params
        assert "boq" not in params
        assert "ground_truth" not in params


def test_adapter_module_has_no_benchmark_or_holdout_imports() -> None:
    source = inspect.getsource(pb_quantity_prediction_adapter)
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden_fragments = (
        "benchmark_accuracy_engine",
        "public_tender_benchmark",
        "benchmark_runner",
        "holdout_suite",
    )
    assert not [
        module
        for module in imported
        if any(fragment in module.lower() for fragment in forbidden_fragments)
    ]
