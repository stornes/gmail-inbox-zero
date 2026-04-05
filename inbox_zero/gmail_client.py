"""Thin Gmail API wrapper. No business logic."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_TOKEN_PATH = Path.home() / ".openclaw" / "tokens" / "gmail_token.json"


@dataclass
class MessageMetadata:
    id: str
    thread_id: str
    from_address: str
    from_email: str
    subject: str
    snippet: str
    label_ids: list[str] = field(default_factory=list)
    is_starred: bool = False


class GmailClient:
    """Thin wrapper around Gmail REST API using requests."""

    def __init__(self, token_path: Optional[Path] = None):
        self.token_path = token_path or DEFAULT_TOKEN_PATH
        self._access_token: Optional[str] = None
        self._label_cache: dict[str, str] = {}

    # -- auth ----------------------------------------------------------------

    def load_and_refresh_token(self) -> str:
        """Load OAuth token from disk and refresh it. Returns access token."""
        if not self.token_path.exists():
            raise FileNotFoundError(
                f"No token found at {self.token_path}. Run gmail_auth.py first."
            )

        with open(self.token_path) as f:
            token_data = json.load(f)

        resp = requests.post(TOKEN_ENDPOINT, data={
            "client_id": token_data["client_id"],
            "client_secret": token_data["client_secret"],
            "refresh_token": token_data["refresh_token"],
            "grant_type": "refresh_token",
        })
        if resp.ok:
            refreshed = resp.json()
            token_data["token"] = refreshed["access_token"]
            with open(self.token_path, "w") as f:
                json.dump(token_data, f, indent=2)

        self._access_token = token_data["token"]
        return self._access_token

    @property
    def access_token(self) -> str:
        if self._access_token is None:
            return self.load_and_refresh_token()
        return self._access_token

    # -- low-level helpers ---------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        resp = requests.get(
            f"{API_BASE}/{endpoint}",
            headers=self._headers(),
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, body: Optional[dict] = None) -> dict:
        resp = requests.post(
            f"{API_BASE}/{endpoint}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=body or {},
        )
        resp.raise_for_status()
        return resp.json()

    # -- public API ----------------------------------------------------------

    def get_profile(self) -> dict:
        """Return the authenticated user's Gmail profile."""
        return self._get("profile")

    def search_messages(self, query: str, max_results: int = 500) -> list[dict]:
        """Search Gmail, returning list of {id, threadId} dicts with pagination."""
        messages: list[dict] = []
        page_token: Optional[str] = None

        while len(messages) < max_results:
            params: dict = {
                "q": query,
                "maxResults": min(100, max_results - len(messages)),
            }
            if page_token:
                params["pageToken"] = page_token

            data = self._get("messages", params)
            batch = data.get("messages", [])
            messages.extend(batch)

            page_token = data.get("nextPageToken")
            if not page_token or not batch:
                break

        return messages[:max_results]

    def get_message_metadata(self, msg_id: str) -> MessageMetadata:
        """Fetch metadata-only view of a single message."""
        resp = requests.get(
            f"{API_BASE}/messages/{msg_id}",
            headers=self._headers(),
            params=[
                ("format", "metadata"),
                ("metadataHeaders", "From"),
                ("metadataHeaders", "Subject"),
            ],
        )
        resp.raise_for_status()
        data = resp.json()

        headers_list = data.get("payload", {}).get("headers", [])
        headers = {h["name"]: h["value"] for h in headers_list}
        from_raw = headers.get("From", "")
        from_email = _extract_email(from_raw)
        label_ids = data.get("labelIds", [])

        return MessageMetadata(
            id=data["id"],
            thread_id=data.get("threadId", ""),
            from_address=from_raw,
            from_email=from_email,
            subject=headers.get("Subject", "(no subject)"),
            snippet=data.get("snippet", ""),
            label_ids=label_ids,
            is_starred="STARRED" in label_ids,
        )

    def get_message_labels(self, msg_id: str) -> list[str]:
        """Return label IDs for a message."""
        data = self._get(f"messages/{msg_id}", {"format": "minimal"})
        return data.get("labelIds", [])

    def list_labels(self) -> list[dict]:
        """Return all labels in the mailbox."""
        data = self._get("labels")
        return data.get("labels", [])

    def archive_messages(self, msg_ids: list[str], batch_size: int = 1000) -> int:
        """Archive messages by removing INBOX label. Returns count processed."""
        if not msg_ids:
            return 0
        for i in range(0, len(msg_ids), batch_size):
            batch = msg_ids[i : i + batch_size]
            self._post("messages/batchModify", {
                "ids": batch,
                "removeLabelIds": ["INBOX"],
            })
        return len(msg_ids)

    def delete_messages(self, msg_ids: list[str], batch_size: int = 100) -> int:
        """Trash messages one by one (safer). Returns count processed."""
        if not msg_ids:
            return 0
        count = 0
        for msg_id in msg_ids[:batch_size]:
            try:
                self._post(f"messages/{msg_id}/trash", {})
                count += 1
            except Exception:
                pass
        return count

    def label_and_archive(
        self, msg_ids: list[str], label_name: str, batch_size: int = 1000
    ) -> int:
        """Add a label and archive messages. Returns count processed."""
        if not msg_ids:
            return 0

        label_id = self.get_or_create_label(label_name)

        for i in range(0, len(msg_ids), batch_size):
            batch = msg_ids[i : i + batch_size]
            self._post("messages/batchModify", {
                "ids": batch,
                "addLabelIds": [label_id],
                "removeLabelIds": ["INBOX"],
            })
        return len(msg_ids)

    def get_or_create_label(self, label_name: str) -> str:
        """Return existing label ID or create a new one."""
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        labels = self.list_labels()
        for label in labels:
            if label["name"] == label_name:
                self._label_cache[label_name] = label["id"]
                return label["id"]

        created = self._post("labels", {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        })
        label_id = created["id"]
        self._label_cache[label_name] = label_id
        return label_id

    def has_sent_to(self, email: str) -> bool:
        """Check whether the authenticated user has ever sent mail to *email*."""
        results = self.search_messages(f"in:sent to:{email}", max_results=1)
        return len(results) > 0


def _extract_email(from_header: str) -> str:
    """Pull bare email from a From header like 'Name <foo@bar.com>'."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).lower()
    # Might already be bare email
    if "@" in from_header:
        return from_header.strip().lower()
    return from_header
