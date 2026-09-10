#!/usr/bin/env python3
"""Extract opening counts from a staged production-only workspace.

Gold/eval files are not copied into the stage.  Relative gold paths therefore
fail with FileNotFoundError because they are absent — not because a hook
denied them.  This script does not put the developer checkout on PYTHONPATH.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pb_provider_runtime_isolation import (
    assert_staged_workspace_has_no_gold_resources,
    run_staged_provider_extract,
    stage_production_provider_workspace,
)


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: run_isolated_opening_count_extract.py PDF OUT.json [STAGE_DIR]",
            file=sys.stderr,
        )
        return 2
    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2])
    if len(sys.argv) > 3:
        stage_dir = Path(sys.argv[3])
    else:
        stage_dir = Path(tempfile.mkdtemp(prefix="planreader-provider-stage-"))
    workspace = stage_production_provider_workspace(stage_dir, pdf)
    assert_staged_workspace_has_no_gold_resources(workspace)
    run_staged_provider_extract(workspace, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("isolated extract did not write a quantity list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
