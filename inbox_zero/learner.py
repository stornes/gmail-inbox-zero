"""Ontology and learning module for gmail-inbox-zero.

Computes sender reputation, adjusts rule confidence based on feedback,
and proposes new rules from sender patterns.
"""

import uuid
from datetime import datetime

from .config import (
    CONFIDENCE_BOOST_PER_HIT,
    CONFIDENCE_DECAY_PER_CORRECTION,
    MIN_CONFIDENCE_BEFORE_DISABLE,
    PROPOSAL_MIN_OCCURRENCES,
)
from .models import ActionType, Rule, RuleSource, Sender


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))


def compute_reputation(sender: Sender) -> float:
    """Compute sender reputation score.

    Formula:
        base = 0.5 (+ 0.3 if contact)
        ratio = (total_kept - total_deleted) / max(total_received, 1)
        reputation = clamp(base + ratio * 0.4, 0.0, 1.0)
    """
    base = 0.5
    if sender.is_contact:
        base += 0.3
    ratio = (sender.total_kept - sender.total_deleted) / max(sender.total_received, 1)
    return _clamp(base + ratio * 0.4, 0.0, 1.0)


def decay_confidence(rule: Rule) -> Rule:
    """Apply one correction penalty to a rule.

    Decreases confidence by CONFIDENCE_DECAY_PER_CORRECTION and increments
    miss_count. Returns the mutated rule.
    """
    rule.confidence = _clamp(rule.confidence - CONFIDENCE_DECAY_PER_CORRECTION, 0.0, 1.0)
    rule.miss_count += 1
    return rule


def boost_confidence(rule: Rule) -> Rule:
    """Apply one uncorrected-hit reward to a rule.

    Increases confidence by CONFIDENCE_BOOST_PER_HIT, capped at 1.0.
    Returns the mutated rule.
    """
    rule.confidence = _clamp(rule.confidence + CONFIDENCE_BOOST_PER_HIT, 0.0, 1.0)
    return rule


def should_disable(rule: Rule) -> bool:
    """Check whether a rule's confidence is below the auto-disable threshold."""
    return rule.confidence < MIN_CONFIDENCE_BEFORE_DISABLE


def propose_rules(senders: list[Sender]) -> list[Rule]:
    """Propose new rules from sender reputation patterns.

    - Senders with 5+ messages and reputation < 0.25: propose DELETE rule
    - Senders with reputation > 0.85: propose KEEP rule
    - Proposed rules: enabled=False, confidence=0.5, source=LEARNED
    """
    proposals: list[Rule] = []
    for sender in senders:
        rep = compute_reputation(sender)
        if sender.total_received >= PROPOSAL_MIN_OCCURRENCES and rep < 0.25:
            proposals.append(
                Rule(
                    id=str(uuid.uuid4()),
                    name=f"Auto-delete {sender.email}",
                    query=f"from:{sender.email}",
                    action=ActionType.DELETE,
                    confidence=0.5,
                    source=RuleSource.LEARNED,
                    enabled=False,
                    created_at=datetime.utcnow(),
                )
            )
        elif rep > 0.85:
            proposals.append(
                Rule(
                    id=str(uuid.uuid4()),
                    name=f"Auto-keep {sender.email}",
                    query=f"from:{sender.email}",
                    action=ActionType.KEEP,
                    confidence=0.5,
                    source=RuleSource.LEARNED,
                    enabled=False,
                    created_at=datetime.utcnow(),
                )
            )
    return proposals
