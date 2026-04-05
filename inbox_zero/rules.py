"""Rule loading, serialization, and migration for gmail-inbox-zero."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import RULES_PATH
from .models import ActionType, Rule, RuleSource


def _rule_to_dict(rule: Rule) -> dict:
    """Serialize a Rule to a JSON-compatible dict."""
    return {
        "id": rule.id,
        "name": rule.name,
        "query": rule.query,
        "action": rule.action.value,
        "label_name": rule.label_name,
        "confidence": rule.confidence,
        "source": rule.source.value,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "hit_count": rule.hit_count,
        "miss_count": rule.miss_count,
        "last_matched": rule.last_matched.isoformat() if rule.last_matched else None,
        "created_at": rule.created_at.isoformat(),
        "notes": rule.notes,
    }


def _dict_to_rule(d: dict) -> Rule:
    """Deserialize a dict to a Rule."""
    return Rule(
        id=d["id"],
        name=d["name"],
        query=d["query"],
        action=ActionType(d["action"]),
        label_name=d.get("label_name"),
        confidence=d.get("confidence", 1.0),
        source=RuleSource(d.get("source", "manual")),
        enabled=d.get("enabled", True),
        priority=d.get("priority", 0),
        hit_count=d.get("hit_count", 0),
        miss_count=d.get("miss_count", 0),
        last_matched=(
            datetime.fromisoformat(d["last_matched"])
            if d.get("last_matched")
            else None
        ),
        created_at=(
            datetime.fromisoformat(d["created_at"])
            if d.get("created_at")
            else datetime.utcnow()
        ),
        notes=d.get("notes", ""),
    )


def load_rules(path: Optional[Path] = None) -> list[Rule]:
    """Load rules from a JSON file."""
    rules_path = path or RULES_PATH
    if not rules_path.exists():
        return []
    with open(rules_path) as f:
        data = json.load(f)
    rules_list = data if isinstance(data, list) else data.get("rules", [])
    return [_dict_to_rule(d) for d in rules_list]


def save_rules(rules: list[Rule], path: Optional[Path] = None) -> None:
    """Save rules to a JSON file."""
    rules_path = path or RULES_PATH
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rules_path, "w") as f:
        json.dump(
            {"rules": [_rule_to_dict(r) for r in rules]},
            f,
            indent=2,
        )


def migrate_legacy_filters(script_path: Optional[Path] = None) -> list[Rule]:
    """Convert legacy hardcoded filters from gmail_inbox_zero.py into Rule objects.

    This reads the ARCHIVE_FILTERS, DELETE_FILTERS, and LABEL_FILTERS dicts
    from the legacy script and converts each entry into a Rule object.

    If script_path is None, builds rules from the known legacy filter definitions
    (to avoid exec/import of the script).
    """
    archive_filters = {
        "newsletters": "in:inbox category:promotions",
        "unsubscribe": 'in:inbox "unsubscribe" -is:starred',
        "marketing": "in:inbox (from:noreply OR from:no-reply OR from:newsletter OR from:marketing)",
        "updates": "in:inbox category:updates -is:starred",
    }

    delete_filters = {
        "bulk_senders": "in:inbox (from:notifications@ OR from:info@ OR from:hello@ OR from:team@)",
        "automated": "in:inbox (from:donotreply@ OR from:do-not-reply@ OR from:automated@)",
        "social": "in:inbox category:social",
        "shopping": "in:inbox (from:order@ OR from:shipping@ OR from:receipt@) older_than:7d",
        "promos": "in:inbox category:promotions",
    }

    label_filters = {
        "Tax": 'in:inbox (skattemelding OR "tax return" OR "avgift" OR "skatten din")',
        "Min Helse": 'in:inbox (from:*helse* OR from:*helsenorge* OR "min helse")',
        "Pasientsky": 'in:inbox (from:*pasientsky* OR "pasientsky" OR from:pasientportalen@)',
    }

    rules: list[Rule] = []
    now = datetime.utcnow()

    for name, query in archive_filters.items():
        rules.append(
            Rule(
                id=str(uuid.uuid4()),
                name=f"archive_{name}",
                query=query,
                action=ActionType.ARCHIVE,
                confidence=1.0,
                source=RuleSource.MANUAL,
                enabled=True,
                created_at=now,
                notes="Migrated from legacy ARCHIVE_FILTERS",
            )
        )

    for name, query in delete_filters.items():
        rules.append(
            Rule(
                id=str(uuid.uuid4()),
                name=f"delete_{name}",
                query=query,
                action=ActionType.DELETE,
                confidence=1.0,
                source=RuleSource.MANUAL,
                enabled=True,
                created_at=now,
                notes="Migrated from legacy DELETE_FILTERS",
            )
        )

    for label_name, query in label_filters.items():
        rules.append(
            Rule(
                id=str(uuid.uuid4()),
                name=f"label_{label_name.lower().replace(' ', '_')}",
                query=query,
                action=ActionType.LABEL,
                label_name=label_name,
                confidence=1.0,
                source=RuleSource.MANUAL,
                enabled=True,
                created_at=now,
                notes="Migrated from legacy LABEL_FILTERS",
            )
        )

    return rules
