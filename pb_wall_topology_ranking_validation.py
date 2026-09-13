"""Read-only validation of #273 wall-evidence ranking. Does not change thresholds."""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pb_migration_contracts import EvidenceResolutionStatus
from pb_vector_geometry_v130 import extract_native_page
from pb_wall_room_topology_contracts import WallCandidate
from pb_wall_room_topology_wall_evidence_ranking import (
    REASON_AMBIGUOUS_THICKNESS,
    REASON_CONNECTED,
    REASON_FILL_SUPPORTED,
    REASON_MULTIPLE_SIGNALS_NO_SCALE,
    REASON_MULTIPLE_SIGNALS_SCALED,
    REASON_NO_EVIDENCE,
    REASON_PAIRED_FACE,
    REASON_ROOM_BOUNDARY,
    rank_wall_candidates,
)

BUCKET_W4_UNRANKED = "w4_unranked"
BUCKET_ABSTAINED = "abstained"
BUCKET_CANDIDATE_SINGLE = "candidate_single"
BUCKET_CANDIDATE_MULTI = "candidate_multi"
BUCKET_AMBIGUOUS = "ambiguous"
BUCKET_CORROBORATED = "corroborated"

BUCKETS = (
    BUCKET_W4_UNRANKED,
    BUCKET_ABSTAINED,
    BUCKET_CANDIDATE_SINGLE,
    BUCKET_CANDIDATE_MULTI,
    BUCKET_AMBIGUOUS,
    BUCKET_CORROBORATED,
)

SIGNAL_NAMES = (
    REASON_PAIRED_FACE,
    REASON_FILL_SUPPORTED,
    REASON_ROOM_BOUNDARY,
    REASON_CONNECTED,
)


def wall_like_fills_from_rects(
    rects: Sequence[Mapping[str, Any]],
) -> List[Tuple[float, float, float, float]]:
    """Same near-black / thin-and-long fill heuristic as #273's audit script.

    Copied rather than re-tuned so this validation uses the ranking contract
    as published, not a new thickness or aspect-ratio band.
    """
    out: List[Tuple[float, float, float, float]] = []
    for rect in rects:
        fill = rect.get("fill")
        if not fill or len(fill) < 3:
            continue
        if max(fill[:3]) > 0.2:
            continue
        x0, y0, x1, y1 = rect["bbox"]
        width, height = x1 - x0, y1 - y0
        long_side, short_side = max(width, height), max(min(width, height), 1e-6)
        if long_side < 4.0 or long_side / short_side < 3.0:
            continue
        out.append((float(x0), float(y0), float(x1), float(y1)))
    return out


def scoped_wall_like_fills(page: Any, bbox: Sequence[float]) -> List[Tuple[float, float, float, float]]:
    native = extract_native_page(page)
    x0, y0, x1, y1 = [float(value) for value in bbox]
    rects = []
    for rect in native.get("rects") or []:
        box = rect.get("bbox")
        if not box or len(box) != 4:
            continue
        rx0, ry0, rx1, ry1 = box
        if rx1 < x0 or rx0 > x1 or ry1 < y0 or ry0 > y1:
            continue
        rects.append(rect)
    return wall_like_fills_from_rects(rects)


def ranking_bucket(wall: WallCandidate) -> str:
    reasons = tuple(wall.reason_codes or ())
    if REASON_NO_EVIDENCE in reasons:
        return BUCKET_ABSTAINED
    if REASON_AMBIGUOUS_THICKNESS in reasons:
        return BUCKET_AMBIGUOUS
    if wall.status == EvidenceResolutionStatus.CORROBORATED or REASON_MULTIPLE_SIGNALS_SCALED in reasons:
        return BUCKET_CORROBORATED
    if REASON_MULTIPLE_SIGNALS_NO_SCALE in reasons:
        return BUCKET_CANDIDATE_MULTI
    if wall.supporting_evidence_ids:
        return BUCKET_CANDIDATE_SINGLE
    return BUCKET_W4_UNRANKED


def ranking_signals(wall: WallCandidate) -> List[str]:
    found: List[str] = []
    for signal in SIGNAL_NAMES:
        if any(item == signal or str(item).startswith(signal + ":") for item in wall.supporting_evidence_ids):
            found.append(signal)
    return found


def apply_ranking_to_snapshot(
    snapshot: Any,
    *,
    wall_like_fills: Sequence[Tuple[float, float, float, float]] = (),
    scale_pt_per_m: Optional[float] = None,
) -> Any:
    """Reissue snapshot walls through #273 ranking. Never drops a candidate."""
    ranked = rank_wall_candidates(
        list(snapshot.walls),
        rooms=snapshot.rooms,
        wall_like_fills=wall_like_fills,
        scale_pt_per_m=scale_pt_per_m,
    )
    if len(ranked) != len(snapshot.walls):
        raise RuntimeError("ranking dropped or invented WallCandidates")
    before_ids = [wall.candidate_id for wall in snapshot.walls]
    after_ids = [wall.candidate_id for wall in ranked]
    if before_ids != after_ids:
        raise RuntimeError("ranking reordered or replaced WallCandidate identities")
    return replace(snapshot, walls=tuple(ranked))


def summarize_ranking(walls: Sequence[WallCandidate]) -> Dict[str, Any]:
    buckets = Counter(ranking_bucket(wall) for wall in walls)
    signals = Counter()
    signal_sets = Counter()
    for wall in walls:
        found = ranking_signals(wall)
        for signal in found:
            signals[signal] += 1
        if found:
            signal_sets["+".join(found)] += 1
        elif ranking_bucket(wall) == BUCKET_ABSTAINED:
            signal_sets["(none)"] += 1
    lengths: Dict[str, List[float]] = {bucket: [] for bucket in BUCKETS}
    isolated_proxy: Dict[str, int] = {bucket: 0 for bucket in BUCKETS}
    for wall in walls:
        bucket = ranking_bucket(wall)
        pts = wall.centerline_pts
        if len(pts) >= 2:
            length = sum(
                math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                for i in range(len(pts) - 1)
            )
            lengths[bucket].append(length)
        if wall.junction_types[0].value == "unresolved" and wall.junction_types[1].value == "unresolved":
            isolated_proxy[bucket] += 1
    return {
        "wall_count": len(walls),
        "buckets": {bucket: int(buckets.get(bucket, 0)) for bucket in BUCKETS},
        "signals": {name: int(signals.get(name, 0)) for name in SIGNAL_NAMES},
        "signal_sets": dict(sorted(signal_sets.items())),
        "length_median_pt": {
            bucket: _median(values) for bucket, values in lengths.items() if values
        },
        "length_p90_pt": {
            bucket: _percentile(values, 90.0) for bucket, values in lengths.items() if values
        },
    }


def stratified_samples(
    walls: Sequence[WallCandidate],
    *,
    per_bucket: int = 12,
    seed: str = "ranking-validation-v1",
) -> Dict[str, List[Dict[str, Any]]]:
    """Deterministic samples. Order is content-hashed, not drawing-specific."""
    grouped: Dict[str, List[WallCandidate]] = {bucket: [] for bucket in BUCKETS}
    for wall in walls:
        grouped[ranking_bucket(wall)].append(wall)
    samples: Dict[str, List[Dict[str, Any]]] = {}
    for bucket, members in grouped.items():
        ordered = sorted(members, key=lambda wall: _sample_key(wall, seed))
        samples[bucket] = [_sample_row(wall, bucket) for wall in ordered[:per_bucket]]
    return samples


def _sample_key(wall: WallCandidate, seed: str) -> str:
    payload = f"{seed}|{wall.candidate_id}|{wall.centerline_pts[0]}|{wall.centerline_pts[-1]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sample_row(wall: WallCandidate, bucket: str) -> Dict[str, Any]:
    pts = wall.centerline_pts
    length = 0.0
    if len(pts) >= 2:
        length = sum(
            math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(len(pts) - 1)
        )
    xs = [float(point[0]) for point in pts]
    ys = [float(point[1]) for point in pts]
    return {
        "bucket": bucket,
        "candidate_id": wall.candidate_id,
        "status": wall.status.value,
        "signals": ranking_signals(wall),
        "reason_codes": [code for code in wall.reason_codes if code.startswith((
            REASON_NO_EVIDENCE,
            REASON_AMBIGUOUS_THICKNESS,
            REASON_MULTIPLE_SIGNALS_NO_SCALE,
            REASON_MULTIPLE_SIGNALS_SCALED,
            REASON_PAIRED_FACE,
            REASON_FILL_SUPPORTED,
            REASON_ROOM_BOUNDARY,
            REASON_CONNECTED,
        )) or code in (
            REASON_NO_EVIDENCE,
            REASON_AMBIGUOUS_THICKNESS,
            REASON_MULTIPLE_SIGNALS_NO_SCALE,
            REASON_MULTIPLE_SIGNALS_SCALED,
        )],
        "supporting_evidence_ids": list(wall.supporting_evidence_ids),
        "length_pt": round(length, 3),
        "start": [round(pts[0][0], 3), round(pts[0][1], 3)] if pts else None,
        "end": [round(pts[-1][0], 3), round(pts[-1][1], 3)] if pts else None,
        "bbox": [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)] if pts else None,
        "thickness_m": wall.thickness_m,
        "junction_types": [item.value for item in wall.junction_types],
        "confidence": wall.confidence,
    }


def ranking_svg(walls: Sequence[WallCandidate]) -> Optional[str]:
    rows = [wall for wall in walls if len(wall.centerline_pts) >= 2]
    if not rows:
        return None
    xs: List[float] = []
    ys: List[float] = []
    for wall in rows:
        xs.extend(float(point[0]) for point in wall.centerline_pts)
        ys.extend(float(point[1]) for point in wall.centerline_pts)
    pad = 12.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    colors = {
        BUCKET_W4_UNRANKED: "#666666",
        BUCKET_ABSTAINED: "#bbbbbb",
        BUCKET_CANDIDATE_SINGLE: "#d4880f",
        BUCKET_CANDIDATE_MULTI: "#2b6cb0",
        BUCKET_AMBIGUOUS: "#c0392b",
        BUCKET_CORROBORATED: "#1e8449",
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {min_y} {width} {height}" '
        f'width="{width}" height="{height}">',
        "<desc>Read-only #273 ranking overlay. Not takeoff authority.</desc>",
    ]
    for wall in rows:
        bucket = ranking_bucket(wall)
        color = colors[bucket]
        x1, y1 = wall.centerline_pts[0]
        x2, y2 = wall.centerline_pts[-1]
        width_px = 2.4 if bucket in (BUCKET_CORROBORATED, BUCKET_CANDIDATE_MULTI) else 1.1
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="{width_px}" data-bucket="{bucket}" '
            f'data-candidate="{wall.candidate_id}"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 3)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 3)


def _percentile(values: Sequence[float], percent: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * (percent / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return round(ordered[low], 3)
    weight = rank - low
    return round(ordered[low] + (ordered[high] - ordered[low]) * weight, 3)
