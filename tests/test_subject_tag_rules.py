from __future__ import annotations

import json
from pathlib import Path

from src.config.settings import ConfigManager
from src.config.subject_tag_rules import SubjectTagRules


def _read_settings(path: Path) -> dict:
    """Read persisted settings to verify rule changes survive a reload."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_sender_rules_add_update_and_remove_are_persisted(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"processing": {}}', encoding="utf-8")
    rules = SubjectTagRules(ConfigManager(str(settings_path)))

    rules.add_sender_tag_rule("@example.com", "#first")
    assert _read_settings(settings_path)["processing"]["subject_tag_rules"]["sender_rules"] == [
        {"pattern": "@example.com", "tag": "#first"}
    ]

    rules.add_sender_tag_rule("@EXAMPLE.COM", "#updated")
    assert _read_settings(settings_path)["processing"]["subject_tag_rules"]["sender_rules"] == [
        {"pattern": "@example.com", "tag": "#updated"}
    ]

    assert rules.remove_sender_tag_rule("@Example.com") is True
    assert _read_settings(settings_path)["processing"]["subject_tag_rules"]["sender_rules"] == []
    assert rules.remove_sender_tag_rule("@missing.com") is False


def test_keyword_rules_add_update_and_remove_are_persisted(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"processing": {}}', encoding="utf-8")
    rules = SubjectTagRules(ConfigManager(str(settings_path)))

    rules.add_keyword_tag_rule(["invoice", "payment"], "#finance")
    assert _read_settings(settings_path)["processing"]["subject_tag_rules"]["keyword_rules"] == [
        {"keywords": ["invoice", "payment"], "tag": "#finance", "match": "all"}
    ]

    rules.add_keyword_tag_rule(["receipt"], "#finance", "any")
    assert _read_settings(settings_path)["processing"]["subject_tag_rules"]["keyword_rules"] == [
        {"keywords": ["receipt"], "tag": "#finance", "match": "any"}
    ]

    assert rules.remove_keyword_tag_rule("#finance") is True
    assert _read_settings(settings_path)["processing"]["subject_tag_rules"]["keyword_rules"] == []
    assert rules.remove_keyword_tag_rule("#missing") is False
