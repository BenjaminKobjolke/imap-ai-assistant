"""Resolves and caches salutation for email recipients."""

from __future__ import annotations

import html
import logging
import re

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import KEY_FORMAL, KEY_SALUTATION
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import (
    SchedulerChoice,
    scheduler_ask,
    scheduler_confirm,
    send_output,
)
from src.processors.greeting_builder import SalutationInfo
from src.search.search_cache import SearchCache

logger = logging.getLogger(__name__)

_MAX_SENT_EMAILS = 3


class SalutationManager:
    """Lookup chain: DB -> sent emails + AI -> manual input."""

    def __init__(
        self,
        cache: SearchCache,
        config: ConfigManager,
        openai_client: OpenAIClient,
        imap_client: EnhancedImapClient,
    ) -> None:
        self._cache = cache
        self._config = config
        self._openai = openai_client
        self._imap = imap_client

    def resolve_salutation(self, email_address: str) -> SalutationInfo:
        """Resolve salutation for *email_address* via DB, AI, or manual input."""
        # 1. DB lookup
        cached = self._cache.get_salutation(email_address)
        if cached is not None:
            send_output(f"  Salutation from cache: '{cached['salutation']}'")
            return SalutationInfo(
                email_address=email_address,
                salutation=cached["salutation"],
                is_formal=cached["is_formal"],
                skip_greeting=cached["skip_greeting"],
            )

        # 2. Search sent folder for recent emails to this person
        send_output(f"  No cached salutation for {email_address}.")
        sent_bodies, match_count = self._search_sent_emails(email_address)

        if sent_bodies:
            # 3. AI detection from sent emails
            send_output(f"  Sending {match_count} email(s) to AI for salutation detection...")
            ai_result = self._openai.detect_salutation(email_address, sent_bodies)
            if ai_result:
                salutation_text = ai_result.get(KEY_SALUTATION, "")
                is_formal = bool(ai_result.get(KEY_FORMAL, True))

                send_output(f"  AI result: '{salutation_text}' ({'formal' if is_formal else 'informal'})")
                if scheduler_confirm("Use this salutation?", default=True):
                    info = SalutationInfo(
                        email_address=email_address,
                        salutation=salutation_text,
                        is_formal=is_formal,
                        skip_greeting=False,
                    )
                    self._save(info)
                    return info
            else:
                send_output("  AI could not detect salutation.")
        else:
            send_output("  No sent emails found for this address.")

        # 4. Manual input
        return self._ask_manual(email_address)

    def _search_sent_emails(self, email_address: str) -> tuple[str, int]:
        """Search sent folder for recent emails to *email_address*.

        Returns (joined_bodies, match_count).
        """
        try:
            account = self._config.get_first_account()
            if not account:
                return "", 0

            sent_folder = self._config.get_sent_folder(account)
            send_output(f"  Searching '{sent_folder}' for emails to {email_address}...")
            messages = self._imap.client.get_all_messages(
                folder=sent_folder, include_attachments=False,
            )
            send_output(f"  Scanned {len(messages)} sent email(s).")

            bodies: list[str] = []
            for _msg_id, email_msg in messages:
                to_addr = getattr(email_msg, "to", None) or getattr(email_msg, "to_address", None)
                if not to_addr or email_address.lower() not in to_addr.lower():
                    continue

                try:
                    _subject, _first_line, body = self._imap.extract_email_content(email_msg)
                    if body:
                        clean = re.sub(r"<[^>]+>", "", body)
                        clean = html.unescape(clean)
                        clean = " ".join(clean.split())
                        bodies.append(clean[:500])
                except Exception as e:
                    logger.debug(f"Error extracting sent email body: {e}")
                    continue

                if len(bodies) >= _MAX_SENT_EMAILS:
                    break

            send_output(f"  Found {len(bodies)} matching email(s).")

            if not bodies:
                return "", 0

            return "\n---\n".join(bodies), len(bodies)

        except Exception as e:
            logger.warning(f"Error searching sent emails for {email_address}: {e}")
            return "", 0

    def _ask_manual(self, email_address: str) -> SalutationInfo:
        """Ask the user to provide salutation manually."""
        send_output(f"  No salutation found for {email_address}.")

        choice = SchedulerChoice(
            "How to address this person?",
            [
                ("Enter salutation manually", "manual"),
                ("No salutation (greeting only)", "no_salutation"),
                ("Skip greeting entirely", "skip"),
            ],
        ).choose()

        if choice == "skip":
            info = SalutationInfo(
                email_address=email_address,
                salutation="",
                is_formal=True,
                skip_greeting=True,
            )
            self._save(info)
            return info

        if choice == "no_salutation":
            info = SalutationInfo(
                email_address=email_address,
                salutation="",
                is_formal=True,
                skip_greeting=False,
            )
            self._save(info)
            return info

        salutation_text = scheduler_ask("Enter salutation (e.g., 'Herr Mueller', 'Benjamin'):", default="")

        formality = SchedulerChoice(
            "Formal or informal?",
            [
                ("Formal (Sie)", "formal"),
                ("Informal (Du)", "informal"),
            ],
        ).choose()

        info = SalutationInfo(
            email_address=email_address,
            salutation=salutation_text,
            is_formal=formality == "formal",
            skip_greeting=False,
        )
        self._save(info)
        return info

    def _save(self, info: SalutationInfo) -> None:
        """Persist salutation to the database."""
        self._cache.save_salutation(
            info.email_address,
            info.salutation,
            is_formal=info.is_formal,
            skip_greeting=info.skip_greeting,
        )
        logger.info(f"Saved salutation for {info.email_address}: '{info.salutation}'")
