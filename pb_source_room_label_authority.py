"""Producer-owned source room-label authority.

Room geometry and room semantics are deliberately separate authorities. This
module binds only literal source text to an already authenticated
SourceRoomFaceRecord. It never infers geometry, room use, quantities, or a
label from proximity alone.

Positive publication requires:
- an already CORROBORATED source-room face scope;
- the entire native PDF text line is a generic room-label semantic candidate;
- every word in that line is independently authenticated by PdfTextIntegrity,
  or by producer-owned two-render raster text corroboration for the exact
  native claim;
- every contributing word centre lies inside exactly one source-room face and
  all words resolve to the same face;
- exactly one authenticated label line resolves to that face.

Raw native text is candidate-generation evidence only. It is never trusted by
itself. There is no nearest-room selection, OCR correction, edit-distance
matching, or benchmark-aware vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import io
import math
import re
from types import MappingProxyType
from typing import Mapping, Optional, Sequence

from PIL import Image, ImageOps

from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_pdf_text_integrity_authority import (
    TEXT_CLIP_STATE_UNRESOLVED,
    TEXT_GLYPH_MAPPING_UNVERIFIED,
)
from pb_portable_raster_ocr_authority import (
    MockOCRBackend,
    TesseractOCRBackend,
)
from pb_raster_text_corroboration_authority import (
    RASTER_TEXT_CORROBORATION_DPIS,
    RasterTextCorroborationProducer,
    RasterTextCorroborationSelector,
    _lossless_rotate,
    _producer_owned_ocr_target,
    normalize_reading,
)
from pb_room_face_takeoff import KNOWN_ROOM_PHRASES, ROOM_LABEL_EXACT
from pb_source_observation_authority import ObservationSelector
from pb_source_room_face_authority import SourceRoomFaceAuthority
from pb_source_visibility_authority import SourceVisibilityProducer


SOURCE_ROOM_LABEL_SCHEMA_VERSION = "1.0.0"
SOURCE_ROOM_LABEL_SCOPE_RESOLVED = "source_room_label_scope_resolved"
SOURCE_ROOM_LABEL_SCOPE_UNAVAILABLE = "source_room_label_scope_unavailable"
SOURCE_ROOM_LABEL_REQUIRED_WORD_UNRESOLVED = (
    "source_room_label_required_word_unresolved"
)
SOURCE_ROOM_LABEL_POSITION_UNRESOLVED = "source_room_label_position_unresolved"
SOURCE_ROOM_LABEL_CONFLICT = "source_room_label_conflict"
SOURCE_ROOM_LABEL_SPLIT_FACE_CANDIDATE = (
    "source_room_label_split_face_candidate"
)

_PRODUCER_SEAL = object()
_AUTHORITY_SEAL = object()
_RECORD_SEAL = object()

# Generic commercial/institutional room semantics not covered by the older
# residential room-label filter. No project names, pages, coordinates,
# dimensions, benchmark object ids, or expected values are present here.
_COMMERCIAL_ROOM_EXACT = frozenset(
    {
        "airlock",
        "amenities",
        "bar",
        "change",
        "chiller",
        "cleaner",
        "coolroom",
        "ens",
        "freezer",
        "f-amb",
        "kiosk",
        "m-amb",
        "lobby",
        "prep",
        "preparation",
        "pwd",
        "reception",
        "sales",
        "servery",
        "staff",
        "utility",
    }
)
_COMMERCIAL_ROOM_PHRASES = frozenset(
    {
        "accessible toilet",
        "cold room",
        "cold store",
        "commercial kitchen",
        "cool room",
        "dry store",
        "female amenities",
        "food prep",
        "food preparation",
        "food service",
        "male amenities",
        "pos counter",
        "staff room",
        "staff change",
        "truck driver lounge",
        "wash up",
        "wc & shower",
    }
)
_MAX_ROOM_LABEL_WORDS = 4
_ROOM_LABEL_OCR_BLANK_MARGIN_MM = 1.0


@dataclass(frozen=True)
class SourceRoomLabelWordEvidence:
    observation_id: str
    receipt_id: str
    trusted_text: str
    authority_kind: str
    authority_record_id: str
    geometry: tuple[float, float, float, float]
    word_no: int


@dataclass(frozen=True)
class SourceRoomLabelRecord:
    record_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    face_id: str
    source_room_face_record_id: str
    label: str
    observation_ids: tuple[str, ...]
    word_evidence: tuple[SourceRoomLabelWordEvidence, ...]
    source_bbox: tuple[float, float, float, float]
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    schema_version: str = SOURCE_ROOM_LABEL_SCHEMA_VERSION
    _seal: object = None

    def __post_init__(self) -> None:
        if self._seal is not _RECORD_SEAL:
            raise TypeError("SourceRoomLabelRecord is producer-owned")
        if self.status is not EvidenceResolutionStatus.CORROBORATED:
            raise ValueError("positive room-label record must be CORROBORATED")
        if not self.label or not self.word_evidence:
            raise ValueError(
                "positive room-label record requires literal word evidence"
            )


@dataclass(frozen=True)
class SourceRoomSplitLabelCandidate:
    """Authenticated whole-line room text whose words own multiple exact faces."""

    record_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    label: str
    observation_ids: tuple[str, ...]
    word_evidence: tuple[SourceRoomLabelWordEvidence, ...]
    word_face_ids: tuple[str, ...]
    source_room_face_record_ids: tuple[str, ...]
    source_bbox: tuple[float, float, float, float]
    status: EvidenceResolutionStatus = EvidenceResolutionStatus.CANDIDATE
    reason_codes: tuple[str, ...] = (SOURCE_ROOM_LABEL_SPLIT_FACE_CANDIDATE,)
    schema_version: str = SOURCE_ROOM_LABEL_SCHEMA_VERSION
    _seal: object = None

    def __post_init__(self) -> None:
        if self._seal is not _RECORD_SEAL:
            raise TypeError("SourceRoomSplitLabelCandidate is producer-owned")
        if self.status is not EvidenceResolutionStatus.CANDIDATE:
            raise ValueError("split-face label evidence must remain CANDIDATE")
        if (
            not self.label
            or len(self.word_evidence) < 2
            or len(self.word_face_ids) != len(self.word_evidence)
            or len(set(self.word_face_ids)) < 2
        ):
            raise ValueError("split-face label candidate requires multiple owned faces")


@dataclass(frozen=True)
class SourceRoomLabelScopeResult:
    status: EvidenceResolutionStatus
    reason_codes: tuple[str, ...]
    records: tuple[SourceRoomLabelRecord, ...]
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str
    split_face_candidates: tuple[SourceRoomSplitLabelCandidate, ...] = ()
    schema_version: str = SOURCE_ROOM_LABEL_SCHEMA_VERSION


@dataclass(frozen=True)
class SourceRoomLabelSelector:
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_id: str
    page_id: str
    decision_scope_id: str

    @property
    def key(self) -> tuple[str, str, str, str, str, str]:
        return (
            str(self.document_id),
            str(self.revision_id),
            str(self.source_sha256),
            str(self.snapshot_id),
            str(self.page_id),
            str(self.decision_scope_id),
        )


@dataclass(frozen=True)
class _Word:
    observation_id: str
    receipt_id: str
    source_partition_id: str
    raw_text: str
    geometry: tuple[float, float, float, float]
    block_no: int
    line_no: int
    word_no: int


def _normalized_room_line(text: str) -> Optional[str]:
    """Return a normalized literal room label or None.

    Candidate recognition is whole-line. A room-looking token embedded in a
    longer equipment/note line cannot be cherry-picked.
    """

    compact = " ".join(str(text or "").strip().split())
    if not compact:
        return None
    words = compact.split()
    if not 1 <= len(words) <= _MAX_ROOM_LABEL_WORDS:
        return None
    normalized = compact.lower()
    if any(any(ch.isdigit() for ch in word) for word in words):
        return None
    if len(words) == 1:
        token = re.sub(r"^[^a-z]+|[^a-z]+$", "", normalized)
        if token in ROOM_LABEL_EXACT or token in _COMMERCIAL_ROOM_EXACT:
            return compact
        return None
    if (
        normalized in KNOWN_ROOM_PHRASES
        or normalized in _COMMERCIAL_ROOM_PHRASES
    ):
        return compact
    return None


def _bbox_union(
    values: Sequence[Sequence[float]],
) -> tuple[float, float, float, float]:
    return (
        min(float(v[0]) for v in values),
        min(float(v[1]) for v in values),
        max(float(v[2]) for v in values),
        max(float(v[3]) for v in values),
    )


def _point_in_polygon(
    point: tuple[float, float],
    polygon: Sequence[Sequence[float]],
) -> bool:
    x, y = point
    pts = tuple((float(p[0]), float(p[1])) for p in polygon)
    if len(pts) < 3:
        return False
    inside = False
    for index, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(index + 1) % len(pts)]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length > 0.0:
            cross = abs((x - x1) * dy - (y - y1) * dx) / length
            if cross <= 1e-6 and (
                min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6
                and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6
            ):
                return True
        if (y1 > y) == (y2 > y):
            continue
        crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        if crossing_x > x:
            inside = not inside
    return inside


def _source_face_polygon_bbox(
    polygon: Sequence[Sequence[float]],
) -> Optional[tuple[float, float, float, float]]:
    """Only an acceleration bound; a bbox never authorizes a room label."""
    try:
        points = tuple((float(point[0]), float(point[1])) for point in polygon)
        if len(points) < 3 or any(
            not math.isfinite(value) for point in points for value in point
        ):
            return None
        return (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        )
    except (TypeError, IndexError, ValueError, OverflowError):
        return None


def _point_may_belong_to_face_bbox(
    point: tuple[float, float],
    bbox: Optional[tuple[float, float, float, float]],
) -> bool:
    """Reject only provably outside points; retain 1e-6 boundary tolerance."""
    if bbox is None:
        return True  # Never prune a face with an unproven bounding box.
    x, y = point
    x0, y0, x1, y1 = bbox
    eps = 1e-6
    return x0 - eps <= x <= x1 + eps and y0 - eps <= y <= y1 + eps


def _line_groups(words: Sequence[_Word]) -> tuple[tuple[_Word, ...], ...]:
    grouped: dict[tuple[str, int, int], list[_Word]] = {}
    for word in words:
        grouped.setdefault(
            (word.source_partition_id, word.block_no, word.line_no),
            [],
        ).append(word)
    out = []
    for key in sorted(grouped):
        ordered = tuple(
            sorted(
                grouped[key],
                key=lambda w: (
                    w.word_no,
                    w.geometry[1],
                    w.geometry[0],
                    w.observation_id,
                ),
            )
        )
        if len({word.word_no for word in ordered}) != len(ordered):
            continue
        out.append(ordered)
    return tuple(out)


def _single_isolated_line_reading(
    backend,
    image: Image.Image,
    *,
    dpi: int,
) -> Optional[str]:
    """Read one already-isolated producer-owned source text line.

    Tesseract receives single-line page segmentation only after the exact
    producer-owned line crop has been rendered. Other selected backends use
    their normal extraction entrypoint. There is no backend retry or image
    preprocessing preference.
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


class SourceRoomLabelAuthority:
    def __init__(
        self,
        results: Mapping[
            tuple[str, str, str, str, str, str],
            SourceRoomLabelScopeResult,
        ],
        *,
        _seal=None,
    ) -> None:
        if _seal is not _AUTHORITY_SEAL:
            raise TypeError("SourceRoomLabelAuthority is producer-owned")
        self._results = MappingProxyType(dict(results))

    def resolve_scope(
        self,
        selector: SourceRoomLabelSelector,
    ) -> SourceRoomLabelScopeResult:
        if type(selector) is not SourceRoomLabelSelector:
            raise TypeError("selector must be SourceRoomLabelSelector")
        result = self._results.get(selector.key)
        if result is not None:
            return result
        return SourceRoomLabelScopeResult(
            status=EvidenceResolutionStatus.ABSTAINED,
            reason_codes=(SOURCE_ROOM_LABEL_SCOPE_UNAVAILABLE,),
            records=(),
            document_id=selector.document_id,
            revision_id=selector.revision_id,
            source_sha256=selector.source_sha256,
            snapshot_id=selector.snapshot_id,
            page_id=selector.page_id,
            decision_scope_id=selector.decision_scope_id,
        )


def _unique_source_faces_for_label_ownership(records):
    """Keep only unambiguous producer face ID AND source receipt identities.

    Never let dict insertion order choose one of several original physical
    room faces. Valid independent source faces remain available for labels.
    """
    faces=tuple(records)
    def valid(value):
        return isinstance(value,str) and bool(value) and value==value.strip()
    face_counts=Counter(
        rec.face_id for rec in faces
        if valid(getattr(rec,"face_id",None))
    )
    receipt_counts=Counter(
        rec.record_id for rec in faces
        if valid(getattr(rec,"record_id",None))
    )
    return tuple(
        rec for rec in faces
        if valid(getattr(rec,"face_id",None))
        and valid(getattr(rec,"record_id",None))
        and face_counts[rec.face_id]==1
        and receipt_counts[rec.record_id]==1
    )


class SourceRoomLabelProducer:
    def __init__(
        self,
        source: SourceVisibilityProducer,
        room_faces: SourceRoomFaceAuthority,
        raster: RasterTextCorroborationProducer,
        *,
        _seal=None,
    ) -> None:
        if _seal is not _PRODUCER_SEAL:
            raise TypeError(
                "SourceRoomLabelProducer must be obtained from a classmethod"
            )
        self._source = source
        self._room_faces = room_faces
        self._raster = raster
        # Preserve the producer-owned complete native text universe while
        # reusing its sealed immutable read-only resolver across each word.
        self._text_integrity_authority = source.text_integrity_authority()
        self._results: dict[
            tuple[str, str, str, str, str, str],
            SourceRoomLabelScopeResult,
        ] = {}

    @classmethod
    def from_authorities(
        cls,
        source: SourceVisibilityProducer,
        room_faces: SourceRoomFaceAuthority,
        *,
        page_ids: Optional[Sequence[str]] = None,
    ) -> "SourceRoomLabelProducer":
        if type(source) is not SourceVisibilityProducer:
            raise TypeError("source must be an actual SourceVisibilityProducer")
        if type(room_faces) is not SourceRoomFaceAuthority:
            raise TypeError(
                "room_faces must be producer-owned SourceRoomFaceAuthority"
            )
        producer = cls(
            source,
            room_faces,
            RasterTextCorroborationProducer.from_source_visibility_producer(
                source
            ),
            _seal=_PRODUCER_SEAL,
        )
        producer._build(page_ids=page_ids)
        return producer

    @classmethod
    def from_authorities_for_tests(
        cls,
        source: SourceVisibilityProducer,
        room_faces: SourceRoomFaceAuthority,
        backend: MockOCRBackend,
        *,
        page_ids: Optional[Sequence[str]] = None,
    ) -> "SourceRoomLabelProducer":
        if (
            type(source) is not SourceVisibilityProducer
            or type(room_faces) is not SourceRoomFaceAuthority
            or type(backend) is not MockOCRBackend
        ):
            raise TypeError(
                "tests require exact producer-owned authorities and MockOCRBackend"
            )
        producer = cls(
            source,
            room_faces,
            RasterTextCorroborationProducer
            .from_source_visibility_producer_for_tests(source, backend),
            _seal=_PRODUCER_SEAL,
        )
        producer._build(page_ids=page_ids)
        return producer

    def _authorize_word(
        self,
        published,
        word: _Word,
    ) -> Optional[SourceRoomLabelWordEvidence]:
        selector = ObservationSelector(
            document_id=published.revision.document_id,
            revision_id=published.revision.revision_id,
            source_sha256=published.revision.source_sha256,
            snapshot_id=published.snapshot.snapshot_id,
            observation_id=word.observation_id,
        )
        native = self._text_integrity_authority.resolve_text(selector)
        if (
            native.status is EvidenceResolutionStatus.CORROBORATED
            and native.receipt is not None
            and native.trusted_text
        ):
            return SourceRoomLabelWordEvidence(
                observation_id=word.observation_id,
                receipt_id=native.receipt.receipt_id,
                trusted_text=str(native.trusted_text),
                authority_kind="native_text_integrity",
                authority_record_id=native.receipt.receipt_id,
                geometry=word.geometry,
                word_no=word.word_no,
            )

        raster = self._raster.publish(
            RasterTextCorroborationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=word.observation_id,
            )
        )
        if (
            raster.status is EvidenceResolutionStatus.CORROBORATED
            and raster.record is not None
            and raster.corroborated_text
        ):
            return SourceRoomLabelWordEvidence(
                observation_id=word.observation_id,
                receipt_id=word.receipt_id,
                trusted_text=str(raster.corroborated_text),
                authority_kind="raster_text_corroboration",
                authority_record_id=raster.record.record_id,
                geometry=word.geometry,
                word_no=word.word_no,
            )
        return None

    def _authorize_line_fallback(
        self,
        published,
        line: Sequence[_Word],
        raw_line: str,
    ) -> Optional[tuple[SourceRoomLabelWordEvidence, ...]]:
        """Authenticate one exact room-label line by two isolated renders.

        This fallback is deliberately narrower than generic OCR. The source
        line must already be a whole-line room semantic candidate and every
        word must be producer-owned native text. Any untrusted word must have
        only the same glyph/clip reasons admitted by RasterTextCorroboration.
        Text-trace failures and all other integrity failures remain fail-closed.

        The union of producer-derived word raster targets is rendered at both
        authority DPIs. Blank margin is added only after rendering, so no
        neighbouring source pixels can enter the proof. Both views must read
        exactly the raw native whole line.
        """

        claim = normalize_reading(raw_line)
        backend = getattr(self._raster, "_backend", None)
        if not claim or not line or backend is None or not backend.is_available():
            return None

        admissible = {
            TEXT_GLYPH_MAPPING_UNVERIFIED,
            TEXT_CLIP_STATE_UNRESOLVED,
        }
        targets: list[tuple[float, float, float, float]] = []
        rotations: set[int] = set()
        source_partitions: set[str] = set()
        source_page_ids: set[str] = set()
        observation_ids: list[str] = []

        for word in line:
            selector = ObservationSelector(
                document_id=published.revision.document_id,
                revision_id=published.revision.revision_id,
                source_sha256=published.revision.source_sha256,
                snapshot_id=published.snapshot.snapshot_id,
                observation_id=word.observation_id,
            )
            text_result = self._text_integrity_authority.resolve_text(
                selector
            )
            receipt = text_result.receipt
            if (
                receipt is None
                or str(receipt.receipt_id) != str(word.receipt_id)
                or str(receipt.page_id) == ""
                or tuple(float(value) for value in receipt.geometry)
                != tuple(float(value) for value in word.geometry)
            ):
                return None

            if (
                text_result.status is EvidenceResolutionStatus.CORROBORATED
                and text_result.trusted_text
            ):
                if normalize_reading(text_result.trusted_text) != normalize_reading(
                    word.raw_text
                ):
                    return None
            else:
                receipt_reasons = tuple(receipt.reason_codes or ())
                reason_set = set(receipt_reasons)
                if (
                    text_result.status is not EvidenceResolutionStatus.ABSTAINED
                    or bool(receipt.trusted)
                    or TEXT_GLYPH_MAPPING_UNVERIFIED not in reason_set
                    or not reason_set.issubset(admissible)
                    or tuple(text_result.reason_codes) != receipt_reasons
                ):
                    return None

            source_result = self._source._producer.authority().resolve(selector)
            observation = source_result.observation
            if (
                source_result.status is not EvidenceResolutionStatus.CORROBORATED
                or observation is None
                or observation.observation_kind != "native_pdf_word"
                or observation.origin_kind != "native"
                or observation.viewport_id is not None
                or observation.document_id != published.revision.document_id
                or observation.revision_id != published.revision.revision_id
                or observation.source_sha256 != published.revision.source_sha256
                or str(observation.page_id) != str(receipt.page_id)
                or str(observation.source_partition_id)
                != str(word.source_partition_id)
                or tuple(float(value) for value in observation.geometry)
                != tuple(float(value) for value in word.geometry)
                or normalize_reading(observation.raw_text)
                != normalize_reading(word.raw_text)
            ):
                return None

            raster_bbox, rotation = _producer_owned_ocr_target(
                self._source._producer,
                revision_id=selector.revision_id,
                source_sha256=selector.source_sha256,
                page_id=str(observation.page_id),
                receipt=receipt,
                word_bbox=tuple(float(value) for value in word.geometry),
                raw_text=str(observation.raw_text),
            )
            targets.append(raster_bbox)
            rotations.add(int(rotation))
            source_partitions.add(str(observation.source_partition_id))
            source_page_ids.add(str(observation.page_id))
            observation_ids.append(str(observation.observation_id))

        if (
            len(rotations) != 1
            or len(source_partitions) != 1
            or len(source_page_ids) != 1
            or not targets
        ):
            return None
        rotation = next(iter(rotations))
        source_partition_id = next(iter(source_partitions))
        source_page_id = next(iter(source_page_ids))
        raster_bbox = (
            min(value[0] for value in targets),
            min(value[1] for value in targets),
            max(value[2] for value in targets),
            max(value[3] for value in targets),
        )

        readings: list[str] = []
        parent_ids: set[tuple[str, str, str]] = set()
        for dpi in RASTER_TEXT_CORROBORATION_DPIS:
            try:
                png_bytes, page_parent = (
                    self._source._producer.render_native_page_png(
                        document_id=published.revision.document_id,
                        revision_id=published.revision.revision_id,
                        source_sha256=published.revision.source_sha256,
                        snapshot_id=published.snapshot.snapshot_id,
                        page_id=source_page_id,
                        dpi=float(dpi),
                        clip_pt=raster_bbox,
                    )
                )
            except Exception:
                return None

            if (
                page_parent.document_id != published.revision.document_id
                or page_parent.revision_id != published.revision.revision_id
                or page_parent.source_sha256 != published.revision.source_sha256
                or str(page_parent.source_partition_id) != source_partition_id
                or str(page_parent.page_id) != source_page_id
            ):
                return None
            parent_ids.add(
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
                int(
                    round(
                        float(dpi)
                        * _ROOM_LABEL_OCR_BLANK_MARGIN_MM
                        / 25.4
                    )
                ),
            )
            isolated = ImageOps.expand(
                normalized,
                border=margin_px,
                fill="white",
            )
            reading = _single_isolated_line_reading(
                backend,
                isolated,
                dpi=int(dpi),
            )
            if reading is None or normalize_reading(reading) != claim:
                return None
            readings.append(reading)

        if (
            len(parent_ids) != 1
            or len(readings) != len(RASTER_TEXT_CORROBORATION_DPIS)
            or len({normalize_reading(value) for value in readings}) != 1
        ):
            return None

        authority_record_id = stable_contract_id(
            "source_room_label_line_raster_corroboration",
            {
                "document_id": published.revision.document_id,
                "revision_id": published.revision.revision_id,
                "source_sha256": published.revision.source_sha256,
                "snapshot_id": published.snapshot.snapshot_id,
                "source_partition_id": source_partition_id,
                "observation_ids": tuple(observation_ids),
                "raw_line": claim,
                "render_dpis": tuple(RASTER_TEXT_CORROBORATION_DPIS),
                "backend_name": str(getattr(backend, "name", "")),
                "backend_version": str(getattr(backend, "version", "")),
            },
            digest_chars=32,
        )
        return tuple(
            SourceRoomLabelWordEvidence(
                observation_id=word.observation_id,
                receipt_id=word.receipt_id,
                trusted_text=word.raw_text,
                authority_kind="raster_text_line_corroboration",
                authority_record_id=authority_record_id,
                geometry=word.geometry,
                word_no=word.word_no,
            )
            for word in line
        )

    def _build(self, *, page_ids: Optional[Sequence[str]]) -> None:
        selected = (
            None
            if page_ids is None
            else {
                str(value).strip()
                for value in page_ids
                if str(value).strip()
            }
        )
        if page_ids is not None and not selected:
            raise ValueError("page_ids must contain at least one page")

        text_authority = self._text_integrity_authority
        words_by_lineage: dict[
            tuple[str, str, str, str, str],
            list[_Word],
        ] = {}
        published_by_lineage: dict[
            tuple[str, str, str, str, str],
            object,
        ] = {}

        for revision_id, published in sorted(
            self._source._published_by_revision.items()
        ):
            if (
                self._source._producer.current_revision_id(
                    published.revision.document_id
                )
                != revision_id
            ):
                continue
            for observation_id in published.text_observation_ids:
                native = text_authority.resolve_text(
                    ObservationSelector(
                        document_id=published.revision.document_id,
                        revision_id=published.revision.revision_id,
                        source_sha256=published.revision.source_sha256,
                        snapshot_id=published.snapshot.snapshot_id,
                        observation_id=observation_id,
                    )
                )
                receipt = native.receipt
                if (
                    receipt is None
                    or receipt.block_no is None
                    or receipt.line_no is None
                    or receipt.word_no is None
                ):
                    continue
                page_id = str(receipt.page_id)
                if selected is not None and page_id not in selected:
                    continue
                geometry = tuple(float(v) for v in tuple(receipt.geometry))
                if (
                    len(geometry) != 4
                    or not all(math.isfinite(v) for v in geometry)
                    or geometry[2] <= geometry[0]
                    or geometry[3] <= geometry[1]
                ):
                    continue
                lineage = (
                    published.revision.document_id,
                    published.revision.revision_id,
                    published.revision.source_sha256,
                    published.snapshot.snapshot_id,
                    page_id,
                )
                published_by_lineage[lineage] = published
                words_by_lineage.setdefault(lineage, []).append(
                    _Word(
                        observation_id=observation_id,
                        receipt_id=receipt.receipt_id,
                        source_partition_id=str(
                            receipt.source_partition_id
                        ),
                        raw_text=str(receipt.raw_text or ""),
                        geometry=geometry,  # type: ignore[arg-type]
                        block_no=int(receipt.block_no),
                        line_no=int(receipt.line_no),
                        word_no=int(receipt.word_no),
                    )
                )

        for scope in self._room_faces._results.values():
            if (
                scope.status is not EvidenceResolutionStatus.CORROBORATED
                or not scope.records
            ):
                continue
            if selected is not None and str(scope.page_id) not in selected:
                continue

            lineage = (
                str(scope.document_id),
                str(scope.revision_id),
                str(scope.source_sha256),
                str(scope.snapshot_id),
                str(scope.page_id),
            )
            published = published_by_lineage.get(lineage)
            if published is None:
                continue
            words = words_by_lineage.get(lineage, ())
            candidates_by_face: dict[
                str,
                list[
                    tuple[
                        str,
                        tuple[SourceRoomLabelWordEvidence, ...],
                        tuple[float, float, float, float],
                    ]
                ],
            ] = {}
            required_word_unresolved = False
            position_unresolved = False
            split_face_candidates: list[SourceRoomSplitLabelCandidate] = []
            # Duplicate physical source-face IDs or shared producer record
            # receipts cannot choose an arbitrary text owner by dict order.
            # Retain other exact independent source-owned rooms.
            authentic_faces = _unique_source_faces_for_label_ownership(scope.records)
            room_by_face = {
                record.face_id: record for record in authentic_faces
            }
            source_face_bounds = tuple(
                (record, _source_face_polygon_bbox(record.polygon_pdf_pts))
                for record in authentic_faces
            )

            for line in _line_groups(words):
                raw_line = " ".join(
                    word.raw_text.strip()
                    for word in line
                    if word.raw_text.strip()
                )
                candidate = _normalized_room_line(raw_line)
                if candidate is None:
                    continue

                evidence: list[SourceRoomLabelWordEvidence] = []
                unresolved = False
                for word in line:
                    authorized = self._authorize_word(published, word)
                    if authorized is None:
                        unresolved = True
                        break
                    evidence.append(authorized)
                if unresolved:
                    fallback = self._authorize_line_fallback(
                        published,
                        line,
                        raw_line,
                    )
                    if fallback is None:
                        required_word_unresolved = True
                        continue
                    evidence = list(fallback)

                label = " ".join(
                    item.trusted_text.strip()
                    for item in evidence
                    if item.trusted_text.strip()
                )
                if _normalized_room_line(label) is None:
                    required_word_unresolved = True
                    continue

                word_face_ids: list[str] = []
                position_ok = True
                for item in evidence:
                    x0, y0, x1, y1 = item.geometry
                    point = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                    matches = [
                        record.face_id
                        for record, bbox in source_face_bounds
                        if _point_may_belong_to_face_bbox(point, bbox)
                        and _point_in_polygon(
                            point,
                            record.polygon_pdf_pts,
                        )
                    ]
                    if len(matches) != 1:
                        position_ok = False
                        break
                    word_face_ids.append(str(matches[0]))
                if not position_ok or not word_face_ids:
                    position_unresolved = True
                    continue

                distinct_face_ids = tuple(dict.fromkeys(word_face_ids))
                if len(distinct_face_ids) > 1:
                    face_records = [
                        room_by_face.get(face_id) for face_id in distinct_face_ids
                    ]
                    if any(record is None for record in face_records):
                        position_unresolved = True
                        continue
                    payload = {
                        "document_id": scope.document_id,
                        "revision_id": scope.revision_id,
                        "source_sha256": scope.source_sha256,
                        "snapshot_id": scope.snapshot_id,
                        "page_id": scope.page_id,
                        "decision_scope_id": scope.decision_scope_id,
                        "label": label,
                        "word_face_ids": tuple(word_face_ids),
                        "source_room_face_record_ids": tuple(
                            record.record_id for record in face_records
                        ),
                        "authority_record_ids": tuple(
                            item.authority_record_id for item in evidence
                        ),
                    }
                    split_face_candidates.append(
                        SourceRoomSplitLabelCandidate(
                            record_id=stable_contract_id(
                                "source_room_split_label_candidate",
                                payload,
                                digest_chars=32,
                            ),
                            document_id=scope.document_id,
                            revision_id=scope.revision_id,
                            source_sha256=scope.source_sha256,
                            snapshot_id=scope.snapshot_id,
                            page_id=scope.page_id,
                            decision_scope_id=scope.decision_scope_id,
                            label=label,
                            observation_ids=tuple(
                                item.observation_id for item in evidence
                            ),
                            word_evidence=tuple(evidence),
                            word_face_ids=tuple(word_face_ids),
                            source_room_face_record_ids=tuple(
                                record.record_id for record in face_records
                            ),
                            source_bbox=_bbox_union(
                                [item.geometry for item in evidence]
                            ),
                            _seal=_RECORD_SEAL,
                        )
                    )
                    position_unresolved = True
                    continue

                common_face = distinct_face_ids[0]
                candidates_by_face.setdefault(common_face, []).append(
                    (
                        label,
                        tuple(evidence),
                        _bbox_union(
                            [item.geometry for item in evidence]
                        ),
                    )
                )

            positive: list[SourceRoomLabelRecord] = []
            conflict = False
            for face_id, candidates in sorted(candidates_by_face.items()):
                if len(candidates) != 1:
                    conflict = True
                    continue
                label, evidence, bbox = candidates[0]
                room = room_by_face.get(face_id)
                if room is None:
                    position_unresolved = True
                    continue
                payload = {
                    "document_id": scope.document_id,
                    "revision_id": scope.revision_id,
                    "source_sha256": scope.source_sha256,
                    "snapshot_id": scope.snapshot_id,
                    "page_id": scope.page_id,
                    "decision_scope_id": scope.decision_scope_id,
                    "face_id": face_id,
                    "source_room_face_record_id": room.record_id,
                    "label": label,
                    "authority_record_ids": tuple(
                        item.authority_record_id
                        for item in evidence
                    ),
                }
                positive.append(
                    SourceRoomLabelRecord(
                        record_id=stable_contract_id(
                            "source_room_label_record",
                            payload,
                            digest_chars=32,
                        ),
                        document_id=scope.document_id,
                        revision_id=scope.revision_id,
                        source_sha256=scope.source_sha256,
                        snapshot_id=scope.snapshot_id,
                        page_id=scope.page_id,
                        decision_scope_id=scope.decision_scope_id,
                        face_id=face_id,
                        source_room_face_record_id=room.record_id,
                        label=label,
                        observation_ids=tuple(
                            item.observation_id for item in evidence
                        ),
                        word_evidence=evidence,
                        source_bbox=bbox,
                        status=EvidenceResolutionStatus.CORROBORATED,
                        reason_codes=(
                            SOURCE_ROOM_LABEL_SCOPE_RESOLVED,
                        ),
                        _seal=_RECORD_SEAL,
                    )
                )

            reasons = (
                [SOURCE_ROOM_LABEL_SCOPE_RESOLVED]
                if positive
                else [SOURCE_ROOM_LABEL_SCOPE_UNAVAILABLE]
            )
            if required_word_unresolved:
                reasons.append(
                    SOURCE_ROOM_LABEL_REQUIRED_WORD_UNRESOLVED
                )
            if position_unresolved:
                reasons.append(SOURCE_ROOM_LABEL_POSITION_UNRESOLVED)
            if conflict:
                reasons.append(SOURCE_ROOM_LABEL_CONFLICT)

            key = (
                str(scope.document_id),
                str(scope.revision_id),
                str(scope.source_sha256),
                str(scope.snapshot_id),
                str(scope.page_id),
                str(scope.decision_scope_id),
            )
            self._results[key] = SourceRoomLabelScopeResult(
                status=(
                    EvidenceResolutionStatus.CORROBORATED
                    if positive
                    else EvidenceResolutionStatus.ABSTAINED
                ),
                reason_codes=tuple(dict.fromkeys(reasons)),
                records=tuple(
                    sorted(
                        positive,
                        key=lambda record: (
                            record.face_id,
                            record.record_id,
                        ),
                    )
                ),
                document_id=scope.document_id,
                revision_id=scope.revision_id,
                source_sha256=scope.source_sha256,
                snapshot_id=scope.snapshot_id,
                page_id=scope.page_id,
                decision_scope_id=scope.decision_scope_id,
                split_face_candidates=tuple(
                    sorted(
                        split_face_candidates,
                        key=lambda record: (record.label, record.record_id),
                    )
                ),
            )

    def authority(self) -> SourceRoomLabelAuthority:
        return SourceRoomLabelAuthority(
            self._results,
            _seal=_AUTHORITY_SEAL,
        )

    def published_results(
        self,
    ) -> tuple[SourceRoomLabelScopeResult, ...]:
        return tuple(
            self._results[key] for key in sorted(self._results)
        )


__all__ = [
    "SOURCE_ROOM_LABEL_SCHEMA_VERSION",
    "SOURCE_ROOM_LABEL_SCOPE_RESOLVED",
    "SOURCE_ROOM_LABEL_SCOPE_UNAVAILABLE",
    "SOURCE_ROOM_LABEL_REQUIRED_WORD_UNRESOLVED",
    "SOURCE_ROOM_LABEL_POSITION_UNRESOLVED",
    "SOURCE_ROOM_LABEL_CONFLICT",
    "SOURCE_ROOM_LABEL_SPLIT_FACE_CANDIDATE",
    "SourceRoomLabelWordEvidence",
    "SourceRoomLabelRecord",
    "SourceRoomSplitLabelCandidate",
    "SourceRoomLabelScopeResult",
    "SourceRoomLabelSelector",
    "SourceRoomLabelAuthority",
    "SourceRoomLabelProducer",
]
