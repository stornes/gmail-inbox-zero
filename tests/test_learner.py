"""Tests for inbox_zero.learner module."""

import pytest

from inbox_zero.config import (
    CONFIDENCE_BOOST_PER_HIT,
    CONFIDENCE_DECAY_PER_CORRECTION,
    MIN_CONFIDENCE_BEFORE_DISABLE,
    PROPOSAL_MIN_OCCURRENCES,
)
from inbox_zero.learner import (
    boost_confidence,
    compute_reputation,
    decay_confidence,
    propose_rules,
    should_disable,
)
from inbox_zero.models import ActionType, Rule, RuleSource, Sender


# -- compute_reputation --


class TestComputeReputation:
    def test_contact_gets_higher_base(self):
        """Contacts start with base 0.8 vs 0.5 for non-contacts."""
        contact = Sender(email="a@b.com", is_contact=True, total_received=0)
        non_contact = Sender(email="c@d.com", is_contact=False, total_received=0)
        assert compute_reputation(contact) > compute_reputation(non_contact)

    def test_non_contact_default(self):
        """Non-contact with no history should have reputation 0.5."""
        sender = Sender(email="a@b.com", total_received=0)
        assert compute_reputation(sender) == 0.5

    def test_contact_default(self):
        """Contact with no history should have reputation 0.8."""
        sender = Sender(email="a@b.com", is_contact=True, total_received=0)
        assert compute_reputation(sender) == 0.8

    def test_all_kept_non_contact(self):
        """Non-contact where all messages are kept: 0.5 + (10/10)*0.4 = 0.9."""
        sender = Sender(
            email="a@b.com",
            total_received=10,
            total_kept=10,
            total_deleted=0,
        )
        assert compute_reputation(sender) == pytest.approx(0.9)

    def test_all_deleted_non_contact(self):
        """Non-contact where all messages are deleted: 0.5 + (-10/10)*0.4 = 0.1."""
        sender = Sender(
            email="a@b.com",
            total_received=10,
            total_kept=0,
            total_deleted=10,
        )
        assert compute_reputation(sender) == pytest.approx(0.1)

    def test_mixed_ratio(self):
        """Non-contact: 7 kept, 3 deleted out of 10: 0.5 + (4/10)*0.4 = 0.66."""
        sender = Sender(
            email="a@b.com",
            total_received=10,
            total_kept=7,
            total_deleted=3,
        )
        assert compute_reputation(sender) == pytest.approx(0.66)

    def test_clamped_to_zero(self):
        """Reputation should not go below 0.0."""
        sender = Sender(
            email="a@b.com",
            total_received=10,
            total_kept=0,
            total_deleted=100,
        )
        assert compute_reputation(sender) == 0.0

    def test_clamped_to_one(self):
        """Contact with extremely favorable ratio should cap at 1.0."""
        sender = Sender(
            email="a@b.com",
            is_contact=True,
            total_received=10,
            total_kept=100,
            total_deleted=0,
        )
        assert compute_reputation(sender) == 1.0


# -- decay_confidence --


class TestDecayConfidence:
    def test_single_decay(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=1.0)
        decay_confidence(rule)
        assert rule.confidence == pytest.approx(1.0 - CONFIDENCE_DECAY_PER_CORRECTION)
        assert rule.miss_count == 1

    def test_multiple_decays(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=1.0)
        for _ in range(4):
            decay_confidence(rule)
        expected = max(1.0 - 4 * CONFIDENCE_DECAY_PER_CORRECTION, 0.0)
        assert rule.confidence == pytest.approx(expected)
        assert rule.miss_count == 4

    def test_decay_does_not_go_below_zero(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=0.1)
        decay_confidence(rule)
        assert rule.confidence >= 0.0


# -- boost_confidence --


class TestBoostConfidence:
    def test_single_boost(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=0.5)
        boost_confidence(rule)
        assert rule.confidence == pytest.approx(0.5 + CONFIDENCE_BOOST_PER_HIT)

    def test_boost_capped_at_one(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=0.999)
        boost_confidence(rule)
        assert rule.confidence == 1.0


# -- should_disable --


class TestShouldDisable:
    def test_below_threshold(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=0.1)
        assert should_disable(rule) is True

    def test_at_threshold(self):
        """At exactly the threshold, should NOT disable (< not <=)."""
        rule = Rule(
            id="1", name="r", query="q", action=ActionType.ARCHIVE,
            confidence=MIN_CONFIDENCE_BEFORE_DISABLE,
        )
        assert should_disable(rule) is False

    def test_above_threshold(self):
        rule = Rule(id="1", name="r", query="q", action=ActionType.ARCHIVE, confidence=0.5)
        assert should_disable(rule) is False


# -- propose_rules --


class TestProposeRules:
    def test_delete_for_low_reputation(self):
        """Sender with 5+ messages and reputation < 0.25 should get DELETE proposal."""
        sender = Sender(
            email="spam@bad.com",
            total_received=10,
            total_kept=0,
            total_deleted=10,
        )
        proposals = propose_rules([sender])
        assert len(proposals) == 1
        assert proposals[0].action == ActionType.DELETE
        assert proposals[0].enabled is False
        assert proposals[0].confidence == 0.5
        assert proposals[0].source == RuleSource.LEARNED
        assert "spam@bad.com" in proposals[0].query

    def test_keep_for_high_reputation(self):
        """Sender with reputation > 0.85 should get KEEP proposal."""
        sender = Sender(
            email="friend@good.com",
            total_received=10,
            total_kept=10,
            total_deleted=0,
        )
        proposals = propose_rules([sender])
        assert len(proposals) == 1
        assert proposals[0].action == ActionType.KEEP

    def test_skip_low_message_count(self):
        """Senders with < 5 messages should not get DELETE proposals."""
        sender = Sender(
            email="spam@bad.com",
            total_received=4,
            total_kept=0,
            total_deleted=4,
        )
        proposals = propose_rules([sender])
        # reputation is 0.5 + (-4/4)*0.4 = 0.1, but total_received < 5
        assert len(proposals) == 0

    def test_mid_reputation_no_proposal(self):
        """Sender with middling reputation gets no proposal."""
        sender = Sender(
            email="meh@mid.com",
            total_received=10,
            total_kept=5,
            total_deleted=5,
        )
        proposals = propose_rules([sender])
        assert len(proposals) == 0

    def test_keep_proposal_no_min_messages(self):
        """KEEP proposals do not require minimum message count."""
        sender = Sender(
            email="vip@co.com",
            is_contact=True,
            total_received=2,
            total_kept=2,
            total_deleted=0,
        )
        # reputation = 0.8 + (2/2)*0.4 = 1.0 (clamped), > 0.85
        proposals = propose_rules([sender])
        assert len(proposals) == 1
        assert proposals[0].action == ActionType.KEEP

    def test_multiple_senders(self):
        """Propose rules for multiple senders at once."""
        senders = [
            Sender(email="spam@bad.com", total_received=10, total_kept=0, total_deleted=10),
            Sender(email="ok@mid.com", total_received=10, total_kept=5, total_deleted=5),
            Sender(email="friend@good.com", total_received=10, total_kept=10, total_deleted=0),
        ]
        proposals = propose_rules(senders)
        actions = {p.action for p in proposals}
        assert ActionType.DELETE in actions
        assert ActionType.KEEP in actions
        assert len(proposals) == 2
