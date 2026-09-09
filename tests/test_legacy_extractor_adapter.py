from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path

import fitz
import pytest

import pb_legacy_extractor_adapter
from pb_legacy_extractor_adapter import (
    LEGACY_EXTRACTOR_ADAPTER_VERSION,
    LEGACY_EXTRACTOR_ENGINE_ID,
    LegacyExtractorAdapter,
    SourceMutationDuringExtractionError,
)
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text(
        (50, 50),
        "GROUND FLOOR PLAN\n"
        "SCALE 1:100\n"
        "DRAWING NO: AD-01\n"
        "12,000\n"
        "6,000\n"
        "FLOOR AREA - 72.00M2\n"
        "D.P.M. under floor bed\n",
    )
    page2 = doc.new_page(width=842, height=595)
    page2.insert_text(
        (50, 50),
        "WINDOW SCHEDULE\n"
        "W1 1200 x 1200 2 No\n",
    )
    doc.save(path)
    doc.close()
    return path


def test_adapter_preserves_legacy_prediction_payload_byte_for_byte_semantics(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "plan.pdf")
    direct = [p.to_dict() for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)]
    adapted = LegacyExtractorAdapter().extract(pdf).to_prediction_dicts()
    assert adapted == direct


def test_adapter_preserves_explicit_page_subset_semantics(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "plan.pdf")
    direct = [p.to_dict() for p in GenericPlanReaderExtractor().extract_from_pdf(pdf, pages=[0])]
    result = LegacyExtractorAdapter().extract(pdf, pages=[0])
    assert result.pages == (0,)
    assert result.to_prediction_dicts() == direct


def test_result_is_content_addressed_and_repeatable(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "plan.pdf")
    raw = pdf.read_bytes()
    expected_sha = hashlib.sha256(raw).hexdigest()

    first = LegacyExtractorAdapter().extract(pdf)
    second = LegacyExtractorAdapter().extract(pdf)

    assert first.source_sha256 == expected_sha
    assert first.source_size_bytes == len(raw)
    assert first.result_id == second.result_id
    assert first.engine_id == LEGACY_EXTRACTOR_ENGINE_ID
    assert first.adapter_version == LEGACY_EXTRACTOR_ADAPTER_VERSION
    assert first.to_dict() == second.to_dict()


def test_adapter_rejects_source_mutation_during_extraction(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"before")

    class MutatingExtractor:
        def extract_from_pdf(self, pdf_path, pages=None):
            Path(pdf_path).write_bytes(b"after")
            return []

    with pytest.raises(SourceMutationDuringExtractionError):
        LegacyExtractorAdapter(extractor_factory=MutatingExtractor).extract(source)


def test_adapter_rejects_duplicate_or_negative_page_indices(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "plan.pdf")
    with pytest.raises(ValueError):
        LegacyExtractorAdapter().extract(pdf, pages=[0, 0])
    with pytest.raises(ValueError):
        LegacyExtractorAdapter().extract(pdf, pages=[-1])


def test_adapter_missing_source_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LegacyExtractorAdapter().extract(tmp_path / "missing.pdf")


def test_adapter_api_has_no_benchmark_or_expected_quantity_inputs() -> None:
    params = inspect.signature(LegacyExtractorAdapter.extract).parameters
    lowered = {name.lower() for name in params}
    assert "benchmark_id" not in lowered
    assert "expected" not in lowered
    assert "expected_quantity" not in lowered
    assert "boq" not in lowered
    assert "ground_truth" not in lowered


def test_adapter_module_imports_no_benchmark_or_gold_modules() -> None:
    source = inspect.getsource(pb_legacy_extractor_adapter)
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
