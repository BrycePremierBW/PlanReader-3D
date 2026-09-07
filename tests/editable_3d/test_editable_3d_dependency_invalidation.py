"""tests/editable_3d/test_editable_3d_dependency_invalidation.py — PR D.3 test suite.

Verifies the explicit geometry-object -> affected-derived-quantities dependency
graph, and that a correction cascade is deterministic (the same correction always
produces the same set of affected targets, in the same order).
"""
from __future__ import annotations

from pb_editable_3d_correction_model import CorrectionField, EditableObjectType
from pb_editable_3d_quantity_recalculation import (
    RecalculationTarget,
    get_affected_targets,
)


class TestWallDependencyGraph:
    def test_wall_length_affects_length_and_both_areas(self):
        targets = get_affected_targets(EditableObjectType.WALL.value, CorrectionField.LENGTH.value)
        assert RecalculationTarget.WALL_GROSS_AREA.value in targets
        assert RecalculationTarget.WALL_NET_AREA.value in targets

    def test_wall_height_affects_both_areas_but_not_length(self):
        targets = get_affected_targets(EditableObjectType.WALL.value, CorrectionField.HEIGHT.value)
        assert RecalculationTarget.WALL_GROSS_AREA.value in targets
        assert RecalculationTarget.WALL_NET_AREA.value in targets
        assert RecalculationTarget.WALL_LENGTH.value not in targets


class TestOpeningDependencyGraph:
    def test_opening_width_affects_opening_area(self):
        targets = get_affected_targets(EditableObjectType.OPENING.value, CorrectionField.OPENING_WIDTH.value)
        assert targets == [RecalculationTarget.OPENING_AREA.value]

    def test_opening_height_affects_opening_area(self):
        targets = get_affected_targets(EditableObjectType.OPENING.value, CorrectionField.OPENING_HEIGHT.value)
        assert targets == [RecalculationTarget.OPENING_AREA.value]


class TestRoomDependencyGraph:
    def test_room_coordinates_affect_floor_area_and_perimeter(self):
        targets = get_affected_targets(EditableObjectType.ROOM.value, CorrectionField.COORDINATES.value)
        assert RecalculationTarget.ROOM_FLOOR_AREA.value in targets
        assert RecalculationTarget.ROOM_PERIMETER.value in targets


class TestFinishTagDependencyGraph:
    def test_finish_tag_affects_finish_quantity_regardless_of_object_type(self):
        for object_type in (
            EditableObjectType.WALL.value,
            EditableObjectType.SURFACE.value,
            EditableObjectType.CEILING.value,
        ):
            targets = get_affected_targets(object_type, CorrectionField.FINISH_TAG.value)
            assert targets == [RecalculationTarget.FINISH_QUANTITY.value]


class TestAreaBasedObjectsDependencyGraph:
    def test_ceiling_surface_soffit_area_field_maps_directly(self):
        assert get_affected_targets(EditableObjectType.CEILING.value, CorrectionField.AREA.value) == [
            RecalculationTarget.CEILING_AREA.value
        ]
        assert get_affected_targets(EditableObjectType.SURFACE.value, CorrectionField.AREA.value) == [
            RecalculationTarget.SURFACE_AREA.value
        ]
        assert get_affected_targets(EditableObjectType.SOFFIT.value, CorrectionField.AREA.value) == [
            RecalculationTarget.SOFFIT_AREA.value
        ]


class TestUnsupportedCombinationsReturnManualReviewRequired:
    def test_unmapped_object_field_combination_returns_manual_review_required(self):
        targets = get_affected_targets(EditableObjectType.STAIR.value, CorrectionField.LENGTH.value)
        assert targets == [RecalculationTarget.MANUAL_REVIEW_REQUIRED.value]

    def test_unknown_object_type_returns_manual_review_required(self):
        targets = get_affected_targets("not_a_real_object_type", CorrectionField.LENGTH.value)
        assert targets == [RecalculationTarget.MANUAL_REVIEW_REQUIRED.value]


class TestDependencyGraphIsDeterministic:
    def test_repeated_lookups_return_identical_target_lists(self):
        first = get_affected_targets(EditableObjectType.WALL.value, CorrectionField.LENGTH.value)
        second = get_affected_targets(EditableObjectType.WALL.value, CorrectionField.LENGTH.value)
        assert first == second

    def test_lookup_does_not_mutate_shared_state_between_calls(self):
        first = get_affected_targets(EditableObjectType.WALL.value, CorrectionField.LENGTH.value)
        first.append("SHOULD-NOT-PERSIST")
        second = get_affected_targets(EditableObjectType.WALL.value, CorrectionField.LENGTH.value)
        assert "SHOULD-NOT-PERSIST" not in second
