#!/usr/bin/env python3
"""
Gmail Inbox Zero — Hybrid approach.
Algorithmic rules for 99% of cases, Ollama (llama3.2) for ambiguous emails.
"""

import json
import sys
import requests
from pathlib import Path

TOKEN_PATH = Path.home() / ".openclaw" / "tokens" / "gmail_token.json"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
OLLAMA_URL = "http://localhost:11434/api/generate"

# Delete these (safe patterns)
DELETE_FILTERS = {
    "bulk_senders": 'in:inbox (from:notifications@ OR from:info@ OR from:hello@ OR from:team@ OR from:noreply@ OR from:donotreply@)',
    "automated": 'in:inbox (from:do-not-reply@ OR from:automated@)',
    "social": "in:inbox category:social",
    "shopping": "in:inbox (from:order@ OR from:shipping@ OR from:receipt@) older_than:7d",
    "promos": "in:inbox category:promotions",
}

# Archive these (lower confidence)
ARCHIVE_FILTERS = {
    "newsletters": "in:inbox category:promotions -from:noreply@",
    "unsubscribe": 'in:inbox "unsubscribe" -is:starred -from:noreply@',
    "marketing": 'in:inbox (newsletter OR marketing) -from:noreply@',
    "updates": "in:inbox category:updates -is:starred -from:noreply@",
}

# Label these
LABEL_FILTERS = {
    "Tax": 'in:inbox (skattemelding OR "tax return" OR "avgift")',
    "Min Helse": 'in:inbox (from:*helse* OR "min helse")',
    "Pasientsky": 'in:inbox (from:*pasientsky* OR "pasientsky")',
}


def load_token():
    if not TOKEN_PATH.exists():
        print("❌ No token. Run gmail_auth.py first.")
        sys.exit(1)
    with open(TOKEN_PATH) as f:
        t = json.load(f)
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
    resp = requests.get(f"{API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {})
    resp.raise_for_status()
    return resp.json()


def gmail_post(token, endpoint, body=None):
    resp = requests.post(f"{API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body or {})
    resp.raise_for_status()
    return resp.json()


def search_messages(token, query, max_results=500):
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


def get_message_full(token, msg_id):
    """Get From/Subject/Snippet for a message."""
    resp = requests.get(f"{API_BASE}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
        params=[(("format", "metadata")), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")])
    resp.raise_for_status()
    data = resp.json()
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    return {
        "id": msg_id,
        "from": headers.get("From", "?"),
        "subject": headers.get("Subject", ""),
        "snippet": data.get("snippet", ""),
    }


def is_in_sent_folder(token, sender_email):
    """Check if we've emailed this sender."""
    try:
        # Extract email from "Name <email@example.com>"
        if "<" in sender_email and ">" in sender_email:
            email = sender_email.split("<")[1].split(">")[0]
        else:
            email = sender_email
        
        msgs = search_messages(token, f'to:{email}', max_results=1)
        return len(msgs) > 0
    except:
        return False


def is_starred(token, msg_id):
    """Check if message is starred."""
    try:
        data = gmail_get(token, f"messages/{msg_id}", {"format": "minimal"})
        labels = data.get("labelIds", [])
        return "STARRED" in labels
    except:
        return False


def classify_with_ollama(from_addr, subject, snippet):
    """Ask llama3.2 if ambiguous email should be KEEP/ARCHIVE/DELETE."""
    prompt = f"""You are an email classifier. Decide if this email is:
- KEEP (important personal/transactional)
- ARCHIVE (probably marketing but keep it)
- DELETE (definitely spam/promotional)

From: {from_addr}
Subject: {subject}
Preview: {snippet[:200]}

Respond with ONLY one word: KEEP, ARCHIVE, or DELETE."""

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": "llama3.2",
            "prompt": prompt,
            "stream": False,
        }, timeout=10)
        if resp.ok:
            result = resp.json()["response"].strip().upper()
            if result in ["KEEP", "ARCHIVE", "DELETE"]:
                return result
    except:
        pass
    
    # Fallback: if from has real name, archive; else delete
    if " " in from_addr or "@" not in from_addr:
        return "ARCHIVE"
    return "DELETE"


def decide_action(token, msg_info):
    """Decide: KEEP/ARCHIVE/DELETE for a message."""
    from_addr = msg_info["from"]
    
    # Rule 1: Sent folder (genuine contact)
    if is_in_sent_folder(token, from_addr):
        return "KEEP"
    
    # Rule 2: Starred
    if is_starred(token, msg_info["id"]):
        return "KEEP"
    
    # Rule 3: Automated patterns → DELETE
    automated_patterns = [
        "noreply@", "no-reply@", "donotreply@", "do-not-reply@",
        "notifications@", "info@", "hello@", "team@",
        "no_reply@"
    ]
    if any(p in from_addr.lower() for p in automated_patterns):
        return "DELETE"
    
    # Rule 4: Real name (has space or comma) → ARCHIVE
    if " " in from_addr or "," in from_addr:
        return "ARCHIVE"
    
    # Ambiguous: ask Ollama
    return classify_with_ollama(from_addr, msg_info["subject"], msg_info["snippet"])


def archive_messages(token, msg_ids):
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
    if not msg_ids:
        return 0
    for msg_id in msg_ids[:100]:
        try:
            gmail_post(token, f"messages/{msg_id}/trash", {})
        except:
            pass
    return len(msg_ids[:100])


def label_and_archive(token, msg_ids, label_name):
    if not msg_ids:
        return 0
    labels_resp = gmail_get(token, "labels")
    label_id = None
    for label in labels_resp.get("labels", []):
        if label["name"] == label_name:
            label_id = label["id"]
            break
    
    if not label_id:
        create_resp = gmail_post(token, "labels", {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show"
        })
        label_id = create_resp["id"]
    
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
    parser = argparse.ArgumentParser(description="Gmail Inbox Zero (Hybrid)")
    parser.add_argument("--all", action="store_true", help="Run all (safe delete + archive + label)")
    parser.add_argument("--smart", action="store_true", help="Smart classify all inbox (uses Ollama)")
    parser.add_argument("--no-dry-run", action="store_true", help="Actually modify")
    parser.add_argument("--preview", type=int, default=2, help="Previews per filter")
    args = parser.parse_args()

    if not any([args.all, args.smart]):
        args.all = True

    token = load_token()
    profile = gmail_get(token, "profile")
    
    print(f"\n📧 {profile['emailAddress']}")
    if args.no_dry_run:
        print("⚡ LIVE MODE\n")
    else:
        print("🔍 DRY RUN\n")

    results = {"keep": 0, "archive": 0, "delete": 0, "labeled": 0}
    dry_run = not args.no_dry_run

    # Safe delete filters
    if args.all or args.smart:
        print("🗑️  DELETE (safe patterns)")
        for name, query in DELETE_FILTERS.items():
            msgs = search_messages(token, query)
            count = len(msgs)
            if count == 0:
                continue
            print(f"  {name}: {count}")
            for msg in msgs[:args.preview]:
                try:
                    info = get_message_full(token, msg["id"])
                    print(f"    • {info['from'][:50]} — {info['subject'][:50]}")
                except:
                    pass
            if count > args.preview:
                print(f"    ... +{count - args.preview}")
            
            if not dry_run:
                deleted = delete_messages(token, [m["id"] for m in msgs])
                results["delete"] += deleted
            else:
                results["delete"] += count

    # Archive filters
    if args.all or args.smart:
        print("\n📋 ARCHIVE (lower confidence)")
        for name, query in ARCHIVE_FILTERS.items():
            msgs = search_messages(token, query)
            count = len(msgs)
            if count == 0:
                continue
            print(f"  {name}: {count}")
            for msg in msgs[:args.preview]:
                try:
                    info = get_message_full(token, msg["id"])
                    print(f"    • {info['from'][:50]} — {info['subject'][:50]}")
                except:
                    pass
            if count > args.preview:
                print(f"    ... +{count - args.preview}")
            
            if not dry_run:
                archived = archive_messages(token, [m["id"] for m in msgs])
                results["archive"] += archived
            else:
                results["archive"] += count

    # Label
    if args.all or args.smart:
        print("\n🏷️  LABEL & ARCHIVE")
        for label_name, query in LABEL_FILTERS.items():
            msgs = search_messages(token, query)
            count = len(msgs)
            if count == 0:
                continue
            print(f"  {label_name}: {count}")
            if not dry_run:
                labeled = label_and_archive(token, [m["id"] for m in msgs], label_name)
                results["labeled"] += labeled
            else:
                results["labeled"] += count

    # Smart classify (if requested)
    if args.smart:
        print("\n🧠 SMART CLASSIFY (all inbox)")
        # Get all inbox
        all_inbox = search_messages(token, "in:inbox", max_results=1000)
        keep_ids = []
        archive_ids = []
        delete_ids = []
        
        for i, msg in enumerate(all_inbox[:100]):  # First 100 for demo
            if i % 10 == 0:
                print(f"  Classifying {i}/100...", end="\r")
            try:
                info = get_message_full(token, msg["id"])
                action = decide_action(token, info)
                
                if action == "KEEP":
                    keep_ids.append(msg["id"])
                    results["keep"] += 1
                elif action == "ARCHIVE":
                    archive_ids.append(msg["id"])
                    results["archive"] += 1
                else:
                    delete_ids.append(msg["id"])
                    results["delete"] += 1
            except:
                pass
        
        print(f"  Classified 100")
        
        if not dry_run:
            if archive_ids:
                archive_messages(token, archive_ids)
            if delete_ids:
                delete_messages(token, delete_ids)

    print(f"\n{'='*50}")
    print(f"✅ Keep: {results['keep']}")
    print(f"📋 Archive: {results['archive']}")
    print(f"🗑️  Delete: {results['delete']}")
    print(f"🏷️  Labeled: {results['labeled']}")
    
    if dry_run:
        print(f"\n💡 Run with --no-dry-run to apply")


if __name__ == "__main__":
    main()
