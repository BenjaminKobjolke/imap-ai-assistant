"""Tests for FolderBrowser — folder hierarchy, pagination, email listing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ai.openai_client import OpenAIClient
from src.browse.folder_browser import (
    PAGE_SIZE,
    FolderBrowser,
    _children_at_level,
    _display_name,
)
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient

# ---------------------------------------------------------------------------
# Folder hierarchy helpers
# ---------------------------------------------------------------------------

class TestChildrenAtLevel:
    """Tests for _children_at_level."""

    def test_root_level(self) -> None:
        """Root level returns only top-level folders (no slash)."""
        folders = ["INBOX", "Company", "Company/Sales", "Company/HR", "Sent"]
        result = _children_at_level(folders, parent=None)
        assert result == ["INBOX", "Company", "Sent"]

    def test_sub_level(self) -> None:
        """Sub-level returns immediate children of the parent."""
        folders = ["Company", "Company/Sales", "Company/HR", "Company/HR/Archive"]
        result = _children_at_level(folders, parent="Company")
        assert result == ["Company/Sales", "Company/HR"]

    def test_deep_nesting(self) -> None:
        """Only direct children are returned, not grandchildren."""
        folders = ["A", "A/B", "A/B/C", "A/B/D", "A/E"]
        result = _children_at_level(folders, parent="A")
        assert result == ["A/B", "A/E"]

    def test_no_children(self) -> None:
        """Leaf folder returns empty list."""
        folders = ["INBOX", "Sent"]
        result = _children_at_level(folders, parent="INBOX")
        assert result == []

    def test_empty_folders(self) -> None:
        """Empty folder list returns empty at any level."""
        assert _children_at_level([], parent=None) == []
        assert _children_at_level([], parent="INBOX") == []


class TestDisplayName:
    """Tests for _display_name."""

    def test_simple_folder(self) -> None:
        """Folder with no slash returns itself."""
        assert _display_name("INBOX") == "INBOX"

    def test_nested_folder(self) -> None:
        """Nested folder returns only the last segment."""
        assert _display_name("Company/Sales") == "Sales"

    def test_deeply_nested(self) -> None:
        """Deeply nested folder returns only the leaf segment."""
        assert _display_name("A/B/C/D") == "D"


# ---------------------------------------------------------------------------
# FolderBrowser.browse
# ---------------------------------------------------------------------------

def _browser(folders: list[str] | None = None) -> FolderBrowser:
    """Create a FolderBrowser with mocked dependencies."""
    client = MagicMock(spec=EnhancedImapClient)
    inner = MagicMock()
    client.client = inner

    if folders is not None:
        inner.list_folders.return_value = folders
    else:
        inner.list_folders.return_value = ["INBOX", "Sent", "Drafts"]

    config = MagicMock(spec=ConfigManager)
    config.search_cache_path = ":memory:"
    openai_client = MagicMock(spec=OpenAIClient)

    return FolderBrowser(client, config, openai_client)


class TestBrowse:
    """Tests for FolderBrowser.browse entry point."""

    @patch("src.browse.folder_browser.send_output")
    def test_browse_empty_folders(self, mock_output: MagicMock) -> None:
        """Browse exits gracefully when there are no folders."""
        browser = _browser(folders=[])
        browser.browse()

        mock_output.assert_called_with("No folders found.")

    @patch("src.browse.folder_browser.send_output")
    def test_browse_list_folders_error(self, mock_output: MagicMock) -> None:
        """Browse exits gracefully when listing folders fails."""
        browser = _browser()
        browser._client.client.list_folders.side_effect = Exception("Connection lost")

        browser.browse()

        assert any("Could not list folders" in str(c) for c in mock_output.call_args_list)

    @patch("src.browse.folder_browser.SchedulerChoice")
    @patch("src.browse.folder_browser.send_output")
    def test_browse_back_at_root_exits(self, mock_output: MagicMock, mock_choice_cls: MagicMock) -> None:
        """Selecting Back at root level exits browsing."""
        browser = _browser(folders=["INBOX", "Sent"])

        mock_choice = MagicMock()
        mock_choice.choose.return_value = "__back__"
        mock_choice_cls.return_value = mock_choice

        browser.browse()

        # Should have shown folder count
        assert any("2 folder(s)" in str(c) for c in mock_output.call_args_list)


class TestBrowseEmails:
    """Tests for email listing within a folder."""

    @patch("src.browse.folder_browser.SchedulerChoice")
    @patch("src.browse.folder_browser.send_output")
    def test_no_emails_in_folder(self, mock_output: MagicMock, mock_choice_cls: MagicMock) -> None:
        """Empty folder shows 'No emails' message."""
        browser = _browser(folders=["INBOX"])
        browser._client.client.get_all_messages.return_value = []

        browser._browse_emails("INBOX")

        mock_output.assert_any_call("  No emails in this folder.")

    @patch("src.browse.folder_browser.SchedulerChoice")
    @patch("src.browse.folder_browser.send_output")
    def test_email_listing_shows_count(self, mock_output: MagicMock, mock_choice_cls: MagicMock) -> None:
        """Email listing displays the total count."""
        browser = _browser(folders=["INBOX"])

        msg1 = MagicMock()
        msg1.from_address = "alice@example.com"
        msg1.subject = "Hello"
        msg1.date = "2026-03-01"
        browser._client.client.get_all_messages.return_value = [(1, msg1)]

        mock_choice = MagicMock()
        mock_choice.choose.return_value = "__back__"
        mock_choice_cls.return_value = mock_choice

        browser._browse_emails("INBOX")

        assert any("1 email(s) found" in str(c) for c in mock_output.call_args_list)


class TestEmailActions:
    """Tests for email action menu."""

    @patch("src.browse.folder_browser.email_action_loop")
    def test_show_body_action(
        self,
        mock_action_loop: MagicMock,
    ) -> None:
        """Selecting 'show_body' is handled by email_action_loop (returns None = back)."""
        browser = _browser()
        mock_action_loop.return_value = None

        msg = MagicMock()
        msg.from_address = "bob@example.com"
        msg.subject = "Test"

        browser._email_actions("INBOX", 42, msg)

        mock_action_loop.assert_called_once_with(
            browser._client, browser._config, "INBOX", "42",
            extra_actions=[("Draft reply", "draft_reply")],
        )

    @patch("src.browse.folder_browser.DraftReplyHandler")
    @patch("src.browse.folder_browser.SearchCache")
    @patch("src.browse.folder_browser.EmailBodyViewer")
    @patch("src.browse.folder_browser.email_action_loop")
    def test_draft_reply_action(
        self,
        mock_action_loop: MagicMock,
        mock_viewer: MagicMock,
        mock_cache_cls: MagicMock,
        mock_handler_cls: MagicMock,
    ) -> None:
        """When email_action_loop returns 'draft_reply', DraftReplyHandler is called."""
        browser = _browser()

        # First call returns "draft_reply", second call returns None (back)
        mock_action_loop.side_effect = ["draft_reply", None]
        mock_viewer.get_body_excerpt.return_value = "Body text"

        msg = MagicMock()
        msg.from_address = "bob@example.com"
        msg.subject = "Test"

        browser._email_actions("INBOX", 42, msg)

        mock_handler_cls.return_value.draft_reply.assert_called_once_with(
            "bob@example.com", "Test", "Body text",
        )

    @patch("src.browse.folder_browser.email_action_loop")
    def test_back_action(
        self,
        mock_action_loop: MagicMock,
    ) -> None:
        """When email_action_loop returns None, _email_actions returns."""
        browser = _browser()
        mock_action_loop.return_value = None

        msg = MagicMock()
        browser._email_actions("INBOX", 1, msg)

        # No assertions needed — just verify no exception and it returned


class TestPageSize:
    """Verify the PAGE_SIZE constant."""

    def test_page_size_is_five(self) -> None:
        """PAGE_SIZE should be 5 as specified."""
        assert PAGE_SIZE == 5
