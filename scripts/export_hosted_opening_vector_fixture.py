"""export_hosted_opening_vector_fixture.py -- deterministic real-PDF vector
fixture exporter for the pb_hosted_opening_geometry test suite.

Why this exists: benchmarks/sources/ is gitignored repo-wide (see
.gitignore) and no source PDF has ever been committed under any existing
policy (`git log --all -- benchmarks/sources/` is empty for every branch).
The Baghau and Dungicha real-fixture PDFs cannot be committed either, so a
clean clone or CI has no way to run the real-fixture tests -- they must
skip. This script closes that gap: it extracts native-vector content
PyMuPDF returns for the exact page and a generously-margined capture
region around the exact viewports pb_hosted_opening_geometry's tests
already exercise, and serialises it (stroked line and curve primitives,
fills, and every attribute the detector reads -- color, width, fill,
rect) into a committed JSON snapshot. Nothing is hand-selected: a drawing
is kept only when at least one of its own 'l'/'c' items genuinely
intersects the capture rectangle -- checked via that item's own bounding
box against the rectangle, which (unlike a plain endpoint-in-region test)
does not miss a long line or curve whose control points sit outside the
region while the primitive itself crosses through it. Once a drawing is
selected this way, ALL of its 'l'/'c' items are kept, not just the one(s)
that triggered selection, so incidental/noise geometry on the same path
(dimension lines, text-leader lines, grid references) is preserved too.

Normalisation, stated precisely (earlier revisions of this docstring
overstated this as "byte-for-byte" / "exactly as PyMuPDF reports them",
which was not accurate): every coordinate, and every color/fill/width
value, is rounded to 4 decimal places before being written out. This is a
deliberate, documented normalisation for deterministic, readable JSON --
not a claim that the file's bytes match PyMuPDF's own internal
float64 representation.

Determinism: running this script twice against the same source PDF
produces byte-identical output (no timestamps, no UUIDs, keys sorted,
drawings kept in PyMuPDF's own stable per-page order). The printed
SHA-256 of each snapshot file, and of the source PDF it was read from,
lets a reviewer confirm a committed snapshot really was produced from the
stated real page without re-running this script.

Usage (from the repository root, with the real PDFs present locally in
benchmarks/sources/):

    python scripts/export_hosted_opening_vector_fixture.py

Each snapshot's own "source" block records the exact source filename,
its SHA-256 and byte size, the 0- and 1-based page index, the capture
region, and this script's own schema version -- everything a later
session needs to verify or regenerate it without guessing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "benchmarks" / "sources"
OUTPUT_DIR = REPO_ROOT / "tests" / "fixtures" / "hosted_opening_geometry"


def _sha256_and_size(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _point(p) -> List[float]:
    return [round(float(p.x), 4), round(float(p.y), 4)]


def _rects_overlap(a, b) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or ax0 > bx1 or ay1 < by0 or ay0 > by1)


def _item_bbox(item) -> Optional[tuple[float, float, float, float]]:
    """Bounding box of a supported 'l' (2-point line) or 'c' (4-point
    cubic curve) item's own control points. A cubic Bezier curve always
    lies within the convex hull of its control points, so this bbox is a
    safe (never-missing, occasionally slightly generous) proxy for "does
    this primitive intersect the region" -- unlike a plain
    point-in-region test on the endpoints alone, it correctly catches a
    long line or curve whose control points sit outside the capture
    region while the primitive itself passes through it."""
    xs: List[float] = []
    ys: List[float] = []
    for p in item[1:]:
        try:
            xs.append(float(p.x))
            ys.append(float(p.y))
        except Exception:
            continue
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _item_intersects_region(item, region) -> bool:
    bbox = _item_bbox(item)
    return bbox is not None and _rects_overlap(bbox, region)


def _serialise_drawing(d: Dict[str, Any], region) -> Optional[Dict[str, Any]]:
    """Select this drawing if ANY of its supported 'l'/'c' items genuinely
    intersects the capture region (by bounding-box test, see
    _item_intersects_region), then serialise ALL of its supported 'l'/'c'
    items -- not just the one(s) that triggered selection -- preserving
    whatever else is on the same drawing path within the region."""
    items = d.get("items") or []
    supported_items = [item for item in items if item and item[0] in ("l", "c")]
    if not any(_item_intersects_region(item, region) for item in supported_items):
        return None
    out_items = [[item[0]] + [_point(p) for p in item[1:]] for item in supported_items]
    if not out_items:
        return None
    color = d.get("color")
    fill = d.get("fill")
    rect = d.get("rect")
    return {
        "color": [round(float(c), 4) for c in color] if color else None,
        "fill": [round(float(c), 4) for c in fill] if fill else None,
        "width": round(float(d["width"]), 4) if d.get("width") is not None else None,
        "rect": (
            [round(rect.x0, 4), round(rect.y0, 4), round(rect.x1, 4), round(rect.y1, 4)]
            if rect is not None
            else None
        ),
        "items": out_items,
    }


def export_page_snapshot(
    *,
    pdf_path: Path,
    page_index_0based: int,
    capture_region: tuple[float, float, float, float],
    tested_viewports: List[tuple[float, float, float, float]],
    scale_pt_per_m: float,
    drawing_title: str,
) -> Dict[str, Any]:
    sha256, byte_size = _sha256_and_size(pdf_path)
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index_0based]
        page_rect = page.rect
        # Kept in PyMuPDF's own stable per-page get_drawings() order --
        # this, not any subsequent sort, is what makes the output
        # deterministic across runs.
        drawings_out = []
        for d in page.get_drawings() or []:
            serialised = _serialise_drawing(d, capture_region)
            if serialised is not None:
                drawings_out.append(serialised)
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "pdf": pdf_path.name,
                "pdf_sha256": sha256,
                "pdf_byte_size": byte_size,
                "pdf_page_0based": page_index_0based,
                "pdf_page_1based": page_index_0based + 1,
                "drawing_title": drawing_title,
                "scale_pt_per_m": scale_pt_per_m,
                "capture_region_pdf_pt": list(capture_region),
                "tested_viewports_pdf_pt": [list(v) for v in tested_viewports],
                "extraction": (
                    "PyMuPDF page.get_drawings(): a drawing is kept when at least one "
                    "of its own supported 'l'/'c' items has a bounding box overlapping "
                    "capture_region_pdf_pt (this bbox test, not a plain endpoint-in-"
                    "region check, is what catches a long line/curve crossing the "
                    "region with both endpoints outside it). Once kept, ALL of that "
                    "drawing's supported 'l'/'c' items are included, not just the "
                    "one(s) that triggered selection. color/fill/width/rect and every "
                    "coordinate are rounded to 4 decimal places -- a documented "
                    "normalisation for deterministic, readable JSON, not raw "
                    "byte-for-byte PyMuPDF float64 data"
                ),
                "generator": "scripts/export_hosted_opening_vector_fixture.py",
            },
            "page_rect": [
                round(page_rect.x0, 4), round(page_rect.y0, 4),
                round(page_rect.x1, 4), round(page_rect.y1, 4),
            ],
            "drawings": drawings_out,
        }
        return snapshot
    finally:
        doc.close()


def _serialise(snapshot: Dict[str, Any]) -> str:
    return json.dumps(snapshot, sort_keys=True, indent=2) + "\n"


_SPECS = [
    dict(
        name="baghau_p36",
        pdf_path=SOURCES_DIR / "bq_and_drawing_1747803602496.pdf",
        page_index_0based=35,
        capture_region=(350.0, 350.0, 950.0, 850.0),
        tested_viewports=[(440.0, 440.0, 880.0, 500.0), (440.0, 440.0, 880.0, 760.0)],
        scale_pt_per_m=28.3,
        drawing_title="Baghau Primary School proposed single classroom -- FLOOR PLAN",
    ),
    dict(
        name="dungicha_p134",
        pdf_path=SOURCES_DIR / "dungicha_3classrooms.pdf",
        page_index_0based=133,
        capture_region=(0.0, 550.0, 900.0, 950.0),
        tested_viewports=[(60.0, 600.0, 800.0, 780.0), (90.0, 790.0, 145.0, 870.0)],
        scale_pt_per_m=28.35,
        drawing_title="Proposed 3No. Classroom Block -- GROUND FLOOR (17)",
    ),
]


def write_snapshots(output_dir: Optional[Path] = None, print_hashes: bool = True) -> Dict[str, str]:
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    digests: Dict[str, str] = {}
    for spec in _SPECS:
        pdf_path = spec["pdf_path"]
        if not pdf_path.exists():
            print(f"SKIP {spec['name']}: source PDF not present at {pdf_path}")
            continue
        snapshot = export_page_snapshot(
            pdf_path=pdf_path,
            page_index_0based=spec["page_index_0based"],
            capture_region=spec["capture_region"],
            tested_viewports=spec["tested_viewports"],
            scale_pt_per_m=spec["scale_pt_per_m"],
            drawing_title=spec["drawing_title"],
        )
        payload = _serialise(snapshot)
        target = output_dir / f"{spec['name']}.json"
        target.write_bytes(payload.encode("utf-8"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        digests[spec["name"]] = digest
        if print_hashes:
            print(
                f"{spec['name']}.json  sha256={digest}  bytes={len(payload)}  "
                f"drawings={len(snapshot['drawings'])}  "
                f"source_pdf_sha256={snapshot['source']['pdf_sha256']}"
            )
    return digests


def main() -> None:
    digests = write_snapshots(OUTPUT_DIR)
    print(f"Wrote {len(digests)} snapshot(s) to {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
