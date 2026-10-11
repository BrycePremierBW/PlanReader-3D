"""CLI for verified composition of benchmark-neutral sealed production runs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from pb_source_closed_run_export import (
    SealedSourceClosedRun,
    combine_source_closed_runs,
    sealed_source_closed_run_from_dict,
)


def load_verified_sealed_run(path: Path | str) -> SealedSourceClosedRun:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{source} must contain a JSON object")
    return sealed_source_closed_run_from_dict(payload)


def combine_sealed_run_files(
    input_paths: Iterable[Path | str],
    *,
    project_id: str | None = None,
) -> SealedSourceClosedRun:
    paths = tuple(Path(path) for path in input_paths)
    if not paths:
        raise ValueError("at least one sealed-run input file is required")
    runs = tuple(load_verified_sealed_run(path) for path in paths)
    return combine_source_closed_runs(runs, project_id=project_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and combine independent benchmark-neutral source-closed "
            "production runs into one deterministic project run."
        )
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Optional exact project id. Defaults to the first verified input run.",
    )
    parser.add_argument(
        "--input",
        dest="inputs",
        action="append",
        type=Path,
        required=True,
        help="Verified sealed-run JSON input. Repeat for each production family.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    # Source-closed family receipts are immutable inputs, not disposable CLI
    # scratch files. Resolve aliases/symlinks before composition so a caller
    # cannot silently replace one authenticated producer run with its aggregate.
    output_identity = args.output.resolve()
    if any(output_identity == source.resolve() for source in args.inputs):
        raise ValueError("combined output must not overwrite a sealed source input")

    combined = combine_sealed_run_files(
        args.inputs,
        project_id=args.project_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete verified aggregate. A failed serialization,
    # filesystem write or rename must not truncate a previous sealed result.
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent,
            prefix=f".{args.output.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(combined.to_json())
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, args.output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
