"""``PhysicalOpeningAuthority.visible_candidate_structures``: read-only, decides nothing.

The accessor exposes the page candidates (member observation ids + pattern) that
``classify_disposition`` / ``prove_existence`` / ``assess_visible_candidate_closure``
already use.  These tests pin that it is a faithful, deterministic, side-effect
free view and that no decision changes because it exists.  The synthetic
drawings check the accessor's behaviour only; they are not evidence about real
drawings and choose no production rule.
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import fitz
import pytest

from pb_migration_contracts import EvidenceResolutionStatus
from pb_physical_opening_authority import (
    JAMB_BOUNDED_TWO_FACE_INTERRUPTION,
    SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,
    STRUCTURAL_OPENING_CANDIDATE,
    VISIBLE_SOURCE_AUTHORITY_REQUIRED,
    PhysicalOpeningAuthority,
    PhysicalOpeningCandidateStructureResult,
)
from pb_source_observation_authority import (
    ObservationSelector,
    SourceObservationAuthorityResult,
    SourceObservationProducer,
)
from pb_source_visibility_authority import SourceVisibilityAuthority, SourceVisibilityProducer

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- fixtures
def _pdf(lines, *, width=700.0, height=650.0) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    for first, second in lines:
        page.draw_line(fitz.Point(*first), fitz.Point(*second), color=(0, 0, 0), width=1)
    payload = doc.tobytes()
    doc.close()
    return payload


def _wall(spans, top=100.0, gap=10.0):
    lines = []
    for x0, x1 in spans:
        lines.append(((x0, top), (x1, top)))
        lines.append(((x0, top + gap), (x1, top + gap)))
    return lines


def _jambs(xs, top=100.0, gap=10.0):
    return [((x, top), (x, top + gap)) for x in xs]


SINGLE = _wall([(20, 100), (140, 220)]) + _jambs([100, 140])
# Two openings separated by a visible solid wall stub. The stub is positive
# source continuation, so it must prevent a false spanning opening candidate.
ADJACENT = _wall([(20, 100), (140, 180), (220, 300)]) + _jambs([100, 140, 180, 220])
# One opening whose top wall face is also drawn by an overlapping stroke.
OVERLAPPING_STROKE = SINGLE + [((50, 100), (100, 100))]
# Look-alikes that must produce no candidate at all.
GAP_WITHOUT_JAMBS = _wall([(20, 100), (140, 220)])
JAMBS_ONLY = _jambs([100, 140])
ONE_FACE_ONLY = [((20, 100), (100, 100)), ((140, 100), (220, 100))] + _jambs([100, 140])
MISALIGNED_FACES = (
    [((20, 100), (100, 100)), ((140, 100), (220, 100))]
    + [((20, 110), (90, 110)), ((150, 110), (220, 110))]
    + _jambs([100, 140])
)


def _publish(lines, *, document_id="cand-struct", **page):
    source = SourceVisibilityProducer(producer_method="cand-struct-test", producer_version="1")
    published = source.ingest_native_pdf_bytes(
        document_id=document_id,
        source_bytes=_pdf(lines, **page),
        source_locator="memory://cand-struct.pdf",
    )
    return source, published


def _selector(published, observation_id):
    return ObservationSelector(
        document_id=published.revision.document_id,
        revision_id=published.revision.revision_id,
        source_sha256=published.revision.source_sha256,
        snapshot_id=published.snapshot.snapshot_id,
        observation_id=observation_id,
    )


def _structures(lines, **page):
    source, published = _publish(lines, **page)
    physical = PhysicalOpeningAuthority(source.authority())
    observation_id = sorted(published.visible_observation_ids)[0]
    return source, published, physical, physical.visible_candidate_structures(
        _selector(published, observation_id)
    )


def _signature(result):
    """Structure that must not depend on ids, coordinates or drawing order."""
    members = [set(c.source_observation_ids) for c in result.candidates]
    overlaps = sorted(
        len(members[i] & members[j])
        for i in range(len(members))
        for j in range(i + 1, len(members))
    )
    return (
        len(result.candidates),
        sorted(len(m) for m in members),
        sorted(c.structural_pattern for c in result.candidates),
        overlaps,
    )


# ------------------------------------------------------------ what it returns
def test_single_opening_is_one_six_member_candidate():
    _source, _published, _physical, result = _structures(SINGLE)
    assert isinstance(result, PhysicalOpeningCandidateStructureResult)
    assert result.status is EvidenceResolutionStatus.CANDIDATE
    assert result.status is not EvidenceResolutionStatus.CORROBORATED  # never authority
    assert result.reason_codes == (STRUCTURAL_OPENING_CANDIDATE,)
    assert result.page_id == "1"
    (candidate,) = result.candidates
    assert candidate.structural_pattern == JAMB_BOUNDED_TWO_FACE_INTERRUPTION
    assert len(candidate.source_observation_ids) == 6
    assert candidate.status is EvidenceResolutionStatus.CANDIDATE


def test_adjacent_openings_do_not_create_spanning_candidate():
    _source, _published, _physical, result = _structures(ADJACENT)
    members = [set(c.source_observation_ids) for c in result.candidates]
    assert len(members) == 2
    assert sorted(len(m) for m in members) == [6, 6]
    # The two real openings share only the solid middle wall-face stub. Positive
    # visible continuation across that stub forbids a third spanning candidate.
    assert len(members[0] & members[1]) == 2
    assert all(not (a <= b) for a in members for b in members if a is not b)


def test_overlapping_strokes_give_candidates_differing_by_one_member():
    _source, _published, _physical, result = _structures(OVERLAPPING_STROKE)
    members = [set(c.source_observation_ids) for c in result.candidates]
    assert len(members) == 2
    assert [len(m) for m in members] == [6, 6]
    assert len(members[0] & members[1]) == 5


@pytest.mark.parametrize(
    "lines", [GAP_WITHOUT_JAMBS, JAMBS_ONLY, ONE_FACE_ONLY, MISALIGNED_FACES]
)
def test_look_alikes_produce_no_candidates(lines):
    _source, _published, _physical, result = _structures(lines)
    assert result.status is EvidenceResolutionStatus.CANDIDATE  # enumerated, nothing found
    assert result.candidates == ()


# ------------------------------------------------- faithful to the disposition
@pytest.mark.parametrize("lines", [SINGLE, ADJACENT, OVERLAPPING_STROKE, GAP_WITHOUT_JAMBS])
def test_structures_are_exactly_the_candidates_the_disposition_uses(lines):
    source, published, physical, _ = _structures(lines)
    result = physical.visible_candidate_structures(
        _selector(published, sorted(published.visible_observation_ids)[0])
    )
    for observation_id in sorted(published.visible_observation_ids):
        disposition = physical.classify_disposition(_selector(published, observation_id))
        containing = {
            c.candidate_id
            for c in result.candidates
            if observation_id in c.source_observation_ids
        }
        assert containing == set(disposition.candidate_ids)


def test_result_is_identical_whichever_page_observation_names_the_page():
    source, published, physical, _ = _structures(ADJACENT)
    results = [
        physical.visible_candidate_structures(_selector(published, observation_id))
        for observation_id in sorted(published.visible_observation_ids)
    ]
    assert all(result == results[0] for result in results)


# --------------------------------------------------- decides nothing / no mutation
def test_calling_the_accessor_changes_no_decision():
    source, published = _publish(ADJACENT)
    touched = PhysicalOpeningAuthority(source.authority())
    fresh = PhysicalOpeningAuthority(source.authority())
    ids = sorted(published.visible_observation_ids)
    touched.visible_candidate_structures(_selector(published, ids[0]))
    for observation_id in ids:
        selector = _selector(published, observation_id)
        assert touched.classify_disposition(selector) == fresh.classify_disposition(selector)
        left, right = touched.prove_existence(selector), fresh.prove_existence(selector)
        assert (left.status, left.reason_codes, left.existence_record) == (
            right.status,
            right.reason_codes,
            right.existence_record,
        )
        assert touched.assess_visible_candidate_closure(
            selector
        ) == fresh.assess_visible_candidate_closure(selector)


def test_result_is_immutable_and_repeatable_and_adds_no_cache_entries():
    source, published, physical, first = _structures(ADJACENT)
    keys_before = set(physical._visible_candidate_cache)  # noqa: SLF001 - state check only
    second = physical.visible_candidate_structures(
        _selector(published, sorted(published.visible_observation_ids)[-1])
    )
    assert second == first
    assert set(physical._visible_candidate_cache) == keys_before  # noqa: SLF001
    assert isinstance(first.candidates, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.status = EvidenceResolutionStatus.CORROBORATED  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.candidates[0].source_observation_ids = ()  # type: ignore[misc]
    assert isinstance(first.candidates[0].source_observation_ids, tuple)


def test_repeated_reads_and_fresh_authorities_agree():
    source, published = _publish(ADJACENT)
    selector = _selector(published, sorted(published.visible_observation_ids)[0])
    first = PhysicalOpeningAuthority(source.authority()).visible_candidate_structures(selector)
    second = PhysicalOpeningAuthority(source.authority()).visible_candidate_structures(selector)
    assert first == second
    ids = [c.candidate_id for c in first.candidates]
    assert ids == sorted(ids)  # candidates are returned in candidate-id order


def test_independent_ingests_of_the_same_drawing_have_the_same_structure():
    signatures = {repr(_signature(_structures(ADJACENT)[3])) for _ in range(3)}
    assert len(signatures) == 1


# ---------------------------------------------------- fail closed / input checks
def test_selector_type_is_validated():
    source, _published = _publish(SINGLE)
    physical = PhysicalOpeningAuthority(source.authority())
    with pytest.raises(TypeError):
        physical.visible_candidate_structures("not-a-selector")  # type: ignore[arg-type]


def test_raw_authority_without_visibility_abstains():
    producer = SourceObservationProducer(producer_method="cand-struct-raw", producer_version="1")
    published = producer.ingest_native_pdf_bytes(
        document_id="cand-struct-raw",
        source_bytes=_pdf(SINGLE),
        source_locator="memory://raw.pdf",
    )
    physical = PhysicalOpeningAuthority(producer.authority())
    observation_id = sorted(published.snapshot.observation_ids)[0]
    result = physical.visible_candidate_structures(_selector(published, observation_id))
    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.candidates == ()
    assert result.reason_codes == (VISIBLE_SOURCE_AUTHORITY_REQUIRED,)


def test_unresolvable_selector_yields_no_candidates():
    source, published = _publish(SINGLE)
    physical = PhysicalOpeningAuthority(source.authority())
    result = physical.visible_candidate_structures(_selector(published, "source_observation_missing"))
    assert result.status is not EvidenceResolutionStatus.CANDIDATE
    assert result.candidates == ()


def test_visibility_conflict_is_reported_not_enumerated(monkeypatch):
    source, published = _publish(SINGLE)
    physical = PhysicalOpeningAuthority(source.authority())

    def conflict(self, selector):
        return SourceObservationAuthorityResult(
            status=EvidenceResolutionStatus.CONFLICT,
            proposition=None,
            physical_opening_existence="physical_opening_existence_unresolved",
            reason_codes=("forced_visibility_conflict",),
        )

    monkeypatch.setattr(SourceVisibilityAuthority, "resolve_visible", conflict)
    result = physical.visible_candidate_structures(
        _selector(published, sorted(published.visible_observation_ids)[0])
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.candidates == ()
    assert result.reason_codes == ("forced_visibility_conflict",)


def test_snapshot_integrity_failure_is_reported_not_enumerated(monkeypatch):
    source, published = _publish(SINGLE)
    physical = PhysicalOpeningAuthority(source.authority())
    failure = SourceObservationAuthorityResult(
        status=EvidenceResolutionStatus.CONFLICT,
        proposition=None,
        physical_opening_existence="physical_opening_existence_unresolved",
        reason_codes=("forced_snapshot_failure",),
    )
    monkeypatch.setattr(
        PhysicalOpeningAuthority,
        "_visible_snapshot_records",
        lambda self, seed: ((), (failure,)),
    )
    result = physical.visible_candidate_structures(
        _selector(published, sorted(published.visible_observation_ids)[0])
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.candidates == ()
    assert result.reason_codes[0] == SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE
    assert "forced_snapshot_failure" in result.reason_codes


# ------------------------------------------------------------ metamorphic checks
def _transform(lines, fn):
    return [(fn(a), fn(b)) for a, b in lines]


@pytest.mark.parametrize("name", ["translate", "scale", "transpose"])
@pytest.mark.parametrize("lines", [SINGLE, ADJACENT, OVERLAPPING_STROKE])
def test_structure_is_invariant_under_exact_similarity_transforms(name, lines):
    _s, _p, _ph, base = _structures(lines)
    fn = {
        "translate": lambda p: (p[0] + 30.0, p[1] + 40.0),
        "scale": lambda p: (p[0] * 2.0, p[1] * 2.0),
        "transpose": lambda p: (p[1], p[0]),
    }[name]
    page = {"scale": {"width": 1400.0, "height": 1300.0}}.get(name, {})
    if name == "transpose":
        page = {"width": 650.0, "height": 700.0}
    _s, _p, _ph, moved = _structures(_transform(lines, fn), **page)
    assert _signature(moved) == _signature(base)


@pytest.mark.parametrize("lines", [SINGLE, ADJACENT, OVERLAPPING_STROKE])
def test_structure_is_invariant_to_drawing_order(lines):
    _s, _p, _ph, base = _structures(lines)
    _s, _p, _ph, reordered = _structures(list(reversed(lines)))
    assert _signature(reordered) == _signature(base)


def test_splitting_a_wall_segment_keeps_the_candidate_structure():
    split = _wall([(20, 60), (60, 100), (140, 220)]) + _jambs([100, 140])
    _s, _p, _ph, base = _structures(SINGLE)
    _s, _p, _ph, result = _structures(split)
    assert len(result.candidates) == len(base.candidates) == 1
    assert len(result.candidates[0].source_observation_ids) == 6


def test_unrelated_content_leaves_existing_candidates_unchanged():
    _s, _p, _ph, base = _structures(ADJACENT)
    extra = [((500, 500), (600, 540)), ((500, 560), (640, 580)), ((10, 300), (10, 340))]
    _s, _p, _ph, more = _structures(ADJACENT + extra)
    assert _signature(more) == _signature(base)


def test_page_expansion_leaves_the_candidate_structure_unchanged():
    _s, _p, _ph, base = _structures(ADJACENT)
    _s, _p, _ph, wide = _structures(ADJACENT, width=2000.0, height=1500.0)
    assert _signature(wide) == _signature(base)


# ------------------------------------------------------------------ isolation
def test_only_the_diagnostic_calls_the_accessor():
    callers = []
    for path in sorted(REPO.glob("*.py")):
        if path.name in {"pb_physical_opening_authority.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        if any(
            isinstance(node, ast.Attribute) and node.attr == "visible_candidate_structures"
            for node in ast.walk(tree)
        ):
            callers.append(path.name)
    assert callers == ["pb_semantic_conflict_diagnostic.py"]
