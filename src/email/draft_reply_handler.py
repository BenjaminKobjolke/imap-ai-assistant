"""Reusable draft-reply flow: salutation, greeting, compose, build, save."""

from __future__ import annotations

import logging
from email.utils import parseaddr

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output
from src.processors.draft_composer import DraftComposer, DraftContext
from src.processors.draft_email_builder import DraftEmailBuilder, DraftEmailContent
from src.processors.greeting_builder import GreetingBuilder
from src.processors.salutation_manager import SalutationManager
from src.search.search_cache import SearchCache

logger = logging.getLogger(__name__)


class DraftReplyHandler:
    """Full draft reply flow reusable across inbox-zero and browse."""

    def __init__(
        self,
        client: EnhancedImapClient,
        config: ConfigManager,
        openai_client: OpenAIClient,
        cache: SearchCache,
    ) -> None:
        self._client = client
        self._config = config
        self._openai = openai_client
        self._cache = cache

    def draft_reply(self, from_addr_raw: str, subject: str, body: str) -> None:
        """Full draft reply flow: salutation, greeting, compose, build, save."""
        _, from_addr = parseaddr(from_addr_raw)
        from_name = from_addr_raw.replace(f"<{from_addr}>", "").strip().strip('"')

        sal_mgr = SalutationManager(self._cache, self._config, self._openai, self._client)
        salutation_info = sal_mgr.resolve_salutation(from_addr)

        greeting = GreetingBuilder.build_greeting(salutation_info)

        context = DraftContext(
            original_subject=subject,
            original_body=body,
            original_from_address=from_addr,
            original_from_name=from_name,
            greeting=greeting,
        )
        composer = DraftComposer(self._openai)
        final_body = composer.compose(context)

        if not final_body:
            send_output("  Draft cancelled.")
            return

        builder = DraftEmailBuilder(self._config, self._client)
        content = DraftEmailContent(
            to_address=from_addr,
            subject=DraftEmailBuilder.make_reply_subject(subject),
            greeting=greeting,
            body_text=final_body,
            footer_html=DraftEmailBuilder.load_footer_html(),
            original_from=from_addr_raw,
            original_subject=subject,
            original_body=body,
        )
        builder.build_and_save(content)
