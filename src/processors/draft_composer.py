"""Interactive AI drafting loop: instruction -> generate -> review -> grammar check."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.ai.openai_client import OpenAIClient
from src.interaction.scheduler_prompts import SchedulerChoice, scheduler_ask, send_output

logger = logging.getLogger(__name__)


@dataclass
class DraftContext:
    """Context needed for the draft generation loop."""

    original_subject: str
    original_body: str
    original_from_address: str
    original_from_name: str
    greeting: str


class DraftComposer:
    """Interactive loop: get instruction, generate draft, review, grammar-check."""

    def __init__(self, openai_client: OpenAIClient) -> None:
        self._openai = openai_client

    def compose(self, context: DraftContext) -> str | None:
        """Run the interactive drafting loop. Returns final body text or None on cancel."""
        conversation_history = ""
        current_body: str | None = None

        while True:
            # Get instruction from user
            if current_body is None:
                instruction = scheduler_ask("What should the reply say?", default="")
            else:
                instruction = scheduler_ask("New instruction (builds on previous):", default="")

            if not instruction.strip():
                send_output("  No instruction given — cancelling draft.")
                return None

            # Track conversation history for multi-turn refinement
            if current_body:
                conversation_history += f"\n---\nPrevious draft:\n{current_body}\n\nNew instruction: {instruction}"
            else:
                conversation_history = f"Initial instruction: {instruction}"

            # Generate draft via AI
            draft = self._openai.generate_draft_reply(
                original_subject=context.original_subject,
                original_body=context.original_body,
                user_instruction=instruction,
                conversation_history=conversation_history,
            )

            if not draft:
                send_output("  AI failed to generate a draft.")
                return None

            current_body = draft
            send_output(f"\n--- Draft ---\n{current_body}\n--- End ---\n")

            # Review loop
            action = self._review_draft()

            if action == "confirm":
                break
            elif action == "edit":
                replacement = scheduler_ask("Enter replacement text:", default=current_body)
                current_body = replacement
                send_output(f"\n--- Updated draft ---\n{current_body}\n--- End ---\n")
                # Re-confirm after edit
                action2 = self._review_draft()
                if action2 == "confirm":
                    break
                elif action2 == "new_instruction":
                    continue
                elif action2 == "edit":
                    replacement2 = scheduler_ask("Enter replacement text:", default=current_body)
                    current_body = replacement2
                    break  # Accept after second edit
                elif action2 == "cancel":
                    return None
            elif action == "new_instruction":
                continue
            elif action == "cancel":
                return None

        # Grammar correction step
        return self._grammar_check(current_body)

    def _review_draft(self) -> str:
        """Show review options and return the chosen action key."""
        return SchedulerChoice(
            "What would you like to do?",
            [
                ("Confirm", "confirm"),
                ("New instruction", "new_instruction"),
                ("Edit text", "edit"),
                ("Cancel", "cancel"),
            ],
        ).choose()

    def _grammar_check(self, body: str) -> str:
        """Run grammar correction and let user accept or re-correct."""
        corrected = self._openai.correct_grammar(body)

        if not corrected or corrected == body:
            send_output("  No grammar corrections needed.")
            return body

        send_output(f"\n--- Grammar corrected ---\n{corrected}\n--- End ---\n")

        while True:
            action = SchedulerChoice(
                "Accept corrected version?",
                [
                    ("Accept", "accept"),
                    ("Use original", "original"),
                    ("Correct again", "again"),
                ],
            ).choose()

            if action == "accept":
                return corrected
            elif action == "original":
                return body
            elif action == "again":
                re_corrected = self._openai.correct_grammar(corrected)
                if not re_corrected or re_corrected == corrected:
                    send_output("  No further corrections.")
                    return corrected
                corrected = re_corrected
                send_output(f"\n--- Re-corrected ---\n{corrected}\n--- End ---\n")
            else:
                return corrected
