"""Semantic conflict diagnostic: diagnostic-only, gold-free, read-only.

Natural authority behaviour is checked on real synthetic drawings.  Rare paths
(closure overlap, source failure, lineage) are forced by wrapping the
authorities' PUBLIC methods the same way while publishing and while diagnosing,
so the attribution table is tested against the decisions the semantic authority
actually took.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from pb_item35_production_authority_shadow import (
    ITEM35_PRODUCTION_SHADOW_SCHEMA_VERSION,
    collect_item35_authority_shadow,
)
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_physical_opening_authority import (
    AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,
    PHYSICAL_OPENING_DISPOSITION_CONFLICT,
    SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,
    PhysicalOpeningAuthority,
    PhysicalOpeningCandidateClosureResult,
    PhysicalOpeningDispositionResult,
)
from pb_provider_gold_isolation import (
    FORBIDDEN_MODULES,
    FORBIDDEN_NAME_FRAGMENTS,
    walk_local_import_graph,
)
from pb_semantic_conflict_diagnostic import (
    CONFLICT_PATH_AMBIGUOUS_CANDIDATES,
    CONFLICT_PATH_CLOSURE_UNRESOLVED_OVERLAP,
    CONFLICT_PATH_DISPOSITION_CONFLICT_OTHER,
    CONFLICT_PATH_LINEAGE_MISMATCH,
    CONFLICT_PATH_SNAPSHOT_INTEGRITY_FAILURE,
    CONFLICT_PATH_SOURCE_OBSERVATION_FAILURE,
    CONFLICT_PATH_UNATTRIBUTED,
    FAMILY_AMBIGUOUS_CANDIDATES,
    FAMILY_CLOSURE_UNRESOLVED_OVERLAP,
    FAMILY_SOURCE_OBSERVATION_FAILURE,
    SHADOW_PRODUCER_VERSION,
    RELATION_NOT_APPLICABLE,
    RELATION_ONE_PROVEN_OPENING_PLUS_COMPETITOR,
    RELATION_SHARED_BETWEEN_PROVEN_OPENINGS,
    RESIDUAL_PATH_CLOSURE_UNRESOLVED,
    RESIDUAL_PATH_UNRESOLVED_DISPOSITION,
    STATIC_UNAVAILABLE,
    aggregate_semantic_conflict_diagnostics,
    collect_semantic_conflict_diagnostic,
    collect_semantic_scope,
    diagnose_semantic_conflicts,
)
from pb_semantic_opening_enumeration_authority import (
    SEMANTIC_OPENING_PHYSICAL_CONFLICT,
    SemanticOpeningEnumerationProducer,
    SemanticOpeningEnumerationResult,
)
from pb_source_observation_authority import ObservationSelector, SourceObservationAuthorityResult
from pb_source_visibility_authority import SourceVisibilityAuthority, SourceVisibilityProducer
from scripts import semantic_conflict_report as report_script

REPO = Path(__file__).resolve().parents[1]
MODULE = "pb_semantic_conflict_diagnostic"
DOC = "conflict-test"


# ---------------------------------------------------------------- fixtures
def _line(page, first, second):
    page.draw_line(fitz.Point(*first), fitz.Point(*second), color=(0, 0, 0), width=1)


def _wall(page, spans, top=100.0, gap=10.0):
    for x0, x1 in spans:
        _line(page, (x0, top), (x1, top))
        _line(page, (x0, top + gap), (x1, top + gap))


def _jamb(page, x, top=100.0, gap=10.0):
    _line(page, (x, top), (x, top + gap))


def _write(path: Path, draw, *, title=True) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=700, height=650)
    if title:
        page.insert_text(fitz.Point(40, 40), "GROUND FLOOR PLAN", color=(0, 0, 0))
    draw(page)
    doc.save(path)
    doc.close()
    return path


def _single(page):  # one clean opening
    _wall(page, [(20, 100), (140, 220)])
    _jamb(page, 100)
    _jamb(page, 140)


def _adjacent_separate(page):  # two openings separated by a short wall stub
    _wall(page, [(20, 100), (140, 180), (220, 300)])
    for x in (100, 140, 180, 220):
        _jamb(page, x)


@pytest.fixture()
def single_pdf(tmp_path):
    return _write(tmp_path / "single.pdf", _single)


@pytest.fixture()
def adjacent_pdf(tmp_path):
    return _write(tmp_path / "adjacent.pdf", _adjacent_separate)


def _diagnose_with(pdf, document_id, pages=None):
    source, result = collect_semantic_scope(pdf, document_id=document_id, pages=pages)
    return source, result, diagnose_semantic_conflicts(
        source_visibility_producer=source, semantic_result=result
    )


def _diagnose(pdf, pages=None):
    return _diagnose_with(pdf, DOC, pages)


# ------------------------------------------ same scope as the Item 35 shadow
@pytest.mark.parametrize("pages", [None, [0]])
def test_collected_semantic_record_is_the_shadows_record(adjacent_pdf, pages):
    diag = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id=DOC, pages=pages)
    shadow = collect_item35_authority_shadow(adjacent_pdf, document_id=DOC, pages=pages)
    assert diag.semantic_record_id == shadow["semantic_record_id"]
    assert diag.counts_dict()["conflict"] > 0
    assert diag.counts_dict()["visible"] == shadow["visible_observation_count"]
    assert diag.counts_dict()["openings"] == shadow["semantic_opening_count"]
    assert diag.counts_dict()["residual"] == shadow["residual_visible_observation_count"]
    assert SEMANTIC_OPENING_PHYSICAL_CONFLICT in diag.semantic_reason_codes
    # Same authenticated scope, fully identified.
    assert diag.document_id == shadow["document_id"]
    assert diag.revision_id == shadow["revision_id"]
    assert diag.source_sha256 == shadow["source_sha256"]
    assert diag.snapshot_id == shadow["snapshot_id"]


def test_a_record_from_another_producer_is_refused(single_pdf, adjacent_pdf):
    source_a, result_a = collect_semantic_scope(single_pdf, document_id=DOC)
    source_b, _result_b = collect_semantic_scope(adjacent_pdf, document_id=DOC)
    with pytest.raises(ValueError, match="does not belong"):
        diagnose_semantic_conflicts(
            source_visibility_producer=source_b, semantic_result=result_a
        )
    assert isinstance(source_a, SourceVisibilityProducer)


def test_input_types_are_validated(single_pdf):
    source, result = collect_semantic_scope(single_pdf, document_id=DOC)
    with pytest.raises(TypeError):
        diagnose_semantic_conflicts(source_visibility_producer=object(), semantic_result=result)
    with pytest.raises(TypeError):
        diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=object())
    # A caller cannot substitute an authority over different data.
    with pytest.raises(TypeError):
        diagnose_semantic_conflicts(  # type: ignore[call-arg]
            source_visibility_producer=source,
            semantic_result=result,
            physical_opening_authority=object(),
        )


# ----------------------------------------------------- natural ambiguity path
def test_ambiguous_candidates_are_identified_with_their_relationships(adjacent_pdf):
    _source, result, diag = _diagnose(adjacent_pdf)
    record = result.record
    assert tuple(sorted(c.evidence.observation_id for c in diag.conflicts)) == tuple(
        record.conflict_observation_ids
    )
    assert diag.rederivation_consistent is True
    assert diag.counts_dict()["conflict"] == len(diag.conflicts) > 0
    for item in diag.conflicts:
        assert item.paths == (CONFLICT_PATH_AMBIGUOUS_CANDIDATES,)
        assert item.disposition.status == "conflict"
        assert item.disposition.disposition == PHYSICAL_OPENING_DISPOSITION_CONFLICT
        assert item.disposition.reason_codes == (AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,)
        assert len(item.disposition.candidate_ids) >= 2
        # source-owned identity of the observation is exposed, not invented
        assert item.evidence.source_primitive_ref
        assert item.evidence.page_id == "1"
        assert len(item.evidence.geometry) == 4
        assert item.in_opening_support is True
    relations = {c.candidate_relation for c in diag.conflicts}
    assert RELATION_SHARED_BETWEEN_PROVEN_OPENINGS in relations
    assert relations <= {
        RELATION_SHARED_BETWEEN_PROVEN_OPENINGS,
        RELATION_ONE_PROVEN_OPENING_PLUS_COMPETITOR,
    }
    shared = [c for c in diag.conflicts if c.candidate_relation == RELATION_SHARED_BETWEEN_PROVEN_OPENINGS]
    assert all(len(c.proven_opening_record_ids) >= 2 for c in shared)
    # Ambiguous observations are grouped only by shared candidate ids.
    assert len(diag.clusters) >= 1
    clustered = {oid for cluster in diag.clusters for oid in cluster.observation_ids}
    assert clustered == {c.evidence.observation_id for c in diag.conflicts}


def test_unresolvable_representatives_are_reported_not_hidden(adjacent_pdf):
    """Producer-selected representatives must re-prove the exact opening.

    Shared support observations can remain ambiguous diagnostics, but they must
    never be selected as semantic representatives.
    """
    seen_unresolved = 0
    for document_id in (DOC, "x:adjacent_separate", "doc-a", "doc-b", "doc-c", "doc-d"):
        _source, result, diag = _diagnose_with(adjacent_pdf, document_id)
        record = result.record
        ambiguous_representatives = {
            representative
            for representative in record.representative_observation_ids
            if representative in set(record.conflict_observation_ids)
        }
        reported = {
            item.representative_observation_id for item in diag.representative_existence_unresolved
        }
        assert reported == ambiguous_representatives
        for item in diag.representative_existence_unresolved:
            assert item.opening_record_id in record.physical_opening_record_ids
            assert item.status == "conflict"
            assert item.reason_codes == (AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,)
        seen_unresolved += len(reported)
        assert (
            "proven_opening_representative_cannot_reprove_existence" in diag.unavailable
        ) == bool(reported)
    # Representatives are selected only from selectors that already proved the
    # exact physical opening, so no semantic representative can be unresolved.
    assert seen_unresolved == 0


def test_clean_scope_has_no_conflict_and_is_consistent(single_pdf):
    _source, _result, diag = _diagnose(single_pdf)
    assert diag.conflicts == () and diag.residuals == () and diag.clusters == ()
    assert diag.rederivation_consistent is True
    assert diag.semantic_status == EvidenceResolutionStatus.CORROBORATED.value


def test_unavailable_information_is_declared_and_not_invented(adjacent_pdf):
    _source, _result, diag = _diagnose(adjacent_pdf)
    assert set(STATIC_UNAVAILABLE) <= set(diag.unavailable)
    # Candidate patterns / members ARE available now (read-only accessor), so they
    # are no longer declared unavailable for a scope whose structure was read ...
    assert "candidate_structural_pattern_for_ambiguous_candidates" not in diag.unavailable
    assert "candidate_member_observation_ids_for_unproven_candidates" not in diag.unavailable

    def keys(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield key
                yield from keys(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from keys(inner)

    # ... but raw member ids are still not copied into the output: only counts and
    # histograms of them are.
    names = set(keys(diag.to_dict()))
    assert not {"structural_pattern", "member_observation_ids", "candidate_members"} & names


# ----------------------------------------------------- forced path attribution
def _wrap_disposition(monkeypatch, overrides):
    original = PhysicalOpeningAuthority.classify_disposition

    def patched(self, selector):
        forced = overrides.get(selector.observation_id)
        return forced if forced is not None else original(self, selector)

    monkeypatch.setattr(PhysicalOpeningAuthority, "classify_disposition", patched)


def _wrap_closure(monkeypatch, unresolved_observation_ids):
    def patched(self, selector):
        return PhysicalOpeningCandidateClosureResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            page_id="1",
            candidate_universe_complete=False,
            raw_candidate_count=3,
            resolved_candidate_count=2,
            unresolved_candidate_ids=("closure_candidate_1",),
            unresolved_observation_ids=tuple(unresolved_observation_ids),
            reason_codes=("physical_opening_candidate_closure_unresolved",),
        )

    monkeypatch.setattr(PhysicalOpeningAuthority, "assess_visible_candidate_closure", patched)


def _wrap_visible(monkeypatch, transform):
    original = SourceVisibilityAuthority.resolve_visible

    def patched(self, selector):
        result = original(self, selector)
        replaced = transform(selector.observation_id, result)
        return replaced if replaced is not None else result

    monkeypatch.setattr(SourceVisibilityAuthority, "resolve_visible", patched)


def _support_ids(pdf):
    _source, result = collect_semantic_scope(pdf, document_id=DOC)
    return tuple(result.record.opening_support_observation_ids)


def test_closure_overlap_with_a_proven_opening_is_attributed(monkeypatch, single_pdf):
    target = min(_support_ids(single_pdf))
    _wrap_closure(monkeypatch, [target])
    _source, result, diag = _diagnose(single_pdf)
    assert result.record.conflict_observation_ids == (target,)
    (item,) = diag.conflicts
    assert item.evidence.observation_id == target
    assert item.paths == (CONFLICT_PATH_CLOSURE_UNRESOLVED_OVERLAP,)
    assert item.in_closure_unresolved is True and item.in_opening_support is True
    assert item.candidate_relation == RELATION_NOT_APPLICABLE
    (closure,) = diag.closure_pages
    assert closure.candidate_universe_complete is False
    assert closure.unresolved_observation_ids == (target,)
    assert diag.rederivation_consistent is True


def test_closure_unresolved_observation_outside_support_is_residual_not_conflict(
    monkeypatch, tmp_path
):
    pdf = _write(tmp_path / "stray.pdf", lambda p: (_single(p), _line(p, (300, 300), (400, 320))))
    source, result = collect_semantic_scope(pdf, document_id=DOC)
    stray = sorted(
        set(result.record.visible_observation_ids) - set(result.record.opening_support_observation_ids)
    )
    assert stray
    with monkeypatch.context() as patch:
        _wrap_closure(patch, [stray[0]])
        source, result = collect_semantic_scope(pdf, document_id=DOC)
        diag = diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=result)
    assert stray[0] in result.record.residual_visible_observation_ids
    assert diag.conflicts == ()
    (residual,) = [r for r in diag.residuals if r.evidence.observation_id == stray[0]]
    assert RESIDUAL_PATH_CLOSURE_UNRESOLVED in residual.paths


def test_source_observation_failure_via_snapshot_integrity_is_attributed(monkeypatch, single_pdf):
    target = min(_support_ids(single_pdf))
    _wrap_disposition(
        monkeypatch,
        {
            target: PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CONFLICT,
                disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                reason_codes=(SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
            )
        },
    )
    _source, result, diag = _diagnose(single_pdf)
    assert target in result.record.conflict_observation_ids
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    # A snapshot-wide integrity failure is not a per-observation visibility conflict.
    assert item.paths == (CONFLICT_PATH_SNAPSHOT_INTEGRITY_FAILURE,)
    assert item.disposition.reason_codes == (SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,)
    summary = aggregate_semantic_conflict_diagnostics([diag])
    assert summary["conflict_family_observation_counts"][FAMILY_SOURCE_OBSERVATION_FAILURE] >= 1


def test_source_observation_failure_at_visibility_is_attributed_in_document_scope(
    monkeypatch, single_pdf
):
    target = min(_support_ids(single_pdf))

    def conflict(observation_id, result):
        if observation_id != target:
            return None
        return SourceObservationAuthorityResult(
            status=EvidenceResolutionStatus.CONFLICT,
            proposition=None,
            physical_opening_existence="physical_opening_existence_unresolved",
            reason_codes=("forced_visibility_conflict",),
        )

    _wrap_visible(monkeypatch, conflict)
    _source, result, diag = _diagnose(single_pdf)
    assert target in result.record.conflict_observation_ids
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    assert item.paths == (CONFLICT_PATH_SOURCE_OBSERVATION_FAILURE,)
    assert item.evidence.visible_status == "conflict"
    assert item.evidence.visible_reason_codes == ("forced_visibility_conflict",)
    assert item.evidence.page_id is None and item.evidence.geometry == ()


def test_lineage_mismatch_is_attributed(monkeypatch, single_pdf):
    target = min(_support_ids(single_pdf))

    def forged(observation_id, result):
        if observation_id != target or result.observation is None:
            return None
        return dataclasses.replace(
            result, observation=dataclasses.replace(result.observation, document_id="other-doc")
        )

    _wrap_visible(monkeypatch, forged)
    _source, result, diag = _diagnose(single_pdf)
    assert target in result.record.conflict_observation_ids
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    assert item.paths == (CONFLICT_PATH_LINEAGE_MISMATCH,)


def test_other_disposition_conflicts_are_not_mislabelled_as_ambiguity(monkeypatch, single_pdf):
    target = min(_support_ids(single_pdf))
    _wrap_disposition(
        monkeypatch,
        {
            target: PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CONFLICT,
                disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                reason_codes=("some_new_conflict_reason",),
            )
        },
    )
    _source, _result, diag = _diagnose(single_pdf)
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    assert item.paths == (CONFLICT_PATH_DISPOSITION_CONFLICT_OTHER,)
    assert item.disposition.reason_codes == ("some_new_conflict_reason",)


def test_unreproducible_conflicts_are_unattributed_not_guessed(monkeypatch, single_pdf):
    target = min(_support_ids(single_pdf))
    with monkeypatch.context() as patch:
        _wrap_disposition(
            patch,
            {
                target: PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CONFLICT,
                    disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                    reason_codes=("some_new_conflict_reason",),
                )
            },
        )
        source, result = collect_semantic_scope(single_pdf, document_id=DOC)
    # Diagnose WITHOUT the wrapper: the public results no longer reproduce it.
    diag = diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=result)
    assert target in result.record.conflict_observation_ids
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    assert item.paths == (CONFLICT_PATH_UNATTRIBUTED,)
    assert diag.rederivation_consistent is False
    assert "observation_paths_not_reproduced_by_public_results" in diag.unavailable


def test_observations_can_carry_more_than_one_path(monkeypatch, single_pdf):
    target = min(_support_ids(single_pdf))
    _wrap_closure(monkeypatch, [target])
    _wrap_disposition(
        monkeypatch,
        {
            target: PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CONFLICT,
                disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                candidate_ids=("cand_b", "cand_a"),
            )
        },
    )
    _source, _result, diag = _diagnose(single_pdf)
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    assert item.paths == tuple(
        sorted((CONFLICT_PATH_AMBIGUOUS_CANDIDATES, CONFLICT_PATH_CLOSURE_UNRESOLVED_OVERLAP))
    )
    assert item.disposition.candidate_ids == ("cand_a", "cand_b")


def test_closure_overlap_requires_the_observation_to_support_a_proven_opening(
    monkeypatch, tmp_path
):
    """An ambiguous observation that is closure-unresolved but supports NO proven
    opening is not an 'overlap with a proven opening'; only ambiguity applies."""
    pdf = _write(tmp_path / "s.pdf", lambda p: (_single(p), _line(p, (300, 300), (400, 320))))
    _source, result = collect_semantic_scope(pdf, document_id=DOC)
    stray = sorted(
        set(result.record.visible_observation_ids) - set(result.record.opening_support_observation_ids)
    )[0]
    _wrap_disposition(
        monkeypatch,
        {
            stray: PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CONFLICT,
                disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                reason_codes=(AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES,),
                candidate_ids=("cand_a", "cand_b"),
            )
        },
    )
    _wrap_closure(monkeypatch, [stray])
    _source, result, diag = _diagnose(pdf)
    assert result.record.conflict_observation_ids == (stray,)
    (item,) = diag.conflicts
    assert item.in_opening_support is False and item.in_closure_unresolved is True
    assert item.paths == (CONFLICT_PATH_AMBIGUOUS_CANDIDATES,)
    assert item.candidate_relation == "no_proven_opening"


def test_a_visibility_conflict_only_counts_as_a_conflict_path_in_document_scope(
    monkeypatch, single_pdf
):
    """In page scope the semantic authority treats a non-corroborated observation as
    unresolved scope, never as a conflict, so it must not be attributed as one."""
    target = min(_support_ids(single_pdf))
    with monkeypatch.context() as patch:
        _wrap_disposition(
            patch,
            {
                target: PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CONFLICT,
                    disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                    reason_codes=("some_new_conflict_reason",),
                )
            },
        )
        source, result = collect_semantic_scope(single_pdf, document_id=DOC, pages=[0])
    assert result.record.decision_scope_kind == "pages"
    assert target in result.record.conflict_observation_ids

    def conflict(observation_id, current):
        if observation_id != target:
            return None
        return SourceObservationAuthorityResult(
            status=EvidenceResolutionStatus.CONFLICT,
            proposition=None,
            physical_opening_existence="physical_opening_existence_unresolved",
            reason_codes=("forced_visibility_conflict",),
        )

    _wrap_visible(monkeypatch, conflict)
    diag = diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=result)
    item = next(c for c in diag.conflicts if c.evidence.observation_id == target)
    assert item.paths == (CONFLICT_PATH_UNATTRIBUTED,)


def test_residual_closure_attribution_requires_an_incomplete_closure(monkeypatch, tmp_path):
    """A closure that reports itself complete adds nothing to the residual set, so
    it must not be credited with an observation that is residual for another reason."""
    pdf = _write(tmp_path / "s.pdf", lambda p: (_single(p), _line(p, (300, 300), (400, 320))))
    _source, result = collect_semantic_scope(pdf, document_id=DOC)
    stray = sorted(
        set(result.record.visible_observation_ids) - set(result.record.opening_support_observation_ids)
    )[0]
    _wrap_disposition(
        monkeypatch,
        {
            stray: PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CANDIDATE,
                disposition="candidate_unresolved",
                reason_codes=("insufficient_independent_source_lineage",),
                candidate_ids=("only_candidate",),
            )
        },
    )

    def complete_but_listing(self, selector):
        return PhysicalOpeningCandidateClosureResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            page_id="1",
            candidate_universe_complete=True,
            raw_candidate_count=1,
            resolved_candidate_count=1,
            unresolved_candidate_ids=(),
            unresolved_observation_ids=(stray,),
            reason_codes=("physical_opening_candidate_closure_resolved",),
        )

    monkeypatch.setattr(
        PhysicalOpeningAuthority, "assess_visible_candidate_closure", complete_but_listing
    )
    _source, result, diag = _diagnose(pdf)
    assert stray in result.record.residual_visible_observation_ids
    (residual,) = [r for r in diag.residuals if r.evidence.observation_id == stray]
    assert residual.paths == (RESIDUAL_PATH_UNRESOLVED_DISPOSITION,)


def test_the_diagnosed_bytes_are_the_hashed_bytes(single_pdf, adjacent_pdf):
    """A caller that already read the file passes those bytes; the path is only a
    locator, so the content diagnosed cannot differ from the content hashed."""
    payload = adjacent_pdf.read_bytes()
    from_bytes = collect_semantic_conflict_diagnostic(
        single_pdf, document_id=DOC, source_bytes=payload
    )
    direct = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id=DOC)
    assert from_bytes.source_sha256 == direct.source_sha256
    assert from_bytes.counts_dict() == direct.counts_dict()


def test_empty_page_scope_is_rejected_before_any_ingestion(monkeypatch, single_pdf):
    def boom(*_args, **_kwargs):
        raise AssertionError("ingestion must not start for an invalid page scope")

    monkeypatch.setattr(SourceVisibilityProducer, "ingest_native_pdf_bytes", boom)
    with pytest.raises(ValueError, match="at least one page"):
        collect_semantic_scope(single_pdf, document_id=DOC, pages=[])


def test_residual_unresolved_dispositions_are_attributed(monkeypatch, tmp_path):
    pdf = _write(tmp_path / "s.pdf", lambda p: (_single(p), _line(p, (300, 300), (400, 320))))
    _source, result = collect_semantic_scope(pdf, document_id=DOC)
    stray = sorted(
        set(result.record.visible_observation_ids) - set(result.record.opening_support_observation_ids)
    )[0]
    _wrap_disposition(
        monkeypatch,
        {
            stray: PhysicalOpeningDispositionResult(
                status=EvidenceResolutionStatus.CANDIDATE,
                disposition="candidate_unresolved",
                reason_codes=("insufficient_independent_source_lineage",),
                candidate_ids=("only_candidate",),
            )
        },
    )
    _source, result, diag = _diagnose(pdf)
    assert stray in result.record.residual_visible_observation_ids
    (residual,) = [r for r in diag.residuals if r.evidence.observation_id == stray]
    assert residual.paths == (RESIDUAL_PATH_UNRESOLVED_DISPOSITION,)
    assert residual.disposition.candidate_ids == ("only_candidate",)


# ------------------------------------------------------- record absent / shell
def test_absent_semantic_record_is_reported_unavailable(single_pdf):
    source, _result = collect_semantic_scope(single_pdf, document_id=DOC)
    absent = SemanticOpeningEnumerationResult(
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("semantic_opening_source_coverage_incomplete",),
        record=None,
    )
    diag = diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=absent)
    assert diag.semantic_record_id is None
    assert diag.conflicts == () and diag.residuals == ()
    assert "semantic_record_absent" in diag.unavailable
    # The cause is public data and must not be discarded.
    assert diag.semantic_status == "abstained"
    assert diag.semantic_reason_codes == ("semantic_opening_source_coverage_incomplete",)
    summary = aggregate_semantic_conflict_diagnostics([diag])
    assert summary["semantic_status_counts"] == {"abstained": 1}
    assert summary["semantic_record_reason_code_counts"] == {
        "semantic_opening_source_coverage_incomplete": 1
    }


# ------------------------------------------------- determinism / immutability
def test_diagnostic_is_deterministic_with_a_recomputable_stable_id(adjacent_pdf):
    first = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id=DOC)
    second = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id=DOC)
    assert first == second and first.record_id == second.record_id
    payload = first.to_dict()
    record_id = payload.pop("record_id")
    assert record_id == stable_contract_id("semantic_conflict_diagnostic", payload, digest_chars=32)
    other = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id="another-doc")
    assert other.record_id != first.record_id
    with pytest.raises(ValueError, match="record_id"):
        dataclasses.replace(first, unavailable=())
    with pytest.raises(ValueError, match="never grants commercial authority"):
        dataclasses.replace(first, commercial_authority_granted=True)


def _shared_objects(pdf, document_id=DOC):
    """The producer objects a diagnostic must leave untouched, built directly so
    the test can hold (and inspect) the semantic producer as well."""
    payload = pdf.read_bytes()
    source = SourceVisibilityProducer(
        producer_method="planreader_live_item35_shadow", producer_version="1.0.0"
    )
    published = source.ingest_native_pdf_bytes(
        document_id=document_id, source_bytes=payload, source_locator=str(pdf)
    )
    semantic_producer = SemanticOpeningEnumerationProducer.from_source_visibility_producer(source)
    scope = f"item35:document:{published.revision.revision_id}"
    result = semantic_producer.publish_document_scope(
        revision_id=published.revision.revision_id, decision_scope_id=scope
    )
    return source, semantic_producer, published, scope, result


def test_diagnosing_leaves_the_shared_producers_untouched(adjacent_pdf):
    source, semantic_producer, published, scope, result = _shared_objects(adjacent_pdf)
    revision = published.revision.revision_id
    results_before = repr(sorted(semantic_producer._results.items(), key=lambda kv: kv[0]))
    physical_keys_before = sorted(semantic_producer._physical_opening_authorities)
    snapshot_before = source.published_snapshot_for_revision(revision)
    visible_before = [
        source.authority().resolve_visible(
            ObservationSelector(
                document_id=snapshot_before.revision.document_id,
                revision_id=revision,
                source_sha256=snapshot_before.revision.source_sha256,
                snapshot_id=snapshot_before.snapshot.snapshot_id,
                observation_id=observation_id,
            )
        )
        for observation_id in snapshot_before.visible_observation_ids
    ]

    first = diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=result)
    second = diagnose_semantic_conflicts(source_visibility_producer=source, semantic_result=result)

    assert first == second and first.counts_dict()["conflict"] > 0
    assert repr(sorted(semantic_producer._results.items(), key=lambda kv: kv[0])) == results_before
    assert sorted(semantic_producer._physical_opening_authorities) == physical_keys_before
    assert source.published_snapshot_for_revision(revision) == snapshot_before
    snapshot_after = source.published_snapshot_for_revision(revision)
    visible_after = [
        source.authority().resolve_visible(
            ObservationSelector(
                document_id=snapshot_after.revision.document_id,
                revision_id=revision,
                source_sha256=snapshot_after.revision.source_sha256,
                snapshot_id=snapshot_after.snapshot.snapshot_id,
                observation_id=observation_id,
            )
        )
        for observation_id in snapshot_after.visible_observation_ids
    ]
    assert visible_after == visible_before
    # The same producer still serves the identical record (its equivocation guard
    # would raise if the diagnostic had altered anything it stores).
    again = semantic_producer.publish_document_scope(revision_id=revision, decision_scope_id=scope)
    assert again == result
    exported = first.to_dict()
    exported["conflicts"].clear()
    assert first.to_dict() == second.to_dict()


def test_the_diagnostic_matches_the_shadow_on_a_shared_scope_and_changes_nothing(adjacent_pdf):
    before = collect_item35_authority_shadow(adjacent_pdf, document_id=DOC)
    diag = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id=DOC)
    after = collect_item35_authority_shadow(adjacent_pdf, document_id=DOC)
    assert before == after
    assert diag.semantic_record_id == before["semantic_record_id"]
    assert SHADOW_PRODUCER_VERSION == ITEM35_PRODUCTION_SHADOW_SCHEMA_VERSION


def test_no_caller_supplied_authority_parameter_exists():
    import inspect

    assert "physical_opening_authority" not in inspect.signature(diagnose_semantic_conflicts).parameters


def test_closure_result_does_not_depend_on_which_page_observation_seeds_it(adjacent_pdf):
    """The diagnostic seeds closure with the smallest diagnosed observation; the
    producer seeds it with the first visible one.  Closure must not care."""
    source, result = collect_semantic_scope(adjacent_pdf, document_id=DOC)
    record = result.record
    physical = PhysicalOpeningAuthority(source.authority())
    seeds = sorted(record.visible_observation_ids)
    results = {
        physical.assess_visible_candidate_closure(
            ObservationSelector(
                document_id=record.document_id,
                revision_id=record.revision_id,
                source_sha256=record.source_sha256,
                snapshot_id=record.snapshot_id,
                observation_id=seed,
            )
        )
        for seed in (seeds[0], seeds[len(seeds) // 2], seeds[-1])
    }
    assert len(results) == 1


# ---------------------------------------------------------------- aggregation
def _closure_diag(monkeypatch, pdf):
    with monkeypatch.context() as patch:
        target = min(_support_ids(pdf))
        _wrap_closure(patch, [target])
        _source, _result, diag = _diagnose(pdf)
    return diag


def _failure_diag(monkeypatch, pdf):
    with monkeypatch.context() as patch:
        target = min(_support_ids(pdf))
        _wrap_disposition(
            patch,
            {
                target: PhysicalOpeningDispositionResult(
                    status=EvidenceResolutionStatus.CONFLICT,
                    disposition=PHYSICAL_OPENING_DISPOSITION_CONFLICT,
                    reason_codes=(SNAPSHOT_OBSERVATION_INTEGRITY_FAILURE,),
                )
            },
        )
        _source, _result, diag = _diagnose(pdf)
    return diag


def test_aggregate_reports_ties_and_is_order_invariant(monkeypatch, single_pdf, adjacent_pdf):
    closure = _closure_diag(monkeypatch, single_pdf)
    failure = _failure_diag(monkeypatch, single_pdf)
    ambiguous = collect_semantic_conflict_diagnostic(adjacent_pdf, document_id=DOC)
    clean = collect_semantic_conflict_diagnostic(single_pdf, document_id="clean")

    two = aggregate_semantic_conflict_diagnostics([closure, failure])
    assert two["dominant_conflict_paths_by_observations"] == sorted(
        [CONFLICT_PATH_CLOSURE_UNRESOLVED_OVERLAP, CONFLICT_PATH_SNAPSHOT_INTEGRITY_FAILURE]
    )
    assert two["dominant_conflict_paths_by_scopes"] == two["dominant_conflict_paths_by_observations"]
    # The families the investigation asks about tie as well; no tie is broken.
    assert two["dominant_conflict_families_by_observations"] == sorted(
        [FAMILY_CLOSURE_UNRESOLVED_OVERLAP, FAMILY_SOURCE_OBSERVATION_FAILURE]
    )
    assert two["dominant_conflict_families_by_scopes"] == two["dominant_conflict_families_by_observations"]

    diagnostics = [closure, failure, ambiguous, clean]
    forward = aggregate_semantic_conflict_diagnostics(diagnostics)
    backward = aggregate_semantic_conflict_diagnostics(list(reversed(diagnostics)))
    assert forward == backward and forward["record_id"] == backward["record_id"]
    assert forward["scope_count"] == 4 and forward["scopes_with_conflict"] == 3
    assert forward["conflict_observations_total"] == sum(len(d.conflicts) for d in diagnostics)
    assert forward["dominant_conflict_paths_by_observations"] == [CONFLICT_PATH_AMBIGUOUS_CANDIDATES]
    counts = forward["conflict_path_observation_counts"]
    assert counts[CONFLICT_PATH_AMBIGUOUS_CANDIDATES] == len(ambiguous.conflicts)
    assert counts[CONFLICT_PATH_CLOSURE_UNRESOLVED_OVERLAP] == 1
    assert counts[CONFLICT_PATH_SNAPSHOT_INTEGRITY_FAILURE] == 1
    assert forward["dominant_conflict_families_by_observations"] == [FAMILY_AMBIGUOUS_CANDIDATES]
    assert forward["conflict_disposition_reason_code_counts"][AMBIGUOUS_PHYSICAL_OPENING_CANDIDATES] == len(
        ambiguous.conflicts
    )
    per_conflict = forward["ambiguous_candidates_per_conflict"]
    assert per_conflict["count"] == len(ambiguous.conflicts)
    assert per_conflict["min"] >= 2
    assert sum(forward["ambiguous_candidate_relation_counts"].values()) == len(ambiguous.conflicts)
    assert forward["conflict_clusters"]["count"] == len(ambiguous.clusters)
    assert forward["proven_openings_with_unresolvable_representative"] == len(
        ambiguous.representative_existence_unresolved
    )
    assert forward["commercial_authority_granted"] is False
    assert set(STATIC_UNAVAILABLE) <= set(forward["unavailable_scope_counts"])


def test_aggregate_edge_cases():
    empty = aggregate_semantic_conflict_diagnostics([])
    assert empty["scope_count"] == 0
    assert empty["dominant_conflict_paths_by_observations"] == []
    assert empty["record_id"] == aggregate_semantic_conflict_diagnostics(iter(()))["record_id"]
    with pytest.raises(TypeError, match="SemanticConflictDiagnostic"):
        aggregate_semantic_conflict_diagnostics([{"not": "a diagnostic"}])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="SemanticConflictDiagnostic"):
        aggregate_semantic_conflict_diagnostics([1, 2])  # type: ignore[list-item]


# ------------------------------------------------- isolation / authority rules
def _pb_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return {name for name in found if name.startswith(("pb_", "scripts"))}


def test_module_only_reads_public_authority_seams():
    assert _pb_imports(REPO / f"{MODULE}.py") == {
        "pb_migration_contracts",
        "pb_physical_opening_authority",
        "pb_semantic_opening_enumeration_authority",
        "pb_source_observation_authority",
        "pb_source_visibility_authority",
    }
    assert _pb_imports(REPO / "scripts" / "semantic_conflict_report.py") == {MODULE}
    source = (REPO / f"{MODULE}.py").read_text(encoding="utf-8")
    # Public seams only: never a private authority method or attribute.
    for private in (
        "._visible_candidates_for",
        "._visible_all_structural_candidates",
        "._visible_structural_candidates",
        "._physical_opening_authorities",
        "._results",
        "._publish_scope",
    ):
        assert private not in source, private


def test_module_and_script_are_gold_free():
    visited, findings = walk_local_import_graph(MODULE)
    assert findings == () and not set(visited) & FORBIDDEN_MODULES
    for path in (REPO / f"{MODULE}.py", REPO / "scripts" / "semantic_conflict_report.py"):
        text = path.read_text(encoding="utf-8").lower()
        for fragment in FORBIDDEN_NAME_FRAGMENTS:
            assert fragment not in text, (path.name, fragment)
        assert "benchmarks/" not in text


def test_no_production_module_imports_the_diagnostic():
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        relative = path.relative_to(REPO)
        if relative.parts[0] in {"tests", "scripts", ".git"} or path.name == f"{MODULE}.py":
            continue
        if MODULE in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(relative))
    assert offenders == []


def test_importing_the_live_extractor_does_not_load_the_diagnostic():
    code = (
        "import sys\n"
        "import pb_planreader_pdf_extractor, pb_item35_production_authority_shadow\n"
        f"sys.exit(1 if {MODULE!r} in sys.modules else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]


# ---------------------------------------------------------------- the script
def test_script_report_is_deterministic_and_carries_the_breakdown(tmp_path, adjacent_pdf, single_pdf):
    missing = tmp_path / "missing.pdf"
    forward = report_script.build_report([adjacent_pdf, single_pdf, missing], detail="full")
    backward = report_script.build_report([missing, single_pdf, adjacent_pdf], detail="full")
    assert json.dumps(forward, sort_keys=True) == json.dumps(backward, sort_keys=True)
    statuses = {entry["label"]: entry["status"] for entry in forward["entries"]}
    assert statuses == {"adjacent.pdf": "ok", "single.pdf": "ok", "missing.pdf": "source_unavailable"}
    assert forward["summary"]["scope_count"] == 2
    assert forward["summary"]["dominant_conflict_paths_by_observations"] == [
        CONFLICT_PATH_AMBIGUOUS_CANDIDATES
    ]
    adjacent = next(e for e in forward["entries"] if e["label"] == "adjacent.pdf")
    assert adjacent["diagnostic"]["conflicts"]
    assert adjacent["examples"] and all(
        example["paths"] == [CONFLICT_PATH_AMBIGUOUS_CANDIDATES] for example in adjacent["examples"]
    )
    summary_only = report_script.build_report([adjacent_pdf], detail="summary")
    assert summary_only["entries"][0]["diagnostic"] is None


def test_script_document_id_is_content_derived(tmp_path, adjacent_pdf):
    other = tmp_path / "sub" / "a_different_name.pdf"
    other.parent.mkdir()
    other.write_bytes(adjacent_pdf.read_bytes())
    report = report_script.build_report([adjacent_pdf, other], detail="full")
    ids = {entry["diagnostic"]["semantic_record_id"] for entry in report["entries"]}
    assert len(ids) == 1
    assert all(
        entry["diagnostic"]["document_id"].startswith("item35_funnel:")
        for entry in report["entries"]
    )


def test_script_reports_errors_instead_of_hiding_them(tmp_path, adjacent_pdf):
    report = report_script.build_report([adjacent_pdf], pages=[9])  # out of range
    (entry,) = report["entries"]
    assert entry["status"] == "error" and "ValueError" in entry["error"]
    assert report["summary"]["scope_count"] == 0


def test_script_cli(tmp_path, adjacent_pdf, capsys):
    out = tmp_path / "out" / "report.json"
    assert report_script.main([str(adjacent_pdf), "--output", str(out), "--detail", "full"]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["scopes_with_conflict"] == 1
    assert report_script.main([str(adjacent_pdf)]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["scope_count"] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert report_script.main([str(empty)]) == 2
    with pytest.raises(SystemExit) as excinfo:
        report_script.main([str(adjacent_pdf), "--pages", "x"])
    assert excinfo.value.code == 2



def test_script_coverage_makes_partial_results_visible(tmp_path, monkeypatch, adjacent_pdf, single_pdf):
    absent_source, _ = collect_semantic_scope(single_pdf, document_id=DOC)
    absent_diag = diagnose_semantic_conflicts(
        source_visibility_producer=absent_source,
        semantic_result=SemanticOpeningEnumerationResult(
            status=EvidenceResolutionStatus.ABSTAINED,
            reason_codes=("semantic_opening_source_coverage_incomplete",),
            record=None,
        ),
    )
    real_collect = report_script.collect_semantic_conflict_diagnostic

    def collect(pdf_path, **kwargs):
        if Path(pdf_path).name == "single.pdf":
            return absent_diag
        return real_collect(pdf_path, **kwargs)

    monkeypatch.setattr(report_script, "collect_semantic_conflict_diagnostic", collect)
    missing = tmp_path / "missing.pdf"
    report = report_script.build_report([adjacent_pdf, single_pdf, missing])
    assert report["coverage"] == {
        "entries_total": 3,
        "entries_with_semantic_record": 1,
        "entries_without_semantic_record": 1,
        "entries_error": 0,
        "entries_source_unavailable": 1,
    }
    absent = next(e for e in report["entries"] if e["label"] == "single.pdf")
    assert absent["status"] == "semantic_record_absent"
    assert absent["semantic_status"] == "abstained"
    assert absent["semantic_reason_codes"] == ["semantic_opening_source_coverage_incomplete"]

    # exit code: partial input is not success
    assert report_script.main([str(adjacent_pdf), str(missing)]) == 1
    assert report_script.main([str(adjacent_pdf)]) == 0
    failing = report_script.build_report([adjacent_pdf], pages=[9])
    assert failing["coverage"]["entries_error"] == 1


def test_script_diagnoses_exactly_the_bytes_it_hashed(monkeypatch, adjacent_pdf):
    captured = {}
    real_collect = report_script.collect_semantic_conflict_diagnostic

    def spy(pdf_path, **kwargs):
        captured.update(kwargs)
        return real_collect(pdf_path, **kwargs)

    monkeypatch.setattr(report_script, "collect_semantic_conflict_diagnostic", spy)
    report = report_script.build_report([adjacent_pdf])
    payload = adjacent_pdf.read_bytes()
    assert captured["source_bytes"] == payload
    assert captured["document_id"] == report_script.document_id_for(payload)
    assert report["entries"][0]["pdf_sha256"] == __import__("hashlib").sha256(payload).hexdigest()


# ------------------------------------------------ candidate structure (schema 1.1.0)
def _overlapping_stroke(page):  # one opening + an overlapping duplicate stroke of a face
    _single(page)
    _line(page, (50, 100), (100, 100))


def _structure_sets(diag):
    return {name: dict(value) if isinstance(value, tuple) else value
            for name, value in dataclasses.asdict(diag.candidate_structure).items()}


def test_candidate_structure_of_adjacent_openings_is_reported_from_member_sets(adjacent_pdf):
    from pb_semantic_conflict_diagnostic import CandidateStructureSummary

    _source, _result, diag = _diagnose(adjacent_pdf)
    assert diag.schema_version == "1.1.0"
    summary = diag.candidate_structure
    assert isinstance(summary, CandidateStructureSummary)
    assert summary.pages_enumerated == 1 and summary.pages_unavailable == 0
    # A visible solid stub separates two real gaps; the false spanning candidate is removed.
    assert summary.candidates_total == 2
    assert dict(summary.candidates_by_pattern) == {"jamb_bounded_two_face_interruption": 2}
    assert dict(summary.members_per_candidate) == {"jamb_bounded_two_face_interruption:6": 2}
    # Ten observations support the two gaps; only the shared stub faces overlap.
    assert summary.observations_in_candidates == 10
    assert summary.observations_in_multiple_candidates == 2
    assert dict(summary.candidates_per_observation) == {"1": 8, "2": 2}
    # Neither separate gap is a one-member variation of the other.
    assert summary.variant_families_total == 2
    assert dict(summary.variant_family_sizes) == {"1": 2}
    assert summary.candidates_with_strict_superset == 0
    assert summary.candidates_with_identical_member_set == 0
    # Only the shared boundary is multiply supported by distinct gap families.
    assert summary.ambiguous_observations_assessed == len(diag.conflicts) == 2
    assert dict(summary.ambiguous_observation_family_span) == {"2": 2}
    assert summary.disposition_candidate_id_mismatches == 0
    assert {c.candidate_family_count for c in diag.conflicts} == {2}


def test_overlapping_strokes_form_one_variant_family(tmp_path):
    pdf = _write(tmp_path / "stroke.pdf", _overlapping_stroke)
    _source, _result, diag = _diagnose(pdf)
    summary = diag.candidate_structure
    assert summary.candidates_total == 2
    assert summary.variant_families_total == 1
    assert dict(summary.variant_family_sizes) == {"2": 1}
    # 5 of 6 members are shared, so 5 observations are ambiguous ...
    assert summary.ambiguous_observations_assessed == len(diag.conflicts) == 5
    # ... and all of them lie inside a single family (no cross-structure ambiguity)
    assert dict(summary.ambiguous_observation_family_span) == {"1": 5}
    assert {c.candidate_family_count for c in diag.conflicts} == {1}
    assert summary.disposition_candidate_id_mismatches == 0
    # Single-family is a description of member sets, never a resolution.
    assert all(c.paths == (CONFLICT_PATH_AMBIGUOUS_CANDIDATES,) for c in diag.conflicts)
    assert all(len(c.disposition.candidate_ids) == 2 for c in diag.conflicts)


def test_clean_scope_assesses_no_page_structure(single_pdf):
    _source, _result, diag = _diagnose(single_pdf)
    summary = diag.candidate_structure
    assert summary.pages_enumerated == 0 and summary.candidates_total == 0
    assert summary.ambiguous_observations_assessed == 0


def test_candidate_structure_is_deterministic_and_part_of_the_stable_id(adjacent_pdf):
    _s, _r, first = _diagnose(adjacent_pdf)
    _s, _r, second = _diagnose(adjacent_pdf)
    assert first.candidate_structure == second.candidate_structure
    assert first.to_dict()["candidate_structure"] == second.to_dict()["candidate_structure"]
    json.dumps(first.to_dict(), sort_keys=True)  # serializable
    # The structure is inside the hashed payload: changing it changes the id check.
    changed = dataclasses.replace(
        first.candidate_structure, candidates_total=first.candidate_structure.candidates_total + 1
    )
    with pytest.raises(ValueError, match="record_id does not match"):
        dataclasses.replace(first, candidate_structure=changed)


@pytest.mark.parametrize("transform", ["translate", "transpose"])
def test_candidate_structure_is_invariant_under_exact_similarity_transforms(
    tmp_path, adjacent_pdf, transform
):
    def moved(page):
        for x0, x1 in [(20, 100), (140, 180), (220, 300)]:
            for offset in (0.0, 10.0):
                a, b = ((x0, 100.0 + offset), (x1, 100.0 + offset))
                if transform == "translate":
                    a, b = (a[0] + 30, a[1] + 40), (b[0] + 30, b[1] + 40)
                else:
                    a, b = (a[1], a[0]), (b[1], b[0])
                _line(page, a, b)
        for x in (100, 140, 180, 220):
            a, b = (x, 100.0), (x, 110.0)
            if transform == "translate":
                a, b = (a[0] + 30, a[1] + 40), (b[0] + 30, b[1] + 40)
            else:
                a, b = (a[1], a[0]), (b[1], b[0])
            _line(page, a, b)

    _s, _r, base = _diagnose(adjacent_pdf)
    _s, _r, other = _diagnose(_write(tmp_path / f"{transform}.pdf", moved))
    assert other.candidate_structure == base.candidate_structure


def test_unavailable_structure_is_declared_not_inferred(monkeypatch, adjacent_pdf):
    from pb_physical_opening_authority import PhysicalOpeningCandidateStructureResult

    def abstain(self, selector):
        return PhysicalOpeningCandidateStructureResult(
            status=EvidenceResolutionStatus.ABSTAINED,
            page_id=None,
            candidates=(),
            reason_codes=("forced_unavailable",),
        )

    monkeypatch.setattr(PhysicalOpeningAuthority, "visible_candidate_structures", abstain)
    _s, _r, diag = _diagnose(adjacent_pdf)
    summary = diag.candidate_structure
    assert summary.pages_enumerated == 0 and summary.pages_unavailable == 1
    assert summary.candidates_total == 0 and summary.ambiguous_observations_assessed == 0
    assert {c.candidate_family_count for c in diag.conflicts} == {None}
    for item in (
        "candidate_structure_unavailable_for_some_pages",
        "candidate_structural_pattern_for_ambiguous_candidates",
        "candidate_member_observation_ids_for_unproven_candidates",
    ):
        assert item in diag.unavailable


def test_an_accessor_that_disagrees_with_the_disposition_is_reported(monkeypatch, adjacent_pdf):
    original = PhysicalOpeningAuthority.visible_candidate_structures

    def dropped(self, selector):
        result = original(self, selector)
        return dataclasses.replace(result, candidates=result.candidates[1:])

    monkeypatch.setattr(PhysicalOpeningAuthority, "visible_candidate_structures", dropped)
    _s, _r, diag = _diagnose(adjacent_pdf)
    summary = diag.candidate_structure
    assert summary.disposition_candidate_id_mismatches > 0
    # A disagreeing observation gets no family count; nothing is guessed.
    assert None in {c.candidate_family_count for c in diag.conflicts}


def test_candidate_structure_aggregation_sums_and_is_order_invariant(
    adjacent_pdf, tmp_path
):
    stroke = _write(tmp_path / "stroke.pdf", _overlapping_stroke)
    _s, _r, first = _diagnose(adjacent_pdf)
    _s, _r, second = _diagnose(stroke)
    forward = aggregate_semantic_conflict_diagnostics([first, second])
    backward = aggregate_semantic_conflict_diagnostics([second, first])
    assert forward == backward
    block = forward["candidate_structure"]
    assert block["candidates_total"] == 4
    assert block["variant_families_total"] == 3
    assert block["ambiguous_observations_assessed"] == 7
    assert block["ambiguous_observation_family_span"] == {"1": 5, "2": 2}
    assert block["variant_family_sizes"] == {"1": 2, "2": 1}
    assert block["disposition_candidate_id_mismatches"] == 0
    assert aggregate_semantic_conflict_diagnostics([])["candidate_structure"]["candidates_total"] == 0


def test_script_report_carries_the_candidate_structure(tmp_path, adjacent_pdf):
    report = report_script.build_report([adjacent_pdf], detail="full")
    (entry,) = report["entries"]
    assert entry["diagnostic"]["candidate_structure"]["candidates_total"] == 2
    assert report["summary"]["candidate_structure"]["candidates_total"] == 2


# ---------------------------------------- member-set analysis on fabricated candidates
def _fabricated(pattern, *members):
    from pb_physical_opening_authority import CandidateSemanticOpening

    return CandidateSemanticOpening(
        candidate_id=f"cand_{pattern}_{'_'.join(members)}",
        source_observation_ids=tuple(sorted(members)),
        source_lineage_root_ids=(),
        document_id="d",
        revision_id="r",
        source_sha256="s",
        snapshot_id="n",
        page_id="1",
        viewport_id=None,
        structural_pattern=pattern,
        status=EvidenceResolutionStatus.CANDIDATE,
        reason_codes=(),
    )


def _analyse(*candidates):
    from pb_semantic_conflict_diagnostic import _analyse_page_candidates, _new_structure_tally

    tally = _new_structure_tally()
    page = _analyse_page_candidates(candidates, tally)
    return page, tally


def test_variant_families_join_transitively_but_only_through_single_substitutions():
    a = _fabricated("p", "o1", "o2", "o3", "o4")
    b = _fabricated("p", "o1", "o2", "o3", "o5")  # differs from a by one member
    c = _fabricated("p", "o1", "o2", "o6", "o5")  # differs from b by one, from a by two
    d = _fabricated("p", "o1", "o7", "o8", "o9")  # shares one member only
    page, tally = _analyse(a, b, c, d)
    roots = dict(zip(page.candidate_ids, page.family_of))
    assert roots[a.candidate_id] == roots[b.candidate_id] == roots[c.candidate_id]
    assert roots[d.candidate_id] != roots[a.candidate_id]
    assert tally["variant_families_total"] == 2
    assert dict(tally["variant_family_sizes"]) == {3: 1, 1: 1}


def test_different_sized_candidates_are_never_variants_of_each_other():
    small = _fabricated("p", "o1", "o2", "o3")
    large = _fabricated("p", "o1", "o2", "o3", "o4")
    page, tally = _analyse(small, large)
    assert tally["variant_families_total"] == 2
    assert tally["candidates_with_strict_superset"] == 1  # `small` is contained in `large`
    assert tally["candidates_with_identical_member_set"] == 0


def test_identical_member_sets_under_different_patterns_are_counted_and_share_a_family():
    first = _fabricated("p1", "o1", "o2", "o3")
    second = _fabricated("p2", "o1", "o2", "o3")
    page, tally = _analyse(first, second)
    assert tally["candidates_with_identical_member_set"] == 2
    assert tally["candidates_with_strict_superset"] == 0
    assert tally["variant_families_total"] == 1


def test_disjoint_and_singly_shared_candidates_stay_separate_families():
    page, tally = _analyse(
        _fabricated("p", "o1", "o2", "o3"),
        _fabricated("p", "o3", "o4", "o5"),
        _fabricated("p", "o6", "o7", "o8"),
    )
    assert tally["variant_families_total"] == 3
    assert dict(tally["candidates_per_observation"]) == {1: 7, 2: 1}
    assert tally["observations_in_multiple_candidates"] == 1


def test_member_set_analysis_ignores_input_order():
    cands = [
        _fabricated("p", "o1", "o2", "o3", "o4"),
        _fabricated("p", "o1", "o2", "o3", "o5"),
        _fabricated("p", "o9", "o8", "o7", "o6"),
    ]
    _p, forward = _analyse(*cands)
    _p, backward = _analyse(*reversed(cands))
    assert {k: v for k, v in forward.items()} == {k: v for k, v in backward.items()}


def test_a_structure_read_for_a_different_page_is_not_used(monkeypatch, adjacent_pdf):
    original = PhysicalOpeningAuthority.visible_candidate_structures

    def other_page(self, selector):
        return dataclasses.replace(original(self, selector), page_id="99")

    monkeypatch.setattr(PhysicalOpeningAuthority, "visible_candidate_structures", other_page)
    _s, _r, diag = _diagnose(adjacent_pdf)
    summary = diag.candidate_structure
    assert summary.pages_enumerated == 0 and summary.pages_unavailable == 1
    assert summary.candidates_total == 0
    assert {c.candidate_family_count for c in diag.conflicts} == {None}
