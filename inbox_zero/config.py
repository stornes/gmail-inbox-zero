"""Constants and paths for gmail-inbox-zero."""

from pathlib import Path

# Confidence thresholds
AUTO_ACT_THRESHOLD = 0.7
REVIEW_THRESHOLD = 0.4
CONFIDENCE_DECAY_PER_CORRECTION = 0.15
CONFIDENCE_BOOST_PER_HIT = 0.005
MIN_CONFIDENCE_BEFORE_DISABLE = 0.2

# Rule proposal thresholds
PROPOSAL_MIN_OCCURRENCES = 5

# Batch sizes
BATCH_SIZE = 1000
DELETE_BATCH_SIZE = 100

# Paths (relative to package root)
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
RULES_PATH = DATA_DIR / "rules.json"
DB_PATH = DATA_DIR / "inbox_zero.db"
