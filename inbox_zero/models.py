"""Data models for gmail-inbox-zero."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class ActionType(Enum):
    ARCHIVE = "archive"
    DELETE = "delete"
    LABEL = "label"
    KEEP = "keep"
    FLAG_REVIEW = "flag_review"


class RuleSource(Enum):
    MANUAL = "manual"
    LEARNED = "learned"
    SYSTEM = "system"


@dataclass
class Rule:
    id: str
    name: str
    query: str
    action: ActionType
    label_name: Optional[str] = None
    confidence: float = 1.0
    source: RuleSource = RuleSource.MANUAL
    enabled: bool = True
    priority: int = 0
    hit_count: int = 0
    miss_count: int = 0
    last_matched: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""


@dataclass
class Sender:
    email: str
    display_name: str = ""
    is_contact: bool = False
    total_received: int = 0
    total_archived: int = 0
    total_deleted: int = 0
    total_kept: int = 0
    reputation_score: float = 0.5
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: Optional[datetime] = None
    categories: str = ""

    def refresh_reputation(self) -> float:
        """Recompute reputation_score from current fields and store it.

        Formula: base=0.5 (+0.3 if contact),
        ratio=(kept-deleted)/max(received,1), clamp(base+ratio*0.4, 0, 1)
        """
        base = 0.5 + (0.3 if self.is_contact else 0.0)
        ratio = (self.total_kept - self.total_deleted) / max(self.total_received, 1)
        self.reputation_score = max(0.0, min(1.0, base + ratio * 0.4))
        return self.reputation_score


@dataclass
class Category:
    id: str
    name: str
    description: str = ""
    keywords: str = ""
    default_action: ActionType = ActionType.ARCHIVE
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ActionLog:
    id: str
    message_id: str
    thread_id: str = ""
    sender_email: str = ""
    subject: str = ""
    rule_id: Optional[str] = None
    action: ActionType = ActionType.ARCHIVE
    confidence: float = 1.0
    was_dry_run: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Correction:
    id: str
    action_log_id: str
    rule_id: Optional[str] = None
    original_action: ActionType = ActionType.ARCHIVE
    corrective_action: str = ""
    detected_at: datetime = field(default_factory=datetime.utcnow)
    applied: bool = False
