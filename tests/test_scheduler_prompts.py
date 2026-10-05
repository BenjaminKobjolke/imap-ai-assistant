"""Tests for the scheduler prompts re-export module.

The actual interaction logic is tested in the interactions-sdk package.
These tests verify that the re-exports work correctly and that the
imap-specific aliases are properly wired up.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.interaction.scheduler_prompts import (
    SchedulerAbortError,
    SchedulerChoice,
    ask_or_accept,
    is_interactive,
    scheduler_ask,
    scheduler_choose,
    scheduler_confirm,
    send_output,
    set_auto_accept,
    start_output_capture,
    stop_output_capture,
)


class TestReExports:
    """Verify that all re-exports point to the correct SDK objects."""

    def test_scheduler_abort_error_is_abort_error(self):
        from interactions_sdk import AbortError
        assert SchedulerAbortError is AbortError

    def test_scheduler_choice_is_interaction_choice(self):
        from interactions_sdk import InteractionChoice
        assert SchedulerChoice is InteractionChoice

    def test_send_output_is_output(self):
        from interactions_sdk import output
        assert send_output is output

    def test_is_interactive_is_sdk_is_interactive(self):
        from interactions_sdk import is_interactive as sdk_is_interactive
        assert is_interactive is sdk_is_interactive

    def test_start_output_capture_is_sdk(self):
        from interactions_sdk import start_output_capture as sdk_start
        assert start_output_capture is sdk_start

    def test_stop_output_capture_is_sdk(self):
        from interactions_sdk import stop_output_capture as sdk_stop
        assert stop_output_capture is sdk_stop


@pytest.fixture
def auto_accept():
    set_auto_accept(True)
    yield
    set_auto_accept(False)


@patch("builtins.print")
@patch("builtins.input", side_effect=AssertionError("prompt was shown"))
class TestAutoAccept:
    """With auto-accept on, prompts answer themselves with their default."""

    def test_confirm_returns_default(self, mock_input: MagicMock, mock_print: MagicMock, auto_accept: None):
        assert scheduler_confirm("Send?", default=True) is True
        assert scheduler_confirm("Send?", default=False) is False

    def test_ask_returns_default(self, mock_input: MagicMock, mock_print: MagicMock, auto_accept: None):
        assert scheduler_ask("Name:", default="Bob") == "Bob"

    def test_choose_returns_default(self, mock_input: MagicMock, mock_print: MagicMock, auto_accept: None):
        assert scheduler_choose("Pick:", ["a", "b"], default=1) == 1

    def test_ask_or_accept_returns_default(self, mock_input: MagicMock, mock_print: MagicMock, auto_accept: None):
        assert ask_or_accept("Title:", default="Original") == "Original"

    def test_no_default_still_prompts(self, mock_input: MagicMock, mock_print: MagicMock, auto_accept: None):
        with patch.dict(os.environ, {}, clear=True), pytest.raises(AssertionError, match="prompt was shown"):
            scheduler_confirm("Send?")


class TestAliasesWork:
    """Smoke tests that the aliases actually work end-to-end."""

    @patch("builtins.input", return_value="y")
    def test_scheduler_confirm_cli(self, mock_input: MagicMock):
        env = os.environ.copy()
        env.pop("INTERACTIVE", None)
        with patch.dict(os.environ, env, clear=True):
            assert scheduler_confirm("Continue?") is True

    @patch("builtins.input", return_value="hello")
    def test_scheduler_ask_cli(self, mock_input: MagicMock):
        env = os.environ.copy()
        env.pop("INTERACTIVE", None)
        with patch.dict(os.environ, env, clear=True):
            assert scheduler_ask("Name:") == "hello"

    @patch("builtins.input", return_value="0")
    @patch("builtins.print")
    def test_scheduler_choose_cli(self, mock_print: MagicMock, mock_input: MagicMock):
        env = os.environ.copy()
        env.pop("INTERACTIVE", None)
        with patch.dict(os.environ, env, clear=True):
            assert scheduler_choose("Pick:", ["a", "b"], default=0) == 0

    @patch("builtins.print")
    def test_send_output_cli(self, mock_print: MagicMock):
        env = os.environ.copy()
        env.pop("INTERACTIVE", None)
        with patch.dict(os.environ, env, clear=True):
            send_output("hello world")
        mock_print.assert_called_once_with("hello world")

    def test_scheduler_abort_error_is_catchable(self):
        with pytest.raises(SchedulerAbortError):
            raise SchedulerAbortError("test")

    @patch("interactions_sdk.choose", return_value=0)
    def test_scheduler_choice_works(self, mock_choose: MagicMock):
        sc = SchedulerChoice("Action:", [("A", "a_key"), ("B", "b_key")])
        result = sc.choose()
        assert result == "a_key"

    @patch("interactions_sdk.ask", return_value="Edited")
    @patch("interactions_sdk.choose", return_value=1)
    def test_ask_or_accept_edit(self, mock_choose: MagicMock, mock_ask: MagicMock):
        result = ask_or_accept("Title:", default="Original")
        assert result == "Edited"

    @patch("interactions_sdk.choose", return_value=0)
    def test_ask_or_accept_accept(self, mock_choose: MagicMock):
        assert ask_or_accept("Title:", default="Original") == "Original"

    def test_output_capture_round_trip(self):
        import interactions_sdk as sdk
        old_buf = sdk._capture_buffer
        old_silent = sdk._capture_silent
        try:
            start_output_capture(silent=True)
            send_output("captured line")
            result = stop_output_capture()
            assert result == "captured line"
        finally:
            sdk._capture_buffer = old_buf
            sdk._capture_silent = old_silent
