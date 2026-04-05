"""Gmail Inbox Zero - Self-learning rule engine for email management."""

from .models import ActionLog, ActionType, Category, Correction, Rule, RuleSource, Sender
from .storage import Storage
from .rules import load_rules, save_rules, migrate_legacy_filters

__all__ = [
    "ActionLog",
    "ActionType",
    "Category",
    "Correction",
    "Rule",
    "RuleSource",
    "Sender",
    "Storage",
    "load_rules",
    "save_rules",
    "migrate_legacy_filters",
]
