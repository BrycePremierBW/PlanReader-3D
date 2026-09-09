"""tests/benchmarks/test_public_tender_verified_benchmark.py — PR F.2 Test Suite.

Verifies the first real public tender benchmark (tenders_ke_kstvet_cbc_classroom):
1. Unverified seeds cannot contribute to accuracy metric
2. Missing real prediction does not equal 100% accuracy
3. Wrong source URL/metadata marked candidate_unverified
4. Actual downloaded SHA stored and validated
5. Matched real drawings + BOQ accepted
6. Unrelated BOQ rejected with wrong_project_source_mismatch
7. Comparable row requires drawing trace
8. Preliminaries excluded from physical measurement scoring
9. Provisional sums excluded from physical accuracy
10. Missing quantity counted as missing, not correct
11. Prediction outside tolerance fails
12. Prediction inside tolerance passes
13. Benchmark discovery records load errors without silently swallowing them
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from pb_public_tender_benchmark import (
    BOQLineCategory,
    BOQLineItem,
    PublicTenderBenchmark,
    classify_boq_line,
    compare_tender_drawings_and_boq,
    evaluate_boq_measurement_traceability,
    get_benchmark_load_errors,
    list_available_public_tender_benchmarks,
)

BENCHMARK_ID = "tenders_ke_kstvet_cbc_classroom"
BENCHMARKS_DIR = Path("benchmarks/public_tenders")


def test_missing_real_prediction_does_not_equal_100_percent_accuracy() -> None:
    """Evaluate accuracy summary without predictions must NOT return 1.0 (100%)."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    res = bench.evaluate_accuracy_summary(predictions=None)

    assert res["accuracy_score"] is None
    assert res["is_scored"] is False
    assert res["benchmark_status"] == "candidate_unscored"
    assert res["preliminaries_excluded_count"] > 0


def test_unverified_seed_cannot_contribute_to_accuracy_metric() -> None:
    """Unverified candidate seeds are blocked from contributing to headline accuracy."""
    bench = PublicTenderBenchmark.load("ungm_unops_wecc_torit")
    assert bench.is_candidate_unverified is True

    dummy_predictions = [{"item_id": "BOQ-WECC-03-01", "value": 780.0}]
    res = bench.evaluate_accuracy_summary(predictions=dummy_predictions)

    assert res["accuracy_score"] is None
    assert res["is_scored"] is False
    assert res["benchmark_status"] == "candidate_unverified"
    assert "error" in res


def test_wrong_source_url_or_metadata_marked_candidate_unverified() -> None:
    """Candidate seeds with unverified URLs/metadata are strictly marked candidate_unverified."""
    manifest_data = json.loads((BENCHMARKS_DIR / "manifest.json").read_text(encoding="utf-8"))
    entries = {b["benchmark_id"]: b for b in manifest_data["benchmarks"]}

    assert entries[BENCHMARK_ID]["status"] in ("verified_scored_benchmark", "verified_public_benchmark")
    assert entries["ungm_unops_wecc_torit"]["status"] == "candidate_unverified"
    assert entries["ungm_category_iv_housing_units"]["status"] == "candidate_unverified"
    assert entries["king_st_122_126"]["status"] == "candidate_unverified"


def test_actual_downloaded_sha_stored_and_validated(tmp_path: Path) -> None:
    """Actual downloaded file SHA-256 matches the manifest and detects corruption."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    doc_meta = bench.download_manifest["documents"][0]
    expected_sha = doc_meta["sha256"]
    assert expected_sha == "6856bfa739aa136dd8e0bf17cb25fd43d0d31c9c3dfe3252525454f09d8fa4dc"
    assert doc_meta["file_size_bytes"] == 1273202
    assert doc_meta["total_pages"] == 55

    # Test validator with matching file content
    dummy_file = tmp_path / "1727358888238-bq-nd-drawing.pdf"
    dummy_file.write_bytes(b"corrupted test bytes")
    is_valid, reason = bench.validate_download_hash(dummy_file)
    assert is_valid is False
    assert "sha256_mismatch" in reason


def test_matched_real_drawings_and_boq_accepted() -> None:
    """Verified tender drawings and BOQ matching reference ID are confirmed."""
    drawings_meta = {
        "project_name": "Proposed Construction of CBC Classroom and Integrated Resource Center",
        "tender_reference": "KSTVET/008/24",
        "organization": "Kenya School of TVET / Ministry of Education",
    }
    boq_meta = {
        "project_name": "Proposed Construction of CBC Classroom and Integrated Resource Center",
        "tender_reference": "KSTVET/008/24",
        "organization": "Kenya School of TVET / Ministry of Education",
    }
    allowed, reason = compare_tender_drawings_and_boq(drawings_meta, boq_meta)
    assert allowed is True
    assert reason == "project_identity_confirmed"


def test_unrelated_boq_rejected() -> None:
    """Unrelated project BOQ is rejected with wrong_project_source_mismatch."""
    drawings_meta = {
        "project_name": "Proposed Construction of CBC Classroom and Integrated Resource Center",
        "tender_reference": "KSTVET/008/24",
        "organization": "Kenya School of TVET / Ministry of Education",
    }
    unrelated_meta = {
        "project_name": "60-62 School Rd Maroochydore",
        "project_number": "26-017",
        "client": "Balleo Pty Ltd",
    }
    allowed, reason = compare_tender_drawings_and_boq(drawings_meta, unrelated_meta)
    assert allowed is False
    assert reason == "wrong_project_source_mismatch"


def test_comparable_row_requires_drawing_trace() -> None:
    """Measurable BOQ items must carry drawing references; missing trace is flagged."""
    items = [
        BOQLineItem(
            line_id="BOQ-C36-A",
            description="150 mm Thick concrete block walling",
            quantity=58.0,
            unit="SM",
            category=BOQLineCategory.MEASURABLE_FROM_DRAWINGS,
            drawing_sheet="KSTVET/08/2024-AD01",
            drawing_page=54,
        ),
        BOQLineItem(
            line_id="BOQ-C36-B",
            description="Ditto gable walling 150mm thick",
            quantity=13.0,
            unit="SM",
            category=BOQLineCategory.MEASURABLE_FROM_DRAWINGS,
            drawing_sheet=None,
            drawing_page=None,
        ),
    ]
    report = evaluate_boq_measurement_traceability(items)
    assert report["measurable_items"] == 2
    assert report["traced_measurable_items"] == 1
    assert report["missing_trace_items_count"] == 1
    assert report["missing_trace_line_ids"] == ["BOQ-C36-B"]


def test_preliminaries_and_provisional_sums_excluded_from_physical_accuracy() -> None:
    """Preliminaries and provisional sums are excluded from physical measurement scoring."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    summary = bench.expected_boq_summary
    assert summary["preliminaries_count"] == 2
    assert summary["provisional_sums_count"] == 1
    assert summary["classified_breakdown"]["preliminaries"] == 2
    assert summary["classified_breakdown"]["provisional_sum"] == 1

    # Check classifier on tender text
    cat_prelim = classify_boq_line("PARTICULAR PRELIMINARIES: Clearing away and site security")
    assert cat_prelim == BOQLineCategory.PRELIMINARIES

    cat_ps = classify_boq_line("Allow a provisional Sum of Only for Electrical works", unit="ITEM", is_provisional=True)
    assert cat_ps == BOQLineCategory.PROVISIONAL_SUM


def test_missing_quantity_counted_as_missing_not_correct() -> None:
    """Missing expected quantity in predictions is counted as missing/failure, not correct."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    # Provide only 1 prediction out of 13 expected items
    partial_predictions = [
        {"item_id": "BOQ-C44-A", "value": 1.0}  # Mild steel double door
    ]
    res = bench.evaluate_accuracy_summary(predictions=partial_predictions)
    assert res["is_scored"] is True
    assert res["passed_items_count"] == 1
    assert res["missing_items_count"] == 12
    assert res["failed_items_count"] == 12
    assert res["accuracy_score"] < 0.15


def test_prediction_outside_tolerance_fails() -> None:
    """Prediction outside tolerance fails."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    # Expected walling is 58.0 m²; predict 90.0 m² (+55% delta)
    bad_predictions = [
        {"item_id": "BOQ-C36-A", "value": 90.0}
    ]
    res = bench.evaluate_accuracy_summary(predictions=bad_predictions)
    item_res = next(r for r in res["detailed_results"] if r["item_id"] == "BOQ-C36-A")
    assert item_res["status"] == "fail"
    assert item_res["pct_delta"] > 50.0


def test_prediction_inside_tolerance_passes() -> None:
    """Predictions within tolerance pass and achieve high accuracy."""
    bench = PublicTenderBenchmark.load(BENCHMARK_ID)
    perfect_predictions = [
        {"item_id": exp["item_id"], "value": exp["expected_quantity"]}
        for exp in bench.expected_boq_summary["sample_measurable_items"]
    ]
    res = bench.evaluate_accuracy_summary(predictions=perfect_predictions)
    assert res["is_scored"] is True
    assert res["passed_items_count"] == 13
    assert res["failed_items_count"] == 0
    assert res["missing_items_count"] == 0
    assert res["accuracy_score"] == 1.0
    for r in res["detailed_results"]:
        assert r["status"] == "pass"


def test_list_benchmarks_does_not_swallow_malformed_manifests(tmp_path: Path) -> None:
    """Benchmark loader records malformed candidates instead of silently swallowing errors."""
    # Create invalid benchmark
    bad_dir = tmp_path / "bad_benchmark"
    bad_dir.mkdir()
    (bad_dir / "source_manifest.json").write_text("{invalid json", encoding="utf-8")

    manifest = {"benchmarks": [{"benchmark_id": "bad_benchmark"}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    benchmarks = list_available_public_tender_benchmarks(directory=tmp_path, strict=False)
    assert len(benchmarks) == 0

    errors = get_benchmark_load_errors()
    assert "bad_benchmark" in errors
    assert len(errors["bad_benchmark"]) > 0

    with pytest.raises(ValueError, match="Malformed public tender benchmark"):
        list_available_public_tender_benchmarks(directory=tmp_path, strict=True)
