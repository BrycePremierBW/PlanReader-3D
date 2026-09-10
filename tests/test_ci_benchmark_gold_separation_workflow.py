from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_gold_separation_runs_for_pull_requests_and_pushes() -> None:
    assert "Enforce benchmark-gold / production-code separation (pull request)" in WORKFLOW
    assert "if: github.event_name == 'pull_request'" in WORKFLOW
    assert "${{ github.event.pull_request.base.sha }}" in WORKFLOW
    assert "${{ github.event.pull_request.head.sha }}" in WORKFLOW

    assert "Enforce benchmark-gold / production-code separation (push)" in WORKFLOW
    assert "if: github.event_name == 'push'" in WORKFLOW
    assert "${{ github.event.before }}" in WORKFLOW
    assert "${{ github.event.after }}" in WORKFLOW


def test_push_gold_separation_fails_closed_on_invalid_range() -> None:
    assert 'ZERO_SHA="0000000000000000000000000000000000000000"' in WORKFLOW
    assert 'if [ -z "$BASE_SHA" ] || [ -z "$HEAD_SHA" ]' in WORKFLOW
    assert 'git cat-file -e "${BASE_SHA}^{commit}"' in WORKFLOW
    assert 'git cat-file -e "${HEAD_SHA}^{commit}"' in WORKFLOW


def test_both_event_paths_call_the_same_checker() -> None:
    command = 'git diff --name-only "$BASE_SHA" "$HEAD_SHA" | python scripts/check_benchmark_gold_separation.py'
    assert WORKFLOW.count(command) == 2
