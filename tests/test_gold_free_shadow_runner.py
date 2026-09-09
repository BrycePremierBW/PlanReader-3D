from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path

import fitz
import pytest

import pb_gold_free_shadow_runner
from pb_gold_free_shadow_runner import (
    GoldFreeShadowRunner,
    ShadowComparisonAmbiguityError,
    SourceMutationDuringShadowRunError,
    canonical_shadow_unit,
    compare_shadow_quantities,
    save_shadow_run_json,
)
from pb_legacy_extractor_adapter import (
    LEGACY_EXTRACTOR_ADAPTER_VERSION,
    LEGACY_EXTRACTOR_ENGINE_ID,
    LegacyExtractionResult,
    LegacyPredictionSnapshot,
)
from pb_migration_contracts import QuantityEvidence


def _source_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_result(
    path: Path,
    *predictions: LegacyPredictionSnapshot,
    pages: tuple[int, ...] | None = None,
) -> LegacyExtractionResult:
    return LegacyExtractionResult(
        result_id="legacy_run_test",
        engine_id=LEGACY_EXTRACTOR_ENGINE_ID,
        adapter_version=LEGACY_EXTRACTOR_ADAPTER_VERSION,
        source_sha256=_source_sha(path),
        source_size_bytes=path.stat().st_size,
        pages=pages,
        predictions=tuple(predictions),
    )


class FakeLegacyAdapter:
    def __init__(self, result: LegacyExtractionResult) -> None:
        self.result = result
        self.last_pages = None

    def extract(self, pdf_path, pages=None):
        self.last_pages = pages
        return self.result


class FakeNewEngine:
    engine_id = "fake_graph_engine"
    engine_version = "0.1.0"

    def __init__(self, quantities=(), *, mutate_source: bool = False) -> None:
        self.quantities = tuple(quantities)
        self.mutate_source = mutate_source
        self.last_pages = None

    def extract_quantities(self, pdf_path, pages=None):
        self.last_pages = pages
        if self.mutate_source:
            Path(pdf_path).write_bytes(b"mutated")
        return self.quantities


def _legacy_prediction(tag: str, value: float, unit: str = "NO") -> LegacyPredictionSnapshot:
    return LegacyPredictionSnapshot(
        tag=tag,
        trade_type="windows" if tag.startswith("W") else "finishes",
        description=f"Legacy {tag}",
        quantity=value,
        unit=unit,
        confidence=0.9,
        source_page=1,
        metadata={"source": "legacy"},
    )


def _quantity(
    quantity_id: str,
    semantic_key: str,
    value: float | None,
    *,
    unit: str = "ea",
    family: str = "opening_count",
    abstained: bool = False,
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
        confidence=0.99 if not abstained else 0.0,
        abstained=abstained,
        blocking_reasons=("insufficient_evidence",) if abstained else (),
    )


def test_unit_normalization_is_generic_and_conservative() -> None:
    assert canonical_shadow_unit("NO") == "ea"
    assert canonical_shadow_unit("EA") == "ea"
    assert canonical_shadow_unit("SM") == "m2"
    assert canonical_shadow_unit("m²") == "m2"
    assert canonical_shadow_unit("LM") == "m"
    assert canonical_shadow_unit("custom_unit") == "custom_unit"


def test_compare_agree_and_differ_without_tolerance_or_gold(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"same source")
    legacy = _legacy_result(
        source,
        _legacy_prediction("W1", 7, "NO"),
        _legacy_prediction("floor_screed", 100, "SM"),
    )
    new = (
        _quantity("q_w1", "W1", 7, unit="ea"),
        _quantity(
            "q_floor",
            "floor_screed",
            102,
            unit="m2",
            family="floor_area",
        ),
    )

    rows = {row.semantic_key: row for row in compare_shadow_quantities(legacy, new)}
    assert rows["W1"].status == "agree"
    assert rows["W1"].absolute_delta == 0
    assert rows["W1"].relative_delta == 0
    assert rows["floor_screed"].status == "differ"
    assert rows["floor_screed"].absolute_delta == 2
    assert rows["floor_screed"].relative_delta == pytest.approx(0.02)


def test_compare_tracks_abstention_and_missing_sides(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy = _legacy_result(
        source,
        _legacy_prediction("W1", 2),
        _legacy_prediction("legacy_only", 3),
    )
    new = (
        _quantity("q_w1", "W1", None, abstained=True),
        _quantity("q_new", "new_only", 5),
    )

    rows = {row.semantic_key: row for row in compare_shadow_quantities(legacy, new)}
    assert rows["W1"].status == "new_abstained"
    assert rows["W1"].new_engine_abstained is True
    assert rows["legacy_only"].status == "legacy_only"
    assert rows["new_only"].status == "new_only"


def test_compare_reports_unit_mismatch_instead_of_converting_quantity(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy = _legacy_result(source, _legacy_prediction("item", 5, "M"))
    new = (_quantity("q_item", "item", 5, unit="m2", family="wall_area"),)
    row = compare_shadow_quantities(legacy, new)[0]
    assert row.status == "unit_mismatch"
    assert row.absolute_delta is None
    assert row.relative_delta is None
    assert row.unit == "legacy:m|new:m2"


def test_duplicate_semantic_keys_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy = _legacy_result(source, _legacy_prediction("W1", 2))
    duplicate_new = (
        _quantity("q1", "W1", 2),
        _quantity("q2", "W1", 2),
    )
    with pytest.raises(ShadowComparisonAmbiguityError):
        compare_shadow_quantities(legacy, duplicate_new)


def test_shadow_runner_freezes_both_outputs_and_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy_result = _legacy_result(
        source,
        _legacy_prediction("W1", 2),
        pages=(0,),
    )
    legacy_adapter = FakeLegacyAdapter(legacy_result)
    new_engine = FakeNewEngine((_quantity("q1", "W1", 2),))
    runner = GoldFreeShadowRunner(legacy_adapter=legacy_adapter)

    first = runner.run(source, new_engine, pages=[0])
    second = runner.run(source, new_engine, pages=[0])

    assert first.result_id == second.result_id
    assert first.source_sha256 == _source_sha(source)
    assert first.legacy_output.result_id == legacy_result.result_id
    assert first.new_engine_id == new_engine.engine_id
    assert first.new_engine_version == new_engine.engine_version
    assert first.comparisons[0].status == "agree"
    assert first.pages == (0,)
    assert legacy_adapter.last_pages == [0]
    assert new_engine.last_pages == (0,)


def test_shadow_runner_rejects_source_mutation_by_new_engine(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy_result = _legacy_result(source, _legacy_prediction("W1", 2))
    runner = GoldFreeShadowRunner(legacy_adapter=FakeLegacyAdapter(legacy_result))
    with pytest.raises(SourceMutationDuringShadowRunError):
        runner.run(source, FakeNewEngine(mutate_source=True))


def test_shadow_runner_requires_engine_identity(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy_result = _legacy_result(source)

    class AnonymousEngine:
        def extract_quantities(self, pdf_path, pages=None):
            return []

    runner = GoldFreeShadowRunner(legacy_adapter=FakeLegacyAdapter(legacy_result))
    with pytest.raises(ValueError):
        runner.run(source, AnonymousEngine())


def test_shadow_artifact_is_atomic_json_and_contains_no_gold_keys(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    legacy_result = _legacy_result(source, _legacy_prediction("W1", 2))
    result = GoldFreeShadowRunner(legacy_adapter=FakeLegacyAdapter(legacy_result)).run(
        source,
        FakeNewEngine((_quantity("q1", "W1", 2),)),
    )
    output = save_shadow_run_json(result, tmp_path / "artifacts" / "shadow.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield str(key).lower()
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    forbidden = {"expected", "expected_quantity", "benchmark_id", "ground_truth"}
    assert forbidden.isdisjoint(set(keys(payload)))
    assert payload["result_id"] == result.result_id
    assert payload["legacy_output"]["source_sha256"] == _source_sha(source)


def test_runner_wires_to_real_legacy_adapter_without_gold(tmp_path: Path) -> None:
    pdf_path = tmp_path / "plan.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text(
        (50, 50),
        "GROUND FLOOR PLAN\n"
        "SCALE 1:100\n"
        "12,000\n"
        "6,000\n",
    )
    doc.save(pdf_path)
    doc.close()

    result = GoldFreeShadowRunner().run(pdf_path, FakeNewEngine())
    assert result.source_sha256 == _source_sha(pdf_path)
    assert result.legacy_output.source_sha256 == result.source_sha256
    assert result.new_output == ()


def test_shadow_runner_module_imports_no_benchmark_or_holdout_modules() -> None:
    source = inspect.getsource(pb_gold_free_shadow_runner)
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
