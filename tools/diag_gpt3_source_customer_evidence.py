"""Benchmark-neutral, fail-closed sealed-run to customer evidence report.

This tool never reads frozen references or maps production rows to benchmark
objects. It proves only the declared sealed quantities and projected rows.
Actual source PDF SHA verification and universe closure require separate runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pb_customer_output_verification import verify_sealed_customer_output
from pb_source_closed_run_export import sealed_source_closed_run_from_dict


def _reject_duplicate_payload_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate source/customer JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json_number(token: str) -> None:
    raise ValueError(f"non-finite source/customer JSON number: {token}")


def _read_strict_evidence_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_payload_keys,
        parse_constant=_reject_nonfinite_json_number,
    )


def build_source_customer_evidence_report(
    sealed_payload: Mapping[str, Any],
    customer_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate cryptographic sealing and exact commercial row bijection."""
    sealed = sealed_source_closed_run_from_dict(sealed_payload)
    verification = verify_sealed_customer_output(sealed, customer_rows)

    produced = [
        {
            "quantity_id": row.quantity_id,
            "family": row.family,
            "semantic_key": row.semantic_key,
            "value": row.value,
            "unit": row.unit,
            "canonical_object_refs": list(row.object_identity_refs),
            "trace_canonical_entity_ids": list(row.trace_canonical_entity_ids),
            "quantity_evidence_ids": list(row.evidence_ids),
            "source_evidence_ids": list(row.trace_evidence_ids),
            "document_id": row.document_id,
            "source_sha256": row.source_sha256,
            "revision_id": row.revision_id,
            "source_page": row.source_page,
            "viewport_id": row.viewport_id,
            "sealed_quantity_fingerprint": row.fingerprint,
        }
        for row in sealed.quantities
        if not row.abstained
    ]
    produced.sort(key=lambda item: item["quantity_id"])
    return {
        "schema": "gpt3_source_customer_evidence_v1",
        "project_id": sealed.project_id,
        "sealed_run_id": sealed.run_id,
        "sealed_run_fingerprint": sealed.fingerprint,
        "sealed_run_fingerprint_verified": True,
        "source_sha256s_declared_in_sealed_run": list(sealed.source_sha256s),
        "source_revision_ids": list(sealed.revision_ids),
        "input_pdf_sha256_verified": False,
        "input_pdf_sha256_verification": "NOT_CHECKED_BY_THIS_DIAGNOSTIC",
        "quantity_to_customer_parity": verification.to_dict(),
        "source_backed_sealed_items": produced,
        "source_object_universe_complete": "NOT_DETERMINED",
        "official_frozen_evaluator_status": "UNPUBLISHED",
        "official_coverage_accuracy": None,
        "official_precision_adjusted_accuracy": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sealed-run", type=Path, required=True)
    parser.add_argument("--customer-rows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sealed_payload = _read_strict_evidence_json(args.sealed_run)
    rows = _read_strict_evidence_json(args.customer_rows)
    if not isinstance(rows, list):
        raise TypeError("customer-rows JSON must be an array")
    report = build_source_customer_evidence_report(sealed_payload, rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
