"""pb_benchmark_schema.py — PlanReader Accuracy Benchmark Schema and Data Contracts.

Defines the JSON schema, dataclasses, and validators for golden benchmark plans,
manifests, expected quantities, schedules, and accuracy scoring.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema


# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

SOURCE_MANIFEST_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SourceManifest",
    "type": "object",
    "required": [
        "benchmark_id",
        "project_name",
        "project_number",
        "client",
        "drawing_issue",
        "drawing_date",
        "allowed_comparison_sources",
        "rejected_comparison_sources",
        "status",
    ],
    "properties": {
        "benchmark_id": {"type": "string"},
        "project_name": {"type": "string"},
        "project_number": {"type": "string"},
        "client": {"type": "string"},
        "drawing_issue": {"type": "string"},
        "drawing_date": {"type": "string"},
        "source_pdf": {"type": ["string", "null"]},
        "source_takeoff": {"type": ["string", "null"]},
        "allowed_comparison_sources": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rejected_comparison_sources": {
            "type": "array",
            "items": {"type": "string"},
        },
        "status": {"type": "string"},
    },
    "additionalProperties": True,
}

EXPECTED_PROJECT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ExpectedProject",
    "type": "object",
    "required": ["project_name", "address", "client", "project_number"],
    "properties": {
        "project_name": {"type": "string"},
        "address": {"type": "string"},
        "client": {"type": "string"},
        "project_number": {"type": "string"},
        "drawing_issue": {"type": "string"},
        "drawing_date": {"type": "string"},
        "drawing_set_title": {"type": "string"},
        "number_of_units": {"type": ["integer", "null"]},
        "number_of_levels": {"type": ["integer", "null"]},
        "sheet_count": {"type": ["integer", "null"]},
    },
    "additionalProperties": True,
}

EXPECTED_QUANTITY_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["quantity_id", "description", "expected_value", "unit", "source", "authority"],
    "properties": {
        "quantity_id": {"type": "string"},
        "description": {"type": "string"},
        "expected_value": {"type": "number"},
        "unit": {"type": "string"},
        "source": {
            "type": "object",
            "required": ["document", "sheet"],
            "properties": {
                "document": {"type": "string"},
                "sheet": {"type": "string"},
                "page": {"type": ["integer", "null"]},
                "line_or_region": {"type": ["string", "null"]},
            },
        },
        "authority": {
            "type": "string",
            "enum": [
                "documented",
                "schedule_extracted",
                "pdf_scaled",
                "ai_detected",
                "user_corrected",
                "user_approved",
                "model_derived",
                "provisional",
                "excluded",
                "reference_only",
            ],
        },
        "scope_disposition": {
            "type": "string",
            "enum": ["included", "excluded", "provisional", "reference_only"],
        },
        "tolerance": {
            "type": "object",
            "properties": {
                "absolute": {"type": "number"},
                "percentage": {"type": "number"},
            },
        },
    },
    "additionalProperties": True,
}

EXPECTED_QUANTITIES_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ExpectedQuantities",
    "type": "array",
    "items": EXPECTED_QUANTITY_ITEM_SCHEMA,
}

TOLERANCES_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Tolerances",
    "type": "object",
    "properties": {
        "default": {
            "type": "object",
            "properties": {
                "absolute": {"type": "number"},
                "percentage": {"type": "number"},
            },
        },
        "categories": {"type": "object"},
    },
    "additionalProperties": True,
}

EXPECTED_RENDER_PAGES_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ExpectedRenderPages",
    "type": "object",
    "required": ["render_pages"],
    "properties": {
        "render_pages": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "descriptions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "additionalProperties": True,
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class SourceManifest:
    benchmark_id: str
    project_name: str
    project_number: str
    client: str
    drawing_issue: str
    drawing_date: str
    source_pdf: Optional[str] = None
    source_takeoff: Optional[str] = None
    allowed_comparison_sources: List[str] = field(default_factory=list)
    rejected_comparison_sources: List[str] = field(default_factory=list)
    status: str = "benchmark_seed"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectIdentity:
    project_name: str
    address: str
    client: str
    project_number: str
    drawing_issue: str = ""
    drawing_date: str = ""
    drawing_set_title: str = ""
    number_of_units: Optional[int] = None
    number_of_levels: Optional[int] = None
    sheet_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Tolerance:
    absolute: float = 0.0
    percentage: float = 0.0  # 0.01 == 1%


@dataclass
class ExpectedQuantity:
    quantity_id: str
    description: str
    expected_value: float
    unit: str
    source: Dict[str, Any]
    authority: str
    scope_disposition: str = "included"
    tolerance: Optional[Tolerance] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.tolerance:
            d["tolerance"] = asdict(self.tolerance)
        return d


@dataclass
class QuantityComparisonResult:
    quantity_id: str
    description: str
    expected: float
    actual: Optional[float]
    unit: str
    difference: Optional[float]
    difference_percent: Optional[float]
    status: str  # exact_match | within_tolerance | outside_tolerance | missing_from_planreader | missing_from_expected | source_mismatch | manual_review_required | provisional_only
    confidence: float
    source_trace: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    benchmark_id: str
    timestamp: str
    source_pdf: Optional[str]
    source_takeoff: Optional[str]
    project_identity: Dict[str, Any]
    comparison_allowed: bool
    rejection_reason: Optional[str]
    pages_classified: Dict[str, Any]
    schedules_extracted: Dict[str, Any]
    quantities_compared: List[Dict[str, Any]]
    summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Validation Functions
# ---------------------------------------------------------------------------

def validate_json_schema(data: Any, schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate python dictionary or list against a JSON schema."""
    validator = jsonschema.Draft7Validator(schema)
    errors = [e.message for e in validator.iter_errors(data)]
    return len(errors) == 0, errors


def validate_benchmark_folder(folder_path: str | Path) -> Tuple[bool, Dict[str, List[str]]]:
    """Validate all required benchmark files in a benchmark directory."""
    path = Path(folder_path)
    report: Dict[str, List[str]] = {}

    required_files = {
        "source_manifest.json": SOURCE_MANIFEST_SCHEMA,
        "expected_project.json": EXPECTED_PROJECT_SCHEMA,
        "expected_quantities.json": EXPECTED_QUANTITIES_SCHEMA,
        "tolerances.json": TOLERANCES_SCHEMA,
    }

    all_valid = True
    for fname, schema in required_files.items():
        fpath = path / fname
        if not fpath.exists():
            report[fname] = [f"Missing required file: {fname}"]
            all_valid = False
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = json.load(f)
            ok, errors = validate_json_schema(content, schema)
            if not ok:
                report[fname] = errors
                all_valid = False
            else:
                report[fname] = []
        except Exception as exc:
            report[fname] = [f"JSON decode error: {exc}"]
            all_valid = False

    # Optional files validation if present
    if (path / "expected_render_pages.json").exists():
        fpath = path / "expected_render_pages.json"
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = json.load(f)
            ok, errors = validate_json_schema(content, EXPECTED_RENDER_PAGES_SCHEMA)
            if not ok:
                report["expected_render_pages.json"] = errors
                all_valid = False
        except Exception as exc:
            report["expected_render_pages.json"] = [f"JSON decode error: {exc}"]
            all_valid = False

    return all_valid, report
