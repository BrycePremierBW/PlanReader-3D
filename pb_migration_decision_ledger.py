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


class LedgerTransactionError(RuntimeError):
    """Injected or real failure inside an atomic ledger transaction."""


class MigrationDecisionLedger:
    """Append-only JSONL + SQLite ledger for family routing decisions."""

    def __init__(self, path: Path | str, *, failpoint: Optional[str] = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.path.with_suffix(".jsonl")
        self.failpoint = failpoint
        self._conn = sqlite3.connect(self.path)
        self._conn.isolation_level = None
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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS current_selections (
                family TEXT NOT NULL,
                project_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                semantic_claim TEXT NOT NULL,
                selected_authority TEXT NOT NULL,
                decision_id INTEGER NOT NULL,
                PRIMARY KEY (family, project_id, revision_id, semantic_claim)
            )
            """
        )

    def close(self) -> None:
        self._conn.close()

    def _maybe_fail(self, name: str) -> None:
        if self.failpoint == name:
            raise LedgerTransactionError(f"injected ledger failure at {name}")

    def append(self, record: MigrationDecisionRecord) -> int:
        """Atomically write audit + current selection + family state, then JSONL."""
        payload = record.to_dict()
        try:
            self._conn.execute("BEGIN")
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
            decision_id = int(cur.lastrowid)
            self._maybe_fail("after_audit_before_state")
            self._conn.execute(
                """
                INSERT INTO family_state (family, current_state, updated_at, last_decision_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(family) DO UPDATE SET
                    current_state=excluded.current_state,
                    updated_at=excluded.updated_at,
                    last_decision_id=excluded.last_decision_id
                """,
                (record.family, record.current_state, record.decided_at, decision_id),
            )
            self._maybe_fail("after_state_before_selection")
            if record.semantic_claim and record.semantic_claim != "*":
                existing = self.selected_authority_count(
                    record.family,
                    record.project_id,
                    record.revision_id,
                    record.semantic_claim,
                )
                if existing > 1:
                    raise LedgerTransactionError("current selection already violated exactly-one invariant")
                self._conn.execute(
                    """
                    INSERT INTO current_selections (
                        family, project_id, revision_id, semantic_claim,
                        selected_authority, decision_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(family, project_id, revision_id, semantic_claim) DO UPDATE SET
                        selected_authority=excluded.selected_authority,
                        decision_id=excluded.decision_id
                    """,
                    (
                        record.family,
                        record.project_id,
                        record.revision_id,
                        record.semantic_claim,
                        record.selected_authority,
                        decision_id,
                    ),
                )
            self._maybe_fail("after_selection_before_commit")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return decision_id

    def selected_authority_count(
        self,
        family: str,
        project_id: str,
        revision_id: str,
        semantic_claim: str,
    ) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM current_selections
            WHERE family = ? AND project_id = ? AND revision_id = ? AND semantic_claim = ?
            """,
            (family, project_id, revision_id, semantic_claim),
        ).fetchone()
        return int(row["n"] if row else 0)

    def current_selected_authority(
        self,
        family: str,
        project_id: str,
        revision_id: str,
        semantic_claim: str,
    ) -> Optional[str]:
        row = self._conn.execute(
            """
            SELECT selected_authority FROM current_selections
            WHERE family = ? AND project_id = ? AND revision_id = ? AND semantic_claim = ?
            """,
            (family, project_id, revision_id, semantic_claim),
        ).fetchone()
        return str(row["selected_authority"]) if row else None

    def force_second_selection(
        self,
        family: str,
        project_id: str,
        revision_id: str,
        semantic_claim: str,
        selected_authority: str,
    ) -> None:
        """Test helper: attempt to insert a second live selection without replacing."""
        self._conn.execute(
            """
            INSERT INTO current_selections (
                family, project_id, revision_id, semantic_claim,
                selected_authority, decision_id
            ) VALUES (?, ?, ?, ?, ?, -1)
            """,
            (family, project_id, revision_id, semantic_claim, selected_authority),
        )
        self._conn.commit()

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
