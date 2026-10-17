from __future__ import annotations

import logging

from src.config.settings import ConfigManager

logger = logging.getLogger(__name__)


class SubjectTagRules:
    """Manage sender and keyword rules that add tags to email subjects."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def add_sender_tag_rule(self, pattern: str, tag: str) -> None:
        """Add a sender rule or update its tag when the pattern already exists."""
        sender_rules = self._config.subject_tag_rules_node().setdefault("sender_rules", [])
        for rule in sender_rules:
            if rule["pattern"].lower() == pattern.lower():
                rule["tag"] = tag
                logger.info("Updated sender tag rule: %s -> %s", pattern, tag)
                self._config.save()
                return

        sender_rules.append({"pattern": pattern, "tag": tag})
        logger.info("Added sender tag rule: %s -> %s", pattern, tag)
        self._config.save()

    def remove_sender_tag_rule(self, pattern: str) -> bool:
        """Remove a sender rule by its case-insensitive pattern."""
        sender_rules = self._config.subject_tag_rules_node().get("sender_rules", [])
        for index, rule in enumerate(sender_rules):
            if rule["pattern"].lower() == pattern.lower():
                sender_rules.pop(index)
                logger.info("Removed sender tag rule: %s", pattern)
                self._config.save()
                return True

        logger.warning("Sender tag rule not found: %s", pattern)
        return False

    def add_keyword_tag_rule(self, keywords: list[str], tag: str, match: str = "all") -> None:
        """Add a keyword rule or replace the rule with the same tag."""
        keyword_rules = self._config.subject_tag_rules_node().setdefault("keyword_rules", [])
        for rule in keyword_rules:
            if rule["tag"] == tag:
                rule["keywords"] = keywords
                rule["match"] = match
                logger.info("Updated keyword tag rule: %s (keywords: %s, match: %s)", tag, keywords, match)
                self._config.save()
                return

        keyword_rules.append({"keywords": keywords, "tag": tag, "match": match})
        logger.info("Added keyword tag rule: %s (keywords: %s, match: %s)", tag, keywords, match)
        self._config.save()

    def remove_keyword_tag_rule(self, tag: str) -> bool:
        """Remove a keyword rule by its tag."""
        keyword_rules = self._config.subject_tag_rules_node().get("keyword_rules", [])
        for index, rule in enumerate(keyword_rules):
            if rule["tag"] == tag:
                keyword_rules.pop(index)
                logger.info("Removed keyword tag rule: %s", tag)
                self._config.save()
                return True

        logger.warning("Keyword tag rule not found: %s", tag)
        return False

    def list_tag_rules(self) -> None:
        """Log configured sender and keyword rules for troubleshooting."""
        rules = self._config.get_subject_tag_rules()
        sender_rules = rules["sender_rules"]
        keyword_rules = rules["keyword_rules"]
        if not sender_rules and not keyword_rules:
            logger.info("No subject tag rules configured.")
            return

        if sender_rules:
            logger.info("Sender rules:")
            for rule in sender_rules:
                logger.info("  %s -> %s", rule["pattern"], rule["tag"])

        if keyword_rules:
            logger.info("Keyword rules:")
            for rule in keyword_rules:
                keywords_str = ", ".join(rule["keywords"])
                match_mode = rule.get("match", "all")
                logger.info("  [%s] (%s) -> %s", match_mode, keywords_str, rule["tag"])
