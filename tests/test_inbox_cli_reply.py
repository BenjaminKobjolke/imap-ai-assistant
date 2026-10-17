"""Tests for InboxCli reply operations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.processors.draft_email_builder import DraftEmailBuilder
from src.processors.inbox_cli import InboxCli
from src.search.search_cache import SearchCache
from tests.inbox_cli_helpers import make_client, make_config, make_email


# ===================================================================
# prepare_reply
# ===================================================================

class TestPrepareReply:
    """Tests for InboxCli.prepare_reply."""

    @patch("src.search.search_cache.SearchCache")
    @patch.object(InboxCli, "_connect")
    def test_outputs_email_and_salutation(
        self, mock_connect: MagicMock, mock_cache_cls: MagicMock, capsys: object,
    ) -> None:
        """Outputs from, subject, date, salutation, and body."""
        messages = [(5, make_email(
            subject="Project Update",
            from_address="alice@corp.com",
            date="2026-03-09",
        ))]
        client = make_client(messages)
        mock_connect.return_value = client

        mock_cache = MagicMock()
        mock_cache.get_salutation.return_value = {
            "salutation": "Frau Mueller",
            "is_formal": True,
            "skip_greeting": False,
        }
        mock_cache_cls.return_value = mock_cache

        config = make_config()
        config.search_cache_path = "test_cache.db"
        cli = InboxCli(config)
        cli.prepare_reply("5")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "alice@corp.com" in captured.out
        assert "Project Update" in captured.out
        assert "2026-03-09" in captured.out
        assert "Frau Mueller (formal)" in captured.out
        assert "--- Body ---" in captured.out
        assert "Hello, this is the body." in captured.out
        client.disconnect.assert_called_once()

    @patch("src.search.search_cache.SearchCache")
    @patch.object(InboxCli, "_connect")
    def test_unknown_salutation(
        self, mock_connect: MagicMock, mock_cache_cls: MagicMock, capsys: object,
    ) -> None:
        """Shows 'unknown' when no salutation cached."""
        messages = [(1, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        mock_cache = MagicMock()
        mock_cache.get_salutation.return_value = None
        mock_cache_cls.return_value = mock_cache

        config = make_config()
        config.search_cache_path = "test_cache.db"
        cli = InboxCli(config)
        cli.prepare_reply("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Salutation: unknown" in captured.out

    @patch.object(InboxCli, "_connect")
    def test_invalid_id(self, mock_connect: MagicMock, capsys: object) -> None:
        """Unknown ID prints error."""
        client = make_client([(1, make_email())])
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.prepare_reply("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out


# ===================================================================
# save_draft_reply
# ===================================================================

class TestSaveDraftReply:
    """Tests for InboxCli.save_draft_reply."""

    @patch.object(DraftEmailBuilder, "load_footer_html", return_value="<footer/>")
    @patch.object(DraftEmailBuilder, "build_and_save", return_value=True)
    @patch.object(InboxCli, "_connect")
    def test_saves_draft_successfully(
        self,
        mock_connect: MagicMock,
        mock_build: MagicMock,
        mock_footer: MagicMock,
        capsys: object,
    ) -> None:
        """Saves draft and prints confirmation."""
        messages = [(3, make_email(subject="Hello World", from_address="bob@test.com"))]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.save_draft_reply("3", "Sehr geehrter Herr Bob,\n\nDanke!")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Draft saved" in captured.out
        assert "Re: Hello World" in captured.out
        mock_build.assert_called_once()
        client.disconnect.assert_called_once()

    @patch.object(DraftEmailBuilder, "load_footer_html", return_value="")
    @patch.object(DraftEmailBuilder, "build_and_save", return_value=False)
    @patch.object(InboxCli, "_connect")
    def test_draft_save_failure(
        self,
        mock_connect: MagicMock,
        mock_build: MagicMock,
        mock_footer: MagicMock,
        capsys: object,
    ) -> None:
        """Prints failure message when draft save fails."""
        messages = [(3, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.save_draft_reply("3", "Reply text")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Failed to save draft" in captured.out

    @patch.object(InboxCli, "_connect")
    def test_invalid_id(self, mock_connect: MagicMock, capsys: object) -> None:
        """Unknown ID prints error."""
        client = make_client([(1, make_email())])
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.save_draft_reply("999", "Reply text")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out


# ===================================================================
# save_salutation
# ===================================================================

class TestSaveSalutation:
    """Tests for InboxCli.save_salutation."""

    @patch("src.search.search_cache.SearchCache")
    def test_saves_formal(self, mock_cache_cls: MagicMock, capsys: object) -> None:
        """Saves formal salutation to cache."""
        mock_cache = MagicMock(spec=SearchCache)
        mock_cache_cls.return_value = mock_cache

        config = make_config()
        config.search_cache_path = "test_cache.db"
        cli = InboxCli(config)
        cli.save_salutation("alice@corp.com", "Frau Mueller", is_formal=True)

        mock_cache.save_salutation.assert_called_once_with(
            "alice@corp.com", "Frau Mueller", is_formal=True,
        )
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Salutation saved" in captured.out
        assert "formal" in captured.out

    @patch("src.search.search_cache.SearchCache")
    def test_saves_informal(self, mock_cache_cls: MagicMock, capsys: object) -> None:
        """Saves informal salutation to cache."""
        mock_cache = MagicMock(spec=SearchCache)
        mock_cache_cls.return_value = mock_cache

        config = make_config()
        config.search_cache_path = "test_cache.db"
        cli = InboxCli(config)
        cli.save_salutation("bob@test.com", "Bob", is_formal=False)

        mock_cache.save_salutation.assert_called_once_with(
            "bob@test.com", "Bob", is_formal=False,
        )
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "informal" in captured.out


# ===================================================================
# prepare_reply — sent email excerpts
# ===================================================================

class TestPrepareReplySentEmails:
    """Tests for sent email excerpts in prepare_reply."""

    @patch("src.search.search_cache.SearchCache")
    @patch.object(InboxCli, "_search_sent_excerpts")
    @patch.object(InboxCli, "_connect")
    def test_includes_sent_emails_when_unknown(
        self,
        mock_connect: MagicMock,
        mock_search_sent: MagicMock,
        mock_cache_cls: MagicMock,
        capsys: object,
    ) -> None:
        """When salutation is unknown, sent email excerpts are included."""
        messages = [(5, make_email(from_address="tamara@corp.com"))]
        client = make_client(messages)
        mock_connect.return_value = client

        mock_cache = MagicMock()
        mock_cache.get_salutation.return_value = None
        mock_cache_cls.return_value = mock_cache

        mock_search_sent.return_value = [
            "Hallo Tamara, danke fuer die schnelle Rueckmeldung.",
            "Hallo Tamara, hier die gewuenschten Unterlagen.",
        ]

        config = make_config()
        config.search_cache_path = "test_cache.db"
        cli = InboxCli(config)
        cli.prepare_reply("5")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Salutation: unknown" in captured.out
        assert "--- Sent Emails to tamara@corp.com ---" in captured.out
        assert "[1]" in captured.out
        assert "[2]" in captured.out
        assert "Hallo Tamara" in captured.out

    @patch("src.search.search_cache.SearchCache")
    @patch.object(InboxCli, "_search_sent_excerpts")
    @patch.object(InboxCli, "_connect")
    def test_no_sent_emails_section_when_known(
        self,
        mock_connect: MagicMock,
        mock_search_sent: MagicMock,
        mock_cache_cls: MagicMock,
        capsys: object,
    ) -> None:
        """When salutation is known, no sent email search is performed."""
        messages = [(5, make_email(from_address="alice@corp.com"))]
        client = make_client(messages)
        mock_connect.return_value = client

        mock_cache = MagicMock()
        mock_cache.get_salutation.return_value = {
            "salutation": "Frau Mueller",
            "is_formal": True,
            "skip_greeting": False,
        }
        mock_cache_cls.return_value = mock_cache

        config = make_config()
        config.search_cache_path = "test_cache.db"
        cli = InboxCli(config)
        cli.prepare_reply("5")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Frau Mueller (formal)" in captured.out
        assert "Sent Emails" not in captured.out
        mock_search_sent.assert_not_called()
