"""SQLite storage manager for gmail-inbox-zero."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import DB_PATH
from .models import (
    ActionLog,
    ActionType,
    Category,
    Correction,
    Sender,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS senders (
    email           TEXT PRIMARY KEY,
    display_name    TEXT DEFAULT '',
    is_contact      INTEGER DEFAULT 0,
    total_received  INTEGER DEFAULT 0,
    total_archived  INTEGER DEFAULT 0,
    total_deleted   INTEGER DEFAULT 0,
    total_kept      INTEGER DEFAULT 0,
    reputation_score REAL DEFAULT 0.5,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT,
    categories      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS categories (
    id              TEXT PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT DEFAULT '',
    keywords        TEXT DEFAULT '',
    default_action  TEXT DEFAULT 'archive',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL,
    thread_id       TEXT DEFAULT '',
    sender_email    TEXT DEFAULT '',
    subject         TEXT DEFAULT '',
    rule_id         TEXT,
    action          TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    was_dry_run     INTEGER DEFAULT 0,
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_log_message ON action_log(message_id);
CREATE INDEX IF NOT EXISTS idx_action_log_rule ON action_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_action_log_timestamp ON action_log(timestamp);

CREATE TABLE IF NOT EXISTS corrections (
    id              TEXT PRIMARY KEY,
    action_log_id   TEXT NOT NULL,
    rule_id         TEXT,
    original_action TEXT NOT NULL,
    corrective_action TEXT NOT NULL,
    detected_at     TEXT NOT NULL,
    applied         INTEGER DEFAULT 0,
    FOREIGN KEY (action_log_id) REFERENCES action_log(id)
);
CREATE INDEX IF NOT EXISTS idx_corrections_rule ON corrections(rule_id);
"""


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-format datetime string, returning None for empty/None."""
    if not value:
        return None
    return datetime.fromisoformat(value)


class Storage:
    """SQLite storage backend for inbox-zero data."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path) if db_path else str(DB_PATH)
        self._persistent_conn: Optional[sqlite3.Connection] = None
        # For in-memory databases, keep a single connection alive
        if self.db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def _connect(self):
        if self._persistent_conn is not None:
            try:
                yield self._persistent_conn
                self._persistent_conn.commit()
            except Exception:
                self._persistent_conn.rollback()
                raise
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init_schema(self):
        """Create all tables and indexes."""
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    # -- Senders --

    def upsert_sender(self, sender: Sender) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO senders
                   (email, display_name, is_contact, total_received,
                    total_archived, total_deleted, total_kept,
                    reputation_score, first_seen, last_seen, categories)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(email) DO UPDATE SET
                    display_name=excluded.display_name,
                    is_contact=excluded.is_contact,
                    total_received=excluded.total_received,
                    total_archived=excluded.total_archived,
                    total_deleted=excluded.total_deleted,
                    total_kept=excluded.total_kept,
                    reputation_score=excluded.reputation_score,
                    last_seen=excluded.last_seen,
                    categories=excluded.categories
                """,
                (
                    sender.email,
                    sender.display_name,
                    int(sender.is_contact),
                    sender.total_received,
                    sender.total_archived,
                    sender.total_deleted,
                    sender.total_kept,
                    sender.reputation_score,
                    sender.first_seen.isoformat(),
                    sender.last_seen.isoformat() if sender.last_seen else None,
                    sender.categories,
                ),
            )

    def get_sender(self, email: str) -> Optional[Sender]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM senders WHERE email = ?", (email,)
            ).fetchone()
        if not row:
            return None
        return Sender(
            email=row["email"],
            display_name=row["display_name"],
            is_contact=bool(row["is_contact"]),
            total_received=row["total_received"],
            total_archived=row["total_archived"],
            total_deleted=row["total_deleted"],
            total_kept=row["total_kept"],
            reputation_score=row["reputation_score"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=_parse_datetime(row["last_seen"]),
            categories=row["categories"],
        )

    def list_senders(self) -> list[Sender]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM senders").fetchall()
        return [
            Sender(
                email=r["email"],
                display_name=r["display_name"],
                is_contact=bool(r["is_contact"]),
                total_received=r["total_received"],
                total_archived=r["total_archived"],
                total_deleted=r["total_deleted"],
                total_kept=r["total_kept"],
                reputation_score=r["reputation_score"],
                first_seen=datetime.fromisoformat(r["first_seen"]),
                last_seen=_parse_datetime(r["last_seen"]),
                categories=r["categories"],
            )
            for r in rows
        ]

    # -- Categories --

    def upsert_category(self, cat: Category) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO categories
                   (id, name, description, keywords, default_action, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    keywords=excluded.keywords,
                    default_action=excluded.default_action
                """,
                (
                    cat.id,
                    cat.name,
                    cat.description,
                    cat.keywords,
                    cat.default_action.value,
                    cat.created_at.isoformat(),
                ),
            )

    def get_category(self, cat_id: str) -> Optional[Category]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM categories WHERE id = ?", (cat_id,)
            ).fetchone()
        if not row:
            return None
        return Category(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            keywords=row["keywords"],
            default_action=ActionType(row["default_action"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_categories(self) -> list[Category]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM categories").fetchall()
        return [
            Category(
                id=r["id"],
                name=r["name"],
                description=r["description"],
                keywords=r["keywords"],
                default_action=ActionType(r["default_action"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # -- Action Log --

    def insert_action_log(self, log: ActionLog) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO action_log
                   (id, message_id, thread_id, sender_email, subject,
                    rule_id, action, confidence, was_dry_run, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.id,
                    log.message_id,
                    log.thread_id,
                    log.sender_email,
                    log.subject,
                    log.rule_id,
                    log.action.value,
                    log.confidence,
                    int(log.was_dry_run),
                    log.timestamp.isoformat(),
                ),
            )

    def get_action_log(self, log_id: str) -> Optional[ActionLog]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM action_log WHERE id = ?", (log_id,)
            ).fetchone()
        if not row:
            return None
        return ActionLog(
            id=row["id"],
            message_id=row["message_id"],
            thread_id=row["thread_id"],
            sender_email=row["sender_email"],
            subject=row["subject"],
            rule_id=row["rule_id"],
            action=ActionType(row["action"]),
            confidence=row["confidence"],
            was_dry_run=bool(row["was_dry_run"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    def list_action_logs(
        self, rule_id: Optional[str] = None, limit: int = 100
    ) -> list[ActionLog]:
        with self._connect() as conn:
            if rule_id:
                rows = conn.execute(
                    "SELECT * FROM action_log WHERE rule_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (rule_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM action_log ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            ActionLog(
                id=r["id"],
                message_id=r["message_id"],
                thread_id=r["thread_id"],
                sender_email=r["sender_email"],
                subject=r["subject"],
                rule_id=r["rule_id"],
                action=ActionType(r["action"]),
                confidence=r["confidence"],
                was_dry_run=bool(r["was_dry_run"]),
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]

    # -- Corrections --

    def insert_correction(self, correction: Correction) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO corrections
                   (id, action_log_id, rule_id, original_action,
                    corrective_action, detected_at, applied)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correction.id,
                    correction.action_log_id,
                    correction.rule_id,
                    correction.original_action.value,
                    correction.corrective_action,
                    correction.detected_at.isoformat(),
                    int(correction.applied),
                ),
            )

    def get_correction(self, correction_id: str) -> Optional[Correction]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM corrections WHERE id = ?", (correction_id,)
            ).fetchone()
        if not row:
            return None
        return Correction(
            id=row["id"],
            action_log_id=row["action_log_id"],
            rule_id=row["rule_id"],
            original_action=ActionType(row["original_action"]),
            corrective_action=row["corrective_action"],
            detected_at=datetime.fromisoformat(row["detected_at"]),
            applied=bool(row["applied"]),
        )

    def list_corrections(
        self, rule_id: Optional[str] = None, unapplied_only: bool = False
    ) -> list[Correction]:
        with self._connect() as conn:
            query = "SELECT * FROM corrections"
            params: list = []
            conditions = []
            if rule_id:
                conditions.append("rule_id = ?")
                params.append(rule_id)
            if unapplied_only:
                conditions.append("applied = 0")
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY detected_at DESC"
            rows = conn.execute(query, params).fetchall()
        return [
            Correction(
                id=r["id"],
                action_log_id=r["action_log_id"],
                rule_id=r["rule_id"],
                original_action=ActionType(r["original_action"]),
                corrective_action=r["corrective_action"],
                detected_at=datetime.fromisoformat(r["detected_at"]),
                applied=bool(r["applied"]),
            )
            for r in rows
        ]

    def mark_correction_applied(self, correction_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE corrections SET applied = 1 WHERE id = ?",
                (correction_id,),
            )
