"""Tests for the rule evaluation engine."""

import pytest

from inbox_zero.engine import ActionSummary, EvaluationResult, RuleEngine, RuleMatch
from inbox_zero.models import ActionType, Rule, RuleSource


def _make_rule(
    *,
    name: str = "test-rule",
    query: str = "from:test@example.com",
    action: ActionType = ActionType.ARCHIVE,
    confidence: float = 1.0,
    priority: int = 0,
    enabled: bool = True,
    rule_id: str | None = None,
) -> Rule:
    return Rule(
        id=rule_id or f"rule-{name}",
        name=name,
        query=query,
        action=action,
        confidence=confidence,
        priority=priority,
        enabled=enabled,
    )


def _make_msg(msg_id: str, thread_id: str = "t1") -> dict:
    return {"id": msg_id, "threadId": thread_id, "sender_email": "", "subject": ""}


class TestRuleSorting:
    """Rules should be evaluated in priority order (highest first)."""

    def test_rules_sorted_by_priority(self):
        low = _make_rule(name="low", priority=1, query="q-low")
        high = _make_rule(name="high", priority=10, query="q-high")

        call_order = []

        def search_fn(query: str) -> list[dict]:
            call_order.append(query)
            return []

        engine = RuleEngine(rules=[low, high], gmail_search_fn=search_fn)
        engine.evaluate()

        # High priority rule should be searched first
        assert call_order == ["q-high", "q-low"]


class TestKeepAlwaysWins:
    """KEEP action should override DELETE and ARCHIVE regardless of priority."""

    def test_keep_beats_delete(self):
        delete_rule = _make_rule(
            name="delete", action=ActionType.DELETE, priority=10, confidence=1.0
        )
        keep_rule = _make_rule(
            name="keep", action=ActionType.KEEP, priority=1, confidence=1.0
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[delete_rule, keep_rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 1
        assert result.auto_actions[0].resolved_action == ActionType.KEEP
        assert result.auto_actions[0].rule.name == "keep"

    def test_keep_beats_archive(self):
        archive_rule = _make_rule(
            name="archive", action=ActionType.ARCHIVE, priority=10, confidence=1.0
        )
        keep_rule = _make_rule(
            name="keep", action=ActionType.KEEP, priority=1, confidence=1.0
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[archive_rule, keep_rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 1
        assert result.auto_actions[0].resolved_action == ActionType.KEEP


class TestHighestPriorityWins:
    """When multiple non-KEEP rules match, highest priority wins."""

    def test_higher_priority_wins(self):
        low = _make_rule(
            name="low", action=ActionType.ARCHIVE, priority=1, confidence=1.0
        )
        high = _make_rule(
            name="high", action=ActionType.DELETE, priority=10, confidence=1.0
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[low, high], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 1
        assert result.auto_actions[0].resolved_action == ActionType.DELETE
        assert result.auto_actions[0].rule.name == "high"


class TestConfidenceTiebreaker:
    """When priorities are equal, highest confidence wins."""

    def test_confidence_breaks_tie(self):
        low_conf = _make_rule(
            name="low-conf",
            action=ActionType.ARCHIVE,
            priority=5,
            confidence=0.8,
        )
        high_conf = _make_rule(
            name="high-conf",
            action=ActionType.DELETE,
            priority=5,
            confidence=0.95,
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[low_conf, high_conf], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 1
        assert result.auto_actions[0].rule.name == "high-conf"
        assert result.auto_actions[0].resolved_action == ActionType.DELETE


class TestFlagReviewDowngrade:
    """Confidence below AUTO_ACT_THRESHOLD (0.7) should be flagged for review."""

    def test_flag_review_when_below_threshold(self):
        rule = _make_rule(
            name="uncertain", action=ActionType.ARCHIVE, confidence=0.5, priority=5
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 0
        assert len(result.flagged_for_review) == 1
        assert result.flagged_for_review[0].resolved_action == ActionType.FLAG_REVIEW
        assert result.summary.flagged == 1

    def test_exactly_at_threshold_is_auto(self):
        rule = _make_rule(
            name="borderline", action=ActionType.ARCHIVE, confidence=0.7, priority=5
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 1
        assert len(result.flagged_for_review) == 0


class TestSkipLowConfidence:
    """Confidence below REVIEW_THRESHOLD (0.4) should be skipped entirely."""

    def test_skip_when_below_review_threshold(self):
        rule = _make_rule(
            name="low", action=ActionType.ARCHIVE, confidence=0.3, priority=5
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 0
        assert len(result.flagged_for_review) == 0
        assert len(result.skipped) == 1

    def test_exactly_at_review_threshold_is_flagged(self):
        rule = _make_rule(
            name="borderline", action=ActionType.ARCHIVE, confidence=0.4, priority=5
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.flagged_for_review) == 1
        assert len(result.skipped) == 0


class TestDeduplication:
    """A message matched by multiple rules should only appear once in results."""

    def test_message_appears_once(self):
        rule_a = _make_rule(
            name="rule-a",
            query="q-a",
            action=ActionType.ARCHIVE,
            priority=10,
            confidence=1.0,
        )
        rule_b = _make_rule(
            name="rule-b",
            query="q-b",
            action=ActionType.DELETE,
            priority=5,
            confidence=1.0,
        )

        msg = _make_msg("m1")

        def search_fn(query: str) -> list[dict]:
            return [msg]

        engine = RuleEngine(rules=[rule_a, rule_b], gmail_search_fn=search_fn)
        result = engine.evaluate()

        # Message should only appear once total across all categories
        total = (
            len(result.auto_actions)
            + len(result.flagged_for_review)
            + len(result.skipped)
        )
        assert total == 1
        # Higher priority rule wins
        assert result.auto_actions[0].rule.name == "rule-a"

    def test_multiple_messages_each_resolved_once(self):
        rule_a = _make_rule(
            name="rule-a", query="q-a", action=ActionType.ARCHIVE, priority=10
        )
        rule_b = _make_rule(
            name="rule-b", query="q-b", action=ActionType.DELETE, priority=5
        )

        msg1 = _make_msg("m1")
        msg2 = _make_msg("m2")

        def search_fn(query: str) -> list[dict]:
            if query == "q-a":
                return [msg1, msg2]
            return [msg1]  # rule_b also matches m1

        engine = RuleEngine(rules=[rule_a, rule_b], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert len(result.auto_actions) == 2
        msg_ids = {m.message_id for m in result.auto_actions}
        assert msg_ids == {"m1", "m2"}


class TestEmptyRules:
    """Engine should handle empty rule lists gracefully."""

    def test_empty_rules(self):
        def search_fn(query: str) -> list[dict]:
            return []

        engine = RuleEngine(rules=[], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert result.auto_actions == []
        assert result.flagged_for_review == []
        assert result.skipped == []
        assert result.summary == ActionSummary()


class TestNoMatchesFound:
    """Engine should handle rules that match no messages."""

    def test_no_matches(self):
        rule = _make_rule(name="no-hits", action=ActionType.DELETE, priority=10)

        def search_fn(query: str) -> list[dict]:
            return []

        engine = RuleEngine(rules=[rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert result.auto_actions == []
        assert result.flagged_for_review == []
        assert result.skipped == []


class TestDisabledRulesIgnored:
    """Disabled rules should not be evaluated."""

    def test_disabled_rule_skipped(self):
        rule = _make_rule(
            name="disabled", action=ActionType.DELETE, priority=10, enabled=False
        )

        called = False

        def search_fn(query: str) -> list[dict]:
            nonlocal called
            called = True
            return [_make_msg("m1")]

        engine = RuleEngine(rules=[rule], gmail_search_fn=search_fn)
        result = engine.evaluate()

        assert not called
        assert result.auto_actions == []


class TestActionSummary:
    """Summary should correctly count actions by type."""

    def test_summary_counts(self):
        archive_rule = _make_rule(
            name="archive", query="q-archive", action=ActionType.ARCHIVE, priority=5
        )
        delete_rule = _make_rule(
            name="delete", query="q-delete", action=ActionType.DELETE, priority=5
        )
        label_rule = _make_rule(
            name="label", query="q-label", action=ActionType.LABEL, priority=5
        )
        keep_rule = _make_rule(
            name="keep", query="q-keep", action=ActionType.KEEP, priority=5
        )

        def search_fn(query: str) -> list[dict]:
            if query == "q-archive":
                return [_make_msg("m1")]
            elif query == "q-delete":
                return [_make_msg("m2")]
            elif query == "q-label":
                return [_make_msg("m3")]
            elif query == "q-keep":
                return [_make_msg("m4")]
            return []

        engine = RuleEngine(
            rules=[archive_rule, delete_rule, label_rule, keep_rule],
            gmail_search_fn=search_fn,
        )
        result = engine.evaluate()

        assert result.summary.archived == 1
        assert result.summary.deleted == 1
        assert result.summary.labeled == 1
        assert result.summary.kept == 1
        assert result.summary.flagged == 0
