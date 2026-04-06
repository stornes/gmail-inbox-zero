"""Rule evaluation engine for gmail-inbox-zero."""

from dataclasses import dataclass, field
from typing import Callable

from inbox_zero.config import AUTO_ACT_THRESHOLD, REVIEW_THRESHOLD
from inbox_zero.models import ActionType, Rule


@dataclass
class RuleMatch:
    message_id: str
    thread_id: str
    rule: Rule
    resolved_action: ActionType
    sender_email: str
    subject: str


@dataclass
class ActionSummary:
    archived: int = 0
    deleted: int = 0
    labeled: int = 0
    kept: int = 0
    flagged: int = 0


@dataclass
class EvaluationResult:
    auto_actions: list[RuleMatch] = field(default_factory=list)
    flagged_for_review: list[RuleMatch] = field(default_factory=list)
    skipped: list[RuleMatch] = field(default_factory=list)
    summary: ActionSummary = field(default_factory=ActionSummary)


class RuleEngine:
    """Evaluates rules against Gmail messages and resolves conflicts."""

    def __init__(
        self,
        rules: list[Rule],
        gmail_search_fn: Callable[[str], list[dict]],
        metadata_fn: Callable[[str], tuple[str, str]] | None = None,
    ) -> None:
        self.rules = rules
        self.gmail_search_fn = gmail_search_fn
        self.metadata_fn = metadata_fn

    def evaluate(self) -> EvaluationResult:
        # 1. Load enabled rules sorted by priority descending
        enabled_rules = sorted(
            [r for r in self.rules if r.enabled],
            key=lambda r: r.priority,
            reverse=True,
        )

        # 2. For each rule, search and build match map
        # match_map: message_id -> list[RuleMatch]
        match_map: dict[str, list[RuleMatch]] = {}

        for rule in enabled_rules:
            messages = self.gmail_search_fn(rule.query)
            for msg in messages:
                match = RuleMatch(
                    message_id=msg["id"],
                    thread_id=msg.get("threadId", ""),
                    rule=rule,
                    resolved_action=rule.action,
                    sender_email="",
                    subject="",
                )
                match_map.setdefault(match.message_id, []).append(match)

        # 3. Conflict resolution per message
        result = EvaluationResult()

        for msg_id, matches in match_map.items():
            winner = self._resolve_conflict(matches)
            if winner is None:
                continue

            # Enrich winner with metadata if available
            if self.metadata_fn and not winner.sender_email:
                sender_email, subject = self.metadata_fn(winner.message_id)
                winner = RuleMatch(
                    message_id=winner.message_id,
                    thread_id=winner.thread_id,
                    rule=winner.rule,
                    resolved_action=winner.resolved_action,
                    sender_email=sender_email,
                    subject=subject,
                )

            # Apply threshold logic
            confidence = winner.rule.confidence

            if confidence < REVIEW_THRESHOLD:
                result.skipped.append(winner)
            elif confidence < AUTO_ACT_THRESHOLD:
                winner = RuleMatch(
                    message_id=winner.message_id,
                    thread_id=winner.thread_id,
                    rule=winner.rule,
                    resolved_action=ActionType.FLAG_REVIEW,
                    sender_email=winner.sender_email,
                    subject=winner.subject,
                )
                result.flagged_for_review.append(winner)
                result.summary.flagged += 1
            else:
                result.auto_actions.append(winner)
                self._update_summary(result.summary, winner.resolved_action)

        return result

    @staticmethod
    def _resolve_conflict(matches: list[RuleMatch]) -> RuleMatch | None:
        """Pick the winning match for a single message.

        KEEP always wins. Otherwise highest priority wins,
        with ties broken by highest confidence.
        """
        if not matches:
            return None

        # KEEP always wins
        keep_matches = [m for m in matches if m.rule.action == ActionType.KEEP]
        if keep_matches:
            # Among KEEP matches, pick highest priority then confidence
            return max(
                keep_matches,
                key=lambda m: (m.rule.priority, m.rule.confidence),
            )

        # Highest priority, then highest confidence
        return max(
            matches,
            key=lambda m: (m.rule.priority, m.rule.confidence),
        )

    @staticmethod
    def _update_summary(summary: ActionSummary, action: ActionType) -> None:
        if action == ActionType.ARCHIVE:
            summary.archived += 1
        elif action == ActionType.DELETE:
            summary.deleted += 1
        elif action == ActionType.LABEL:
            summary.labeled += 1
        elif action == ActionType.KEEP:
            summary.kept += 1
        elif action == ActionType.FLAG_REVIEW:
            summary.flagged += 1
