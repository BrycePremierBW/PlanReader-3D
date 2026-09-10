from __future__ import annotations

from pb_migration_contracts import DocumentEvidence, EntityEvidence, EvidenceAtom, EvidenceResolutionStatus, ViewportEvidence, ViewportResolutionStatus
from pb_migration_provider_envelope import ProviderContext
from pb_wall_height_authority import build_wall_height_quantity

SHA = "e" * 64


def _context():
    return ProviderContext(
        run_id="run", workspace_id="ws", project_id="project", document_id="doc",
        source_sha256=SHA, revision_id="R1", current_revision_id="R1",
        selected_pages=(0,), owned_viewport_ids=("vp",), evidence_snapshot_id="evsnap",
        canonical_graph_snapshot_id="graphsnap", measurement_authority_snapshot_id="measuresnap",
        owned_page_numbers=(1,), viewport_page_ownership=(("vp", 1),),
    )


def _document(ids):
    return DocumentEvidence(document_id="doc", source_sha256=SHA, page_count=1, page_ids=("page-1",), evidence_ids=tuple(ids))


def _viewport():
    return ViewportEvidence(
        viewport_id="vp", document_id="doc", page_id="page-1", bbox=(0, 0, 100, 100),
        view_type="floor_plan", status=ViewportResolutionStatus.RESOLVED, confidence=1.0,
    )


def _entity(ids):
    return EntityEvidence(
        candidate_entity_id="w1", candidate_type="wall", evidence_ids=tuple(ids),
        status=EvidenceResolutionStatus.CORROBORATED, confidence=1.0,
    )


def _ev(eid, kind, value, unit="m", method="vector_text", metadata=None):
    return EvidenceAtom(
        evidence_id=eid, document_id="doc", page_id="page-1", viewport_id="vp",
        kind=kind, method=method, normalized_value=value, unit=unit, confidence=1.0,
        status=EvidenceResolutionStatus.CORROBORATED, metadata=metadata or {},
    )


def test_explicit_height_is_firm() -> None:
    ev = _ev("h", "wall_height_dimension", 3000, "mm")
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("h",)), viewport=_viewport(),
        entity=_entity(("h",)), direct_height_evidence=ev,
    )
    assert qty.abstained is False
    assert qty.value == 3.0


def test_legitimate_documented_2_8m_is_allowed() -> None:
    ev = _ev("h", "wall_height_dimension", 2.8, "m", method="vector_text")
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("h",)), viewport=_viewport(),
        entity=_entity(("h",)), direct_height_evidence=ev,
    )
    assert qty.abstained is False
    assert qty.value == 2.8


def test_legacy_default_2_8m_is_never_authority() -> None:
    ev = _ev("h", "wall_height_dimension", 2.8, "m", method="legacy_default")
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("h",)), viewport=_viewport(),
        entity=_entity(("h",)), direct_height_evidence=ev,
    )
    assert qty.abstained
    assert "default_or_assumed_height_forbidden" in qty.blocking_reasons


def test_assumed_height_metadata_is_never_authority() -> None:
    ev = _ev("h", "wall_height_dimension", 2.8, "m", metadata={"assumed": True})
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("h",)), viewport=_viewport(),
        entity=_entity(("h",)), direct_height_evidence=ev,
    )
    assert qty.abstained
    assert "default_or_assumed_height_forbidden" in qty.blocking_reasons


def test_supported_datum_pair_derives_height() -> None:
    lower = _ev("d1", "floor_level_datum", 12.4, "m")
    upper = _ev("d2", "ceiling_level_datum", 15.2, "m")
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("d1", "d2")), viewport=_viewport(),
        entity=_entity(("d1", "d2")), lower_datum_evidence=lower, upper_datum_evidence=upper,
    )
    assert qty.abstained is False
    assert qty.value == 2.8
    assert qty.formula == "upper_datum - lower_datum"


def test_missing_height_evidence_abstains() -> None:
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("x",)), viewport=_viewport(),
        entity=_entity(("x",)),
    )
    assert qty.abstained
    assert "no_authoritative_wall_height_evidence" in qty.blocking_reasons


def test_unresolved_height_evidence_abstains() -> None:
    ev = EvidenceAtom(
        evidence_id="h", document_id="doc", page_id="page-1", viewport_id="vp",
        kind="wall_height_dimension", method="vector_text", normalized_value=3.0, unit="m",
        confidence=0.5, status=EvidenceResolutionStatus.CANDIDATE,
    )
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("h",)), viewport=_viewport(),
        entity=_entity(("h",)), direct_height_evidence=ev,
    )
    assert qty.abstained
    assert "height_evidence_not_corroborated" in qty.blocking_reasons


def test_nonpositive_datum_difference_abstains() -> None:
    lower = _ev("d1", "floor_level_datum", 15.2, "m")
    upper = _ev("d2", "ceiling_level_datum", 12.4, "m")
    qty = build_wall_height_quantity(
        wall_id="w1", context=_context(), document=_document(("d1", "d2")), viewport=_viewport(),
        entity=_entity(("d1", "d2")), lower_datum_evidence=lower, upper_datum_evidence=upper,
    )
    assert qty.abstained
    assert "nonpositive_or_invalid_datum_height" in qty.blocking_reasons
