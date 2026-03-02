import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

CUSTOM_HEADERS = [
    "X-IMAP-Assistant-Task-ID",
    "X-IMAP-Assistant-Original-Sender",
    "X-IMAP-Assistant-Created",
    "X-IMAP-Assistant-Draft-Created",
]


def _safe_print(text):
    """Print text safely on Windows console by replacing unencodable chars."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


class EmailInspector:
    """Utility class for inspecting and debugging emails from IMAP folders."""

    @staticmethod
    def print_summary(index, total, email_message, imap_client, saved_path=None):
        """Print a formatted console summary for a single email."""
        subject = email_message.subject or "(no subject)"
        from_addr = email_message.from_address or "(unknown)"

        # Extract body preview
        _, _, body_excerpt = imap_client.extract_email_content(email_message)
        body_preview = body_excerpt[:200] if body_excerpt else "(empty body)"

        # Extract custom header
        task_id = "N/A"
        if hasattr(email_message, "raw_message") and email_message.raw_message:
            task_id = email_message.raw_message.get("X-IMAP-Assistant-Task-ID", "N/A")

        # Attachment info
        attachments = getattr(email_message, "attachments", []) or []
        attachment_names = [a.filename for a in attachments if a.filename]
        has_calendar = bool(email_message.get_body("text/calendar")) if hasattr(email_message, "get_body") else False
        if has_calendar and "calendar.ics" not in attachment_names:
            attachment_names.append("calendar.ics (MIME part)")

        if attachment_names:
            att_str = f"{len(attachment_names)} ({', '.join(attachment_names)})"
        else:
            att_str = "none"

        _safe_print(f"\n--- Email {index}/{total} ---")
        _safe_print(f"  From:        {from_addr}")
        _safe_print(f"  Subject:     {subject}")
        _safe_print(f"  Date:        {getattr(email_message, 'date', 'N/A')}")
        _safe_print(f"  Task ID:     {task_id}")
        _safe_print(f"  Attachments: {att_str}")
        _safe_print(f"  Body (first 200 chars): {body_preview}")
        if saved_path:
            _safe_print(f"  Saved to:    {saved_path}")
        _safe_print(f"---{'─' * 20}---")

    @staticmethod
    def save_to_file(email_message, imap_client, output_dir="debug"):
        """Save full email details and attachments to a subdirectory.

        Returns the path of the saved directory, or None on failure.
        """
        try:
            subject = email_message.subject or "no_subject"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_subject = re.sub(r'[^\w\s-]', '', subject)[:50].strip().replace(' ', '_')
            dir_name = f"{timestamp}_{safe_subject}"
            dir_path = os.path.join(output_dir, dir_name)
            os.makedirs(dir_path, exist_ok=True)

            from_addr = email_message.from_address or "(unknown)"

            # Get full bodies
            plain_body = ""
            has_html = False
            try:
                plain_body = email_message.get_body("text/plain") or ""
                has_html = bool(email_message.get_body("text/html"))
            except Exception:
                pass

            # Extract text/calendar MIME part
            calendar_body = None
            try:
                calendar_body = email_message.get_body("text/calendar")
            except Exception:
                pass

            # Extract custom headers
            custom_headers = {}
            if hasattr(email_message, "raw_message") and email_message.raw_message:
                for header_name in CUSTOM_HEADERS:
                    value = email_message.raw_message.get(header_name)
                    if value:
                        custom_headers[header_name] = value

            # Build raw headers dump
            raw_headers_dump = ""
            if hasattr(email_message, "raw_message") and email_message.raw_message:
                raw_headers_dump = "\n".join(
                    f"  {key}: {value}"
                    for key, value in email_message.raw_message.items()
                )

            # Save attachments
            attachments = getattr(email_message, "attachments", []) or []
            saved_attachments = []
            for attachment in attachments:
                if attachment.filename and attachment.data:
                    safe_att_name = re.sub(r'[^\w.\s-]', '_', attachment.filename)[:100]
                    att_path = os.path.join(dir_path, safe_att_name)
                    with open(att_path, "wb") as af:
                        af.write(attachment.data)
                    saved_attachments.append((attachment.filename, attachment.content_type, att_path))
                    logger.debug(f"Saved attachment: {att_path}")

            # Save text/calendar MIME part as calendar.ics if not already in attachments
            calendar_in_attachments = any(
                a.content_type == "text/calendar" for a in attachments
            )
            if calendar_body and not calendar_in_attachments:
                ics_path = os.path.join(dir_path, "calendar.ics")
                with open(ics_path, "w", encoding="utf-8") as cf:
                    cf.write(calendar_body)
                saved_attachments.append(("calendar.ics", "text/calendar (MIME part)", ics_path))
                logger.debug(f"Saved calendar MIME part: {ics_path}")

            # Write email summary
            summary_path = os.path.join(dir_path, "email.txt")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"Subject: {subject}\n")
                f.write(f"From: {from_addr}\n")
                f.write(f"Date: {getattr(email_message, 'date', 'N/A')}\n")
                f.write("\n")

                if custom_headers:
                    f.write("=== Custom Headers ===\n")
                    for key, value in custom_headers.items():
                        f.write(f"  {key}: {value}\n")
                    f.write("\n")

                if saved_attachments:
                    f.write("=== Attachments ===\n")
                    for att_name, att_type, att_path in saved_attachments:
                        f.write(f"  {att_name} ({att_type})\n")
                    f.write("\n")

                f.write("=== Plain Text Body ===\n")
                f.write(plain_body if plain_body else "(empty)")
                f.write("\n\n")

                f.write(f"=== HTML Body: {'present' if has_html else 'absent'} ===\n\n")

                if raw_headers_dump:
                    f.write("=== Raw Headers ===\n")
                    f.write(raw_headers_dump)
                    f.write("\n")

            logger.info(f"Saved email inspection to {dir_path}")
            return dir_path

        except Exception as e:
            logger.error(f"Error saving email inspection file: {e}")
            return None
