from __future__ import annotations

import pytest

from pb_migration_contracts import (
    DocumentEvidence,
    EntityEvidence,
    EvidenceAtom,
    EvidenceResolutionStatus,
    MIGRATION_CONTRACT_SCHEMA_VERSION,
    MigrationAuthorityState,
    QuantityEvidence,
    ShadowQuantityComparison,
    ViewportEvidence,
    ViewportResolutionStatus,
    canonical_contract_json,
    stable_contract_id,
)


SOURCE_SHA = "a" * 64


def test_stable_contract_id_is_mapping_order_independent() -> None:
    first = stable_contract_id("qty", {"b": 2, "a": 1})
    second = stable_contract_id("qty", {"a": 1, "b": 2})
    assert first == second
    assert first.startswith("qty_")


def test_stable_contract_id_rejects_bad_prefix_and_digest_length() -> None:
    with pytest.raises(ValueError):
        stable_contract_id("---", {"x": 1})
    with pytest.raises(ValueError):
        stable_contract_id("doc", {"x": 1}, digest_chars=4)


def test_document_evidence_validates_hash_pages_and_uniqueness() -> None:
    doc = DocumentEvidence(
        document_id="doc_1",
        source_sha256=SOURCE_SHA.upper(),
        page_count=2,
        page_ids=("p1", "p2"),
        evidence_ids=("ev1", "ev2"),
        producer="native_pdf",
        producer_version="1",
    )
    assert doc.source_sha256 == SOURCE_SHA
    assert doc.schema_version == MIGRATION_CONTRACT_SCHEMA_VERSION

    with pytest.raises(ValueError):
        DocumentEvidence(document_id="doc", source_sha256="bad", page_count=1)
    with pytest.raises(ValueError):
        DocumentEvidence(
            document_id="doc",
            source_sha256=SOURCE_SHA,
            page_count=2,
            page_ids=("p1",),
        )
    with pytest.raises(ValueError):
        DocumentEvidence(
            document_id="doc",
            source_sha256=SOURCE_SHA,
            page_count=2,
            page_ids=("p1", "p1"),
        )


def test_evidence_atom_is_source_trace_only_and_validates_bbox() -> None:
    atom = EvidenceAtom(
        evidence_id="ev_1",
        document_id="doc_1",
        page_id="p1",
        viewport_id="vp1",
        kind="figured_dimension",
        method="native_text",
        raw_text="15,950",
        bbox=(1, 2, 3, 4),
        normalized_value=15.95,
        unit="m",
        confidence=0.99,
    )
    payload = atom.to_dict()
    assert payload["status"] == "raw"
    assert payload["bbox"] == [1.0, 2.0, 3.0, 4.0]

    with pytest.raises(ValueError):
        EvidenceAtom(
            evidence_id="ev_bad",
            document_id="doc_1",
            page_id="p1",
            kind="dimension",
            method="native",
            bbox=(4, 2, 3, 5),
        )


def test_viewport_ambiguity_cannot_claim_resolved_scale() -> None:
    with pytest.raises(ValueError):
        ViewportEvidence(
            viewport_id="vp1",
            document_id="doc1",
            page_id="p1",
            bbox=(0, 0, 100, 100),
            view_type="floor_plan",
            status=ViewportResolutionStatus.AMBIGUOUS,
            resolved_scale_id="scale_1",
            confidence=0.5,
        )

    resolved = ViewportEvidence(
        viewport_id="vp1",
        document_id="doc1",
        page_id="p1",
        bbox=(0, 0, 100, 100),
        view_type="floor_plan",
        status=ViewportResolutionStatus.RESOLVED,
        resolved_scale_id="scale_1",
        scale_evidence_ids=("ev_scale",),
        confidence=0.99,
    )
    assert resolved.to_dict()["status"] == "resolved"


def test_entity_evidence_requires_real_trace_and_conflicts_are_explicit() -> None:
    with pytest.raises(ValueError):
        EntityEvidence(
            candidate_entity_id="ent1",
            candidate_type="wall",
            evidence_ids=(),
        )

    with pytest.raises(ValueError):
        EntityEvidence(
            candidate_entity_id="ent1",
            candidate_type="wall",
            evidence_ids=("ev1",),
            status=EvidenceResolutionStatus.CONFLICT,
        )

    conflict = EntityEvidence(
        candidate_entity_id="ent1",
        candidate_type="wall",
        evidence_ids=("ev1", "ev2"),
        status=EvidenceResolutionStatus.CONFLICT,
        conflict_evidence_ids=("ev2",),
        confidence=0.4,
        reason_codes=("dimension_disagreement",),
    )
    assert conflict.to_dict()["status"] == "conflict"


def test_quantity_evidence_requires_trace_or_explicit_abstention() -> None:
    with pytest.raises(ValueError):
        QuantityEvidence(
            quantity_id="q1",
            family="floor_area",
            semantic_key="floor_screed",
            value=10.0,
            unit="m2",
            authority="documented_dimension",
            status="firm",
            confidence=1.0,
        )

    measured = QuantityEvidence(
        quantity_id="q1",
        family="floor_area",
        semantic_key="floor_screed",
        value=10.0,
        unit="m2",
        input_entity_ids=("floor_1",),
        evidence_ids=("ev_area",),
        formula="polygon_area",
        formula_version="1",
        authority="documented_dimension",
        status="firm",
        confidence=0.99,
    )
    assert measured.value == 10.0
    assert measured.to_dict()["abstained"] is False

    abstained = QuantityEvidence(
        quantity_id="q2",
        family="wall_area",
        semantic_key="perimeter_walling",
        value=None,
        unit="m2",
        authority="provisional",
        status="blocked",
        confidence=0.0,
        abstained=True,
        blocking_reasons=("wall_height_unresolved",),
    )
    assert abstained.to_dict()["value"] is None

    with pytest.raises(ValueError):
        QuantityEvidence(
            quantity_id="q3",
            family="wall_area",
            semantic_key="perimeter_walling",
            value=None,
            unit="m2",
            authority="provisional",
            status="blocked",
            confidence=0.0,
            abstained=True,
        )


def test_quantity_rejects_negative_or_non_finite_values() -> None:
    base = dict(
        quantity_id="q1",
        family="floor_area",
        semantic_key="floor",
        unit="m2",
        evidence_ids=("ev1",),
        authority="documented_dimension",
        status="firm",
        confidence=1.0,
    )
    with pytest.raises(ValueError):
        QuantityEvidence(value=-1.0, **base)
    with pytest.raises(ValueError):
        QuantityEvidence(value=float("nan"), **base)


def test_canonical_json_serializes_enums_and_nested_metadata_deterministically() -> None:
    q = QuantityEvidence(
        quantity_id="q1",
        family="opening_count",
        semantic_key="W1",
        value=2,
        unit="ea",
        evidence_ids=("ev1",),
        authority="schedule_extracted",
        status="firm",
        confidence=1.0,
        metadata={"z": 2, "a": {"b": 1}},
    )
    first = canonical_contract_json(q)
    second = canonical_contract_json(q)
    assert first == second
    assert '"schema_version":"1.0.0"' in first


def test_shadow_contract_is_deliberately_gold_free() -> None:
    row = ShadowQuantityComparison(
        family="opening_count",
        semantic_key="W1",
        legacy_quantity_id="legacy_w1",
        new_quantity_id="new_w1",
        legacy_value=7,
        new_value=7,
        unit="ea",
        absolute_delta=0,
        relative_delta=0,
        status="agree",
    )
    payload = row.to_dict()
    assert "expected" not in payload
    assert "expected_quantity" not in payload
    assert "benchmark" not in payload


def test_authority_state_vocabulary_is_frozen_for_migration_control() -> None:
    assert [state.value for state in MigrationAuthorityState] == [
        "legacy_authoritative",
        "new_shadow",
        "new_selective",
        "new_authoritative",
        "legacy_retired",
    ]
