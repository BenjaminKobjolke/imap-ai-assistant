"""Tests for DraftComposer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ai.openai_client import OpenAIClient
from src.processors.draft_composer import DraftComposer, DraftContext


def _context() -> DraftContext:
    """Create a test DraftContext."""
    return DraftContext(
        original_subject="Test Subject",
        original_body="Test body content",
        original_from_address="sender@example.com",
        original_from_name="Sender",
        greeting="Hallo Herr Mueller",
    )


def _composer(openai_mock: MagicMock | None = None) -> DraftComposer:
    """Create a DraftComposer with mocked OpenAI."""
    mock = openai_mock or MagicMock(spec=OpenAIClient)
    return DraftComposer(mock)


class TestComposeConfirmFlow:
    """Tests for the confirm-immediately flow."""

    @patch("src.processors.draft_composer.SchedulerChoice")
    @patch("src.processors.draft_composer.scheduler_ask")
    @patch("src.processors.draft_composer.send_output")
    def test_confirm_immediately(
        self,
        _out: MagicMock,
        mock_ask: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """User gives instruction, confirms draft, grammar returns same text."""
        mock_ask.return_value = "write that I agree"
        # First choice: confirm, no grammar choice needed (same text)
        mock_choice_cls.return_value.choose.return_value = "confirm"

        ai = MagicMock(spec=OpenAIClient)
        ai.generate_draft_reply.return_value = "I agree with your proposal."
        ai.correct_grammar.return_value = "I agree with your proposal."

        result = _composer(ai).compose(_context())

        assert result == "I agree with your proposal."
        ai.generate_draft_reply.assert_called_once()
        ai.correct_grammar.assert_called_once()


class TestComposeNewInstruction:
    """Tests for the new-instruction flow."""

    @patch("src.processors.draft_composer.SchedulerChoice")
    @patch("src.processors.draft_composer.scheduler_ask")
    @patch("src.processors.draft_composer.send_output")
    def test_new_instruction_then_confirm(
        self,
        _out: MagicMock,
        mock_ask: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """User provides new instruction after first draft, then confirms."""
        mock_ask.side_effect = ["first instruction", "make it shorter"]
        mock_choice_cls.return_value.choose.side_effect = ["new_instruction", "confirm", "accept"]

        ai = MagicMock(spec=OpenAIClient)
        ai.generate_draft_reply.side_effect = ["Long draft text here.", "Short text."]
        ai.correct_grammar.return_value = "Short text corrected."

        result = _composer(ai).compose(_context())

        assert result == "Short text corrected."
        assert ai.generate_draft_reply.call_count == 2


class TestComposeCancel:
    """Tests for cancellation."""

    @patch("src.processors.draft_composer.SchedulerChoice")
    @patch("src.processors.draft_composer.scheduler_ask")
    @patch("src.processors.draft_composer.send_output")
    def test_cancel_returns_none(
        self,
        _out: MagicMock,
        mock_ask: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """When user cancels, returns None."""
        mock_ask.return_value = "some instruction"
        mock_choice_cls.return_value.choose.return_value = "cancel"

        ai = MagicMock(spec=OpenAIClient)
        ai.generate_draft_reply.return_value = "Draft text."

        result = _composer(ai).compose(_context())

        assert result is None

    @patch("src.processors.draft_composer.scheduler_ask")
    @patch("src.processors.draft_composer.send_output")
    def test_empty_instruction_returns_none(
        self,
        _out: MagicMock,
        mock_ask: MagicMock,
    ) -> None:
        """When user gives empty instruction, returns None."""
        mock_ask.return_value = ""

        result = _composer().compose(_context())

        assert result is None


class TestGrammarCheck:
    """Tests for the grammar correction step."""

    @patch("src.processors.draft_composer.SchedulerChoice")
    @patch("src.processors.draft_composer.scheduler_ask")
    @patch("src.processors.draft_composer.send_output")
    def test_grammar_use_original(
        self,
        _out: MagicMock,
        mock_ask: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """User can choose to keep original text over grammar correction."""
        mock_ask.return_value = "write something"
        # confirm draft, then "original" for grammar
        mock_choice_cls.return_value.choose.side_effect = ["confirm", "original"]

        ai = MagicMock(spec=OpenAIClient)
        ai.generate_draft_reply.return_value = "Draft mit Fehler."
        ai.correct_grammar.return_value = "Draft ohne Fehler."

        result = _composer(ai).compose(_context())

        assert result == "Draft mit Fehler."
