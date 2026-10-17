"""Focused tests for shared OpenAI chat request handling."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai.openai_client import ChatCall, OpenAIClient
from src.logging.app_logger import ApplicationLogger


@pytest.fixture
def client() -> OpenAIClient:
    """Build a client without opening a real OpenAI connection."""
    with patch("src.ai.openai_client.OpenAI"):
        return OpenAIClient("key", app_logger=MagicMock(spec=ApplicationLogger))


def _response(content: str | None, usage: bool = True) -> MagicMock:
    response = MagicMock()
    response.choices = [] if content is None else [MagicMock(message=MagicMock(content=content))]
    response.usage = MagicMock(prompt_tokens=11, completion_tokens=7, total_tokens=18) if usage else None
    return response


def test_chat_strips_content_and_logs_request_response_and_usage(client: OpenAIClient) -> None:
    client.app_logger.log_ai_request.return_value = "req-1"
    client.client.chat.completions.create.return_value = _response("  answer  ")

    result = client._chat(ChatCall(
        operation="sample",
        system_prompt="system prompt",
        user_prompt="user prompt",
        request_data={"subject": "example", "user_prompt": "user prompt"},
        max_completion_tokens=42,
        temperature=0.25,
    ))

    assert result == "answer"
    client.app_logger.log_ai_request.assert_called_once()
    operation, request_data, metadata = client.app_logger.log_ai_request.call_args.args
    assert operation == "sample"
    assert request_data == {"subject": "example", "user_prompt": "user prompt", "system_prompt": "system prompt"}
    assert metadata == {"model": client.model, "max_completion_tokens": 42, "temperature": 0.25}
    request_id = client.app_logger.log_ai_request.return_value
    response_args = client.app_logger.log_ai_response.call_args.args
    assert response_args[0] == request_id
    assert response_args[1] == "sample"
    assert response_args[2] == "answer"
    assert response_args[4] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def test_chat_returns_none_when_choices_are_empty(client: OpenAIClient) -> None:
    client.client.chat.completions.create.return_value = _response(None)

    result = client._chat(ChatCall("sample", "system", "user", {}, 42, 0.25))

    assert result is None
    client.app_logger.log_ai_response.assert_not_called()


def test_chat_logs_api_exception_and_reraises(client: OpenAIClient) -> None:
    error = RuntimeError("api unavailable")
    client.app_logger.log_ai_request.return_value = "req-7"
    client.client.chat.completions.create.side_effect = error

    with pytest.raises(RuntimeError, match="api unavailable"):
        client._chat(ChatCall(
            "sample", "system", "user", {"request_id": "req-7"}, 42, 0.25,
            error_context={"item": "x"},
        ))

    client.app_logger.log_ai_error.assert_called_once_with("req-7", "sample", error, {"item": "x"})


def test_chat_can_request_json_mode(client: OpenAIClient) -> None:
    client.client.chat.completions.create.return_value = _response("{}")

    client._chat(ChatCall("sample", "system", "user", {}, 42, 0.25, json_mode=True))

    assert client.client.chat.completions.create.call_args.kwargs["response_format"] == {"type": "json_object"}


def test_email_processing_does_not_use_body_excerpt_as_fallback_sender(client: OpenAIClient) -> None:
    client.client.chat.completions.create.side_effect = RuntimeError("api unavailable")

    result = client.process_email_to_todo("Subject", "first line", "body excerpt")

    assert result.title == "Subject"
