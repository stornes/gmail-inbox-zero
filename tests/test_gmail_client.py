"""Tests for inbox_zero.gmail_client with mocked HTTP responses."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from inbox_zero.gmail_client import GmailClient, MessageMetadata, _extract_email


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def token_file(tmp_path):
    """Create a temporary token JSON file."""
    token_data = {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "refresh_token": "test-refresh-token",
        "token": "old-access-token",
    }
    path = tmp_path / "gmail_token.json"
    path.write_text(json.dumps(token_data))
    return path


@pytest.fixture
def client(token_file):
    """Return a GmailClient pointed at the temp token file."""
    return GmailClient(token_path=token_file)


# ---------------------------------------------------------------------------
# Token loading and refresh
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    def test_load_and_refresh_writes_new_token(self, client, token_file):
        """Successful refresh updates the token file and returns new token."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "new-access-token"}

        with patch("inbox_zero.gmail_client.requests.post", return_value=mock_resp) as mock_post:
            token = client.load_and_refresh_token()

        assert token == "new-access-token"
        saved = json.loads(token_file.read_text())
        assert saved["token"] == "new-access-token"

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["data"]["grant_type"] == "refresh_token"

    def test_load_keeps_old_token_on_failed_refresh(self, client, token_file):
        """If refresh fails, the existing token is still returned."""
        mock_resp = MagicMock()
        mock_resp.ok = False

        with patch("inbox_zero.gmail_client.requests.post", return_value=mock_resp):
            token = client.load_and_refresh_token()

        assert token == "old-access-token"

    def test_missing_token_file_raises(self, tmp_path):
        """FileNotFoundError when the token file doesn't exist."""
        c = GmailClient(token_path=tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError):
            c.load_and_refresh_token()


# ---------------------------------------------------------------------------
# search_messages pagination
# ---------------------------------------------------------------------------

class TestSearchMessages:
    def _make_client_with_token(self, token_file):
        c = GmailClient(token_path=token_file)
        c._access_token = "test-token"
        return c

    def test_single_page(self, token_file):
        client = self._make_client_with_token(token_file)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "messages": [{"id": "1", "threadId": "t1"}, {"id": "2", "threadId": "t2"}],
        }

        with patch("inbox_zero.gmail_client.requests.get", return_value=mock_resp):
            results = client.search_messages("in:inbox", max_results=10)

        assert len(results) == 2

    def test_multi_page(self, token_file):
        client = self._make_client_with_token(token_file)

        page1 = MagicMock()
        page1.raise_for_status = MagicMock()
        page1.json.return_value = {
            "messages": [{"id": str(i), "threadId": f"t{i}"} for i in range(100)],
            "nextPageToken": "page2",
        }
        page2 = MagicMock()
        page2.raise_for_status = MagicMock()
        page2.json.return_value = {
            "messages": [{"id": str(i), "threadId": f"t{i}"} for i in range(100, 150)],
        }

        with patch("inbox_zero.gmail_client.requests.get", side_effect=[page1, page2]):
            results = client.search_messages("in:inbox", max_results=500)

        assert len(results) == 150

    def test_max_results_cap(self, token_file):
        client = self._make_client_with_token(token_file)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "messages": [{"id": str(i), "threadId": f"t{i}"} for i in range(50)],
        }

        with patch("inbox_zero.gmail_client.requests.get", return_value=mock_resp):
            results = client.search_messages("in:inbox", max_results=10)

        # Should be capped at max_results
        assert len(results) == 10


# ---------------------------------------------------------------------------
# archive_messages batching
# ---------------------------------------------------------------------------

class TestArchiveMessages:
    def test_empty_list_returns_zero(self, token_file):
        client = GmailClient(token_path=token_file)
        client._access_token = "tok"
        assert client.archive_messages([]) == 0

    def test_single_batch(self, token_file):
        client = GmailClient(token_path=token_file)
        client._access_token = "tok"
        ids = [str(i) for i in range(5)]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {}

        with patch("inbox_zero.gmail_client.requests.post", return_value=mock_resp) as mock_post:
            count = client.archive_messages(ids)

        assert count == 5
        assert mock_post.call_count == 1

    def test_multiple_batches(self, token_file):
        client = GmailClient(token_path=token_file)
        client._access_token = "tok"
        ids = [str(i) for i in range(5)]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {}

        with patch("inbox_zero.gmail_client.requests.post", return_value=mock_resp) as mock_post:
            count = client.archive_messages(ids, batch_size=2)

        assert count == 5
        # 5 items / batch_size 2 = 3 POST calls
        assert mock_post.call_count == 3


# ---------------------------------------------------------------------------
# MessageMetadata construction
# ---------------------------------------------------------------------------

class TestMessageMetadata:
    def test_basic_construction(self):
        m = MessageMetadata(
            id="abc",
            thread_id="t1",
            from_address="Foo <foo@bar.com>",
            from_email="foo@bar.com",
            subject="Hello",
            snippet="Preview text",
            label_ids=["INBOX", "STARRED"],
            is_starred=True,
        )
        assert m.id == "abc"
        assert m.is_starred is True

    def test_defaults(self):
        m = MessageMetadata(
            id="x",
            thread_id="tx",
            from_address="",
            from_email="",
            subject="",
            snippet="",
        )
        assert m.label_ids == []
        assert m.is_starred is False

    def test_get_message_metadata_parses_response(self, token_file):
        client = GmailClient(token_path=token_file)
        client._access_token = "tok"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Hello world",
            "labelIds": ["INBOX", "STARRED"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "Subject", "value": "Test subject"},
                ],
            },
        }

        with patch("inbox_zero.gmail_client.requests.get", return_value=mock_resp):
            meta = client.get_message_metadata("msg1")

        assert meta.id == "msg1"
        assert meta.thread_id == "thread1"
        assert meta.from_email == "alice@example.com"
        assert meta.from_address == "Alice <alice@example.com>"
        assert meta.subject == "Test subject"
        assert meta.is_starred is True


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

class TestExtractEmail:
    def test_angle_brackets(self):
        assert _extract_email("Alice <alice@foo.com>") == "alice@foo.com"

    def test_bare_email(self):
        assert _extract_email("bob@bar.com") == "bob@bar.com"

    def test_no_email(self):
        assert _extract_email("unknown") == "unknown"
