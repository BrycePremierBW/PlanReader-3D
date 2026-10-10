from __future__ import annotations

from types import SimpleNamespace

from pb_physical_wall_candidate_authority import (
    MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
    _annotate_producer_owned_annotation_masks,
    _filter_repeated_non_physical_drafting_primitives,
    filtered_wall_topology_source_segment_count,
)


def _line(
    raw_id: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    path_index: int,
    stroke=(0.0, 0.0, 0.0),
    width: float = 0.48,
) -> dict:
    return {
        "id": raw_id,
        "kind": "line",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "path_index": path_index,
        "stroke": stroke,
        "stroke_present": True,
        "fill": None,
        "fill_present": False,
        "width": width,
        "width_present": True,
    }


def _fill_rect_edges(path_index: int, *, annotation_mask: bool = False) -> list[dict]:
    result = []
    points = ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0))
    for idx, (first, second) in enumerate(zip(points, points[1:] + points[:1])):
        result.append(
            {
                "id": f"fill-{idx}",
                "kind": "rect_edge",
                "x1": first[0],
                "y1": first[1],
                "x2": second[0],
                "y2": second[1],
                "path_index": path_index,
                "stroke": None,
                "stroke_present": False,
                "fill": (0.4, 0.4, 0.4),
                "fill_present": True,
                "width": 0.0,
                "width_present": False,
                "annotation_mask_authority": ("producer_owned" if annotation_mask else ""),
                "annotation_mask_text_sized": annotation_mask,
                "annotation_text_overlap": annotation_mask,
                "physical_wall_authority": False if annotation_mask else None,
                "participates_in_source_physical_object": False if annotation_mask else None,
            }
        )
    return result


def _filter(segments: list[dict]) -> tuple[dict, ...]:
    return _filter_repeated_non_physical_drafting_primitives(
        segments,
        page_width=1000.0,
        page_height=1000.0,
    )


def test_unique_short_wall_return_is_preserved() -> None:
    short = _line("short", 0.0, 0.0, 1.0, 0.0, path_index=1)
    assert _filter([short]) == (short,)


def test_unique_diagonal_wall_is_preserved() -> None:
    diagonal = _line("diag", 0.0, 0.0, 20.0, 20.0, path_index=1)
    assert _filter([diagonal]) == (diagonal,)


def test_small_closed_room_under_five_square_metres_equivalent_fixture_is_preserved() -> None:
    walls = [
        _line("n", 0.0, 0.0, 12.0, 0.0, path_index=1),
        _line("e", 12.0, 0.0, 12.0, 10.0, path_index=2),
        _line("s", 12.0, 10.0, 0.0, 10.0, path_index=3),
        _line("w", 0.0, 10.0, 0.0, 0.0, path_index=4),
    ]
    assert _filter(walls) == tuple(walls)


def test_green_stroked_insulated_panel_boundaries_are_preserved() -> None:
    green = (0.0, 0.5, 0.0)
    walls = [
        _line("g1", 0.0, 0.0, 80.0, 0.0, path_index=1, stroke=green),
        _line("g2", 0.0, 8.0, 80.0, 8.0, path_index=2, stroke=green),
    ]
    assert _filter(walls) == tuple(walls)


def test_legitimate_fill_only_rectangle_survives_without_annotation_mask_proof() -> None:
    fill_edges = _fill_rect_edges(path_index=1)
    assert _filter(fill_edges) == tuple(fill_edges)


def test_producer_authenticated_annotation_mask_edges_are_excluded() -> None:
    fill_edges = _fill_rect_edges(path_index=1, annotation_mask=True)
    assert _filter(fill_edges) == ()


def test_dense_repeated_non_orthogonal_singleton_motif_is_excluded() -> None:
    motif = [
        _line(
            f"h-{idx}",
            float(idx * 3),
            0.0,
            float(idx * 3 + 3),
            3.0,
            path_index=idx,
            stroke=(0.5, 0.5, 0.5),
            width=0.24,
        )
        for idx in range(8)
    ]
    assert _filter(motif) == ()


def test_repeated_orthogonal_short_returns_below_motif_threshold_are_preserved() -> None:
    walls = [
        _line(
            f"r-{idx}",
            float(idx * 2),
            0.0,
            float(idx * 2 + 2),
            0.0,
            path_index=idx,
        )
        for idx in range(4)
    ]
    assert _filter(walls) == tuple(walls)


def test_complexity_census_uses_filtered_topology_not_raw_cad_density() -> None:
    motif = [
        _line(
            f"dense-{idx}",
            float(idx % 100),
            float(idx // 100),
            float(idx % 100) + 3.0,
            float(idx // 100) + 3.0,
            path_index=idx,
            stroke=(0.5, 0.5, 0.5),
            width=0.24,
        )
        for idx in range(MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS + 8)
    ]
    assert len(motif) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS
    assert (
        filtered_wall_topology_source_segment_count(
            motif,
            page_width=1000.0,
            page_height=1000.0,
        )
        == 0
    )


def test_complexity_census_preserves_unproven_filled_physical_geometry() -> None:
    fill_edges = _fill_rect_edges(path_index=1)
    assert (
        filtered_wall_topology_source_segment_count(
            fill_edges,
            page_width=1000.0,
            page_height=1000.0,
        )
        == len(fill_edges)
    )


def _sequenced_fill_rect_edges(
    *,
    sequence_number: int,
    x0: float = 10.0,
    y0: float = 10.0,
    x1: float = 30.0,
    y1: float = 30.0,
) -> list[dict]:
    points = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    result = []
    for edge_index, (first, second) in enumerate(
        zip(points, points[1:] + points[:1])
    ):
        result.append(
            {
                "id": f"mask-edge-{edge_index}",
                "kind": "rect_edge",
                "x1": first[0],
                "y1": first[1],
                "x2": second[0],
                "y2": second[1],
                "path_index": 77,
                "item_index": 3,
                "edge_index": edge_index,
                "sequence_number": sequence_number,
                "stroke": None,
                "stroke_present": False,
                "fill": (1.0, 1.0, 1.0),
                "fill_present": True,
                "width": 0.0,
                "width_present": False,
            }
        )
    return result


def test_immediately_painted_tight_text_backing_rectangle_is_authenticated() -> None:
    edges = _sequenced_fill_rect_edges(sequence_number=40)
    receipt = SimpleNamespace(
        sequence_number=41,
        geometry=(11.0, 11.0, 29.0, 29.0),
    )

    annotated = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(receipt,)
    )

    assert all(
        edge.get("annotation_mask_authority") == "producer_owned"
        and edge.get("annotation_mask_text_sized") is True
        and edge.get("annotation_text_overlap") is True
        and edge.get("physical_wall_authority") is False
        and edge.get("participates_in_source_physical_object") is False
        for edge in annotated
    )
    assert _filter(list(annotated)) == ()


def test_text_mask_uses_established_majority_coverage_boundary() -> None:
    edges = _sequenced_fill_rect_edges(sequence_number=40)
    at_boundary = SimpleNamespace(
        sequence_number=41,
        geometry=(15.0, 10.0, 25.0, 30.0),
    )
    below_boundary = SimpleNamespace(
        sequence_number=41,
        geometry=(15.1, 10.0, 25.0, 30.0),
    )

    accepted = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(at_boundary,)
    )
    rejected = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(below_boundary,)
    )

    assert all(
        edge.get("annotation_mask_authority") == "producer_owned"
        for edge in accepted
    )
    assert all(not edge.get("annotation_mask_authority") for edge in rejected)


def test_text_mask_uses_established_pdf_text_geometry_tolerance() -> None:
    edges = _sequenced_fill_rect_edges(sequence_number=40)
    within_tolerance = SimpleNamespace(
        sequence_number=41,
        geometry=(9.6, 9.6, 30.4, 30.4),
    )
    outside_tolerance = SimpleNamespace(
        sequence_number=41,
        geometry=(9.4, 9.4, 30.6, 30.6),
    )

    accepted = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(within_tolerance,)
    )
    rejected = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(outside_tolerance,)
    )

    assert all(
        edge.get("annotation_mask_authority") == "producer_owned"
        for edge in accepted
    )
    assert all(not edge.get("annotation_mask_authority") for edge in rejected)


def test_nonadjacent_text_does_not_authenticate_fill_rectangle() -> None:
    edges = _sequenced_fill_rect_edges(sequence_number=40)
    receipt = SimpleNamespace(
        sequence_number=42,
        geometry=(11.0, 11.0, 29.0, 29.0),
    )

    annotated = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(receipt,)
    )

    assert all(not edge.get("annotation_mask_authority") for edge in annotated)
    assert _filter(list(annotated)) == tuple(annotated)


def test_oversized_fill_rectangle_does_not_authenticate_as_text_mask() -> None:
    edges = _sequenced_fill_rect_edges(
        sequence_number=40, x0=0.0, y0=0.0, x1=100.0, y1=100.0
    )
    receipt = SimpleNamespace(
        sequence_number=41,
        geometry=(45.0, 45.0, 55.0, 55.0),
    )

    annotated = _annotate_producer_owned_annotation_masks(
        edges, text_receipts=(receipt,)
    )

    assert all(not edge.get("annotation_mask_authority") for edge in annotated)
    assert _filter(list(annotated)) == tuple(annotated)


def test_singleton_motif_geometry_is_computed_once(monkeypatch) -> None:
    import pb_physical_wall_candidate_authority as module

    lines = [
        _line(
            f"once-{index}",
            float(index),
            0.0,
            float(index) + 3.0,
            3.0,
            path_index=index,
            stroke=(0.5, 0.5, 0.5),
            width=0.24,
        )
        for index in range(12)
    ]
    original_length = module._segment_length
    original_angle = module._segment_angle_deg
    calls = {"length": 0, "angle": 0}

    def counted_length(segment):
        calls["length"] += 1
        return original_length(segment)

    def counted_angle(segment):
        calls["angle"] += 1
        return original_angle(segment)

    monkeypatch.setattr(module, "_segment_length", counted_length)
    monkeypatch.setattr(module, "_segment_angle_deg", counted_angle)

    module._filter_repeated_non_physical_drafting_primitives(
        lines,
        page_width=1000.0,
        page_height=1000.0,
    )

    assert calls == {"length": len(lines), "angle": len(lines)}


def test_repeated_motif_preserves_only_explicit_source_proven_primitives() -> None:
    motif = [
        _line(
            f"protected-{idx}",
            float(idx * 3),
            0.0,
            float(idx * 3 + 3),
            3.0,
            path_index=idx,
            stroke=(0.5, 0.5, 0.5),
            width=0.24,
        )
        for idx in range(8)
    ]

    filtered = _filter_repeated_non_physical_drafting_primitives(
        motif,
        page_width=1000.0,
        page_height=1000.0,
        preserved_source_primitive_ids=frozenset(
            {"protected-2", "protected-5"}
        ),
    )

    assert tuple(segment["id"] for segment in filtered) == (
        "protected-2",
        "protected-5",
    )


def test_unprotected_members_of_same_repeated_family_remain_filtered() -> None:
    motif = [
        _line(
            f"mixed-{idx}",
            float(idx * 3),
            0.0,
            float(idx * 3 + 3),
            3.0,
            path_index=idx,
            stroke=(0.5, 0.5, 0.5),
            width=0.24,
        )
        for idx in range(8)
    ]

    filtered = _filter_repeated_non_physical_drafting_primitives(
        motif,
        page_width=1000.0,
        page_height=1000.0,
        preserved_source_primitive_ids=frozenset({"mixed-0"}),
    )

    assert tuple(segment["id"] for segment in filtered) == ("mixed-0",)


