from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import json
import fitz
import pytest

import pb_auto_geometry_v1219 as auto
from pb_customer_output_verification import verify_sealed_customer_output
from pb_live_canonical_coverage_registry import collect_live_canonical_coverage
from pb_live_opening_count_source_closed_export import (
    build_live_opening_count_source_traces,
    seal_live_opening_count_run,
)
from pb_live_physical_net_wall_integration import (
    collect_live_physical_net_wall_claim,
)
from pb_source_closed_run_export import SourceClosedRunConflictError
from pb_takeoff_coverage_audit_adapter import build_runtime_coverage_publication
from tests.test_live_physical_opening_void_composition import _complete_void_pdf


def _floor_plan_with_schedule_quantity(
    *,
    tag: str = "W1",
    quantity: int | None,
) -> bytes:
    payload = _complete_void_pdf(tag=tag)
    doc = fitz.open(stream=payload, filetype="pdf")
    try:
        page = doc[0]
        # View classification is source-owned; make the synthetic source an
        # explicit floor plan rather than relying on a viewport-name heuristic.
        page.insert_text(fitz.Point(20.0, 24.0), "FLOOR PLAN")
        if quantity is not None:
            # Extend the existing synthetic opening schedule with a real
            # explicit quantity column. The historical default count=1 is not
            # sufficient for the positive commercial path.
            page.insert_text(fitz.Point(680.0, 500.0), "QTY")
            page.insert_text(fitz.Point(680.0, 530.0), str(int(quantity)))
        return bytes(doc.tobytes(garbage=4, deflate=True))
    finally:
        doc.close()


def test_explicit_schedule_quantity_reaches_live_opening_count_quantity_and_registry(
    tmp_path,
) -> None:
    path = tmp_path / "counted-opening.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))

    claim = collect_live_physical_net_wall_claim(path, pages=(0,))

    assert len(claim.canonical_openings) == 1
    opening = claim.canonical_openings[0]
    assert opening.opening_kind == "window"
    assert opening.type_mark == "W1"

    assert len(claim.opening_count_quantity_evidence) == 1, {
        "claim_reasons": claim.reason_codes,
        "opening": claim.canonical_openings[0].to_dict() if claim.canonical_openings else None,
    }
    quantity = claim.opening_count_quantity_evidence[0]
    assert quantity.family == "opening_count"
    assert quantity.semantic_key == "opening_count:W1"
    assert quantity.value == 1.0
    assert quantity.unit == "ea"
    assert quantity.input_entity_ids == (opening.canonical_opening_id,)
    assert quantity.metadata["schedule_corroborated"] is True
    assert quantity.metadata["opening_mark"] == "W1"

    summaries, gaps = collect_live_canonical_coverage(
        objects=claim.canonical_openings,
        quantities=claim.opening_count_quantity_evidence,
        registry_run_scope="live-opening-count-regression",
    )
    assert summaries
    # Other lifecycle diagnostics may remain for the shared door/window identity
    # family; the count bridge only needs to prove an explicit quantity link.
    records = [
        record
        for summary in summaries
        for record in summary.object_records
        if record.object_id == opening.canonical_opening_id
    ]
    assert len(records) == 1
    assert quantity.quantity_id in records[0].quantity_ids

    report = build_runtime_coverage_publication(summaries, family_gaps=gaps)
    opening_family = report["family_reports"]["opening"]
    assert opening_family["stage_counts"]["QUANTIFIED"] == 1
    assert "explicit_quantity_link_unavailable" not in opening_family["reason_codes"]


def test_explicit_schedule_count_reaches_customer_runtime_row_even_without_wall_quantity(
    tmp_path,
) -> None:
    path = tmp_path / "counted-opening-customer.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    assert claim.opening_count_quantity_evidence, {
        "claim_reasons": claim.reason_codes,
        "opening": claim.canonical_openings[0].to_dict() if claim.canonical_openings else None,
    }
    count_quantity = claim.opening_count_quantity_evidence[0]

    app = SimpleNamespace(
        lquery=lambda *_args, **_kwargs: [{"id": 1, "path": str(path)}]
    )
    with patch(
        "pb_live_physical_net_wall_integration.collect_live_physical_net_wall_claim",
        return_value=claim,
    ):
        wall_rows = auto._try_physical_net_wall_rows(
            app,
            1,
            [{
                "document_id": 1,
                "page_no": 1,
                "selected": 1,
                "page_type": "floor plan",
            }],
            [],
        )

    # The wall fixture has no independent wall-height authority; opening
    # commercial output must not be gated on a successful net-wall row.
    assert wall_rows is None
    opening_rows = app._live_opening_takeoff_rows_by_workspace[1]
    count_rows = [
        dict(zip(auto.TAKEOFF_ROW_FIELDS, row))
        for row in opening_rows
        if count_quantity.quantity_id in str(
            dict(zip(auto.TAKEOFF_ROW_FIELDS, row))["source_reference"]
        )
    ]
    assert len(count_rows) == 1
    row = count_rows[0]
    assert row["section"] == "Openings"
    assert row["element"] == "Window count"
    assert row["location"] == "W1"
    assert row["quantity"] == 1.0
    assert row["unit"] == "ea"
    assert row["quantity_status"] == "To review"
    assert row["inclusion_status"] == "PROVISIONAL"
    provenance = json.loads(row["notes"])
    assert provenance["adapter"] == "commercial_takeoff"
    assert provenance["quantity"]["quantity_id"] == count_quantity.quantity_id
    assert provenance["measurement_authority"]["method"] == "direct_evidence"
    assert provenance["source_trace"]["canonical_entity_ids"] == list(
        count_quantity.input_entity_ids
    )

    sealed = seal_live_opening_count_run(
        claim,
        workspace_id=1,
        project_id="customer-workspace:1",
    )
    verified = verify_sealed_customer_output(sealed, [row])
    assert verified.valid_quantity_count == 1
    assert verified.customer_row_count == 1
    assert verified.verified_quantity_ids == (count_quantity.quantity_id,)


def test_implicit_schedule_default_never_becomes_live_commercial_count(
    tmp_path,
) -> None:
    path = tmp_path / "implicit-count-opening.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=None))

    claim = collect_live_physical_net_wall_claim(path, pages=(0,))

    assert claim.canonical_openings
    assert claim.opening_count_quantity_evidence == ()



def test_authenticated_opening_count_seals_exact_member_lineage(tmp_path) -> None:
    path = tmp_path / "counted-opening-sealed.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    assert len(claim.opening_count_quantity_evidence) == 1
    assert len(claim.canonical_openings) == 1
    quantity = claim.opening_count_quantity_evidence[0]
    opening = claim.canonical_openings[0]

    traces = build_live_opening_count_source_traces(
        claim,
        workspace_id=7,
        project_id="source-project",
    )
    trace = traces[quantity.quantity_id]
    assert trace.project_id == "source-project"
    assert trace.canonical_entity_ids == quantity.input_entity_ids
    assert set(quantity.evidence_ids).issubset(set(trace.evidence_ids))
    assert trace.metadata["aggregate_source_trace"] is False
    assert tuple(trace.metadata["member_opening_ids"]) == tuple(
        sorted(quantity.input_entity_ids)
    )
    assert trace.metadata["opening_mark"] == "W1"
    assert trace.source_page == opening.page_id
    assert trace.viewport_id == opening.viewport_id

    sealed = seal_live_opening_count_run(
        claim,
        workspace_id=7,
        project_id="source-project",
    )
    assert len(sealed.quantities) == 1
    row = sealed.quantities[0]
    assert row.quantity_id == quantity.quantity_id
    assert row.object_identity_refs == quantity.input_entity_ids
    assert row.value == 1.0
    assert row.unit == "ea"
    assert row.lineage_ok is True


def test_authenticated_opening_count_sealed_run_is_deterministic(tmp_path) -> None:
    path = tmp_path / "counted-opening-deterministic.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))

    first = seal_live_opening_count_run(
        claim,
        workspace_id=7,
        project_id="source-project",
    )
    second = seal_live_opening_count_run(
        claim,
        workspace_id=7,
        project_id="source-project",
    )

    assert first.run_id == second.run_id
    assert first.fingerprint == second.fingerprint
    assert first.to_json() == second.to_json()


def test_opening_count_sealing_rejects_unknown_physical_member(tmp_path) -> None:
    path = tmp_path / "counted-opening-unknown-member.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    quantity = claim.opening_count_quantity_evidence[0]
    damaged = replace(
        quantity,
        input_entity_ids=("unknown-physical-opening",),
    )
    damaged_claim = replace(
        claim,
        opening_count_quantity_evidence=(damaged,),
    )

    with pytest.raises(
        SourceClosedRunConflictError,
        match="unknown physical identity",
    ):
        seal_live_opening_count_run(
            damaged_claim,
            workspace_id=7,
            project_id="source-project",
        )


def test_opening_count_sealing_rejects_missing_member_evidence(tmp_path) -> None:
    path = tmp_path / "counted-opening-missing-evidence.pdf"
    path.write_bytes(_floor_plan_with_schedule_quantity(quantity=1))
    claim = collect_live_physical_net_wall_claim(path, pages=(0,))
    quantity = claim.opening_count_quantity_evidence[0]
    opening = claim.canonical_openings[0]
    physical_ids = set(opening.source_observation_ids)
    assert physical_ids
    damaged = replace(
        quantity,
        evidence_ids=tuple(
            value
            for value in quantity.evidence_ids
            if value not in physical_ids
        ),
    )
    damaged_claim = replace(
        claim,
        opening_count_quantity_evidence=(damaged,),
    )

    with pytest.raises(
        SourceClosedRunConflictError,
        match="omits physical member evidence",
    ):
        seal_live_opening_count_run(
            damaged_claim,
            workspace_id=7,
            project_id="source-project",
        )

@pytest.mark.parametrize("extra_member", ("", "duplicate"))
def test_count_bridge_refuses_malformed_representative_universe(extra_member):
    """A 'complete' count may not omit blank or duplicated source members."""
    from pb_live_opening_count_quantity_publication import (
        publish_live_authenticated_opening_count_quantities,
    )
    from pb_live_wall_opening_authority_composition import (
        compose_live_wall_opening_authority,
    )
    from pb_source_visibility_authority import SourceVisibilityProducer

    source = SourceVisibilityProducer(
        producer_method="count-representative-universe-test",
        producer_version="1",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="count-representative-universe-test",
        source_bytes=_floor_plan_with_schedule_quantity(quantity=1),
        source_locator="memory://count-representative-universe-test.pdf",
    )
    composition = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )
    original = composition.semantic_enumeration_result
    assert original.record is not None
    reps = original.record.representative_observation_ids
    assert reps
    extra = reps[0] if extra_member == "duplicate" else ""
    malformed = replace(
        original,
        record=replace(
            original.record,
            representative_observation_ids=(*reps, extra),
        ),
    )
    changed = replace(composition, semantic_enumeration_result=malformed)
    quantities = publish_live_authenticated_opening_count_quantities(
        source_visibility_producer=source,
        wall_opening_composition=changed,
    )
    assert quantities == ()

def test_count_bridge_rejects_two_representatives_for_same_opening():
    """Source identity collision must not overwrite a schedule binding."""
    from pb_live_opening_count_quantity_publication import (
        publish_live_authenticated_opening_count_quantities,
    )
    from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
    from pb_source_visibility_authority import SourceVisibilityProducer
    from pb_source_observation_authority import ObservationSelector

    source = SourceVisibilityProducer(
        producer_method="count-binding-collision-test", producer_version="1",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="count-binding-collision-test",
        source_bytes=_floor_plan_with_schedule_quantity(quantity=1),
        source_locator="memory://count-binding-collision-test.pdf",
    )
    composition = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )
    result = composition.semantic_enumeration_result
    assert result.record is not None
    original_id = result.record.representative_observation_ids[0]
    original_selector = ObservationSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        observation_id=original_id,
    )
    same_opening = composition.physical_opening_authority.prove_existence(original_selector)
    assert same_opening.existence_record is not None
    duplicated = replace(
        composition,
        semantic_enumeration_result=replace(
            result,
            record=replace(
                result.record,
                representative_observation_ids=(original_id, "second-observation"),
            ),
        ),
    )
    with patch.object(
        composition.physical_opening_authority,
        "prove_existence",
        return_value=same_opening,
    ):
        assert publish_live_authenticated_opening_count_quantities(
            source_visibility_producer=source,
            wall_opening_composition=duplicated,
        ) == ()

@pytest.mark.parametrize("field,value", (
    ("physical_opening_universe_complete", 1),
    ("physical_opening_universe_complete", "true"),
    ("representative_observation_ids", None),
    ("representative_observation_ids", "observation-one"),
    ("representative_observation_ids", (42,)),
    ("representative_observation_ids", ("   ",)),
    ("representative_observation_ids", ("same", "same")),
    ("snapshot_id", "foreign-snapshot"),
))
def test_count_bridge_rejects_eight_malformed_source_inventory_cases(field, value):
    """No schedule count may be published from an untrusted semantic inventory."""
    from pb_live_opening_count_quantity_publication import (
        publish_live_authenticated_opening_count_quantities,
    )
    from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
    from pb_source_visibility_authority import SourceVisibilityProducer

    source = SourceVisibilityProducer(
        producer_method="count-malformed-source-inventory-test",
        producer_version="1",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="count-malformed-source-inventory-test",
        source_bytes=_floor_plan_with_schedule_quantity(quantity=1),
        source_locator="memory://count-malformed-source-inventory-test.pdf",
    )
    composition = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )
    result = composition.semantic_enumeration_result
    assert result.record is not None
    altered = replace(
        composition,
        semantic_enumeration_result=replace(
            result, record=replace(result.record, **{field: value}),
        ),
    )
    assert publish_live_authenticated_opening_count_quantities(
        source_visibility_producer=source,
        wall_opening_composition=altered,
    ) == ()

@pytest.mark.parametrize("defect", (
    "unresolved_member", "foreign_document", "foreign_revision",
    "foreign_sha", "foreign_snapshot", "blank_physical_id",
))
def test_count_universe_never_silently_drops_or_replays_physical_member(defect):
    from pb_live_opening_count_quantity_publication import (
        publish_live_authenticated_opening_count_quantities,
    )
    from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
    from pb_source_visibility_authority import SourceVisibilityProducer
    from pb_source_observation_authority import ObservationSelector
    from pb_migration_contracts import EvidenceResolutionStatus

    source = SourceVisibilityProducer(
        producer_method="count-member-integrity-test", producer_version="1",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="count-member-integrity-test",
        source_bytes=_floor_plan_with_schedule_quantity(quantity=1),
        source_locator="memory://count-member-integrity-test.pdf",
    )
    composition = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )
    semantic = composition.semantic_enumeration_result
    assert semantic.record is not None
    original_selector = ObservationSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        observation_id=semantic.record.representative_observation_ids[0],
    )
    original = composition.physical_opening_authority.prove_existence(original_selector)
    assert original.existence_record is not None
    if defect == "unresolved_member":
        replay = replace(original, status=EvidenceResolutionStatus.ABSTAINED)
    else:
        change = {
            "foreign_document": {"document_id": "other-document"},
            "foreign_revision": {"revision_id": "other-revision"},
            "foreign_sha": {"source_sha256": "other-sha"},
            "foreign_snapshot": {"snapshot_id": "other-snapshot"},
            "blank_physical_id": {"record_id": "   "},
        }[defect]
        replay = replace(original, existence_record=replace(original.existence_record, **change))
    with patch.object(
        composition.physical_opening_authority,
        "prove_existence",
        return_value=replay,
    ):
        assert publish_live_authenticated_opening_count_quantities(
            source_visibility_producer=source,
            wall_opening_composition=composition,
        ) == ()
