"""Finalize split source-closed project handoffs into one verified project run.

This is a benchmark-neutral convenience layer over the strict sealed-run loader
and combiner. It discovers the standard <project>.core.json and
<project>.surfaces.json files, verifies every present run, combines the
available groups deterministically, and emits <project>.json plus a small
handoff summary.

Missing groups are reported, not manufactured. No benchmark truth, expected
quantities, tolerances, identity maps, or scoring logic are read here.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pb_combine_source_closed_runs import combine_sealed_run_files


GROUPS = ("core", "surfaces")


def finalize_split_project_handoff(
    *,
    project_id: str,
    input_dir: Path | str,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    if type(project_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", project_id):
        raise ValueError("project_id must be a single canonical filename-safe token")
    clean_project_id = project_id

    source_dir = Path(input_dir)
    target_dir = Path(output_dir) if output_dir is not None else source_dir

    available: list[tuple[str, Path]] = []
    missing: list[str] = []
    for group in GROUPS:
        path = source_dir / f"{clean_project_id}.{group}.json"
        if path.is_file():
            available.append((group, path))
        else:
            missing.append(group)

    if not available:
        raise FileNotFoundError(
            f"no split sealed runs found for project {clean_project_id!r}"
        )

    combined = combine_sealed_run_files(
        [path for _, path in available],
        project_id=clean_project_id,
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{clean_project_id}.json"
    output_path.write_text(combined.to_json(), encoding="utf-8")

    summary = {
        "schema_version": "1.0.0",
        "project_id": clean_project_id,
        "available_groups": [group for group, _ in available],
        "missing_groups": missing,
        "complete_group_set": not missing,
        "input_files": {group: str(path) for group, path in available},
        "output_file": str(output_path),
        "run_id": combined.run_id,
        "source_sha256s": list(combined.source_sha256s),
        "revision_ids": list(combined.revision_ids),
        "quantity_count": len(combined.quantities),
    }
    summary_path = target_dir / f"{clean_project_id}.handoff-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and finalize core/surfaces source-closed project handoffs "
            "into the exact <project_id>.json shape consumed by V2 scoring."
        )
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = finalize_split_project_handoff(
        project_id=args.project_id,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
