"""SHA-pinned source raster flank first-failure audit; never publishes hosts."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from pb_live_physical_net_wall_integration import LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION
from pb_live_wall_opening_authority_composition import compose_live_wall_opening_authority
from pb_migration_contracts import EvidenceResolutionStatus
from pb_opening_host_binding_authority import _authenticated_raster_source_lines, _opening_geometry
from pb_physical_wall_candidate_authority import (
    MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS, PhysicalWallCandidateSelector,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_visibility_authority import SourceVisibilityProducer
from tools.gptmax_raster_flank_ownership import audit_raster_flank_ownership


def _opening_row(trace, authority, wall):
    row={"opening_identity_id":trace.opening_identity_id,
         "representative_observation_id":trace.representative_observation_id,
         "original_binding_reason_codes":list(trace.reason_codes),
         "source_audit_abstained":True,"first_observed_failure":None,
         "flank_audit":None}
    if not wall.scope_complete or wall.equivalence is None:
        row["first_observed_failure"]="original_wall_scope_unavailable"
        return row
    selector=ObservationSelector(document_id=wall.document_id,revision_id=wall.revision_id,
        source_sha256=wall.source_sha256,snapshot_id=wall.snapshot_id,
        observation_id=trace.representative_observation_id)
    result=authority.prove_existence(selector)
    opening=result.existence_record
    if result.status is not EvidenceResolutionStatus.CORROBORATED or opening is None:
        row["first_observed_failure"]="original_opening_existence_unavailable"
        return row
    if opening.record_id != trace.opening_identity_id or opening.page_id != wall.page_id:
        row["first_observed_failure"]="original_opening_identity_or_page_mismatch"
        return row
    geometry=_opening_geometry(authority,opening)
    if geometry is None:
        row["first_observed_failure"]="original_opening_geometry_unavailable"
        return row
    support=[]
    visibility=authority.source_visibility_authority()
    for observation_id in opening.source_observation_ids:
        receipt=visibility.resolve_raster_opening_primitive(ObservationSelector(
            document_id=opening.document_id,revision_id=opening.revision_id,
            source_sha256=opening.source_sha256,snapshot_id=opening.snapshot_id,
            observation_id=observation_id))
        if receipt.status is not EvidenceResolutionStatus.CORROBORATED or receipt.observation is None:
            row["first_observed_failure"]="original_g17_support_unavailable"
            return row
        support.append(receipt.observation)
    lines=_authenticated_raster_source_lines(authority,opening,wall.source_observation_ids)
    try:
        audit=audit_raster_flank_ownership(wall.records,lines,support,opening,geometry)
    except ValueError as exc:
        row["first_observed_failure"]="source_flank_or_edge_receipt_invalid"
        row["source_receipt_rejection"]=str(exc)
        return row
    row.update(source_audit_abstained=False,first_observed_failure=None,flank_audit=audit)
    return row


def original_raster_flank_report(source_bytes, *, page_id, expected_source_sha):
    digest=sha256(source_bytes).hexdigest()
    if digest != expected_source_sha:
        raise ValueError("original source PDF SHA-256 mismatch")
    if not isinstance(page_id,str) or not page_id.isascii() or not page_id.isdigit() or int(page_id)<1:
        raise ValueError("invalid original source page")
    producer=SourceVisibilityProducer(producer_method="live-physical-net-wall",
        producer_version=LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION)
    source=producer.ingest_native_pdf_bytes(document_id=f"live-source:{digest[:32]}",
        source_bytes=source_bytes,source_locator="memory://live-physical-net-wall-source.pdf",
        page_ids=(page_id,))
    composition=compose_live_wall_opening_authority(source_visibility_producer=producer,
        revision_id=source.revision.revision_id,page_ids=(page_id,))
    published=producer.published_snapshot_for_revision(source.revision.revision_id)
    if published is None:
        raise ValueError("original source snapshot unavailable")
    wall=composition.physical_wall_candidate_authority.resolve_scope(PhysicalWallCandidateSelector(
        document_id=published.revision.document_id,revision_id=published.revision.revision_id,
        source_sha256=digest,snapshot_id=published.snapshot.snapshot_id,page_id=page_id,
        decision_scope_id=f"wall-source:page-{page_id}"))
    targets=[t for t in composition.opening_bindings if not t.host_wall_id and t.page_id==page_id
        and any("raster_source_band_" in code for code in t.reason_codes)]
    rows=[_opening_row(t,composition.physical_opening_authority,wall)
          for t in sorted(targets,key=lambda t:t.opening_identity_id or "")]
    return {"source_sha256":digest,"page_id":page_id,
        "selected_geometry_page_ids":[page_id],
        "primitive_safety_cap":MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
        "revision_id":published.revision.revision_id,"snapshot_id":published.snapshot.snapshot_id,
        "summary":{"physical_existence_claims":len(composition.opening_bindings),
            "host_bindings":sum(bool(t.host_wall_id) for t in composition.opening_bindings),
            "host_frames":sum(bool(f.record_id) for f in composition.host_frames)},
        "opening_bindings":[asdict(t) for t in composition.opening_bindings],
        "host_frames":[asdict(f) for f in composition.host_frames],
        "targeted_opening_count":len(targets),"opening_rows":rows,
        "audited_opening_count":sum(not r["source_audit_abstained"] for r in rows),
        "abstained_opening_count":sum(r["source_audit_abstained"] for r in rows),
        "host_publication_allowed":False,"opening_count_publication_allowed":False,
        "metric_quantity_publication_allowed":False,"benchmark_accuracy":None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf",type=Path,required=True)
    parser.add_argument("--page-id",required=True)
    parser.add_argument("--expected-source-sha",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=original_raster_flank_report(args.pdf.read_bytes(),page_id=args.page_id,
        expected_source_sha=args.expected_source_sha)
    args.output.write_text(json.dumps(report,sort_keys=True,indent=2,
        default=lambda v:v.value,allow_nan=False)+"\n")
    print(json.dumps({"source_sha256":report["source_sha256"],"summary":report["summary"],
        "targeted_openings":report["targeted_opening_count"],
        "audited_openings":report["audited_opening_count"],
        "abstained_openings":report["abstained_opening_count"]}))


if __name__=="__main__":
    main()
