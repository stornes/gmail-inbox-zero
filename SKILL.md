---
name: gmail-inbox-zero
description: Achieve Gmail inbox zero by automatically archiving and deleting marketing emails, with smart labeling for confirmations, receipts, and Norwegian health/tax documents. Use when you want to batch-clean your inbox of newsletters, bulk senders, social updates, and promotional emails while protecting important transactional and personal messages.
---

# Gmail Inbox Zero

Automatically manage Gmail inbox by archiving and deleting marketing emails, with intelligent labeling for important categories.

## Prerequisites

OAuth token must be set up first:
```bash
python3 ~/clawd/skills/gmail-auth/gmail_auth.py --authenticate stornes@gmail.com
```

This creates `~/.openclaw/tokens/gmail_token.json` (auto-refreshed).

## Commands

### List what would be archived/deleted (dry run)

```bash
gmail_inbox_zero.py --preview 3
```

Shows emails per category (3 previews each), no changes made.

### Archive marketing emails

```bash
gmail_inbox_zero.py --archive --no-dry-run
```

**Archives (moves to All Mail):**
- newsletters (category:promotions)
- unsubscribe (emails with unsubscribe links)
- marketing (noreply/newsletter/marketing senders)
- updates (category:updates)

### Delete aggressively

```bash
gmail_inbox_zero.py --delete --no-dry-run
```

**Deletes immediately:**
- bulk_senders (notifications@, info@, hello@, team@)
- automated (donotreply@ senders)
- social (category:social)
- shopping (order confirmations older than 7 days)
- promos (category:promotions, old and new)

### Label and archive important categories

```bash
gmail_inbox_zero.py --label --no-dry-run
```

Auto-detects and labels:
- **Tax** — skattemelding, tax, avgift
- **Min Helse** — Norwegian health system emails
- **Pasientsky** — patient portal notifications

Then archives them.

### Full run (archive + delete + label)

```bash
gmail_inbox_zero.py --all --no-dry-run
```

Runs all three operations in sequence.

## Safety

- **Dry run by default** — add `--no-dry-run` to actually modify inbox
- **Preview mode** — see what will happen before committing
- **Personal emails protected** — (coming soon) real human senders never deleted
- **Starred emails safe** — marked important messages never touched

## Scheduling

Add to cron to run daily:
```bash
# 06:00 daily — clean up overnight's mail
0 6 * * * /Users/sst/clawd/skills/gmail-inbox-zero/scripts/gmail_inbox_zero.py --all --no-dry-run
```

## Configuration

Edit filter queries in the script itself (top of file):

```python
FILTERS = {
    "newsletters": "in:inbox category:promotions",
    # ... customize as needed
}
```

## JSON output

```bash
gmail_inbox_zero.py --archive --json
```

Returns structured data for integration with other tools.
