"""Tests for the shared folder_picker module."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from src.search.folder_picker import folder_search_loop, pick_from_matches


# ===================================================================
# pick_from_matches
# ===================================================================


class TestPickFromMatches:
    """Tests for pick_from_matches."""

    @patch("src.search.folder_picker.SchedulerChoice")
    def test_returns_selected_folder(self, mock_cls: MagicMock) -> None:
        """When user picks a folder, it is returned."""
        mock_cls.return_value.choose.return_value = "Company/Sales"

        result = pick_from_matches(["Company/Sales", "Company/HR"])

        assert result == "Company/Sales"

    @patch("src.search.folder_picker.SchedulerChoice")
    def test_search_again_returns_none(self, mock_cls: MagicMock) -> None:
        """When user picks 'Search again', None is returned."""
        mock_cls.return_value.choose.return_value = "search_again"

        result = pick_from_matches(["Company/Sales"])

        assert result is None

    @patch("src.search.folder_picker.SchedulerChoice")
    def test_abort_returns_sentinel_when_allowed(self, mock_cls: MagicMock) -> None:
        """When allow_abort=True and user aborts, _abort_ sentinel is returned."""
        mock_cls.return_value.choose.return_value = "abort"

        result = pick_from_matches(["INBOX"], allow_abort=True)

        assert result == "_abort_"
        mock_cls.assert_called_once()
        # Verify abort=True was passed
        _, kwargs = mock_cls.call_args
        assert kwargs["abort"] is True

    @patch("src.search.folder_picker.SchedulerChoice")
    def test_abort_not_available_when_disallowed(self, mock_cls: MagicMock) -> None:
        """When allow_abort=False, abort is not offered."""
        mock_cls.return_value.choose.return_value = "INBOX"

        pick_from_matches(["INBOX"], allow_abort=False)

        _, kwargs = mock_cls.call_args
        assert kwargs["abort"] is False


# ===================================================================
# folder_search_loop
# ===================================================================


class TestFolderSearchLoop:
    """Tests for folder_search_loop."""

    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_cancel_returns_none(
        self, mock_ask: MagicMock, _mock_pick: MagicMock,
    ) -> None:
        """Typing 'cancel' returns None without showing matches."""
        mock_ask.return_value = "cancel"

        result = folder_search_loop(["INBOX", "Sent"])

        assert result is None

    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_empty_input_returns_none(
        self, mock_ask: MagicMock, _mock_pick: MagicMock,
    ) -> None:
        """Empty input returns None."""
        mock_ask.return_value = ""

        result = folder_search_loop(["INBOX"])

        assert result is None

    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_abort_returns_sentinel_when_allowed(
        self, mock_ask: MagicMock, _mock_pick: MagicMock,
    ) -> None:
        """Typing 'abort' with allow_abort=True returns the sentinel."""
        mock_ask.return_value = "abort"

        result = folder_search_loop(["INBOX"], allow_abort=True)

        assert result == "_abort_"

    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_abort_treated_as_search_term_when_disallowed(
        self, mock_ask: MagicMock, mock_pick: MagicMock,
    ) -> None:
        """Typing 'abort' with allow_abort=False treats it as a search term."""
        # First call: user types "abort" which matches nothing
        # Second call: user types "cancel" to exit
        mock_ask.side_effect = ["abort", "cancel"]
        mock_pick.return_value = None

        result = folder_search_loop(["INBOX"])

        # "abort" doesn't match any folder, so it shows "no matches"
        # then "cancel" exits
        assert result is None

    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_matching_folder_returned(
        self, mock_ask: MagicMock, mock_pick: MagicMock,
    ) -> None:
        """When user searches and picks a folder, it is returned."""
        mock_ask.return_value = "sale"
        mock_pick.return_value = "Company/Sales"

        result = folder_search_loop(["Company/Sales", "Company/HR", "INBOX"])

        assert result == "Company/Sales"

    @patch("src.search.folder_picker.send_output")
    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_no_matches_loops(
        self, mock_ask: MagicMock, mock_pick: MagicMock, mock_output: MagicMock,
    ) -> None:
        """When no folders match, the loop continues with 'Try again'."""
        # First search: no match; second search: cancel
        mock_ask.side_effect = ["zzz", "cancel"]

        result = folder_search_loop(["INBOX", "Sent"])

        assert result is None
        # Verify "No folders matching" message was shown
        mock_output.assert_any_call("  No folders matching 'zzz'. Try again.")

    @patch("src.search.folder_picker.send_output")
    @patch("src.search.folder_picker.pick_from_matches")
    @patch("src.search.folder_picker.scheduler_ask")
    def test_too_many_matches_truncated(
        self, mock_ask: MagicMock, mock_pick: MagicMock, mock_output: MagicMock,
    ) -> None:
        """When more than 5 folders match, only first 5 are shown."""
        folders = [f"Company/Dept{i}" for i in range(10)]
        mock_ask.return_value = "dept"
        mock_pick.return_value = "Company/Dept0"

        result = folder_search_loop(folders)

        assert result == "Company/Dept0"
        # pick_from_matches should receive only 5 items
        actual_matches = mock_pick.call_args[0][0]
        assert len(actual_matches) == 5
