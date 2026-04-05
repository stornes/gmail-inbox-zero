"""Action executor: takes resolved rule matches and executes them via GmailClient."""

import logging
from dataclasses import dataclass, field

from .gmail_client import GmailClient

logger = logging.getLogger(__name__)


@dataclass
class ActionSummary:
    archived: int = 0
    deleted: int = 0
    labeled: int = 0
    kept: int = 0
    flagged: int = 0


@dataclass
class RuleMatch:
    """Lightweight match record for the action executor.

    This is intentionally separate from engine.RuleMatch so that WP3
    stays self-contained and does not depend on models.py.
    """
    message_id: str
    thread_id: str
    rule_name: str
    resolved_action: str          # "archive" | "delete" | "label" | "keep" | "flag_review"
    sender_email: str
    subject: str
    label_name: str | None = None  # required when resolved_action == "label"


def execute_actions(
    client: GmailClient,
    matches: list[RuleMatch],
    *,
    dry_run: bool = True,
    archive_batch_size: int = 1000,
    delete_batch_size: int = 100,
) -> ActionSummary:
    """Execute resolved actions in batch. Returns an ActionSummary.

    When *dry_run* is True, logs what would happen but does not call Gmail.
    """
    summary = ActionSummary()

    # Partition by action type
    to_archive: list[str] = []
    to_delete: list[str] = []
    label_groups: dict[str, list[str]] = {}

    for m in matches:
        action = m.resolved_action.lower()

        if action == "archive":
            to_archive.append(m.message_id)
            summary.archived += 1

        elif action == "delete":
            to_delete.append(m.message_id)
            summary.deleted += 1

        elif action == "label":
            label = m.label_name or "Unlabeled"
            label_groups.setdefault(label, []).append(m.message_id)
            summary.labeled += 1

        elif action == "keep":
            summary.kept += 1

        elif action == "flag_review":
            summary.flagged += 1

        else:
            logger.warning("Unknown action %r for message %s", action, m.message_id)

    if dry_run:
        logger.info(
            "[DRY RUN] Would archive %d, delete %d, label %d, keep %d, flag %d",
            summary.archived,
            summary.deleted,
            summary.labeled,
            summary.kept,
            summary.flagged,
        )
        return summary

    # Execute
    if to_archive:
        client.archive_messages(to_archive, batch_size=archive_batch_size)

    if to_delete:
        client.delete_messages(to_delete, batch_size=delete_batch_size)

    for label_name, msg_ids in label_groups.items():
        client.label_and_archive(msg_ids, label_name)

    return summary
