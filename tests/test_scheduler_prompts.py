"""Tests for the scheduler prompts wrapper module."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.interaction.scheduler_prompts import (
    SchedulerAbortError,
    SchedulerChoice,
    is_interactive,
    scheduler_ask,
    scheduler_choose,
    scheduler_confirm,
    send_output,
)


class TestIsInteractive:
    """Tests for the is_interactive helper."""

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.interaction.scheduler_prompts._SDK_AVAILABLE", True)
    @patch("src.interaction.scheduler_prompts.is_run_by_task_scheduler", return_value=False)
    def test_returns_false_when_env_var_unset(self, mock_check: MagicMock) -> None:
        """Should return False when TASK_SCHEDULER is not set."""
        assert is_interactive() is False

    @patch("src.interaction.scheduler_prompts._SDK_AVAILABLE", True)
    @patch("src.interaction.scheduler_prompts.is_run_by_task_scheduler", return_value=True)
    def test_returns_true_when_scheduler_active(self, mock_check: MagicMock) -> None:
        """Should return True when SDK reports scheduler is active."""
        assert is_interactive() is True

    @patch.dict(os.environ, {"TASK_SCHEDULER": "1"})
    @patch("src.interaction.scheduler_prompts._SDK_AVAILABLE", False)
    def test_graceful_degradation_without_sdk(self) -> None:
        """Should return False and log warning when SDK missing but env var set."""
        assert is_interactive() is False


class TestSchedulerConfirm:
    """Tests for scheduler_confirm wrapper."""

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="")
    def test_returns_default_when_not_interactive(self, mock_input: MagicMock, mock_interactive: MagicMock) -> None:
        """Should return default value when user presses Enter."""
        assert scheduler_confirm("Continue?", default=True) is True
        assert scheduler_confirm("Continue?", default=False) is False

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="y")
    def test_console_confirm_yes(self, mock_input: MagicMock, mock_interactive: MagicMock) -> None:
        """Should return True when user types 'y' in console."""
        assert scheduler_confirm("Continue?", default=False) is True

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="n")
    def test_console_confirm_no(self, mock_input: MagicMock, mock_interactive: MagicMock) -> None:
        """Should return False when user types 'n' in console."""
        assert scheduler_confirm("Continue?", default=True) is False

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.confirm", return_value=False)
    def test_delegates_to_sdk_when_interactive(self, mock_confirm: MagicMock, mock_interactive: MagicMock) -> None:
        """Should delegate to SDK confirm when interactive."""
        result = scheduler_confirm("Deploy?", default=True)
        assert result is False
        mock_confirm.assert_called_once_with("Deploy?", default=True)

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.confirm", return_value=None)
    def test_aborts_when_sdk_returns_none(self, mock_confirm: MagicMock, mock_interactive: MagicMock) -> None:
        """Should raise SchedulerAbortError when SDK returns None."""
        with pytest.raises(SchedulerAbortError):
            scheduler_confirm("Continue?", default=True)


class TestSchedulerAsk:
    """Tests for scheduler_ask wrapper."""

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="")
    def test_returns_default_when_not_interactive(self, mock_input: MagicMock, mock_interactive: MagicMock) -> None:
        """Should return default value when user presses Enter."""
        assert scheduler_ask("Enter name:", default="hello") == "hello"

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="custom text")
    def test_console_ask_custom(self, mock_input: MagicMock, mock_interactive: MagicMock) -> None:
        """Should return user input when typed in console."""
        assert scheduler_ask("Enter name:", default="default") == "custom text"

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.ask", return_value="custom text")
    def test_delegates_to_sdk_when_interactive(self, mock_ask: MagicMock, mock_interactive: MagicMock) -> None:
        """Should delegate to SDK ask when interactive."""
        result = scheduler_ask("Enter name:", default="default")
        assert result == "custom text"
        mock_ask.assert_called_once_with("Enter name:", default="default")

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.ask", return_value=None)
    def test_aborts_when_sdk_returns_none(self, mock_ask: MagicMock, mock_interactive: MagicMock) -> None:
        """Should raise SchedulerAbortError when SDK returns None."""
        with pytest.raises(SchedulerAbortError):
            scheduler_ask("Enter name:", default="default")


class TestSchedulerChoose:
    """Tests for scheduler_choose wrapper."""

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_returns_default_when_not_interactive(
        self, mock_print: MagicMock, mock_input: MagicMock, mock_interactive: MagicMock,
    ) -> None:
        """Should return default index when user presses Enter."""
        assert scheduler_choose("Pick:", ["a", "b", "c"], default=1) == 1

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="2")
    @patch("builtins.print")
    def test_console_choose_custom(
        self, mock_print: MagicMock, mock_input: MagicMock, mock_interactive: MagicMock,
    ) -> None:
        """Should return selected index when user types a number."""
        assert scheduler_choose("Pick:", ["a", "b", "c"], default=0) == 2

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.choose", return_value=2)
    def test_delegates_to_sdk_when_interactive(self, mock_choose: MagicMock, mock_interactive: MagicMock) -> None:
        """Should delegate to SDK choose when interactive."""
        result = scheduler_choose("Pick env:", ["dev", "staging", "prod"], default=0)
        assert result == 2
        mock_choose.assert_called_once_with("Pick env:", ["dev", "staging", "prod"], default=0, hidden_options=None)

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.choose", return_value=None)
    def test_aborts_when_sdk_returns_none(self, mock_choose: MagicMock, mock_interactive: MagicMock) -> None:
        """Should raise SchedulerAbortError when SDK returns None."""
        with pytest.raises(SchedulerAbortError):
            scheduler_choose("Pick:", ["a", "b"], default=0)


class TestSchedulerChooseHiddenOptions:
    """Tests for hidden_options support in scheduler_choose."""

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.choose", return_value=3)
    def test_passes_hidden_options_to_sdk(self, mock_choose: MagicMock, mock_interactive: MagicMock) -> None:
        """Should forward hidden_options to the SDK choose call."""
        hidden = {"a": "Abort"}
        scheduler_choose("Pick:", ["x", "y"], default=0, hidden_options=hidden)
        mock_choose.assert_called_once_with("Pick:", ["x", "y"], default=0, hidden_options=hidden)

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="a")
    @patch("builtins.print")
    def test_console_hidden_shortcut_returns_offset_index(
        self, mock_print: MagicMock, mock_input: MagicMock, mock_interactive: MagicMock,
    ) -> None:
        """Typing a hidden shortcut key should return len(options) + position."""
        result = scheduler_choose("Pick:", ["x", "y"], default=0, hidden_options={"a": "Abort"})
        assert result == 2  # len(["x", "y"]) + 0

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_console_shows_hidden_hint(
        self, mock_print: MagicMock, mock_input: MagicMock, mock_interactive: MagicMock,
    ) -> None:
        """Hidden options should produce a hint line like (a=Abort)."""
        scheduler_choose("Pick:", ["x", "y"], default=0, hidden_options={"a": "Abort"})
        printed = [str(c) for c in mock_print.call_args_list]
        assert any("a=Abort" in line for line in printed)


class TestSchedulerChoiceAbort:
    """Tests for SchedulerChoice abort flag."""

    @patch("src.interaction.scheduler_prompts.scheduler_choose", return_value=2)
    def test_abort_returns_abort_action(self, mock_choose: MagicMock) -> None:
        """SchedulerChoice(abort=True) returns 'abort' when hidden option is selected."""
        sc = SchedulerChoice("Action:", [("A", "a_key"), ("B", "b_key")], abort=True)
        result = sc.choose()
        assert result == "abort"
        # Verify hidden_options was passed
        mock_choose.assert_called_once_with(
            "Action:", ["A", "B"], default=0, hidden_options={"a": "Abort"},
        )

    @patch("src.interaction.scheduler_prompts.scheduler_choose", return_value=0)
    def test_normal_choice_still_works_with_abort(self, mock_choose: MagicMock) -> None:
        """Normal selection should return the correct action key even with abort enabled."""
        sc = SchedulerChoice("Action:", [("A", "a_key"), ("B", "b_key")], abort=True)
        result = sc.choose()
        assert result == "a_key"


class TestSchedulerOutput:
    """Tests for send_output wrapper."""

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=False)
    @patch("builtins.print")
    def test_calls_print_when_not_interactive(self, mock_print: MagicMock, mock_interactive: MagicMock) -> None:
        """Should call print() when not interactive."""
        send_output("hello world")
        mock_print.assert_called_once_with("hello world")

    @patch("src.interaction.scheduler_prompts.is_interactive", return_value=True)
    @patch("src.interaction.scheduler_prompts.output")
    def test_delegates_to_sdk_when_interactive(self, mock_output: MagicMock, mock_interactive: MagicMock) -> None:
        """Should delegate to SDK output() when interactive."""
        send_output("status update")
        mock_output.assert_called_once_with("status update")
