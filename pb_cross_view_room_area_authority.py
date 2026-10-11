"""Source-owned cross-view room-area authority.

This authority composes only already-authenticated evidence:
- a canonical physical room with an authenticated source room label;
- the exact same independently trusted native label line on another decoded view;
- one native-text-authenticated horizontal and one vertical figured dimension,
  each WITNESS_BOUND by the existing native vector binder and independently
  mapped back to unique producer-owned visible source observations.

It never accepts caller-supplied room names, page numbers, dimensions, geometry,
expected quantities or benchmark identities. Scale status is deliberately not an
input: authenticated figured dimensions remain valid when page scale is absent
or conflicting.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import math
from types import MappingProxyType
from weakref import WeakKeyDictionary

import fitz
from PIL import Image, ImageOps
from typing import Mapping, Optional, Sequence

from pb_dimension_graph_constraint_engine import DimensionOrientation
from pb_drawing_evidence_binding import DrawingViewType
from pb_figured_dimension_authority import (
    DimensionParseError,
    parse_figured_dimension_mm,
)
from pb_figured_dimension_evidence import (
    BindingStatus,
    extract_dimension_evidence_bundle,
)
from pb_live_canonical_room_composition import (
    LiveCanonicalRoomComposition,
    LiveCanonicalRoomObject,
)
from pb_migration_contracts import (
    EvidenceAtom,
    EvidenceResolutionStatus,
    stable_contract_id,
)
from pb_page_scale_calibration_authority import (
    POINTS_PER_METRE_AT_1_1,
    ScaleCalibrationStatus,
    ScaleSourceReading,
    ScaleSourceType,
    resolve_page_scale_calibration,
)
from pb_pdf_text_integrity_authority import (
    TEXT_CLIP_STATE_UNRESOLVED,
    TEXT_GLYPH_MAPPING_UNVERIFIED,
)
from pb_portable_raster_ocr_authority import (
    TesseractOCRBackend,
    select_production_ocr_backend,
)
from pb_raster_text_corroboration_authority import (
    RASTER_TEXT_CORROBORATION_DPIS,
    RasterTextCorroborationProducer,
    RasterTextCorroborationSelector,
    _lossless_rotate,
    _producer_owned_ocr_target,
    normalize_reading,
)
from pb_source_observation_authority import ObservationSelector
from pb_source_room_label_authority import _normalized_room_line
from pb_source_visibility_authority import (
    NATIVE_PDF_VISIBLE_SEGMENT,
    SourceVisibilityProducer,
)


CROSS_VIEW_ROOM_AREA_SCHEMA_VERSION = "1.0.0"
CROSS_VIEW_ROOM_AREA_RESOLVED = "cross_view_room_area_resolved"
CROSS_VIEW_ROOM_AREA_PARTIAL = "cross_view_room_area_partial"
CROSS_VIEW_ROOM_AREA_UNAVAILABLE = "cross_view_room_area_unavailable"
CROSS_VIEW_ROOM_AREA_CONFLICT = "cross_view_room_area_conflict"
CROSS_VIEW_ROOM_AREA_LABEL_UNAVAILABLE = "cross_view_room_area_label_unavailable"
CROSS_VIEW_ROOM_AREA_DIMENSIONS_UNAVAILABLE = (
    "cross_view_room_area_dimensions_unavailable"
)
CROSS_VIEW_ROOM_AREA_LINEAGE_CONFLICT = "cross_view_room_area_lineage_conflict"
CROSS_VIEW_ROOM_AREA_EVIDENCE_RESOLVED = (
    "authenticated_cross_view_room_area"
)

_PRODUCER_SEAL = object()
_RECORD_SEAL = object()

# Source-owned acceleration only: exact PDF-derived dimension bundles may be
# reused for other labels on the SAME producer, revision, snapshot, page and
# view type. Per-label native text, raster corroboration and physical witness
# authority below always run anew; no pre-authenticated quantity is cached.
# A weak producer key prevents retained PDF evidence after producer lifetime.
_DIMENSION_BUNDLE_CACHE: WeakKeyDictionary = WeakKeyDictionary()
_DIMENSION_BUNDLE_CACHE_MAX_PAGES = 8


def _norm_label(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _finite_bbox(value: Sequence[object]) -> Optional[tuple[float, float, float, float]]:
    if len(value) < 4:
        return None
    try:
        out = tuple(float(value[index]) for index in range(4))
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(item) for item in out):
        return None
    if out[2] <= out[0] or out[3] <= out[1]:
        return None
    return out


@dataclass(frozen=True)
class _TrustedLine:
    page_id: str
    text: str
    bbox: tuple[float, float, float, float]
    observation_ids: tuple[str, ...]
    receipt_ids: tuple[str, ...]
    source_partition_id: str
    block_no: int
    line_no: int
    label_members: tuple[str, ...] = ()


@dataclass(frozen=True)
class _TrustedBoundDimension:
    dimension_id: str
    text_observation_id: str
    text_receipt_id: str
    text_source_partition_id: str
    text_block_no: Optional[int]
    text_line_no: Optional[int]
    text_word_no: Optional[int]
    value_mm: float
    orientation: str
    endpoints_pt: tuple[tuple[float, float], tuple[float, float]]
    dimension_line_observation_ids: tuple[str, ...]
    witness_observation_ids: tuple[str, ...]
    witness_geometries: tuple[
        tuple[float, float, float, float], ...
    ]
    text_bbox: Optional[tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class CrossViewRoomAreaRecord:
    physical_room_id: str
    source_room_face_record_id: str
    room_label: str
    source_dimension_page_id: str
    source_label_observation_ids: tuple[str, ...]
    source_label_receipt_ids: tuple[str, ...]
    horizontal_dimension_id: str
    vertical_dimension_id: str
    area_evidence: EvidenceAtom
    schema_version: str = CROSS_VIEW_ROOM_AREA_SCHEMA_VERSION
    _seal: object = None

    def __post_init__(self) -> None:
        if self._seal is not _RECORD_SEAL:
            raise TypeError("CrossViewRoomAreaRecord is producer-owned")


@dataclass(frozen=True)
class CrossViewRoomAreaResult:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    records: tuple[CrossViewRoomAreaRecord, ...]
    unresolved_physical_room_ids: tuple[str, ...]
    schema_version: str = CROSS_VIEW_ROOM_AREA_SCHEMA_VERSION
    unresolved_first_failure_codes: tuple[tuple[str, str], ...] = ()

    @property
    def unresolved_first_failure_by_physical_room_id(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.unresolved_first_failure_codes))

    @property
    def evidence_by_physical_room_id(self) -> Mapping[str, EvidenceAtom]:
        return MappingProxyType(
            {
                record.physical_room_id: record.area_evidence
                for record in self.records
            }
        )

    @property
    def evidence_by_source_room_face_record_id(self) -> Mapping[str, EvidenceAtom]:
        return MappingProxyType(
            {
                record.source_room_face_record_id: record.area_evidence
                for record in self.records
            }
        )


def _isolated_line_text_corroboration(
    source: SourceVisibilityProducer,
    *,
    published,
    ordered: Sequence[tuple[str, object, object]],
    raw_line: str,
    backend,
) -> Optional[str]:
    """Authenticate one exact native text line by two isolated renders.

    The line must already be a contiguous producer-owned native PDF text line
    whose raw claim exactly matches a requested canonical room label. This
    fallback is used only when one or more individual word crops cannot be read.
    Every word must otherwise be eligible for the existing glyph-only raster
    corroboration boundary. The union of the producer-derived word raster
    targets is rendered at both authority DPIs, normalized by one common
    producer-derived quarter-turn, and must yield exactly the native line in
    both views. Blank margin is added only after rendering and cannot introduce
    neighbouring source pixels.
    """

    raw_claim = normalize_reading(raw_line)
    if not raw_claim or not ordered or not backend.is_available():
        return None

    targets: list[tuple[float, float, float, float]] = []
    rotations: set[int] = set()
    parent_keys: set[tuple[str, str, str]] = set()
    admissible = {
        TEXT_GLYPH_MAPPING_UNVERIFIED,
        TEXT_CLIP_STATE_UNRESOLVED,
    }

    for observation_id, text_result, receipt in ordered:
        reason_set = set(tuple(getattr(receipt, "reason_codes", ()) or ()))
        if text_result.status is EvidenceResolutionStatus.CORROBORATED:
            if not getattr(text_result, "trusted_text", None):
                return None
        elif (
            text_result.status is not EvidenceResolutionStatus.ABSTAINED
            or bool(getattr(receipt, "trusted", False))
            or TEXT_GLYPH_MAPPING_UNVERIFIED not in reason_set
            or not reason_set.issubset(admissible)
            or tuple(text_result.reason_codes)
            != tuple(getattr(receipt, "reason_codes", ()) or ())
        ):
            return None

        selector = ObservationSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            observation_id=observation_id,
        )
        source_result = source._producer.authority().resolve(selector)
        observation = source_result.observation
        if (
            source_result.status is not EvidenceResolutionStatus.CORROBORATED
            or observation is None
            or observation.observation_kind != "native_pdf_word"
            or observation.origin_kind != "native"
            or observation.viewport_id is not None
            or str(observation.page_id) != str(receipt.page_id)
            or tuple(observation.geometry) != tuple(receipt.geometry)
        ):
            return None
        bbox = _finite_bbox(observation.geometry)
        if bbox is None:
            return None
        target, rotation = _producer_owned_ocr_target(
            source._producer,
            revision_id=selector.revision_id,
            source_sha256=selector.source_sha256,
            page_id=str(observation.page_id),
            receipt=receipt,
            word_bbox=bbox,
            raw_text=str(observation.raw_text),
        )
        targets.append(target)
        rotations.add(int(rotation))

    if len(rotations) != 1 or not targets:
        return None
    rotation = next(iter(rotations))
    raster_bbox = (
        min(value[0] for value in targets),
        min(value[1] for value in targets),
        max(value[2] for value in targets),
        max(value[3] for value in targets),
    )

    readings: list[str] = []
    for dpi in RASTER_TEXT_CORROBORATION_DPIS:
        try:
            png_bytes, page_parent = source._producer.render_native_page_png(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                page_id=str(ordered[0][2].page_id),
                dpi=float(dpi),
                clip_pt=raster_bbox,
            )
        except Exception:
            return None
        parent_keys.add(
            (
                str(page_parent.observation_id),
                str(page_parent.source_partition_id),
                str(page_parent.page_id),
            )
        )
        try:
            rendered = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            normalized = _lossless_rotate(rendered, rotation)
        except Exception:
            return None
        margin_px = max(
            1,
            int(round(float(dpi) * _DIMENSION_OCR_BLANK_MARGIN_MM / 25.4)),
        )
        isolated = ImageOps.expand(normalized, border=margin_px, fill="white")
        reading = _single_isolated_ocr_reading(
            backend,
            isolated,
            dpi=int(dpi),
        )
        if reading is None or normalize_reading(reading) != raw_claim:
            return None
        readings.append(reading)

    if (
        len(parent_keys) != 1
        or len(readings) != len(RASTER_TEXT_CORROBORATION_DPIS)
    ):
        return None
    normalized_readings = tuple(normalize_reading(value) for value in readings)
    if len(set(normalized_readings)) != 1 or normalized_readings[0] != raw_claim:
        return None
    return raw_claim


def _trusted_lines_for_page(
    source: SourceVisibilityProducer,
    *,
    revision_id: str,
    page_id: str,
    candidate_labels: Sequence[str],
    allow_compound_annotations: bool = False,
) -> tuple[_TrustedLine, ...]:
    published = source.published_snapshot_for_revision(revision_id)
    if published is None:
        return ()
    text_authority = source.text_integrity_authority()
    raster = RasterTextCorroborationProducer.from_source_visibility_producer(source)
    line_ocr_backend, _line_ocr_selection_reason = select_production_ocr_backend()
    wanted_labels = {
        _norm_label(value)
        for value in candidate_labels
        if _norm_label(value)
    }
    if not wanted_labels:
        return ()
    grouped: dict[
        tuple[str, int, int],
        list[tuple[str, object, object]],
    ] = {}

    for observation_id in published.text_observation_ids:
        result = text_authority.resolve_text(
            ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=observation_id,
            )
        )
        receipt = result.receipt
        if (
            receipt is None
            or str(receipt.page_id) != str(page_id)
            or receipt.block_no is None
            or receipt.line_no is None
            or receipt.word_no is None
        ):
            continue
        grouped.setdefault(
            (
                str(receipt.source_partition_id),
                int(receipt.block_no),
                int(receipt.line_no),
            ),
            [],
        ).append((str(observation_id), result, receipt))

    lines: list[_TrustedLine] = []
    for key in sorted(grouped):
        items = grouped[key]
        word_nos = [
            int(receipt.word_no)
            for _observation_id, _result, receipt in items
        ]
        if len(set(word_nos)) != len(word_nos):
            continue
        lo, hi = min(word_nos), max(word_nos)
        if set(word_nos) != set(range(lo, hi + 1)):
            continue

        ordered = sorted(items, key=lambda item: int(item[2].word_no))
        raw_line = " ".join(
            str(item[2].raw_text or "").strip()
            for item in ordered
            if str(item[2].raw_text or "").strip()
        )
        normalized_raw = _norm_label(raw_line)
        label_members: tuple[str, ...] = ()
        if normalized_raw in wanted_labels:
            label_members = (normalized_raw,)
        elif allow_compound_annotations and "/" in raw_line:
            parts = tuple(
                _norm_label(part)
                for part in raw_line.split("/")
                if _norm_label(part)
            )
            if (
                len(parts) >= 2
                and len(set(parts)) == len(parts)
                and any(part in wanted_labels for part in parts)
                and all(_normalized_room_line(part) is not None for part in parts)
            ):
                label_members = parts
        if not label_members:
            continue

        trusted_words: list[str] = []
        failed = False
        for observation_id, native, _receipt in ordered:
            trusted: Optional[str] = None
            if (
                native.status is EvidenceResolutionStatus.CORROBORATED
                and native.trusted_text
            ):
                trusted = str(native.trusted_text)
            else:
                corroborated = raster.publish(
                    RasterTextCorroborationSelector(
                        document_id=published.revision.document_id,
                        revision_id=published.revision.revision_id,
                        source_sha256=published.revision.source_sha256,
                        snapshot_id=published.snapshot.snapshot_id,
                        observation_id=observation_id,
                    )
                )
                if (
                    corroborated.status is EvidenceResolutionStatus.CORROBORATED
                    and corroborated.record is not None
                    and corroborated.corroborated_text
                ):
                    trusted = str(corroborated.corroborated_text)
            if not trusted:
                failed = True
                break
            trusted_words.append(trusted.strip())
        if failed:
            line_text = _isolated_line_text_corroboration(
                source,
                published=published,
                ordered=ordered,
                raw_line=raw_line,
                backend=line_ocr_backend,
            )
            if not line_text:
                continue
        else:
            line_text = " ".join(value for value in trusted_words if value)
        normalized_line_text = _norm_label(line_text)
        if len(label_members) == 1:
            if normalized_line_text != label_members[0]:
                continue
        else:
            trusted_members = tuple(
                _norm_label(part)
                for part in line_text.split("/")
                if _norm_label(part)
            )
            if trusted_members != label_members:
                continue

        boxes = [_finite_bbox(item[2].geometry) for item in ordered]
        if any(box is None for box in boxes):
            continue
        concrete_boxes = tuple(box for box in boxes if box is not None)
        lines.append(
            _TrustedLine(
                page_id=str(page_id),
                text=line_text,
                bbox=(
                    min(box[0] for box in concrete_boxes),
                    min(box[1] for box in concrete_boxes),
                    max(box[2] for box in concrete_boxes),
                    max(box[3] for box in concrete_boxes),
                ),
                observation_ids=tuple(str(item[0]) for item in ordered),
                receipt_ids=tuple(str(item[2].receipt_id) for item in ordered),
                source_partition_id=str(key[0]),
                block_no=int(key[1]),
                line_no=int(key[2]),
                label_members=label_members,
            )
        )
    return tuple(lines)


def _canonical_segment_geometry(
    values: Sequence[object],
) -> Optional[tuple[float, float, float, float]]:
    if len(values) != 4:
        return None
    try:
        coords = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in coords):
        return None
    first = (coords[0], coords[1])
    second = (coords[2], coords[3])
    if second < first:
        first, second = second, first
    if first == second:
        return None
    return (first[0], first[1], second[0], second[1])


def _bbox_key(
    values: Sequence[object],
) -> Optional[tuple[float, float, float, float]]:
    bbox = _finite_bbox(values)
    if bbox is None:
        return None
    return tuple(round(value, 4) for value in bbox)


_DIMENSION_OCR_BLANK_MARGIN_MM = 1.0


def _single_isolated_ocr_reading(
    backend,
    image: Image.Image,
    *,
    dpi: int,
) -> Optional[str]:
    """Read one already-isolated source word with the selected OCR backend.

    Tesseract gets single-line page segmentation only for this exact,
    producer-owned word crop. Other selected production backends receive the
    same isolated image through their normal extraction entrypoint. There is
    never a retry on a different backend.
    """

    if not backend.is_available():
        return None

    if type(backend) is TesseractOCRBackend:
        try:
            import pytesseract

            command = backend._resolved_cmd()
            if not command:
                return None
            pytesseract.pytesseract.tesseract_cmd = command
            raw = pytesseract.image_to_string(image, config="--psm 7")
        except Exception:
            return None
        readings = tuple(
            normalize_reading(line)
            for line in str(raw or "").splitlines()
            if normalize_reading(line)
        )
        return readings[0] if len(readings) == 1 else None

    try:
        lines = tuple(backend.extract_lines(image, dpi=int(dpi)))
    except Exception:
        return None
    readings = tuple(
        normalize_reading(getattr(line, "text", ""))
        for line in lines
        if normalize_reading(getattr(line, "text", ""))
    )
    return readings[0] if len(readings) == 1 else None


def _isolated_dimension_numeric_corroboration(
    source: SourceVisibilityProducer,
    *,
    published,
    selector: ObservationSelector,
    text_result,
    backend,
) -> Optional[str]:
    """Authenticate one witness-bound numeric word by two isolated renders.

    This is a deliberately narrower fallback than general raster OCR:
    - the caller has already reduced the universe to WITNESS_BOUND dimension
      word bboxes;
    - only native text failures eligible for RasterTextCorroboration are
      accepted;
    - the exact producer-owned source word region is rendered independently at
      300 and 450 DPI;
    - blank margin is added only after rendering, so no neighbouring source
      pixels can enter the OCR proof;
    - both renders must yield exactly one reading and parse to exactly the same
      figured millimetre value as the native numeric claim.
    """

    receipt = getattr(text_result, "receipt", None)
    if receipt is None:
        return None
    receipt_reasons = tuple(getattr(receipt, "reason_codes", ()) or ())
    reason_set = set(receipt_reasons)
    admissible = {
        TEXT_GLYPH_MAPPING_UNVERIFIED,
        TEXT_CLIP_STATE_UNRESOLVED,
    }
    if (
        text_result.status is not EvidenceResolutionStatus.ABSTAINED
        or bool(getattr(receipt, "trusted", False))
        or TEXT_GLYPH_MAPPING_UNVERIFIED not in reason_set
        or not reason_set.issubset(admissible)
        or tuple(text_result.reason_codes) != receipt_reasons
    ):
        return None

    source_result = source._producer.authority().resolve(selector)
    observation = source_result.observation
    if (
        source_result.status is not EvidenceResolutionStatus.CORROBORATED
        or observation is None
        or observation.observation_kind != "native_pdf_word"
        or observation.origin_kind != "native"
        or observation.viewport_id is not None
        or str(observation.page_id) != str(receipt.page_id)
        or tuple(observation.geometry) != tuple(receipt.geometry)
    ):
        return None

    bbox = _finite_bbox(observation.geometry)
    if bbox is None:
        return None
    native_claim = normalize_reading(observation.raw_text)
    if not native_claim:
        return None
    try:
        native_mm = float(parse_figured_dimension_mm(native_claim))
    except DimensionParseError:
        return None

    raster_bbox, ocr_rotation_degrees = _producer_owned_ocr_target(
        source._producer,
        revision_id=selector.revision_id,
        source_sha256=selector.source_sha256,
        page_id=str(observation.page_id),
        receipt=receipt,
        word_bbox=bbox,
        raw_text=str(observation.raw_text),
    )

    readings: list[str] = []
    parent_keys: set[tuple[str, str, str]] = set()
    for dpi in RASTER_TEXT_CORROBORATION_DPIS:
        try:
            png_bytes, page_parent = source._producer.render_native_page_png(
                document_id=selector.document_id,
                revision_id=selector.revision_id,
                source_sha256=selector.source_sha256,
                snapshot_id=selector.snapshot_id,
                page_id=str(observation.page_id),
                dpi=float(dpi),
                clip_pt=raster_bbox,
            )
        except Exception:
            return None
        if (
            page_parent.page_id != observation.page_id
            or page_parent.source_partition_id != observation.source_partition_id
            or page_parent.document_id != observation.document_id
            or page_parent.revision_id != observation.revision_id
            or page_parent.source_sha256 != observation.source_sha256
        ):
            return None
        parent_keys.add(
            (
                str(page_parent.observation_id),
                str(page_parent.source_partition_id),
                str(page_parent.page_id),
            )
        )

        try:
            rendered = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            normalized = _lossless_rotate(
                rendered,
                int(ocr_rotation_degrees),
            )
        except Exception:
            return None

        margin_px = max(
            1,
            int(round(float(dpi) * _DIMENSION_OCR_BLANK_MARGIN_MM / 25.4)),
        )
        isolated = ImageOps.expand(
            normalized,
            border=margin_px,
            fill="white",
        )
        reading = _single_isolated_ocr_reading(
            backend,
            isolated,
            dpi=int(dpi),
        )
        if reading is None:
            return None
        try:
            reading_mm = float(parse_figured_dimension_mm(reading))
        except DimensionParseError:
            return None
        if abs(reading_mm - native_mm) > 1e-6:
            return None
        readings.append(reading)

    if len(parent_keys) != 1 or len(readings) != len(RASTER_TEXT_CORROBORATION_DPIS):
        return None
    try:
        parsed = tuple(float(parse_figured_dimension_mm(value)) for value in readings)
    except DimensionParseError:
        return None
    if len(set(parsed)) != 1 or abs(parsed[0] - native_mm) > 1e-6:
        return None
    return native_claim


def _trusted_native_dimensions_for_page(
    source: SourceVisibilityProducer,
    *,
    revision_id: str,
    page_id: str,
    candidate_lines: Sequence[_TrustedLine] = (),
    view_type: str = DrawingViewType.UNKNOWN.value,
) -> tuple[_TrustedBoundDimension, ...]:
    """Resolve source-owned native figured dimensions without trusting raw text.

    Geometry is derived only from the immutable PDF bytes held by the source
    producer. Positive dimensions additionally require PdfTextIntegrity for the
    exact word and a unique mapping of every bound vector segment back to a
    producer-owned native visible observation.
    """
    published = source.published_snapshot_for_revision(revision_id)
    if published is None:
        return ()
    try:
        page_number = int(str(page_id))
    except (TypeError, ValueError):
        return ()
    if page_number not in set(published.coverage.decoded_pages):
        return ()

    writer = source._producer
    source_bytes = writer._store.source_bytes_by_revision.get(revision_id)
    if (
        not isinstance(source_bytes, bytes)
        or not writer._store.source_bytes_match_revision(
            revision_id,
            source_bytes,
            published.revision.source_sha256,
        )
    ):
        return ()

    cache_key = (
        str(revision_id),
        str(published.snapshot.snapshot_id),
        int(page_number),
        str(view_type),
    )
    try:
        producer_bundles = _DIMENSION_BUNDLE_CACHE.setdefault(source, {})
        bundle = producer_bundles.get(cache_key)
        if bundle is None:
            pdf = fitz.open(stream=source_bytes, filetype="pdf")
            try:
                if page_number < 1 or page_number > pdf.page_count:
                    return ()
                bundle = extract_dimension_evidence_bundle(
                    pdf.load_page(page_number - 1),
                    page_num=page_number,
                    view_type=view_type,
                )
            finally:
                pdf.close()
            if len(producer_bundles) >= _DIMENSION_BUNDLE_CACHE_MAX_PAGES:
                producer_bundles.pop(next(iter(producer_bundles)))
            producer_bundles[cache_key] = bundle
    except Exception:
        return ()

    observations = {
        observation.dimension_id: observation
        for observation in bundle.observations
    }
    needed_bbox_keys: set[tuple[float, float, float, float]] = set()
    for binding in bundle.bindings:
        if (
            binding.status != BindingStatus.WITNESS_BOUND.value
            or binding.endpoints is None
            or not binding.dimension_line_id
            or len(binding.witness_line_ids) < 2
        ):
            continue
        observation = observations.get(binding.observation_id)
        if (
            observation is None
            or observation.bbox is None
            or observation.orientation
            not in {
                DimensionOrientation.HORIZONTAL.value,
                DimensionOrientation.VERTICAL.value,
            }
        ):
            continue

        # Geometry-only narrowing: authenticate only WITNESS_BOUND dimensions
        # whose producer-owned source span can contain an already-authenticated
        # candidate room label. This is a negative/performance filter only; it
        # cannot make any dimension authoritative. The existing text, witness,
        # scale-consistency and intersection gates remain mandatory below.
        if candidate_lines:
            first, second = binding.endpoints
            if observation.orientation == DimensionOrientation.HORIZONTAL.value:
                lo, hi = sorted((float(first[0]), float(second[0])))
                relevant = False
                for line in candidate_lines:
                    x0, y0, x1, y1 = line.bbox
                    centre = (x0 + x1) / 2.0
                    word_count = max(1, len(line.receipt_ids))
                    tolerance = max(
                        (x1 - x0) / word_count,
                        (y1 - y0) / word_count,
                        1e-6,
                    )
                    if lo - tolerance <= centre <= hi + tolerance:
                        relevant = True
                        break
                if not relevant:
                    continue
            else:
                lo, hi = sorted((float(first[1]), float(second[1])))
                relevant = False
                for line in candidate_lines:
                    x0, y0, x1, y1 = line.bbox
                    centre = (y0 + y1) / 2.0
                    word_count = max(1, len(line.receipt_ids))
                    tolerance = max(
                        (x1 - x0) / word_count,
                        (y1 - y0) / word_count,
                        1e-6,
                    )
                    if lo - tolerance <= centre <= hi + tolerance:
                        relevant = True
                        break
                if not relevant:
                    continue

        key = _bbox_key(observation.bbox)
        if key is not None:
            needed_bbox_keys.add(key)

    text_authority = source.text_integrity_authority()
    dimension_ocr_backend, _ocr_selection_reason = (
        select_production_ocr_backend()
    )
    trusted_by_bbox: dict[
        tuple[float, float, float, float],
        list[
            tuple[
                str,
                str,
                str,
                str,
                Optional[int],
                Optional[int],
                Optional[int],
            ]
        ],
    ] = {}
    page_text_ids = text_authority.observation_ids_for_page(
        published.snapshot.snapshot_id,
        str(page_id),
    )
    for observation_id in published.text_observation_ids:
        if str(observation_id) not in page_text_ids:
            continue
        selector = ObservationSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            observation_id=observation_id,
        )
        resolved = text_authority.resolve_text(selector)
        receipt = resolved.receipt
        if receipt is None or str(receipt.page_id) != str(page_id):
            continue
        key = _bbox_key(receipt.geometry)
        if key is None or key not in needed_bbox_keys:
            continue

        trusted_text: Optional[str] = None
        if (
            resolved.status is EvidenceResolutionStatus.CORROBORATED
            and resolved.trusted_text
        ):
            trusted_text = str(resolved.trusted_text)
        else:
            trusted_text = _isolated_dimension_numeric_corroboration(
                source,
                published=published,
                selector=selector,
                text_result=resolved,
                backend=dimension_ocr_backend,
            )

        if not trusted_text:
            continue
        trusted_by_bbox.setdefault(key, []).append(
            (
                trusted_text,
                str(observation_id),
                str(receipt.receipt_id),
                str(receipt.source_partition_id),
                None if receipt.block_no is None else int(receipt.block_no),
                None if receipt.line_no is None else int(receipt.line_no),
                None if receipt.word_no is None else int(receipt.word_no),
            )
        )

    visibility = source.authority()
    page_visible_ids = visibility.visible_observation_ids_for_page(
        published.snapshot.snapshot_id,
        str(page_id),
    )
    source_ids_by_geometry: dict[
        tuple[float, float, float, float],
        list[str],
    ] = {}
    source_geometry_by_id: dict[
        str,
        tuple[float, float, float, float],
    ] = {}
    for observation_id in published.visible_observation_ids:
        if str(observation_id) not in page_visible_ids:
            continue
        resolved = visibility.resolve_visible(
            ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=observation_id,
            )
        )
        observation = resolved.observation
        if (
            resolved.status is not EvidenceResolutionStatus.CORROBORATED
            or observation is None
            or str(observation.page_id) != str(page_id)
            or observation.observation_kind != NATIVE_PDF_VISIBLE_SEGMENT
        ):
            continue
        geometry = _canonical_segment_geometry(observation.geometry)
        if geometry is None:
            continue
        source_observation_id = str(observation.observation_id)
        source_ids_by_geometry.setdefault(geometry, []).append(
            source_observation_id
        )
        source_geometry_by_id[source_observation_id] = geometry

    geometry_by_segment_id = {
        segment.segment_id: _canonical_segment_geometry(
            (
                segment.start[0],
                segment.start[1],
                segment.end[0],
                segment.end[1],
            )
        )
        for segment in bundle.observed_geometry
    }

    def source_ids_for_segment(segment_id: str) -> tuple[str, ...]:
        parts = tuple(
            part
            for part in str(segment_id or "").split("+")
            if part
        )
        if not parts:
            return ()
        out: list[str] = []
        for part in parts:
            geometry = geometry_by_segment_id.get(part)
            if geometry is None:
                return ()
            matches = tuple(
                dict.fromkeys(source_ids_by_geometry.get(geometry, ()))
            )
            if not matches:
                return ()
            # Exact coincident source primitives are one unambiguous physical
            # line geometry. Preserve every producer-owned observation ID
            # rather than selecting one arbitrarily. No tolerance, containment
            # or nearest-geometry fallback is permitted here.
            out.extend(matches)
        return tuple(dict.fromkeys(out))

    positive: list[_TrustedBoundDimension] = []
    for binding in bundle.bindings:
        if (
            binding.status != BindingStatus.WITNESS_BOUND.value
            or binding.endpoints is None
            or not binding.dimension_line_id
            or len(binding.witness_line_ids) < 2
        ):
            continue
        observation = observations.get(binding.observation_id)
        if (
            observation is None
            or observation.bbox is None
            or observation.orientation
            not in {
                DimensionOrientation.HORIZONTAL.value,
                DimensionOrientation.VERTICAL.value,
            }
        ):
            continue

        trusted = trusted_by_bbox.get(_bbox_key(observation.bbox), ())
        if len(trusted) != 1:
            continue
        (
            trusted_text,
            text_observation_id,
            text_receipt_id,
            text_source_partition_id,
            text_block_no,
            text_line_no,
            text_word_no,
        ) = trusted[0]
        try:
            parsed_mm = parse_figured_dimension_mm(trusted_text)
            observation_mm = float(observation.value_m) * 1000.0
        except (DimensionParseError, TypeError, ValueError):
            continue
        if abs(float(parsed_mm) - observation_mm) > 1e-6:
            continue

        dimension_line_ids = source_ids_for_segment(binding.dimension_line_id)
        if not dimension_line_ids:
            continue
        witness_ids: list[str] = []
        failed = False
        for witness_line_id in binding.witness_line_ids:
            mapped = source_ids_for_segment(witness_line_id)
            if not mapped:
                failed = True
                break
            witness_ids.extend(mapped)
        witness_ids = list(dict.fromkeys(witness_ids))
        if failed or len(witness_ids) < 2:
            continue
        witness_geometries = tuple(
            source_geometry_by_id.get(observation_id)
            for observation_id in witness_ids
        )
        if any(geometry is None for geometry in witness_geometries):
            continue
        concrete_witness_geometries = tuple(
            geometry
            for geometry in witness_geometries
            if geometry is not None
        )

        endpoints = (
            (
                float(binding.endpoints[0][0]),
                float(binding.endpoints[0][1]),
            ),
            (
                float(binding.endpoints[1][0]),
                float(binding.endpoints[1][1]),
            ),
        )
        if not all(
            math.isfinite(value)
            for endpoint in endpoints
            for value in endpoint
        ):
            continue
        dimension_id = stable_contract_id(
            "cross_view_native_dimension",
            {
                "document_id": published.revision.document_id,
                "revision_id": published.revision.revision_id,
                "source_sha256": published.revision.source_sha256,
                "snapshot_id": published.snapshot.snapshot_id,
                "page_id": str(page_id),
                "text_observation_id": text_observation_id,
                "text_receipt_id": text_receipt_id,
                "value_mm": float(parsed_mm),
                "orientation": observation.orientation,
                "endpoints_pt": endpoints,
                "dimension_line_observation_ids": dimension_line_ids,
                "witness_observation_ids": tuple(sorted(witness_ids)),
            },
            digest_chars=32,
        )
        positive.append(
            _TrustedBoundDimension(
                dimension_id=dimension_id,
                text_observation_id=text_observation_id,
                text_receipt_id=text_receipt_id,
                text_source_partition_id=text_source_partition_id,
                text_block_no=text_block_no,
                text_line_no=text_line_no,
                text_word_no=text_word_no,
                value_mm=float(parsed_mm),
                orientation=str(observation.orientation),
                endpoints_pt=endpoints,
                dimension_line_observation_ids=dimension_line_ids,
                witness_observation_ids=tuple(sorted(witness_ids)),
                witness_geometries=concrete_witness_geometries,
                text_bbox=_finite_bbox(observation.bbox),
            )
        )

    return tuple(
        sorted(
            positive,
            key=lambda item: (
                item.orientation,
                item.endpoints_pt,
                item.value_mm,
                item.dimension_id,
            ),
        )
    )

def _dimension_is_immediate_label_annotation(
    line: _TrustedLine,
    dimension: _TrustedBoundDimension,
) -> bool:
    """Return whether native text structure owns one figured dimension.

    The historical same-block next-line relation remains authoritative.
    A second form handles PDF producers that split one visual label/value
    annotation into consecutive native text blocks. That form is accepted only
    when both records are line zero, the numeric word is word zero, and the
    native text bboxes overlap along the dimension axis. No nearest-text search
    or free-distance ranking is used.
    """
    if (
        not line.source_partition_id
        or line.source_partition_id != dimension.text_source_partition_id
        or dimension.text_block_no is None
        or dimension.text_line_no is None
        or dimension.text_word_no != 0
    ):
        return False
    if (
        dimension.text_block_no == line.block_no
        and dimension.text_line_no == line.line_no + 1
    ):
        return True
    if (
        dimension.text_block_no != line.block_no + 1
        or line.line_no != 0
        or dimension.text_line_no != 0
        or dimension.text_bbox is None
    ):
        return False

    lx0, ly0, lx1, ly1 = line.bbox
    dx0, dy0, dx1, dy1 = dimension.text_bbox
    if dimension.orientation == DimensionOrientation.HORIZONTAL.value:
        return min(lx1, dx1) - max(lx0, dx0) > 0.0
    if dimension.orientation == DimensionOrientation.VERTICAL.value:
        return min(ly1, dy1) - max(ly0, dy0) > 0.0
    return False


def _segment_orientation_value(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _point_on_segment(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
    *,
    tolerance: float = 1e-6,
) -> bool:
    return (
        min(first[0], second[0]) - tolerance
        <= point[0]
        <= max(first[0], second[0]) + tolerance
        and min(first[1], second[1]) - tolerance
        <= point[1]
        <= max(first[1], second[1]) + tolerance
        and abs(_segment_orientation_value(first, second, point))
        <= tolerance
    )


def _source_segments_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    # A source witness line must have TWO distinct finite endpoints. Without
    # this an all-zero segment can masquerade as a physical junction simply
    # because its point lies on an unrelated crossing line. Infinity/NaN and
    # overflow-length spans are equally non-authentic geometry.
    if len(left) != 4 or len(right) != 4:
        return False
    try:
        coordinates = (*left, *right)
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in coordinates):
            return False
        for segment in (left, right):
            length = math.hypot(
                segment[2] - segment[0], segment[3] - segment[1]
            )
            if not math.isfinite(length) or length <= 0:
                return False
    except (TypeError, ValueError, OverflowError):
        return False
    a = (left[0], left[1])
    b = (left[2], left[3])
    c = (right[0], right[1])
    d = (right[2], right[3])
    o1 = _segment_orientation_value(a, b, c)
    o2 = _segment_orientation_value(a, b, d)
    o3 = _segment_orientation_value(c, d, a)
    o4 = _segment_orientation_value(c, d, b)
    tolerance = 1e-6
    if (
        ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance))
        and ((o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance))
    ):
        return True
    return (
        (abs(o1) <= tolerance and _point_on_segment(c, a, b))
        or (abs(o2) <= tolerance and _point_on_segment(d, a, b))
        or (abs(o3) <= tolerance and _point_on_segment(a, c, d))
        or (abs(o4) <= tolerance and _point_on_segment(b, c, d))
    )


def _witness_systems_intersect(
    horizontal: _TrustedBoundDimension,
    vertical: _TrustedBoundDimension,
) -> bool:
    """Require one physical junction between the two witness systems."""
    return any(
        _source_segments_intersect(left, right)
        for left in horizontal.witness_geometries
        for right in vertical.witness_geometries
    )


def _dimension_span_pt(dimension: _TrustedBoundDimension) -> float:
    first, second = dimension.endpoints_pt
    return math.hypot(
        float(second[0]) - float(first[0]),
        float(second[1]) - float(first[1]),
    )


def _figured_pair_scale_consistent(
    *,
    page_id: str,
    horizontal: _TrustedBoundDimension,
    vertical: _TrustedBoundDimension,
) -> bool:
    """Use the existing page-scale conflict contract as a pair-consistency gate.

    The resulting calibration is never published or consumed as measurement
    authority. It is used only to reject two figured dimensions whose source
    spans imply materially different drawing ratios.
    """
    try:
        page_no = int(str(page_id))
    except (TypeError, ValueError):
        return False

    readings: list[ScaleSourceReading] = []
    for name, dimension in (
        ("horizontal", horizontal),
        ("vertical", vertical),
    ):
        span_pt = _dimension_span_pt(dimension)
        metres = float(dimension.value_mm) / 1000.0
        if (
            not math.isfinite(span_pt)
            or span_pt <= 0.0
            or not math.isfinite(metres)
            or metres <= 0.0
        ):
            return False
        points_per_metre = span_pt / metres
        if not math.isfinite(points_per_metre) or points_per_metre <= 0.0:
            return False
        ratio = POINTS_PER_METRE_AT_1_1 / points_per_metre
        readings.append(
            ScaleSourceReading(
                source_type=ScaleSourceType.INFERRED.value,
                scale_text=f"cross-view figured {name} consistency",
                ratio=ratio,
                confidence=1.0,
            )
        )

    calibration = resolve_page_scale_calibration(
        page_no=page_no,
        sheet_label="",
        readings=readings,
    )
    return calibration.status == ScaleCalibrationStatus.PROVISIONAL.value


def _line_inside_dimension_pair(
    line: _TrustedLine,
    horizontal: _TrustedBoundDimension,
    vertical: _TrustedBoundDimension,
) -> bool:
    """Require the authenticated label to belong spatially to the figured box.

    Architectural dimensions are normally offset outside the measured room.
    Permit only a typography-derived offset from the source label itself,
    rather than a fixed page/project distance.
    """
    hx = sorted(
        (
            float(horizontal.endpoints_pt[0][0]),
            float(horizontal.endpoints_pt[1][0]),
        )
    )
    vy = sorted(
        (
            float(vertical.endpoints_pt[0][1]),
            float(vertical.endpoints_pt[1][1]),
        )
    )
    x0, y0, x1, y1 = line.bbox
    centre_x = (x0 + x1) / 2.0
    centre_y = (y0 + y1) / 2.0
    word_count = max(1, len(line.receipt_ids))
    typography_tolerance = max(
        (x1 - x0) / word_count,
        (y1 - y0) / word_count,
        1e-6,
    )
    return (
        hx[0] - typography_tolerance
        <= centre_x
        <= hx[1] + typography_tolerance
        and vy[0] - typography_tolerance
        <= centre_y
        <= vy[1] + typography_tolerance
    )


def _quarantine_reused_cross_view_dimensions(
    records: Sequence[CrossViewRoomAreaRecord],
) -> tuple[list[CrossViewRoomAreaRecord], set[str]]:
    """Reconcile original dimension observation ownership, not numeric size.

    A dimension ID is only source-comparable within its authenticated support
    page. Two genuinely different rooms cannot each reuse the same original
    horizontal or vertical producer record as an independent FIRM area witness.
    """
    owners: dict[tuple[str, str], set[str]] = {}
    for record in records:
        room_id = str(record.physical_room_id)
        for dimension_id in (
            record.horizontal_dimension_id,
            record.vertical_dimension_id,
        ):
            owners.setdefault(
                (str(record.source_dimension_page_id), str(dimension_id)), set()
            ).add(room_id)
    conflicted = set().union(
        *(room_ids for room_ids in owners.values() if len(room_ids) > 1),
        set(),
    )
    return (
        [record for record in records
         if str(record.physical_room_id) not in conflicted],
        conflicted,
    )


class CrossViewRoomAreaProducer:
    def __init__(
        self,
        *,
        source: SourceVisibilityProducer,
        rooms: LiveCanonicalRoomComposition,
        _seal: object = None,
    ) -> None:
        if _seal is not _PRODUCER_SEAL:
            raise TypeError("CrossViewRoomAreaProducer must be obtained from a classmethod")
        if type(source) is not SourceVisibilityProducer:
            raise TypeError("source must be exact SourceVisibilityProducer")
        if type(rooms) is not LiveCanonicalRoomComposition:
            raise TypeError("rooms must be exact LiveCanonicalRoomComposition")
        self._source = source
        self._rooms = rooms

    @classmethod
    def from_source(
        cls,
        *,
        source: SourceVisibilityProducer,
        rooms: LiveCanonicalRoomComposition,
    ) -> "CrossViewRoomAreaProducer":
        return cls(
            source=source,
            rooms=rooms,
            _seal=_PRODUCER_SEAL,
        )

    def publish(self) -> CrossViewRoomAreaResult:
        rooms = tuple(self._rooms.rooms)
        if not rooms:
            return CrossViewRoomAreaResult(
                EvidenceResolutionStatus.ABSTAINED,
                (CROSS_VIEW_ROOM_AREA_UNAVAILABLE,),
                (),
                (),
            )

        revision_ids = {str(room.revision_id) for room in rooms}
        document_ids = {str(room.document_id) for room in rooms}
        source_hashes = {str(room.source_sha256).lower() for room in rooms}
        source_snapshots = {str(room.snapshot_id) for room in rooms}
        if (
            len(revision_ids) != 1
            or len(document_ids) != 1
            or len(source_hashes) != 1
            or len(source_snapshots) != 1
        ):
            unresolved_ids = tuple(sorted(str(room.physical_room_id) for room in rooms))
            return CrossViewRoomAreaResult(
                EvidenceResolutionStatus.CONFLICT,
                (CROSS_VIEW_ROOM_AREA_LINEAGE_CONFLICT,),
                (),
                unresolved_ids,
                unresolved_first_failure_codes=tuple(
                    (room_id, "cross_view_source_lineage_conflict")
                    for room_id in unresolved_ids
                ),
            )
        revision_id = next(iter(revision_ids))
        published = self._source.published_snapshot_for_revision(revision_id)
        if (
            published is None
            or published.revision.document_id != next(iter(document_ids))
            or published.revision.source_sha256.lower() != next(iter(source_hashes))
            or published.snapshot.snapshot_id != next(iter(source_snapshots))
        ):
            unresolved_ids = tuple(sorted(str(room.physical_room_id) for room in rooms))
            return CrossViewRoomAreaResult(
                EvidenceResolutionStatus.CONFLICT,
                (CROSS_VIEW_ROOM_AREA_LINEAGE_CONFLICT,),
                (),
                unresolved_ids,
                unresolved_first_failure_codes=tuple(
                    (room_id, "cross_view_source_lineage_conflict")
                    for room_id in unresolved_ids
                ),
            )

        # Quarantine duplicate source ownership before any native dimension
        # work. Neither multiple labels for one physical room nor multiple
        # physical rooms claiming one source face can independently mint areas.
        physical_counts: dict[str, int] = {}
        face_owners: dict[str, list[str]] = {}
        for source_room in rooms:
            physical_id = str(source_room.physical_room_id or "").strip()
            face_id = str(source_room.source_room_face_record_id or "").strip()
            if physical_id:
                physical_counts[physical_id] = physical_counts.get(physical_id, 0) + 1
            if face_id:
                face_owners.setdefault(face_id, []).append(physical_id)
        duplicate_physical_ids = {
            room_id for room_id, count in physical_counts.items() if count > 1
        }
        duplicate_face_room_ids = {
            room_id
            for room_ids in face_owners.values()
            if len(room_ids) > 1
            for room_id in room_ids
        }
        conflicted_ids = duplicate_physical_ids | duplicate_face_room_ids

        eligible: list[LiveCanonicalRoomObject] = [
            room
            for room in rooms
            if str(room.physical_room_id) not in conflicted_ids
            and room.geometry_complete
            and str(room.physical_room_id or "").strip()
            and str(room.source_room_face_record_id or "").strip()
            and _norm_label(room.room_label)
            and str(room.room_label_binding_record_id or "").strip()
            and bool(room.room_label_evidence_ids)
        ]
        labels: dict[str, list[LiveCanonicalRoomObject]] = {}
        for room in eligible:
            labels.setdefault(_norm_label(room.room_label), []).append(room)

        duplicate_room_ids = {
            room.physical_room_id
            for group in labels.values()
            if len(group) != 1
            for room in group
        }

        # Source decode coverage is already 1-based. Resolve trusted label
        # lines first and run the expensive dimension/OCR authority only on
        # source pages that can actually support a unique cross-view room
        # proposition. This is both fail-closed and important for large plan
        # sets with dozens or hundreds of irrelevant sheets.
        unique_labels = {
            label: grouped_rooms[0]
            for label, grouped_rooms in labels.items()
            if len(grouped_rooms) == 1
        }
        page_results: dict[str, tuple[_TrustedBoundDimension, ...]] = {}
        support_label_pages: dict[str, set[str]] = {}
        support_dimension_pages: dict[str, set[str]] = {}
        page_lines: dict[str, tuple[_TrustedLine, ...]] = {}
        page_annotation_lines: dict[str, tuple[_TrustedLine, ...]] = {}
        for page_number in tuple(published.coverage.decoded_pages):
            page_id = str(int(page_number))
            trusted_lines = _trusted_lines_for_page(
                self._source,
                revision_id=revision_id,
                page_id=page_id,
                candidate_labels=tuple(unique_labels),
            )
            relevant_lines = tuple(
                line
                for line in trusted_lines
                if (
                    _norm_label(line.text) in unique_labels
                    and str(unique_labels[_norm_label(line.text)].page_id)
                    != page_id
                )
            )
            if not relevant_lines:
                continue
            for line in relevant_lines:
                support_label_pages.setdefault(_norm_label(line.text), set()).add(page_id)
            trusted_dimensions = _trusted_native_dimensions_for_page(
                self._source,
                revision_id=revision_id,
                page_id=page_id,
                candidate_lines=relevant_lines,
            )
            if not trusted_dimensions:
                continue
            page_results[page_id] = trusted_dimensions
            page_lines[page_id] = relevant_lines
            for line in relevant_lines:
                support_dimension_pages.setdefault(_norm_label(line.text), set()).add(page_id)
            annotation_lines = _trusted_lines_for_page(
                self._source,
                revision_id=revision_id,
                page_id=page_id,
                candidate_labels=tuple(unique_labels),
                allow_compound_annotations=True,
            )
            page_annotation_lines[page_id] = tuple(
                line
                for line in annotation_lines
                if any(
                    member in unique_labels
                    and str(unique_labels[member].page_id) != page_id
                    for member in (
                        line.label_members
                        or (_norm_label(line.text),)
                    )
                )
            )

        records: list[CrossViewRoomAreaRecord] = []
        eligible_object_ids = {id(room) for room in eligible}
        unresolved: set[str] = {
            str(room.physical_room_id)
            for room in rooms
            if id(room) not in eligible_object_ids
        }
        unresolved.update(str(value) for value in duplicate_room_ids)
        unresolved.update(conflicted_ids)
        first_failures = {
            room_id: "cross_view_room_prerequisites_unavailable"
            for room_id in unresolved
        }
        first_failures.update({
            str(room_id): "cross_view_room_label_duplicate"
            for room_id in duplicate_room_ids
        })
        first_failures.update({
            room_id: "cross_view_physical_room_identity_conflict"
            for room_id in duplicate_physical_ids
        })
        first_failures.update({
            room_id: "cross_view_source_room_face_identity_conflict"
            for room_id in duplicate_face_room_ids
        })
        conflict_seen = bool(duplicate_room_ids or conflicted_ids)

        for label, grouped_rooms in sorted(labels.items()):
            if len(grouped_rooms) != 1:
                continue
            room = grouped_rooms[0]
            matches: list[
                tuple[
                    tuple[_TrustedLine, ...],
                    str,
                    _TrustedBoundDimension,
                    _TrustedBoundDimension,
                ]
            ] = []
            for page_id, trusted_lines in sorted(page_lines.items()):
                if page_id == str(room.page_id):
                    continue
                trusted_dimensions = page_results[page_id]
                horizontals = tuple(
                    item
                    for item in trusted_dimensions
                    if item.orientation == DimensionOrientation.HORIZONTAL.value
                )
                verticals = tuple(
                    item
                    for item in trusted_dimensions
                    if item.orientation == DimensionOrientation.VERTICAL.value
                )
                if not horizontals or not verticals:
                    continue
                for line in trusted_lines:
                    if _norm_label(line.text) != label:
                        continue
                    for horizontal in horizontals:
                        for vertical in verticals:
                            if (
                                _line_inside_dimension_pair(
                                    line,
                                    horizontal,
                                    vertical,
                                )
                                and _figured_pair_scale_consistent(
                                    page_id=page_id,
                                    horizontal=horizontal,
                                    vertical=vertical,
                                )
                                and _witness_systems_intersect(
                                    horizontal,
                                    vertical,
                                )
                            ):
                                matches.append(
                                    (
                                        (line,),
                                        page_id,
                                        horizontal,
                                        vertical,
                                    )
                                )

            if not matches:
                annotation_matches: list[
                    tuple[
                        tuple[_TrustedLine, ...],
                        str,
                        _TrustedBoundDimension,
                        _TrustedBoundDimension,
                    ]
                ] = []
                seen_annotation_pairs: set[tuple[str, str, str]] = set()
                for page_id, trusted_lines in sorted(page_annotation_lines.items()):
                    if page_id == str(room.page_id):
                        continue
                    label_lines = tuple(
                        line
                        for line in trusted_lines
                        if (
                            _norm_label(line.text) == label
                            or label in line.label_members
                        )
                    )
                    if not label_lines:
                        continue
                    trusted_dimensions = page_results[page_id]
                    owned_horizontals = tuple(
                        (line, dimension)
                        for line in label_lines
                        for dimension in trusted_dimensions
                        if (
                            dimension.orientation
                            == DimensionOrientation.HORIZONTAL.value
                            and _dimension_is_immediate_label_annotation(
                                line, dimension
                            )
                        )
                    )
                    owned_verticals = tuple(
                        (line, dimension)
                        for line in label_lines
                        for dimension in trusted_dimensions
                        if (
                            dimension.orientation
                            == DimensionOrientation.VERTICAL.value
                            and _dimension_is_immediate_label_annotation(
                                line, dimension
                            )
                        )
                    )
                    for horizontal_line, horizontal in owned_horizontals:
                        for vertical_line, vertical in owned_verticals:
                            if not any(
                                _norm_label(owner.text) == label
                                for owner in (horizontal_line, vertical_line)
                            ):
                                continue
                            if not _figured_pair_scale_consistent(
                                page_id=page_id,
                                horizontal=horizontal,
                                vertical=vertical,
                            ):
                                continue
                            key = (
                                str(page_id),
                                horizontal.dimension_id,
                                vertical.dimension_id,
                            )
                            if key in seen_annotation_pairs:
                                continue
                            seen_annotation_pairs.add(key)
                            support_lines = tuple(
                                dict.fromkeys(
                                    (horizontal_line, vertical_line)
                                )
                            )
                            annotation_matches.append(
                                (
                                    support_lines,
                                    page_id,
                                    horizontal,
                                    vertical,
                                )
                            )
                matches.extend(annotation_matches)

            if len(matches) != 1:
                physical_id = str(room.physical_room_id)
                unresolved.add(physical_id)
                if len(matches) > 1:
                    conflict_seen = True
                    first_failures[physical_id] = (
                        "cross_view_multiple_authenticated_dimension_pairs"
                    )
                elif not support_label_pages.get(label):
                    first_failures[physical_id] = (
                        "cross_view_trusted_support_label_unavailable"
                    )
                elif not support_dimension_pages.get(label):
                    first_failures[physical_id] = (
                        "cross_view_trusted_support_dimensions_unavailable"
                    )
                else:
                    first_failures[physical_id] = (
                        "cross_view_owned_dimension_pair_unavailable"
                    )
                continue

            support_lines, dimension_page_id, horizontal, vertical = matches[0]
            line = support_lines[0]
            support_observation_ids = tuple(
                dict.fromkeys(
                    observation_id
                    for support_line in support_lines
                    for observation_id in support_line.observation_ids
                )
            )
            support_receipt_ids = tuple(
                dict.fromkeys(
                    receipt_id
                    for support_line in support_lines
                    for receipt_id in support_line.receipt_ids
                )
            )
            area_m2 = round(
                float(horizontal.value_mm)
                * float(vertical.value_mm)
                / 1_000_000.0,
                6,
            )
            if not math.isfinite(area_m2) or area_m2 <= 0.0:
                physical_id = str(room.physical_room_id)
                unresolved.add(physical_id)
                first_failures[physical_id] = "cross_view_metric_area_invalid"
                continue

            horizontal_x = sorted(
                (
                    float(horizontal.endpoints_pt[0][0]),
                    float(horizontal.endpoints_pt[1][0]),
                )
            )
            vertical_y = sorted(
                (
                    float(vertical.endpoints_pt[0][1]),
                    float(vertical.endpoints_pt[1][1]),
                )
            )
            source_dimension_box = (
                horizontal_x[0],
                vertical_y[0],
                horizontal_x[1],
                vertical_y[1],
            )
            evidence_id = stable_contract_id(
                "cross_view_room_area",
                {
                    "document_id": room.document_id,
                    "physical_room_id": room.physical_room_id,
                    "source_room_face_record_id": room.source_room_face_record_id,
                    "dimension_page_id": dimension_page_id,
                    "label_receipt_ids": support_receipt_ids,
                    "horizontal_dimension_id": horizontal.dimension_id,
                    "vertical_dimension_id": vertical.dimension_id,
                    "area_m2": area_m2,
                },
                digest_chars=32,
            )
            area_evidence = EvidenceAtom(
                evidence_id=evidence_id,
                document_id=str(room.document_id),
                page_id=str(room.page_id),
                viewport_id=room.viewport_id,
                kind="explicit_room_area",
                method="authenticated_cross_view_figured_dimensions",
                normalized_value=area_m2,
                unit="m2",
                confidence=1.0,
                status=EvidenceResolutionStatus.CORROBORATED,
                reason_codes=(CROSS_VIEW_ROOM_AREA_EVIDENCE_RESOLVED,),
                metadata={
                    "physical_room_id": str(room.physical_room_id),
                    "source_room_face_record_id": str(
                        room.source_room_face_record_id
                    ),
                    "room_label_binding_record_id": str(
                        room.room_label_binding_record_id
                    ),
                    "room_label_evidence_ids": list(room.room_label_evidence_ids),
                    "source_dimension_page_id": str(dimension_page_id),
                    "source_dimension_snapshot_id": str(
                        published.snapshot.snapshot_id
                    ),
                    "source_label_text": line.text,
                    "source_label_observation_ids": list(support_observation_ids),
                    "source_label_receipt_ids": list(support_receipt_ids),
                    "source_label_bbox_pdf_pts": list(line.bbox),
                    "source_label_bboxes_pdf_pts": [
                        list(support_line.bbox)
                        for support_line in support_lines
                    ],
                    "source_label_support_mode": (
                        "single_label_witness_junction"
                        if len(support_lines) == 1
                        else "repeated_label_annotation_blocks"
                    ),
                    "source_dimension_box_pdf_pts": list(source_dimension_box),
                    "horizontal_endpoints_pt": [
                        list(horizontal.endpoints_pt[0]),
                        list(horizontal.endpoints_pt[1]),
                    ],
                    "vertical_endpoints_pt": [
                        list(vertical.endpoints_pt[0]),
                        list(vertical.endpoints_pt[1]),
                    ],
                    "figured_dimension_ids": [
                        horizontal.dimension_id,
                        vertical.dimension_id,
                    ],
                    "horizontal_dimension_id": horizontal.dimension_id,
                    "horizontal_text_observation_id": (
                        horizontal.text_observation_id
                    ),
                    "horizontal_value_mm": int(horizontal.value_mm),
                    "horizontal_dimension_line_observation_ids": list(
                        horizontal.dimension_line_observation_ids
                    ),
                    "horizontal_witness_observation_ids": list(
                        horizontal.witness_observation_ids
                    ),
                    "vertical_dimension_id": vertical.dimension_id,
                    "vertical_text_observation_id": vertical.text_observation_id,
                    "vertical_value_mm": int(vertical.value_mm),
                    "vertical_dimension_line_observation_ids": list(
                        vertical.dimension_line_observation_ids
                    ),
                    "vertical_witness_observation_ids": list(
                        vertical.witness_observation_ids
                    ),
                    "room_revision_id": str(room.revision_id),
                    "room_snapshot_id": str(room.snapshot_id),
                    "source_sha256": str(room.source_sha256),
                },
            )
            records.append(
                CrossViewRoomAreaRecord(
                    physical_room_id=str(room.physical_room_id),
                    source_room_face_record_id=str(
                        room.source_room_face_record_id
                    ),
                    room_label=str(room.room_label),
                    source_dimension_page_id=str(dimension_page_id),
                    source_label_observation_ids=support_observation_ids,
                    source_label_receipt_ids=support_receipt_ids,
                    horizontal_dimension_id=horizontal.dimension_id,
                    vertical_dimension_id=vertical.dimension_id,
                    area_evidence=area_evidence,
                    _seal=_RECORD_SEAL,
                )
            )

        # Across distinct physical rooms, an original producer-owned native
        # figured dimension observation may support at most one whole-room
        # area. A shared horizontal OR vertical source dimension on the same
        # support page is not independent proof of two metric room areas.
        # Quarantine both claimants, regardless of producer iteration order.
        records, reused_source_owners = _quarantine_reused_cross_view_dimensions(
            records
        )
        if reused_source_owners:
            unresolved.update(reused_source_owners)
            first_failures.update({
                room_id: "cross_view_dimension_source_owner_conflict"
                for room_id in reused_source_owners
            })
            conflict_seen = True

        records.sort(key=lambda item: item.physical_room_id)
        unresolved_ids = tuple(sorted(unresolved))
        if records and not unresolved_ids:
            status = EvidenceResolutionStatus.CORROBORATED
            reasons = (CROSS_VIEW_ROOM_AREA_RESOLVED,)
        elif records:
            status = EvidenceResolutionStatus.CANDIDATE
            reasons = (CROSS_VIEW_ROOM_AREA_PARTIAL,)
        elif conflict_seen:
            status = EvidenceResolutionStatus.CONFLICT
            reasons = (CROSS_VIEW_ROOM_AREA_CONFLICT,)
        else:
            status = EvidenceResolutionStatus.ABSTAINED
            reasons = (
                CROSS_VIEW_ROOM_AREA_LABEL_UNAVAILABLE,
                CROSS_VIEW_ROOM_AREA_DIMENSIONS_UNAVAILABLE,
            )
        return CrossViewRoomAreaResult(
            status=status,
            reason_codes=reasons,
            records=tuple(records),
            unresolved_physical_room_ids=unresolved_ids,
            unresolved_first_failure_codes=tuple(sorted(
                (room_id, first_failures[room_id])
                for room_id in unresolved_ids if room_id in first_failures
            )),
        )


__all__ = [
    "CROSS_VIEW_ROOM_AREA_CONFLICT",
    "CROSS_VIEW_ROOM_AREA_DIMENSIONS_UNAVAILABLE",
    "CROSS_VIEW_ROOM_AREA_EVIDENCE_RESOLVED",
    "CROSS_VIEW_ROOM_AREA_LABEL_UNAVAILABLE",
    "CROSS_VIEW_ROOM_AREA_LINEAGE_CONFLICT",
    "CROSS_VIEW_ROOM_AREA_PARTIAL",
    "CROSS_VIEW_ROOM_AREA_RESOLVED",
    "CROSS_VIEW_ROOM_AREA_SCHEMA_VERSION",
    "CROSS_VIEW_ROOM_AREA_UNAVAILABLE",
    "CrossViewRoomAreaProducer",
    "CrossViewRoomAreaRecord",
    "CrossViewRoomAreaResult",
]
