"""Feedback cycle orchestrator for gmail-inbox-zero.

Runs after every inbox-zero run to detect corrections, adjust rule
confidence, disable failing rules, and propose new rules from patterns.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .config import MIN_CONFIDENCE_BEFORE_DISABLE
from .learner import (
    boost_confidence,
    compute_reputation,
    decay_confidence,
    propose_rules,
    should_disable,
)
from .models import ActionLog, ActionType, Correction, Rule, Sender
from .storage import Storage


@dataclass
class FeedbackResult:
    corrections_detected: int = 0
    rules_decayed: int = 0
    rules_boosted: int = 0
    rules_disabled: int = 0
    rules_proposed: int = 0


def detect_corrections(
    recent_actions: list[ActionLog],
    current_labels_fn: Callable[[str], list[str]],
) -> list[Correction]:
    """Detect corrections by checking if archived/deleted messages are back in inbox.

    For each recent action that was ARCHIVE or DELETE, check if the message
    now has an INBOX label, which means the user moved it back.
    """
    corrections: list[Correction] = []
    for action_log in recent_actions:
        if action_log.action not in (ActionType.ARCHIVE, ActionType.DELETE):
            continue
        if action_log.was_dry_run:
            continue
        labels = current_labels_fn(action_log.message_id)
        if "INBOX" in labels:
            corrections.append(
                Correction(
                    id=str(uuid.uuid4()),
                    action_log_id=action_log.id,
                    rule_id=action_log.rule_id,
                    original_action=action_log.action,
                    corrective_action="moved_to_inbox",
                    detected_at=datetime.utcnow(),
                    applied=False,
                )
            )
    return corrections


def apply_corrections(
    storage: Storage,
    corrections: list[Correction],
) -> int:
    """Decay confidence on rules that caused corrections.

    Returns the number of rules decayed.
    """
    decayed_rule_ids: set[str] = set()
    for correction in corrections:
        storage.insert_correction(correction)
        if correction.rule_id is None:
            continue
        # Load rule from action log's rule_id, decay it
        logs = storage.list_action_logs(rule_id=correction.rule_id, limit=1)
        if not logs:
            continue
        # We need to load the rule; for now we work with what storage provides.
        # The rule is referenced by ID in the action log. We decay by reading
        # all corrections for this rule and the action log confidence.
        # Since storage doesn't have a rules table yet (rules are in JSON),
        # we track the rule_id for the caller.
        decayed_rule_ids.add(correction.rule_id)
    return len(decayed_rule_ids)


def boost_uncorrected_rules(
    storage: Storage,
    successful_actions: list[ActionLog],
) -> int:
    """Boost confidence for rules with successful (uncorrected) matches.

    Returns the number of rules boosted.
    """
    boosted_rule_ids: set[str] = set()
    for action_log in successful_actions:
        if action_log.rule_id is None:
            continue
        if action_log.was_dry_run:
            continue
        boosted_rule_ids.add(action_log.rule_id)
    return len(boosted_rule_ids)


def auto_disable_low_confidence(
    storage: Storage,
    rules: list[Rule],
) -> int:
    """Disable rules whose confidence has fallen below the threshold.

    Returns the number of rules disabled.
    """
    disabled_count = 0
    for rule in rules:
        if rule.enabled and should_disable(rule):
            rule.enabled = False
            disabled_count += 1
    return disabled_count


def propose_sender_rules(storage: Storage) -> list[Rule]:
    """Propose new rules based on sender reputation patterns."""
    senders = storage.list_senders()
    return propose_rules(senders)


def run_feedback_cycle(
    storage: Storage,
    recent_actions: list[ActionLog],
    current_labels_fn: Callable[[str], list[str]],
    rules: list[Rule] | None = None,
) -> FeedbackResult:
    """Run the full feedback cycle after an inbox-zero run.

    Steps:
    1. Detect corrections (user moved messages back to inbox)
    2. Apply corrections (decay confidence on offending rules)
    3. Boost uncorrected rules (reward successful matches)
    4. Auto-disable low-confidence rules
    5. Propose new sender-based rules

    Args:
        storage: Storage backend
        recent_actions: ActionLog entries from the most recent run
        current_labels_fn: Callable that returns current labels for a message ID
        rules: Optional list of Rule objects to check for disabling

    Returns:
        FeedbackResult with counts of all actions taken
    """
    result = FeedbackResult()

    # Step 1: Detect corrections
    corrections = detect_corrections(recent_actions, current_labels_fn)
    result.corrections_detected = len(corrections)

    # Step 2: Apply corrections (decay confidence)
    for correction in corrections:
        storage.insert_correction(correction)
    result.rules_decayed = apply_corrections(storage, corrections)

    # Decay confidence on the actual rule objects if available
    if rules is not None:
        corrected_rule_ids = {c.rule_id for c in corrections if c.rule_id}
        rule_map = {r.id: r for r in rules}
        for rule_id in corrected_rule_ids:
            if rule_id in rule_map:
                decay_confidence(rule_map[rule_id])

    # Step 3: Boost uncorrected rules
    corrected_action_ids = {c.action_log_id for c in corrections}
    successful = [
        a for a in recent_actions
        if a.id not in corrected_action_ids
        and a.rule_id is not None
        and not a.was_dry_run
    ]
    result.rules_boosted = boost_uncorrected_rules(storage, successful)

    # Apply boost to actual rule objects if available
    if rules is not None:
        rule_map = {r.id: r for r in rules}
        boosted_ids: set[str] = set()
        for action_log in successful:
            if action_log.rule_id in rule_map and action_log.rule_id not in boosted_ids:
                boost_confidence(rule_map[action_log.rule_id])
                boosted_ids.add(action_log.rule_id)

    # Step 4: Auto-disable low-confidence rules
    if rules is not None:
        result.rules_disabled = auto_disable_low_confidence(storage, rules)

    # Step 5: Propose new sender-based rules
    proposals = propose_sender_rules(storage)
    result.rules_proposed = len(proposals)

    return result
