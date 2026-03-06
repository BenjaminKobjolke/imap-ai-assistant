"""Tests for EmailAttachmentViewer — attachment listing and downloading."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config.settings import ConfigManager
from src.email.email_attachment_viewer import EmailAttachmentViewer
from src.email.imap_client import EnhancedImapClient


def _make_attachment(filename: str = "doc.pdf", content_type: str = "application/pdf", data: bytes = b"pdf-bytes") -> MagicMock:
    att = MagicMock()
    att.filename = filename
    att.content_type = content_type
    att.data = data
    return att


class TestShowAttachments:
    """Tests for EmailAttachmentViewer.show_attachments."""

    @patch("src.email.email_attachment_viewer.send_output")
    @patch("src.email.email_attachment_viewer.EmailMessage")
    def test_no_attachments(self, mock_email_cls: MagicMock, mock_output: MagicMock) -> None:
        """Shows 'No attachments' when email has none."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)
        inner = MagicMock()
        client.client = inner
        inner.client.fetch.return_value = {42: {b"BODY[]": b"raw"}}

        mock_msg = MagicMock()
        mock_msg.attachments = []
        mock_email_cls.from_bytes.return_value = mock_msg

        EmailAttachmentViewer.show_attachments(client, config, "INBOX", "42")

        mock_output.assert_called_with("  No attachments.")

    @patch("src.email.email_attachment_viewer.send_output")
    def test_fetch_empty(self, mock_output: MagicMock) -> None:
        """Shows error when fetch returns empty."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)
        inner = MagicMock()
        client.client = inner
        inner.client.fetch.return_value = {}

        EmailAttachmentViewer.show_attachments(client, config, "INBOX", "42")

        mock_output.assert_called_with("  Could not fetch email.")

    @patch("src.email.email_attachment_viewer.SchedulerChoice")
    @patch("src.email.email_attachment_viewer.send_output")
    @patch("src.email.email_attachment_viewer.EmailMessage")
    def test_lists_attachments(self, mock_email_cls: MagicMock, mock_output: MagicMock, mock_choice_cls: MagicMock) -> None:
        """Lists attachments and shows choice menu."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)
        inner = MagicMock()
        client.client = inner
        inner.client.fetch.return_value = {42: {b"BODY[]": b"raw"}}

        att = _make_attachment("report.pdf", "application/pdf")
        mock_msg = MagicMock()
        mock_msg.attachments = [att]
        mock_email_cls.from_bytes.return_value = mock_msg

        # User picks "Back"
        mock_choice_cls.return_value.choose.return_value = "back"

        EmailAttachmentViewer.show_attachments(client, config, "INBOX", "42")

        assert any("report.pdf" in str(call) for call in mock_output.call_args_list)


class TestDownloadAttachment:
    """Tests for EmailAttachmentViewer._download_attachment."""

    @patch("src.email.email_attachment_viewer.send_output")
    def test_download_creates_file(self, mock_output: MagicMock, tmp_path: Path) -> None:
        """Downloads attachment to disk."""
        att = _make_attachment("notes.txt", "text/plain", b"hello world")

        EmailAttachmentViewer._download_attachment(att, tmp_path)

        saved = tmp_path / "notes.txt"
        assert saved.exists()
        assert saved.read_bytes() == b"hello world"
        assert any("Downloaded to" in str(call) for call in mock_output.call_args_list)

    @patch("src.email.email_attachment_viewer.send_output")
    def test_sanitizes_filename(self, mock_output: MagicMock, tmp_path: Path) -> None:
        """Unsafe characters in filename are replaced."""
        att = _make_attachment("my<file>.exe", "application/octet-stream", b"data")

        EmailAttachmentViewer._download_attachment(att, tmp_path)

        # The angle brackets should be replaced
        saved_files = list(tmp_path.iterdir())
        assert len(saved_files) == 1
        assert "<" not in saved_files[0].name
        assert ">" not in saved_files[0].name

    @patch("src.email.email_attachment_viewer.send_output")
    def test_creates_download_dir(self, mock_output: MagicMock, tmp_path: Path) -> None:
        """Creates download directory if it doesn't exist."""
        new_dir = tmp_path / "sub" / "dir"
        att = _make_attachment("file.txt", "text/plain", b"data")

        EmailAttachmentViewer._download_attachment(att, new_dir)

        assert new_dir.exists()
        assert (new_dir / "file.txt").exists()
