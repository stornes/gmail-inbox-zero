"""Tests for inbox_zero.models."""

from datetime import datetime

from inbox_zero.models import (
    ActionLog,
    ActionType,
    Category,
    Correction,
    Rule,
    RuleSource,
    Sender,
)


class TestActionType:
    def test_values(self):
        assert ActionType.ARCHIVE.value == "archive"
        assert ActionType.DELETE.value == "delete"
        assert ActionType.LABEL.value == "label"
        assert ActionType.KEEP.value == "keep"
        assert ActionType.FLAG_REVIEW.value == "flag_review"

    def test_from_value(self):
        assert ActionType("archive") is ActionType.ARCHIVE
        assert ActionType("delete") is ActionType.DELETE

    def test_all_members(self):
        assert len(ActionType) == 5


class TestRuleSource:
    def test_values(self):
        assert RuleSource.MANUAL.value == "manual"
        assert RuleSource.LEARNED.value == "learned"
        assert RuleSource.SYSTEM.value == "system"

    def test_all_members(self):
        assert len(RuleSource) == 3


class TestRule:
    def test_required_fields(self):
        r = Rule(id="r1", name="test", query="in:inbox", action=ActionType.ARCHIVE)
        assert r.id == "r1"
        assert r.name == "test"
        assert r.query == "in:inbox"
        assert r.action is ActionType.ARCHIVE

    def test_defaults(self):
        r = Rule(id="r1", name="test", query="q", action=ActionType.DELETE)
        assert r.label_name is None
        assert r.confidence == 1.0
        assert r.source is RuleSource.MANUAL
        assert r.enabled is True
        assert r.priority == 0
        assert r.hit_count == 0
        assert r.miss_count == 0
        assert r.last_matched is None
        assert isinstance(r.created_at, datetime)
        assert r.notes == ""

    def test_custom_values(self):
        now = datetime(2025, 1, 1)
        r = Rule(
            id="r2",
            name="custom",
            query="from:test@",
            action=ActionType.LABEL,
            label_name="Important",
            confidence=0.8,
            source=RuleSource.LEARNED,
            enabled=False,
            priority=10,
            hit_count=5,
            miss_count=2,
            last_matched=now,
            created_at=now,
            notes="test note",
        )
        assert r.label_name == "Important"
        assert r.confidence == 0.8
        assert r.source is RuleSource.LEARNED
        assert r.enabled is False
        assert r.priority == 10
        assert r.hit_count == 5
        assert r.miss_count == 2
        assert r.last_matched == now
        assert r.created_at == now
        assert r.notes == "test note"


class TestSender:
    def test_required_fields(self):
        s = Sender(email="test@example.com")
        assert s.email == "test@example.com"

    def test_defaults(self):
        s = Sender(email="x@y.com")
        assert s.display_name == ""
        assert s.is_contact is False
        assert s.total_received == 0
        assert s.total_archived == 0
        assert s.total_deleted == 0
        assert s.total_kept == 0
        assert s.reputation_score == 0.5
        assert isinstance(s.first_seen, datetime)
        assert s.last_seen is None
        assert s.categories == ""


class TestCategory:
    def test_required_fields(self):
        c = Category(id="c1", name="Newsletters")
        assert c.id == "c1"
        assert c.name == "Newsletters"

    def test_defaults(self):
        c = Category(id="c1", name="Test")
        assert c.description == ""
        assert c.keywords == ""
        assert c.default_action is ActionType.ARCHIVE
        assert isinstance(c.created_at, datetime)


class TestActionLog:
    def test_required_fields(self):
        a = ActionLog(id="a1", message_id="msg1")
        assert a.id == "a1"
        assert a.message_id == "msg1"

    def test_defaults(self):
        a = ActionLog(id="a1", message_id="msg1")
        assert a.thread_id == ""
        assert a.sender_email == ""
        assert a.subject == ""
        assert a.rule_id is None
        assert a.action is ActionType.ARCHIVE
        assert a.confidence == 1.0
        assert a.was_dry_run is False
        assert isinstance(a.timestamp, datetime)


class TestCorrection:
    def test_required_fields(self):
        c = Correction(id="c1", action_log_id="a1")
        assert c.id == "c1"
        assert c.action_log_id == "a1"

    def test_defaults(self):
        c = Correction(id="c1", action_log_id="a1")
        assert c.rule_id is None
        assert c.original_action is ActionType.ARCHIVE
        assert c.corrective_action == ""
        assert isinstance(c.detected_at, datetime)
        assert c.applied is False
