"""Observe original raster component rejections without changing primitives."""
from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import cv2

import pb_raster_visible_segment_detector as detector
from pb_live_physical_net_wall_integration import (
    LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION,
)
from pb_physical_wall_candidate_authority import MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS
from pb_source_visibility_authority import RASTER_RENDER_DPI, SourceVisibilityProducer


def nonpublishing_component_receipts(stats, *, orientation: str, min_line_px: int) -> list[dict]:
    """Read component stats, not source ownership or manufactured centerlines."""
    if orientation not in ("horizontal", "vertical"):
        raise ValueError("invalid original component orientation")
    if type(min_line_px) is not int or min_line_px <= 0:
        raise ValueError("invalid original component minimum")
    if not isinstance(stats, (list, tuple)) or len(stats) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
        raise ValueError("invalid or over-limit original component inventory")
    rows = []
    addresses = set()
    for stat in stats:
        if (not isinstance(stat, (list, tuple)) or len(stat) != 5
                or any(type(v) is not int for v in stat)):
            raise ValueError("invalid original component stats")
        x, y, width, height, area = stat
        if min(x, y) < 0 or min(width, height) <= 0 or area < 0 or area > width * height:
            raise ValueError("invalid original component extent or area")
        bbox = (x, y, x + width - 1, y + height - 1)
        if bbox in addresses:
            raise ValueError("duplicate original component address")
        addresses.add(bbox)
        along, cross = (width, height) if orientation == "horizontal" else (height, width)
        reasons = []
        if area <= 0:
            reasons.append("nonpositive_component_area")
        if along < min_line_px:
            reasons.append("component_along_length_below_existing_minimum")
        if along < max(3, 3 * cross):
            reasons.append("component_aspect_below_existing_minimum")
        rows.append({"orientation": orientation, "pixel_bbox": list(bbox),
                     "width_px": width, "height_px": height, "foreground_area_px": area,
                     "minimum_line_px": min_line_px, "existing_rejection_reasons": reasons,
                     "component_passes_existing_pre_snap_filter": not reasons,
                     "source_ownership_proven": False, "host_publication_allowed": False})
    return sorted(rows, key=lambda r: (r["orientation"], r["pixel_bbox"]))


def observe_original_detector_components(png_bytes: bytes):
    """Return unchanged detector segments plus nonpublishing mask receipts."""
    original = detector._component_segments
    receipts = []

    def observe(mask, *, orientation, min_line_px):
        _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        receipts.extend(nonpublishing_component_receipts(
            [[int(v) for v in stat] for stat in stats[1:]],
            orientation=orientation, min_line_px=min_line_px))
        if len(receipts) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
            raise ValueError("over-limit original component observational inventory")
        return original(mask, orientation=orientation, min_line_px=min_line_px)

    with patch.object(detector, "_component_segments", observe):
        observed = detector.detect_axis_aligned_raster_segments(png_bytes, dpi=RASTER_RENDER_DPI)
    baseline = detector.detect_axis_aligned_raster_segments(png_bytes, dpi=RASTER_RENDER_DPI)
    if baseline != observed:
        raise ValueError("original detector component observation changed output")
    return observed, sorted(receipts, key=lambda r: (r["orientation"], r["pixel_bbox"]))


def original_source_component_census(source_bytes: bytes, *, page_id: str, expected_source_sha: str) -> dict:
    digest = sha256(source_bytes).hexdigest()
    if digest != expected_source_sha:
        raise ValueError("original component source PDF SHA mismatch")
    if not isinstance(page_id, str) or not page_id.isdigit() or int(page_id) < 1:
        raise ValueError("invalid original component source page")
    producer = SourceVisibilityProducer(producer_method="live-physical-net-wall",
                                       producer_version=LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION)
    published = producer.ingest_native_pdf_bytes(
        document_id=f"live-source:{digest[:32]}", source_bytes=source_bytes,
        source_locator="memory://live-physical-net-wall-source.pdf", page_ids=(page_id,))
    png, parent = producer._producer.render_native_page_png(
        document_id=published.revision.document_id, revision_id=published.revision.revision_id,
        source_sha256=digest, snapshot_id=published.snapshot.snapshot_id,
        page_id=page_id, dpi=float(RASTER_RENDER_DPI))
    segments, receipts = observe_original_detector_components(png)
    return {"source_sha256": digest, "document_id": published.revision.document_id,
            "revision_id": published.revision.revision_id, "snapshot_id": published.snapshot.snapshot_id,
            "page_id": page_id, "viewport_id": None, "render_sha256": sha256(png).hexdigest(),
            "render_dpi": RASTER_RENDER_DPI, "native_page_parent_observation_id": parent.observation_id,
            "detector_version": detector.RASTER_VISIBLE_SEGMENT_DETECTOR_VERSION,
            "observed_original_segment_count": len(segments), "original_detector_output_unchanged": True,
            "observed_component_receipts": receipts, "primitive_safety_cap": MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
            "original_source_render_reauthenticated": True, "source_universe_completeness_proven": False,
            "source_ownership_proven": False, "physical_equivalence_proven": False,
            "host_publication_allowed": False, "opening_count_publication_allowed": False,
            "metric_quantity_publication_allowed": False, "benchmark_accuracy": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = original_source_component_census(args.pdf.read_bytes(), page_id=args.page_id,
                                              expected_source_sha=args.expected_source_sha)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("source_sha256", "render_sha256",
                     "observed_original_segment_count", "original_detector_output_unchanged")}))


if __name__ == "__main__":
    main()
