"""Append-only migration decision ledger (JSONL + SQLite).

Does not add a graph database.  Historical rows are inserted, never updated.
Rollback writes a new decision; it does not rewrite prior rows or estimator-
approved commercial takeoff rows.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional

from pb_migration_contracts import MigrationAuthorityState, canonical_contract_json
from pb_migration_provider_envelope import fingerprint_payload


LEDGER_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class MigrationDecisionRecord:
    family: str
    provider_id: str
    provider_version: str
    provider_fingerprint: str
    prior_state: str
    current_state: str
    project_id: str
    revision_id: str
    semantic_claim: str
    selected_authority: str
    fallback_reason: str
    blocker: str
    decided_at: str
    code_commit: str
    run_id: str
    extra: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = LEDGER_SCHEMA_VERSION
        return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_commit_sha(repo_root: Optional[Path] = None) -> str:
    head = (repo_root or Path(".")).joinpath(".git/HEAD")
    if not head.is_file():
        return "unknown"
    ref = head.read_text(encoding="utf-8").strip()
    if ref.startswith("ref:"):
        target = (repo_root or Path(".")).joinpath(".git", ref.split(" ", 1)[1])
        if target.is_file():
            return target.read_text(encoding="utf-8").strip()
        return ref
    return ref


class MigrationDecisionLedger:
    """Append-only JSONL + SQLite ledger for family routing decisions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.path.with_suffix(".jsonl")
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                prior_state TEXT NOT NULL,
                current_state TEXT NOT NULL,
                project_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                semantic_claim TEXT NOT NULL,
                selected_authority TEXT NOT NULL,
                fallback_reason TEXT NOT NULL,
                blocker TEXT NOT NULL,
                decided_at TEXT NOT NULL,
                code_commit TEXT NOT NULL,
                run_id TEXT NOT NULL,
                extra_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS family_state (
                family TEXT PRIMARY KEY,
                current_state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_decision_id INTEGER
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def append(self, record: MigrationDecisionRecord) -> int:
        payload = record.to_dict()
        cur = self._conn.execute(
            """
            INSERT INTO migration_decisions (
                family, provider_id, provider_version, provider_fingerprint,
                prior_state, current_state, project_id, revision_id, semantic_claim,
                selected_authority, fallback_reason, blocker, decided_at, code_commit,
                run_id, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.family,
                record.provider_id,
                record.provider_version,
                record.provider_fingerprint,
                record.prior_state,
                record.current_state,
                record.project_id,
                record.revision_id,
                record.semantic_claim,
                record.selected_authority,
                record.fallback_reason,
                record.blocker,
                record.decided_at,
                record.code_commit,
                record.run_id,
                canonical_contract_json(record.extra),
            ),
        )
        self._conn.execute(
            """
            INSERT INTO family_state (family, current_state, updated_at, last_decision_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(family) DO UPDATE SET
                current_state=excluded.current_state,
                updated_at=excluded.updated_at,
                last_decision_id=excluded.last_decision_id
            """,
            (record.family, record.current_state, record.decided_at, cur.lastrowid),
        )
        self._conn.commit()
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return int(cur.lastrowid)

    def family_state(self, family: str, default: str = MigrationAuthorityState.NEW_SHADOW.value) -> str:
        row = self._conn.execute(
            "SELECT current_state FROM family_state WHERE family = ?",
            (family,),
        ).fetchone()
        return str(row["current_state"]) if row else default

    def history(self, family: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM migration_decisions WHERE family = ? ORDER BY id ASC",
            (family,),
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_for_claim(self, family: str, semantic_claim: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            """
            SELECT * FROM migration_decisions
            WHERE family = ? AND semantic_claim = ?
            ORDER BY id DESC LIMIT 1
            """,
            (family, semantic_claim),
        ).fetchone()
        return dict(row) if row else None


def record_state_transition(
    ledger: MigrationDecisionLedger,
    *,
    family: str,
    provider_id: str,
    provider_version: str,
    provider_fingerprint: str,
    prior_state: str,
    current_state: str,
    project_id: str,
    revision_id: str = "",
    semantic_claim: str = "*",
    selected_authority: str,
    fallback_reason: str = "",
    blocker: str = "",
    run_id: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> MigrationDecisionRecord:
    record = MigrationDecisionRecord(
        family=family,
        provider_id=provider_id,
        provider_version=provider_version,
        provider_fingerprint=provider_fingerprint,
        prior_state=prior_state,
        current_state=current_state,
        project_id=project_id,
        revision_id=revision_id,
        semantic_claim=semantic_claim,
        selected_authority=selected_authority,
        fallback_reason=fallback_reason,
        blocker=blocker,
        decided_at=utc_now(),
        code_commit=current_commit_sha(),
        run_id=run_id or fingerprint_payload({"family": family, "ts": utc_now()}),
        extra=dict(extra or {}),
    )
    ledger.append(record)
    return record
