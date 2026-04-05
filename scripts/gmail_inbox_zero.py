#!/usr/bin/env python3
"""
Gmail Inbox Zero — Auto-archive/delete marketing emails + label important stuff.
Direct Gmail API (no gog dependency). OAuth token via ~/.openclaw/tokens/gmail_token.json
"""

import json
import sys
import requests
from pathlib import Path
from datetime import datetime

TOKEN_PATH = Path.home() / ".openclaw" / "tokens" / "gmail_token.json"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Archive these (remove INBOX label)
ARCHIVE_FILTERS = {
    "newsletters": "in:inbox category:promotions",
    "unsubscribe": 'in:inbox "unsubscribe" -is:starred',
    "marketing": 'in:inbox (from:noreply OR from:no-reply OR from:newsletter OR from:marketing)',
    "updates": "in:inbox category:updates -is:starred",
}

# Delete these (move to Trash)
DELETE_FILTERS = {
    "bulk_senders": 'in:inbox (from:notifications@ OR from:info@ OR from:hello@ OR from:team@)',
    "automated": 'in:inbox (from:donotreply@ OR from:do-not-reply@ OR from:automated@)',
    "social": "in:inbox category:social",
    "shopping": "in:inbox (from:order@ OR from:shipping@ OR from:receipt@) older_than:7d",
    "promos": "in:inbox category:promotions",
}

# Detect and label these
LABEL_FILTERS = {
    "Tax": 'in:inbox (skattemelding OR "tax return" OR "avgift" OR "skatten din")',
    "Min Helse": 'in:inbox (from:*helse* OR from:*helsenorge* OR "min helse")',
    "Pasientsky": 'in:inbox (from:*pasientsky* OR "pasientsky" OR from:pasientportalen@)',
}


def load_token():
    """Load and refresh OAuth token."""
    if not TOKEN_PATH.exists():
        print("❌ No token found. Run gmail_auth.py first.")
        sys.exit(1)

    with open(TOKEN_PATH) as f:
        t = json.load(f)

    # Refresh if needed
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": t["client_id"],
        "client_secret": t["client_secret"],
        "refresh_token": t["refresh_token"],
        "grant_type": "refresh_token"
    })
    if resp.ok:
        data = resp.json()
        t["token"] = data["access_token"]
        with open(TOKEN_PATH, "w") as f:
            json.dump(t, f, indent=2)
    
    return t["token"]


def gmail_get(token, endpoint, params=None):
    """GET request to Gmail API."""
    resp = requests.get(f"{API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {})
    resp.raise_for_status()
    return resp.json()


def gmail_post(token, endpoint, body=None):
    """POST request to Gmail API."""
    resp = requests.post(f"{API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body or {})
    resp.raise_for_status()
    return resp.json()


def search_messages(token, query, max_results=500):
    """Search Gmail and return message IDs."""
    messages = []
    page_token = None
    
    while len(messages) < max_results:
        params = {"q": query, "maxResults": min(100, max_results - len(messages))}
        if page_token:
            params["pageToken"] = page_token
        
        data = gmail_get(token, "messages", params)
        batch = data.get("messages", [])
        messages.extend(batch)
        
        page_token = data.get("nextPageToken")
        if not page_token or not batch:
            break
    
    return messages[:max_results]


def get_message_snippet(token, msg_id):
    """Get From/Subject for a message."""
    resp = requests.get(f"{API_BASE}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
        params=[(("format", "metadata")), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")])
    resp.raise_for_status()
    data = resp.json()
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    return {
        "id": msg_id,
        "from": headers.get("From", "?")[:50],
        "subject": headers.get("Subject", "(no subject)")[:60],
    }


def archive_messages(token, msg_ids):
    """Archive messages (remove INBOX label)."""
    if not msg_ids:
        return 0
    for i in range(0, len(msg_ids), 1000):
        batch = msg_ids[i:i+1000]
        gmail_post(token, "messages/batchModify", {
            "ids": batch,
            "removeLabelIds": ["INBOX"]
        })
    return len(msg_ids)


def delete_messages(token, msg_ids):
    """Delete messages (move to Trash)."""
    if not msg_ids:
        return 0
    for msg_id in msg_ids[:100]:  # Delete one by one (safer)
        try:
            gmail_post(token, f"messages/{msg_id}/trash", {})
        except Exception:
            pass
    return len(msg_ids[:100])


def label_and_archive(token, msg_ids, label_name):
    """Label messages and archive them."""
    if not msg_ids:
        return 0
    
    # Get or create label
    labels_resp = gmail_get(token, "labels")
    label_id = None
    for label in labels_resp.get("labels", []):
        if label["name"] == label_name:
            label_id = label["id"]
            break
    
    if not label_id:
        # Create label
        create_resp = gmail_post(token, "labels", {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show"
        })
        label_id = create_resp["id"]
    
    # Apply label and archive
    for i in range(0, len(msg_ids), 1000):
        batch = msg_ids[i:i+1000]
        gmail_post(token, "messages/batchModify", {
            "ids": batch,
            "addLabelIds": [label_id],
            "removeLabelIds": ["INBOX"]
        })
    
    return len(msg_ids)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gmail Inbox Zero")
    parser.add_argument("--archive", action="store_true", help="Archive marketing emails")
    parser.add_argument("--delete", action="store_true", help="Delete aggressive filters")
    parser.add_argument("--label", action="store_true", help="Label important categories")
    parser.add_argument("--all", action="store_true", help="Run all three")
    parser.add_argument("--no-dry-run", action="store_true", help="Actually modify inbox")
    parser.add_argument("--preview", type=int, default=3, help="Emails to preview per filter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not any([args.archive, args.delete, args.label, args.all]):
        args.all = True  # Default to all

    token = load_token()
    profile = gmail_get(token, "profile")
    
    if not args.json:
        print(f"\n📧 {profile['emailAddress']}")
        if args.no_dry_run:
            print("⚡ LIVE MODE\n")
        else:
            print("🔍 DRY RUN\n")

    results = {"archived": 0, "deleted": 0, "labeled": 0}
    dry_run = not args.no_dry_run

    # Archive
    if args.all or args.archive:
        if not args.json:
            print("📋 ARCHIVE FILTERS")
        for name, query in ARCHIVE_FILTERS.items():
            msgs = search_messages(token, query)
            count = len(msgs)
            if count == 0:
                continue
            if not args.json:
                print(f"  {name}: {count}")
                for msg in msgs[:args.preview]:
                    try:
                        info = get_message_snippet(token, msg["id"])
                        print(f"    • {info['from']} — {info['subject']}")
                    except:
                        pass
                if count > args.preview:
                    print(f"    ... +{count - args.preview}")
            
            if not dry_run:
                archived = archive_messages(token, [m["id"] for m in msgs])
                results["archived"] += archived
            else:
                results["archived"] += count

    # Delete
    if args.all or args.delete:
        if not args.json:
            print("\n🗑️  DELETE FILTERS")
        for name, query in DELETE_FILTERS.items():
            msgs = search_messages(token, query)
            count = len(msgs)
            if count == 0:
                continue
            if not args.json:
                print(f"  {name}: {count}")
                for msg in msgs[:args.preview]:
                    try:
                        info = get_message_snippet(token, msg["id"])
                        print(f"    • {info['from']} — {info['subject']}")
                    except:
                        pass
                if count > args.preview:
                    print(f"    ... +{count - args.preview}")
            
            if not dry_run:
                deleted = delete_messages(token, [m["id"] for m in msgs])
                results["deleted"] += deleted
            else:
                results["deleted"] += count

    # Label
    if args.all or args.label:
        if not args.json:
            print("\n🏷️  LABEL & ARCHIVE")
        for label_name, query in LABEL_FILTERS.items():
            msgs = search_messages(token, query)
            count = len(msgs)
            if count == 0:
                continue
            if not args.json:
                print(f"  {label_name}: {count}")
                for msg in msgs[:args.preview]:
                    try:
                        info = get_message_snippet(token, msg["id"])
                        print(f"    • {info['from']} — {info['subject']}")
                    except:
                        pass
                if count > args.preview:
                    print(f"    ... +{count - args.preview}")
            
            if not dry_run:
                labeled = label_and_archive(token, [m["id"] for m in msgs], label_name)
                results["labeled"] += labeled
            else:
                results["labeled"] += count

    if args.json:
        print(json.dumps(results))
    else:
        print(f"\n{'='*50}")
        print(f"📊 Archived: {results['archived']}")
        print(f"🗑️  Deleted: {results['deleted']}")
        print(f"🏷️  Labeled: {results['labeled']}")
        if dry_run:
            print(f"\n💡 Run with --no-dry-run to apply changes")


if __name__ == "__main__":
    main()
