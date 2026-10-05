"""Tests for rule instructions appended to the todo user prompt."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai.openai_client import OpenAIClient

EXTRA = "Do not add the name of the sender to the title. Costs $5."
RESPONSE = '{"title": "DeePS Anpassungen umsetzen", "assignee": "self", "priority": 2, "due_date": "tomorrow"}'


@pytest.fixture
def client() -> OpenAIClient:
    with patch("src.ai.openai_client.OpenAI"):
        openai_client = OpenAIClient("key")
    completion = MagicMock()
    completion.choices[0].message.content = RESPONSE
    openai_client.client.chat.completions.create.return_value = completion
    return openai_client


def _user_prompt(client: OpenAIClient) -> str:
    messages = client.client.chat.completions.create.call_args.kwargs["messages"]
    return str(messages[1]["content"])


def test_extra_instructions_are_appended(client: OpenAIClient) -> None:
    client.process_email_to_todo("Subject", "first", "body", EXTRA)
    assert _user_prompt(client).endswith(f"\n\nAdditional instructions:\n{EXTRA}")


def test_prompt_unchanged_without_extra_instructions(client: OpenAIClient) -> None:
    client.process_email_to_todo("Subject", "first", "body")
    assert "Additional instructions:" not in _user_prompt(client)
