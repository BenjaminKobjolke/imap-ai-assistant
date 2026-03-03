"""RSVP handling for meeting invites — build, draft, and send acceptance replies."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output

logger = logging.getLogger(__name__)


class InviteRsvp:
    """Builds and sends/saves RSVP acceptance replies for meeting invites."""

    @staticmethod
    def handle_rsvp(
        client: EnhancedImapClient,
        config: ConfigManager,
        account_config: dict,
        invite: object,
    ) -> None:
        """Create an RSVP acceptance as a draft or send it directly via SMTP."""
        if config.meetings_rsvp_send_directly:
            success = InviteRsvp._send_rsvp_email(config, account_config, invite)
            if success:
                send_output(f"  RSVP sent to {invite.organizer_email}.")
            else:
                send_output("  Failed to send RSVP.")
        else:
            success = InviteRsvp._create_rsvp_draft(client, config, account_config, invite)
            if success:
                send_output("  RSVP draft created in Drafts folder.")
            else:
                send_output("  Failed to create RSVP draft.")

    @staticmethod
    def _build_rsvp_ics(invite: object, user_email: str) -> str:
        """Build a METHOD:REPLY ICS string with PARTSTAT=ACCEPTED."""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//IMAP AI Assistant//EN",
            "METHOD:REPLY",
            "BEGIN:VEVENT",
        ]

        if invite.uid:
            lines.append(f"UID:{invite.uid}")
        if invite.dtstart:
            lines.append(f"DTSTART:{invite.dtstart.strftime('%Y%m%dT%H%M%SZ')}")
        if invite.dtend:
            lines.append(f"DTEND:{invite.dtend.strftime('%Y%m%dT%H%M%SZ')}")
        if invite.summary:
            lines.append(f"SUMMARY:{invite.summary}")
        if invite.organizer_email:
            lines.append(f"ORGANIZER:mailto:{invite.organizer_email}")

        now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        lines.append(f"DTSTAMP:{now_utc}")
        lines.append("SEQUENCE:0")

        lines.append(
            f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT"
            f";PARTSTAT=ACCEPTED;CN={user_email}:mailto:{user_email}"
        )
        lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")

        return "\r\n".join(lines)

    @staticmethod
    def _build_rsvp_message(invite: object, user_email: str) -> MIMEMultipart:
        """Build an iTIP REPLY MIME message for an RSVP acceptance."""
        reply_ics = InviteRsvp._build_rsvp_ics(invite, user_email)
        subject = f"Accepted: {invite.summary or invite.subject}"
        body_html = (
            '<div style="font-family: Arial, sans-serif; font-size: 14px;">'
            f"<p>Accepted: {invite.summary or invite.subject}</p>"
            "</div>"
        )

        msg = MIMEMultipart("mixed")
        msg["From"] = user_email
        msg["To"] = invite.organizer_email
        msg["Subject"] = subject
        msg["X-IMAP-Assistant-Invite-RSVP"] = "ACCEPTED"

        html_part = MIMEText(body_html, "html")
        msg.attach(html_part)

        cal_part = MIMENonMultipart("text", "calendar", charset="utf-8", method="REPLY")
        cal_part.set_payload(reply_ics.encode("utf-8"))
        cal_part["Content-Transfer-Encoding"] = "8bit"
        cal_part.add_header("Content-Disposition", "inline", filename="invite.ics")
        msg.attach(cal_part)

        return msg

    @staticmethod
    def _create_rsvp_draft(
        client: EnhancedImapClient,
        config: ConfigManager,
        account_config: dict,
        invite: object,
    ) -> bool:
        """Save an iTIP RSVP acceptance as a draft in the Drafts folder."""
        if not invite.organizer_email:
            logger.warning("No organizer email found, cannot create RSVP draft")
            return False

        user_email = account_config.get("email_address", "")
        drafts_folder = config.get_drafts_folder(account_config)

        try:
            msg = InviteRsvp._build_rsvp_message(invite, user_email)
            client.client.client.append(
                drafts_folder,
                msg.as_bytes(),
                [b"\\Draft"],
            )
            logger.info("RSVP draft created for %s", invite.organizer_email)
            return True
        except Exception as e:
            logger.error("Failed to create RSVP draft: %s", e)
            return False

    @staticmethod
    def _send_rsvp_email(
        config: ConfigManager,
        account_config: dict,
        invite: object,
    ) -> bool:
        """Send an iTIP RSVP acceptance directly via SMTP."""
        if not invite.organizer_email:
            logger.warning("No organizer email found, cannot send RSVP")
            return False

        smtp_cfg = config.get_account_smtp_config(account_config)
        if not smtp_cfg:
            logger.error("No SMTP configuration available for RSVP send")
            return False

        user_email = account_config.get("email_address", "")

        try:
            msg = InviteRsvp._build_rsvp_message(invite, user_email)

            server = smtplib.SMTP(smtp_cfg["server"], smtp_cfg.get("port", 587))
            if smtp_cfg.get("use_tls", True):
                server.starttls()
            server.login(smtp_cfg["username"], smtp_cfg["password"])
            server.sendmail(user_email, invite.organizer_email, msg.as_string())
            server.quit()

            logger.info("RSVP sent directly to %s", invite.organizer_email)
            return True
        except Exception as e:
            logger.error("Failed to send RSVP: %s", e)
            return False
