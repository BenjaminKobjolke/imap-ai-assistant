"""Tests for subject tag rule matching in TodoService."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigManager
from src.services.todo_service import TodoService, forwarded_senders

FORWARDED_BODY = (
    "\n\n-------- Original Message --------\n"
    "From: Elisa Schmid <elisa.schmid@nuernbergmesse.de>\n"
    "To: Benjamin Kobjolke <b.kobjolke@xida.de>\n"
    "Subject: DeePS - finale Anpassungen\n"
)

SENDER_PROMPT = "Do not add the name of the sender to the title."
KEYWORD_PROMPT = "Start the title with 'Report'."

RULES = {
    "sender_rules": [
        {"pattern": "@nuernbergmesse.de", "tag": "#p_deeps", "assignee": "markus", "prompt": SENDER_PROMPT},
        {"pattern": "@example.com", "tag": "#example"},
    ],
    "keyword_rules": [
        {"keywords": ["invoice", "urgent"], "tag": "#billing", "match": "all"},
        {
            "keywords": ["report", "summary"],
            "tag": "#reports",
            "match": "any",
            "assignee": "tamara",
            "prompt": KEYWORD_PROMPT,
        },
    ],
}


@pytest.fixture
def service() -> TodoService:
    config = MagicMock(spec=ConfigManager)
    config.get_subject_tag_rules.return_value = RULES
    with patch("src.services.todo_service.SmtpClient"):
        return TodoService(config)


class TestResolveExtraTags:
    def test_sender_and_keyword_tags_joined_sender_first(self, service: TodoService) -> None:
        tags = service.resolve_extra_tags("Elisa <elisa@NuernbergMesse.de>", "Weekly Report")
        assert tags == "#p_deeps #reports"

    def test_match_all_needs_every_keyword(self, service: TodoService) -> None:
        assert service.resolve_extra_tags("a@b.c", "Invoice") == ""
        assert service.resolve_extra_tags("a@b.c", "URGENT invoice") == "#billing"

    def test_no_match_returns_empty(self, service: TodoService) -> None:
        assert service.resolve_extra_tags("a@b.c", "Hello") == ""


class TestResolveRuleAssignee:
    def test_matching_rule_with_assignee(self, service: TodoService) -> None:
        assert service.resolve_rule_assignee("x@nuernbergmesse.de", "Hello") == "markus"

    def test_matching_rule_without_assignee_is_skipped(self, service: TodoService) -> None:
        assert service.resolve_rule_assignee("x@example.com", "Summary") == "tamara"

    def test_no_match_returns_none(self, service: TodoService) -> None:
        assert service.resolve_rule_assignee("a@b.c", "Hello") is None

    def test_matching_rule_without_assignee_returns_none(self, service: TodoService) -> None:
        assert service.resolve_rule_assignee("x@example.com", "Hello") is None


class TestResolveRulePrompt:
    def test_sender_and_keyword_prompts_joined_sender_first(self, service: TodoService) -> None:
        prompt = service.resolve_rule_prompt("x@nuernbergmesse.de", "Weekly Report")
        assert prompt == f"{SENDER_PROMPT}\n{KEYWORD_PROMPT}"

    def test_matching_rule_without_prompt_returns_empty(self, service: TodoService) -> None:
        assert service.resolve_rule_prompt("x@example.com", "Hello") == ""

    def test_no_match_returns_empty(self, service: TodoService) -> None:
        assert service.resolve_rule_prompt("a@b.c", "Hello") == ""


class TestForwardedSenders:
    def test_finds_from_line(self) -> None:
        assert forwarded_senders(FORWARDED_BODY) == "Elisa Schmid <elisa.schmid@nuernbergmesse.de>"

    def test_finds_german_von_line(self) -> None:
        assert forwarded_senders("Hi\nVon: Max <max@example.com>\n") == "Max <max@example.com>"

    def test_no_header_returns_empty(self) -> None:
        assert forwarded_senders("Markus, wichtig\n\nHello") == ""

    def test_sender_rule_matches_forwarded_sender(self, service: TodoService) -> None:
        sender = f"Benjamin <b.kobjolke@xida.de> {forwarded_senders(FORWARDED_BODY)}"
        assert service.resolve_extra_tags(sender, "Fwd: Hello") == "#p_deeps"
        assert service.resolve_rule_assignee(sender, "Fwd: Hello") == "markus"
