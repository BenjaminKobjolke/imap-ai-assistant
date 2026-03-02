from __future__ import annotations

from src.config.settings import ConfigManager


class TagRulesWizard:
    """Interactive wizard and CLI helpers for managing subject tag rules."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def list_tag_rules(self) -> None:
        """List all subject tag rules."""
        self.config.list_tag_rules()

    def add_sender_tag(self, pattern: str, tag: str) -> None:
        """Add a sender-based subject tag rule."""
        self.config.add_sender_tag_rule(pattern, tag)

    def remove_sender_tag(self, pattern: str) -> None:
        """Remove a sender-based subject tag rule."""
        if not self.config.remove_sender_tag_rule(pattern):
            print(f"No sender tag rule found for pattern: {pattern}")

    def add_keyword_tag(self, tag: str, keywords: list[str], match: str = "all") -> None:
        """Add a keyword-based subject tag rule."""
        self.config.add_keyword_tag_rule(keywords, tag, match)

    def remove_keyword_tag(self, tag: str) -> None:
        """Remove a keyword-based subject tag rule."""
        if not self.config.remove_keyword_tag_rule(tag):
            print(f"No keyword tag rule found for tag: {tag}")

    def setup_tag_rules(self) -> None:
        """Interactive wizard to list, add, edit, and delete subject tag rules."""
        while True:
            rules = self.config.get_subject_tag_rules()
            sender_rules = rules["sender_rules"]
            keyword_rules = rules["keyword_rules"]

            combined: list[tuple[str, dict]] = []
            for rule in sender_rules:
                combined.append(("sender", rule))
            for rule in keyword_rules:
                combined.append(("keyword", rule))

            print("\nSubject Tag Rules")
            print("=================\n")

            if not combined:
                print("  (no rules configured)\n")
            else:
                if sender_rules:
                    print("Sender rules:")
                    for i, rule in enumerate(sender_rules, 1):
                        print(f"  {i}. {rule['pattern']} -> {rule['tag']}")
                    print()

                if keyword_rules:
                    print("Keyword rules:")
                    offset = len(sender_rules)
                    for i, rule in enumerate(keyword_rules, offset + 1):
                        keywords_str = ", ".join(rule["keywords"])
                        match_mode = rule.get("match", "all")
                        print(f"  {i}. [{match_mode}] ({keywords_str}) -> {rule['tag']}")
                    print()

            print("Actions: [a]dd  [e]dit NUMBER  [d]elete NUMBER  [Enter] done")
            choice = input("  > ").strip().lower()

            if choice == "":
                print("Done.")
                return

            if choice == "a":
                self._add()
            elif choice.startswith("e"):
                self._edit(choice, combined)
            elif choice.startswith("d"):
                self._delete(choice, combined)
            else:
                print("  Invalid action.")

    def _add(self) -> None:
        """Prompt the user to add a new sender or keyword tag rule."""
        print("\n  Type: [s]ender  [k]eyword")
        rule_type = input("  > ").strip().lower()

        if rule_type == "s":
            pattern = input("  Sender pattern (e.g. @example.com): ").strip()
            if not pattern:
                print("  Cancelled.")
                return
            tag = input("  Tag (e.g. #project_tag): ").strip()
            if not tag:
                print("  Cancelled.")
                return
            self.config.add_sender_tag_rule(pattern, tag)
            print(f"  Added: {pattern} -> {tag}")

        elif rule_type == "k":
            tag = input("  Tag (e.g. #project_tag): ").strip()
            if not tag:
                print("  Cancelled.")
                return
            keywords_str = input("  Keywords (comma-separated): ").strip()
            if not keywords_str:
                print("  Cancelled.")
                return
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
            if not keywords:
                print("  Cancelled.")
                return
            print("  Match mode: [a]ll  [n]any")
            match_choice = input("  > ").strip().lower()
            match_mode = "any" if match_choice == "n" else "all"
            self.config.add_keyword_tag_rule(keywords, tag, match_mode)
            print(f"  Added: [{match_mode}] ({', '.join(keywords)}) -> {tag}")

        else:
            print("  Cancelled.")

    def _edit(self, choice: str, combined: list[tuple[str, dict]]) -> None:
        """Edit an existing tag rule by its index."""
        parts = choice.split()
        if len(parts) < 2 or not parts[1].isdigit():
            print("  Usage: e NUMBER")
            return

        idx = int(parts[1]) - 1
        if idx < 0 or idx >= len(combined):
            print("  Invalid rule number.")
            return

        rule_type, rule = combined[idx]

        if rule_type == "sender":
            print(f"\n  Current: {rule['pattern']} -> {rule['tag']}")
            new_pattern = input(f"  Pattern [{rule['pattern']}]: ").strip()
            new_tag = input(f"  Tag [{rule['tag']}]: ").strip()

            old_pattern = rule["pattern"]
            final_pattern = new_pattern if new_pattern else old_pattern
            final_tag = new_tag if new_tag else rule["tag"]

            if final_pattern != old_pattern:
                self.config.remove_sender_tag_rule(old_pattern)
            self.config.add_sender_tag_rule(final_pattern, final_tag)
            print(f"  Updated: {final_pattern} -> {final_tag}")

        else:
            keywords_str = ", ".join(rule["keywords"])
            match_mode = rule.get("match", "all")
            print(f"\n  Current: [{match_mode}] ({keywords_str}) -> {rule['tag']}")

            new_tag = input(f"  Tag [{rule['tag']}]: ").strip()
            new_keywords = input(f"  Keywords (comma-separated) [{keywords_str}]: ").strip()
            print(f"  Match mode: [a]ll  [n]any  [{match_mode[0]}]")
            new_match = input("  > ").strip().lower()

            old_tag = rule["tag"]
            final_tag = new_tag if new_tag else old_tag
            final_keywords = (
                [k.strip() for k in new_keywords.split(",") if k.strip()]
                if new_keywords
                else rule["keywords"]
            )
            if new_match == "n":
                final_match = "any"
            elif new_match == "a":
                final_match = "all"
            else:
                final_match = match_mode

            if final_tag != old_tag:
                self.config.remove_keyword_tag_rule(old_tag)
            self.config.add_keyword_tag_rule(final_keywords, final_tag, final_match)
            print(f"  Updated: [{final_match}] ({', '.join(final_keywords)}) -> {final_tag}")

    def _delete(self, choice: str, combined: list[tuple[str, dict]]) -> None:
        """Delete a tag rule by its index after confirmation."""
        parts = choice.split()
        if len(parts) < 2 or not parts[1].isdigit():
            print("  Usage: d NUMBER")
            return

        idx = int(parts[1]) - 1
        if idx < 0 or idx >= len(combined):
            print("  Invalid rule number.")
            return

        rule_type, rule = combined[idx]

        if rule_type == "sender":
            label = f"{rule['pattern']} -> {rule['tag']}"
        else:
            keywords_str = ", ".join(rule["keywords"])
            match_mode = rule.get("match", "all")
            label = f"[{match_mode}] ({keywords_str}) -> {rule['tag']}"

        confirm = input(f"  Delete '{label}'? [y/N] ").strip().lower()
        if confirm == "y":
            if rule_type == "sender":
                self.config.remove_sender_tag_rule(rule["pattern"])
            else:
                self.config.remove_keyword_tag_rule(rule["tag"])
            print("  Deleted.")
        else:
            print("  Cancelled.")
