"""Tests for EmailBodyViewer — shared body fetching and display utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.constants import MIME_TEXT_HTML, MIME_TEXT_PLAIN
from src.email.email_body_viewer import EmailBodyViewer
from src.email.imap_client import EnhancedImapClient


# ---------------------------------------------------------------------------
# show_body
# ---------------------------------------------------------------------------

class TestShowBody:
    """Tests for EmailBodyViewer.show_body."""

    @patch("src.email.email_body_viewer.send_output")
    @patch("src.email.email_body_viewer.EmailMessage")
    def test_show_body_plain_text(self, mock_email_cls: MagicMock, mock_output: MagicMock) -> None:
        """Plain text body is displayed between separator lines."""
        client = MagicMock(spec=EnhancedImapClient)
        inner = MagicMock()
        client.client = inner
        raw_data = b"raw email bytes"
        inner.client.fetch.return_value = {42: {b"BODY[]": raw_data}}

        mock_msg = MagicMock()
        mock_msg.get_body.side_effect = lambda ct: "Hello world" if ct == MIME_TEXT_PLAIN else None
        mock_email_cls.from_bytes.return_value = mock_msg

        EmailBodyViewer.show_body(client, "INBOX", "42")

        inner.client.select_folder.assert_called_once_with("INBOX")
        assert any("Hello world" in str(call) for call in mock_output.call_args_list)

    @patch("src.email.email_body_viewer.send_output")
    @patch("src.email.email_body_viewer.EmailMessage")
    def test_show_body_html_fallback(self, mock_email_cls: MagicMock, mock_output: MagicMock) -> None:
        """When no plain text, HTML is stripped of tags and shown."""
        client = MagicMock(spec=EnhancedImapClient)
        inner = MagicMock()
        client.client = inner
        raw_data = b"raw email bytes"
        inner.client.fetch.return_value = {42: {b"BODY[]": raw_data}}

        mock_msg = MagicMock()
        mock_msg.get_body.side_effect = lambda ct: (
            None if ct == MIME_TEXT_PLAIN else "<b>Bold</b> text"
        )
        mock_email_cls.from_bytes.return_value = mock_msg

        EmailBodyViewer.show_body(client, "INBOX", "42")

        assert any("Bold text" in str(call) for call in mock_output.call_args_list)

    @patch("src.email.email_body_viewer.send_output")
    def test_show_body_fetch_empty(self, mock_output: MagicMock) -> None:
        """When fetch returns empty, a message is shown."""
        client = MagicMock(spec=EnhancedImapClient)
        inner = MagicMock()
        client.client = inner
        inner.client.fetch.return_value = {}

        EmailBodyViewer.show_body(client, "INBOX", "42")

        mock_output.assert_called_once_with("  Could not fetch email body.")

    @patch("src.email.email_body_viewer.send_output")
    @patch("src.email.email_body_viewer.EmailMessage")
    def test_show_body_empty_body(self, mock_email_cls: MagicMock, mock_output: MagicMock) -> None:
        """When email has no body at all, shows empty message."""
        client = MagicMock(spec=EnhancedImapClient)
        inner = MagicMock()
        client.client = inner
        raw_data = b"raw email bytes"
        inner.client.fetch.return_value = {42: {b"BODY[]": raw_data}}

        mock_msg = MagicMock()
        mock_msg.get_body.return_value = None
        mock_email_cls.from_bytes.return_value = mock_msg

        EmailBodyViewer.show_body(client, "INBOX", "42")

        mock_output.assert_called_with("  (empty body)")


# ---------------------------------------------------------------------------
# get_body_excerpt
# ---------------------------------------------------------------------------

class TestGetBodyExcerpt:
    """Tests for EmailBodyViewer.get_body_excerpt."""

    def test_plain_text_body(self) -> None:
        """Plain text body is returned truncated to max_chars."""
        msg = MagicMock()
        msg.get_body.side_effect = lambda ct: "A" * 1000 if ct == MIME_TEXT_PLAIN else None

        result = EmailBodyViewer.get_body_excerpt(msg, max_chars=100)

        assert len(result) == 100
        assert result == "A" * 100

    def test_html_fallback(self) -> None:
        """When no plain text, HTML is stripped and returned."""
        msg = MagicMock()
        msg.get_body.side_effect = lambda ct: (
            None if ct == MIME_TEXT_PLAIN else "<p>Hello</p>"
        )

        result = EmailBodyViewer.get_body_excerpt(msg)

        assert result == "Hello"

    def test_no_body_returns_placeholder(self) -> None:
        """When no body at all, returns placeholder string."""
        msg = MagicMock()
        msg.get_body.return_value = None

        result = EmailBodyViewer.get_body_excerpt(msg)

        assert result == "(no body content)"

    def test_no_get_body_method(self) -> None:
        """Objects without get_body return the placeholder."""
        msg = object()

        result = EmailBodyViewer.get_body_excerpt(msg)

        assert result == "(no body content)"

    def test_default_max_chars(self) -> None:
        """Default max_chars is 800."""
        msg = MagicMock()
        msg.get_body.side_effect = lambda ct: "X" * 2000 if ct == MIME_TEXT_PLAIN else None

        result = EmailBodyViewer.get_body_excerpt(msg)

        assert len(result) == 800
