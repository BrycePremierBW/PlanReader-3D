"""B01: raster XObject grouping is evidence, not viewport authority."""
from types import SimpleNamespace
from pb_viewport_segmentation import _source_image_placement_groups


class _Page:
    def get_images(self, full=True):
        assert full is True
        return [(12,), (13,)]
    def get_image_rects(self, xref):
        if xref == 12:
            return [
                SimpleNamespace(x0=0, y0=0, x1=100, y1=100),
                SimpleNamespace(x0=100, y0=0, x1=200, y1=100),
                SimpleNamespace(x0=0, y0=0, x1=100, y1=100),
            ]
        return [SimpleNamespace(x0=500, y0=500, x1=600, y1=600)]


def test_real_raster_xref_groups_preserve_source_identity_and_do_not_seal():
    groups = _source_image_placement_groups(_Page())
    assert [g["xref"] for g in groups] == [12, 13]
    assert [g["placements"] for g in groups] == [2, 1]
    assert all(g["source_region_complete"] is False for g in groups)
    assert groups[0]["native_bboxes"] == (
        (0.0, 0.0, 100.0, 100.0),
        (100.0, 0.0, 200.0, 100.0),
    )


def test_missing_raster_source_metadata_does_not_grant_authority():
    assert _source_image_placement_groups(object()) == ()
