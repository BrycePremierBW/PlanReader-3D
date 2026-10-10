"""Live source-authenticated opening-count QuantityEvidence publication.

This module is a narrow commercial bridge over already reviewed producer-owned
authorities. It does not create opening instances, infer schedule counts, or
accept caller-selected candidate sets.

A positive quantity requires:
- a complete source-authenticated semantic physical-opening universe;
- producer-owned physical opening identity for every member;
- a unique source schedule-row binding for each classified member;
- an explicit (not historical default) schedule quantity;
- exact agreement between the authenticated physical instance count and the
  source-declared schedule quantity; and
- authoritative floor-plan view classification.

Schedule-only quantities and implicit default counts remain fail-closed.
"""
from __future__ import annotations

from pb_generic_opening_count_authority import (
    GenericOpeningCountProducer,
    GenericOpeningCountSelector,
)
from pb_live_wall_opening_authority_composition import (
    LiveWallOpeningAuthorityComposition,
)
from pb_migration_contracts import EvidenceResolutionStatus, QuantityEvidence
from pb_opening_tag_normalization import normalize_opening_tag
from pb_page_view_class_source_adapter import (
    build_source_page_view_class_authority,
)
from pb_schedule_opening_instance_binding_authority import (
    ScheduleOpeningInstanceBindingProducer,
    ScheduleOpeningInstanceBindingSelector,
)
from pb_schedule_row_quantity_authority import ScheduleRowQuantityProducer
from pb_schedule_row_quantity_binding_adapter import (
    publish_schedule_row_quantity_from_binding,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer


LIVE_OPENING_COUNT_QUANTITY_SCHEMA_VERSION = "1.0.0"


def publish_live_authenticated_opening_count_quantities(
    *,
    source_visibility_producer: SourceVisibilityProducer,
    wall_opening_composition: LiveWallOpeningAuthorityComposition,
) -> tuple[QuantityEvidence, ...]:
    """Publish deterministic per-mark counts from live producer-owned authority.

    The caller supplies no opening IDs, marks, counts, schedule rows, or expected
    quantities. Every positive selector is discovered from the producer-owned
    semantic opening inventory and source-authenticated schedule bindings.
    """

    if type(source_visibility_producer) is not SourceVisibilityProducer:
        raise TypeError("source_visibility_producer must be producer-owned")
    if type(wall_opening_composition) is not LiveWallOpeningAuthorityComposition:
        raise TypeError(
            "wall_opening_composition must be LiveWallOpeningAuthorityComposition"
        )

    published = source_visibility_producer.published_snapshot_for_revision(
        wall_opening_composition.revision_id
    )
    semantic = wall_opening_composition.semantic_enumeration_result
    semantic_record = semantic.record
    if (
        published is None
        or semantic.status is not EvidenceResolutionStatus.CORROBORATED
        or semantic_record is None
        or semantic_record.physical_opening_universe_complete is not True
        or published.revision.document_id != semantic_record.document_id
        or published.revision.revision_id != semantic_record.revision_id
        or published.revision.source_sha256 != semantic_record.source_sha256
        or published.snapshot.snapshot_id != semantic_record.snapshot_id
    ):
        return ()

    scope_id = str(semantic_record.decision_scope_id or "").strip()
    if not scope_id:
        return ()

    # The producer's representative universe must not silently lose blank
    # members or duplicate source observations when later keyed by identity.
    raw_representatives = semantic_record.representative_observation_ids
    if not isinstance(raw_representatives, (tuple, list)):
        return ()
    representatives = tuple(
        value.strip() if isinstance(value, str) else ""
        for value in raw_representatives
    )
    if (
        not representatives
        or any(not value for value in representatives)
        or len(set(representatives)) != len(representatives)
    ):
        return ()

    binding_producer = (
        ScheduleOpeningInstanceBindingProducer.from_source_visibility_producer(
            source_visibility_producer
        )
    )
    physical = wall_opening_composition.physical_opening_authority

    # Discover every binding from the complete producer-owned semantic universe.
    # A missing binding is retained as unresolved by GenericOpeningCountAuthority;
    # this bridge never narrows the universe to the convenient members.
    binding_selectors: dict[str, ScheduleOpeningInstanceBindingSelector] = {}
    binding_results = {}
    for observation_id in representatives:
        opening_selector = ObservationSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            observation_id=str(observation_id),
        )
        existence = physical.prove_existence(opening_selector)
        opening = existence.existence_record
        if (
            existence.status is not EvidenceResolutionStatus.CORROBORATED
            or opening is None
        ):
            continue
        if (
            opening.document_id != published.revision.document_id
            or opening.revision_id != published.revision.revision_id
            or opening.source_sha256 != published.revision.source_sha256
            or opening.snapshot_id != published.snapshot.snapshot_id
            or not isinstance(opening.record_id, str)
            or not opening.record_id.strip()
        ):
            return ()
        selector = ScheduleOpeningInstanceBindingSelector(
            document_id=opening.document_id,
            revision_id=opening.revision_id,
            source_sha256=opening.source_sha256,
            snapshot_id=opening.snapshot_id,
            decision_scope_id=scope_id,
            opening_record_id=opening.record_id,
        )
        if opening.record_id in binding_selectors:
            # Two representatives resolving to one physical opening cannot
            # silently overwrite a binding and certify complete count coverage.
            return ()
        binding_selectors[opening.record_id] = selector
        binding_results[opening.record_id] = binding_producer.publish_scope(
            opening_selector=opening_selector,
            decision_scope_id=scope_id,
        )

    if not binding_selectors:
        return ()

    binding_authority = binding_producer.authority()
    row_quantity_producer = ScheduleRowQuantityProducer.create()

    # Publish each exact explicit schedule row once through the existing
    # authority-resolved adapter. Historical parser default count=1 never
    # reaches this positive path.
    published_rows: set[tuple[str, tuple[str, ...]]] = set()
    authenticated_marks: set[str] = set()
    for opening_id in sorted(binding_results):
        result = binding_results[opening_id]
        record = result.record
        if (
            result.status is not EvidenceResolutionStatus.CORROBORATED
            or record is None
            or not record.schedule_row_count_explicit
            or record.schedule_row_count is None
        ):
            continue

        normalized = normalize_opening_tag(record.schedule_row_type_mark)
        if normalized is None:
            continue
        if (
            not isinstance(record.schedule_page_id, str)
            or not record.schedule_page_id.strip()
            or not isinstance(record.schedule_row_observation_ids, (tuple, list))
            or not record.schedule_row_observation_ids
            or any(not isinstance(value, str) or not value.strip()
                   for value in record.schedule_row_observation_ids)
            or len(set(record.schedule_row_observation_ids))
            != len(record.schedule_row_observation_ids)
        ):
            continue
        row_key = (
            record.schedule_page_id,
            tuple(sorted(record.schedule_row_observation_ids)),
        )
        if row_key not in published_rows:
            row_result = publish_schedule_row_quantity_from_binding(
                schedule_row_quantity_producer=row_quantity_producer,
                schedule_binding_authority=binding_authority,
                binding_selector=binding_selectors[opening_id],
            )
            if (
                row_result.status is not EvidenceResolutionStatus.CORROBORATED
                or row_result.record is None
            ):
                continue
            published_rows.add(row_key)
        authenticated_marks.add(normalized.tag)

    if not authenticated_marks:
        return ()

    view_authority = build_source_page_view_class_authority(
        source_visibility_producer=source_visibility_producer,
        revision_id=published.revision.revision_id,
        page_ids=wall_opening_composition.page_ids,
    )
    count_producer = GenericOpeningCountProducer.from_authorities(
        opening_universe_authority=(
            wall_opening_composition.opening_universe_completeness_authority
        ),
        physical_opening_authority=physical,
        viewport_view_class_authority=view_authority,
        schedule_binding_authority=binding_authority,
        schedule_row_quantity_authority=row_quantity_producer.authority(),
    )

    quantities: list[QuantityEvidence] = []
    seen_quantity_ids: set[str] = set()
    for mark in sorted(authenticated_marks):
        result = count_producer.publish(
            GenericOpeningCountSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                decision_scope_id=scope_id,
                opening_mark=mark,
            )
        )
        record = result.record
        quantity = record.quantity_evidence if record is not None else None
        if (
            result.status is not EvidenceResolutionStatus.CORROBORATED
            or record is None
            or not record.schedule_corroborated
            or quantity is None
            or quantity.abstained
            or not quantity.input_entity_ids
        ):
            continue
        if quantity.quantity_id in seen_quantity_ids:
            continue
        seen_quantity_ids.add(quantity.quantity_id)
        quantities.append(quantity)

    return tuple(sorted(quantities, key=lambda item: item.quantity_id))


__all__ = [
    "LIVE_OPENING_COUNT_QUANTITY_SCHEMA_VERSION",
    "publish_live_authenticated_opening_count_quantities",
]
