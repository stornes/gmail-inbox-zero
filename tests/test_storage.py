"""Tests for inbox_zero.storage."""

import uuid
from datetime import datetime

import pytest

from inbox_zero.models import (
    ActionLog,
    ActionType,
    Category,
    Correction,
    Sender,
)
from inbox_zero.storage import Storage


@pytest.fixture
def store():
    """Create an in-memory storage instance with schema initialized."""
    s = Storage(db_path=":memory:")
    s.init_schema()
    return s


class TestSchemaInit:
    def test_creates_tables(self, store):
        """Schema init should create all four tables."""
        with store._connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        names = [t["name"] for t in tables]
        assert "senders" in names
        assert "categories" in names
        assert "action_log" in names
        assert "corrections" in names

    def test_idempotent(self, store):
        """Calling init_schema twice should not raise."""
        store.init_schema()


class TestSenderCRUD:
    def test_upsert_and_get(self, store):
        now = datetime(2025, 3, 1, 12, 0, 0)
        sender = Sender(
            email="test@example.com",
            display_name="Test User",
            is_contact=True,
            total_received=10,
            reputation_score=0.8,
            first_seen=now,
        )
        store.upsert_sender(sender)
        result = store.get_sender("test@example.com")

        assert result is not None
        assert result.email == "test@example.com"
        assert result.display_name == "Test User"
        assert result.is_contact is True
        assert result.total_received == 10
        assert result.reputation_score == 0.8

    def test_get_nonexistent(self, store):
        assert store.get_sender("nobody@nowhere.com") is None

    def test_upsert_updates(self, store):
        now = datetime(2025, 3, 1)
        sender = Sender(email="a@b.com", first_seen=now)
        store.upsert_sender(sender)

        sender.display_name = "Updated"
        sender.total_received = 5
        store.upsert_sender(sender)

        result = store.get_sender("a@b.com")
        assert result.display_name == "Updated"
        assert result.total_received == 5

    def test_list_senders(self, store):
        now = datetime(2025, 1, 1)
        store.upsert_sender(Sender(email="a@x.com", first_seen=now))
        store.upsert_sender(Sender(email="b@x.com", first_seen=now))
        senders = store.list_senders()
        assert len(senders) == 2
        emails = {s.email for s in senders}
        assert emails == {"a@x.com", "b@x.com"}


class TestCategoryCRUD:
    def test_upsert_and_get(self, store):
        now = datetime(2025, 3, 1)
        cat = Category(
            id="cat1",
            name="Newsletters",
            description="Email newsletters",
            keywords="newsletter,digest",
            default_action=ActionType.ARCHIVE,
            created_at=now,
        )
        store.upsert_category(cat)
        result = store.get_category("cat1")

        assert result is not None
        assert result.name == "Newsletters"
        assert result.description == "Email newsletters"
        assert result.default_action is ActionType.ARCHIVE

    def test_get_nonexistent(self, store):
        assert store.get_category("nope") is None

    def test_list_categories(self, store):
        now = datetime(2025, 1, 1)
        store.upsert_category(Category(id="c1", name="A", created_at=now))
        store.upsert_category(Category(id="c2", name="B", created_at=now))
        cats = store.list_categories()
        assert len(cats) == 2


class TestActionLogCRUD:
    def test_insert_and_get(self, store):
        now = datetime(2025, 3, 1, 10, 0, 0)
        log = ActionLog(
            id="log1",
            message_id="msg123",
            thread_id="thr1",
            sender_email="from@test.com",
            subject="Hello",
            rule_id="rule1",
            action=ActionType.ARCHIVE,
            confidence=0.9,
            was_dry_run=True,
            timestamp=now,
        )
        store.insert_action_log(log)
        result = store.get_action_log("log1")

        assert result is not None
        assert result.message_id == "msg123"
        assert result.action is ActionType.ARCHIVE
        assert result.was_dry_run is True
        assert result.confidence == 0.9

    def test_get_nonexistent(self, store):
        assert store.get_action_log("nope") is None

    def test_list_by_rule(self, store):
        now = datetime(2025, 1, 1)
        store.insert_action_log(
            ActionLog(id="l1", message_id="m1", rule_id="r1", timestamp=now)
        )
        store.insert_action_log(
            ActionLog(id="l2", message_id="m2", rule_id="r2", timestamp=now)
        )
        store.insert_action_log(
            ActionLog(id="l3", message_id="m3", rule_id="r1", timestamp=now)
        )
        logs = store.list_action_logs(rule_id="r1")
        assert len(logs) == 2
        assert all(l.rule_id == "r1" for l in logs)

    def test_list_with_limit(self, store):
        now = datetime(2025, 1, 1)
        for i in range(5):
            store.insert_action_log(
                ActionLog(id=f"l{i}", message_id=f"m{i}", timestamp=now)
            )
        logs = store.list_action_logs(limit=3)
        assert len(logs) == 3


class TestCorrectionCRUD:
    def _setup_action_log(self, store):
        now = datetime(2025, 1, 1)
        store.insert_action_log(
            ActionLog(id="alog1", message_id="msg1", timestamp=now)
        )

    def test_insert_and_get(self, store):
        self._setup_action_log(store)
        now = datetime(2025, 3, 1)
        corr = Correction(
            id="cor1",
            action_log_id="alog1",
            rule_id="rule1",
            original_action=ActionType.ARCHIVE,
            corrective_action="move_to_inbox",
            detected_at=now,
            applied=False,
        )
        store.insert_correction(corr)
        result = store.get_correction("cor1")

        assert result is not None
        assert result.action_log_id == "alog1"
        assert result.original_action is ActionType.ARCHIVE
        assert result.corrective_action == "move_to_inbox"
        assert result.applied is False

    def test_get_nonexistent(self, store):
        assert store.get_correction("nope") is None

    def test_mark_applied(self, store):
        self._setup_action_log(store)
        now = datetime(2025, 1, 1)
        store.insert_correction(
            Correction(id="c1", action_log_id="alog1", detected_at=now)
        )
        store.mark_correction_applied("c1")
        result = store.get_correction("c1")
        assert result.applied is True

    def test_list_unapplied(self, store):
        self._setup_action_log(store)
        # Need second action log for second correction
        store.insert_action_log(
            ActionLog(
                id="alog2", message_id="msg2", timestamp=datetime(2025, 1, 1)
            )
        )
        now = datetime(2025, 1, 1)
        store.insert_correction(
            Correction(id="c1", action_log_id="alog1", detected_at=now, applied=False)
        )
        store.insert_correction(
            Correction(id="c2", action_log_id="alog2", detected_at=now, applied=True)
        )
        unapplied = store.list_corrections(unapplied_only=True)
        assert len(unapplied) == 1
        assert unapplied[0].id == "c1"

    def test_list_by_rule(self, store):
        self._setup_action_log(store)
        store.insert_action_log(
            ActionLog(
                id="alog2", message_id="msg2", timestamp=datetime(2025, 1, 1)
            )
        )
        now = datetime(2025, 1, 1)
        store.insert_correction(
            Correction(
                id="c1", action_log_id="alog1", rule_id="r1", detected_at=now
            )
        )
        store.insert_correction(
            Correction(
                id="c2", action_log_id="alog2", rule_id="r2", detected_at=now
            )
        )
        results = store.list_corrections(rule_id="r1")
        assert len(results) == 1
        assert results[0].rule_id == "r1"
