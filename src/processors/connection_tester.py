from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient

logger = logging.getLogger(__name__)


class ConnectionTester:
    """Tests for verifying email and API connections."""

    def __init__(
        self,
        config: ConfigManager,
        imap_client: EnhancedImapClient | None,
        smtp_client: SmtpClient | None,
        openai_client: Any,
    ) -> None:
        self.config = config
        self.imap_client = imap_client
        self.smtp_client = smtp_client
        self.openai_client = openai_client

    def test_email(self) -> None:
        """Send a test email to self and verify it arrives via IMAP."""
        account_config = self.config.get_first_account()
        if not account_config:
            print("SEND: ERROR - No main account configuration found")
            return

        email_address = account_config.get("email_address", "")
        if not email_address:
            print("SEND: ERROR - No email_address configured for the first account")
            return

        smtp_cfg = self.config.get_account_smtp_config(account_config)
        if not smtp_cfg:
            print("SEND: ERROR - No SMTP configuration available for the first account")
            return

        smtp_client = SmtpClient(smtp_cfg)
        marker = f"IMAP-AI-Assistant-Test-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Step 1: Send test email
        print(f"SEND: Sending test email to {email_address} ...")
        try:
            smtp_client.send_email(
                to_email=email_address,
                subject=marker,
                body="This is an automated test email from IMAP AI Assistant.",
                from_email=smtp_cfg.get("from_email", ""),
            )
            print("SEND: OK")
        except Exception as e:
            print(f"SEND: ERROR - {e}")
            return

        # Step 2: Connect IMAP and poll for arrival
        print("RECEIVE: Connecting to IMAP ...")
        client = EnhancedImapClient(account_config)
        if not client.connect():
            print("RECEIVE: ERROR - Failed to connect to IMAP server")
            return

        try:
            max_attempts = 5
            poll_interval = 3
            for attempt in range(1, max_attempts + 1):
                time.sleep(poll_interval)
                print(f"RECEIVE: Checking for test email (attempt {attempt}/{max_attempts}) ...")
                messages = client.client.get_messages(
                    search_criteria=["UNSEEN", "SUBJECT", marker],
                    folder="INBOX",
                )
                if messages:
                    msg_id = messages[0][0]
                    client.client.delete_message(msg_id)
                    print("RECEIVE: OK")
                    return

            print(
                "RECEIVE: ERROR - Test email was sent but could not be found in INBOX. "
                "Check IMAP settings or allow more delivery time."
            )
        finally:
            client.disconnect()

    def test_connections(self) -> bool:
        """Test all connections and configurations."""
        logger.info("Testing all connections...")

        all_good = True

        # Test configuration
        if not self.config.is_valid():
            logger.error("❌ Configuration validation failed")
            all_good = False
        else:
            logger.info("✅ Configuration is valid")

        # Test IMAP connection
        if self.imap_client:
            if self.imap_client.connect():
                logger.info("✅ IMAP connection successful")
                self.imap_client.disconnect()
            else:
                logger.error("❌ IMAP connection failed")
                all_good = False
        else:
            logger.error("❌ IMAP client not initialized")
            all_good = False

        # Test SMTP connection
        if self.smtp_client:
            if self.smtp_client.test_connection():
                logger.info("✅ SMTP connection successful")
            else:
                logger.error("❌ SMTP connection failed")
                all_good = False
        else:
            logger.error("❌ SMTP client not initialized")
            all_good = False

        # Test OpenAI connection
        if self.openai_client:
            if self.openai_client.test_connection():
                logger.info("✅ OpenAI API connection successful")
            else:
                logger.error("❌ OpenAI API connection failed")
                all_good = False
        else:
            logger.error("❌ OpenAI client not initialized")
            all_good = False

        if all_good:
            logger.info("🎉 All connections and configurations are working properly!")
        else:
            logger.error("⚠️  Some connections or configurations have issues")

        return all_good
