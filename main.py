from __future__ import annotations

import argparse
import logging
import os
import sys

# Ensure stdout/stderr can handle Unicode on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from src.processors.email_processor import EmailProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Suppress INFO logs when running under the scheduler bot
if os.environ.get("TASK_SCHEDULER") == "1":
    logging.getLogger().setLevel(logging.WARNING)

# Suppress DEBUG logs from underlying libraries
logging.getLogger('imap_client_lib').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('googleapiclient').setLevel(logging.WARNING)
logging.getLogger('google.auth').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> None:
    """Main application entry point."""
    parser = argparse.ArgumentParser(description='IMAP AI Assistant - AI-powered email to todo conversion')
    parser.add_argument('--test', action='store_true', help='Test all connections and configurations')
    parser.add_argument('--status', action='store_true', help='Show status summary')
    parser.add_argument('--responses', action='store_true', help='Process assignee responses')
    parser.add_argument('--inspect', metavar='FOLDER', help='Inspect emails in the given IMAP folder (e.g. INBOX)')
    parser.add_argument('--use-processor-account', action='store_true',
                        help='Use processor account instead of main account (for --inspect)')
    parser.add_argument('--setup-meetings', action='store_true',
                        help='Interactive setup for meeting calendar and conflict-check calendars')
    parser.add_argument('--list-calendars', action='store_true',
                        help='List available Google Calendar IDs for configuration')
    parser.add_argument('--process-invites', action='store_true',
                        help='Interactively process meeting invites and add to Google Calendar')
    parser.add_argument('--cleanup-meetings', action='store_true',
                        help='Archive old meeting emails based on their calendar date')
    parser.add_argument('--meetings', metavar='DATE',
                        help="List meetings for a date. Accepts: today, tomorrow, 5, 12.03, 12.03.2026")
    parser.add_argument('--test-email', action='store_true',
                        help='Send a test email and verify it arrives via IMAP')
    parser.add_argument('--todays-meetings', action='store_true', help="List today's meetings with times")
    parser.add_argument('--todays-meeting', type=int, metavar='N',
                        help="Show details for today's meeting N (use --todays-meetings to see indices)")
    parser.add_argument('--workflow', nargs='?', const='__list__', metavar='NAME',
                        help="Run a workflow by name, or list available workflows if no name given")
    parser.add_argument('--set-meeting-calendar', metavar='ID',
                        help='Set the Google Calendar ID used for adding events')
    parser.add_argument('--set-meeting-free-check-calendar', metavar='ID',
                        help='Add a Google Calendar ID to check for scheduling conflicts')
    parser.add_argument('--remove-meeting-free-check-calendar', metavar='ID',
                        help='Remove a Google Calendar ID from the conflict-check list')
    parser.add_argument('--add-date', nargs='+', metavar='ARG',
                        help='Create event: TITLE [DATE] [START[-END]] [@CALENDAR]')
    parser.add_argument('--set-add-date-calendar', metavar='ID',
                        help='Set default Google Calendar for --add-date events')
    parser.add_argument('--tag-rules', action='store_true',
                        help='List all subject tag rules')
    parser.add_argument('--setup-tag-rules', action='store_true',
                        help='Interactive wizard to manage subject tag rules')
    parser.add_argument('--add-sender-tag', nargs=2, metavar=('PATTERN', 'TAG'),
                        help='Add a sender-based subject tag rule (e.g. @nuernbergmesse.de #project_tag)')
    parser.add_argument('--remove-sender-tag', metavar='PATTERN',
                        help='Remove a sender-based subject tag rule by pattern')
    parser.add_argument('--add-keyword-tag', nargs='+', metavar='ARG',
                        help='Add keyword tag rule (match=all): TAG KEYWORD [KEYWORD...]')
    parser.add_argument('--add-keyword-tag-any', nargs='+', metavar='ARG',
                        help='Add keyword tag rule (match=any): TAG KEYWORD [KEYWORD...]')
    parser.add_argument('--remove-keyword-tag', metavar='TAG',
                        help='Remove a keyword-based subject tag rule by tag')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run without sending emails, moving messages, or marking as read')
    parser.add_argument('--inbox-zero', action='store_true',
                        help='Interactively process INBOX emails one by one')
    parser.add_argument('--unread-only', action='store_true',
                        help='Only process unread emails (use with --inbox-zero)')
    parser.add_argument('--browse', action='store_true',
                        help='Browse IMAP folders and emails interactively')
    parser.add_argument('--search', nargs='?', const='__wizard__', metavar='TERM',
                        help='Search emails. Prefix with to:/from:/s: for field-specific. No arg = wizard.')
    parser.add_argument('--body', metavar='TERM', help='Search body text (use with --search)')
    parser.add_argument('--date', metavar='DD.MM.YYYY', help='Filter by exact date')
    parser.add_argument('--date-after', metavar='DATE', help='Filter emails after date')
    parser.add_argument('--date-before', metavar='DATE', help='Filter emails before date')
    parser.add_argument('--path', metavar='FOLDER', help='Search in specific IMAP folder')
    parser.add_argument('--update-cache', action='store_true', help='Rebuild email search cache')
    parser.add_argument('--fast', action='store_true',
                        help='Skip folders with unchanged message count (use with --update-cache)')
    parser.add_argument('--folders', metavar='FOLDERS',
                        help='Semicolon-separated folder list for --update-cache')
    parser.add_argument('--update-calendars', action='store_true',
                        help='Update the cached Google Calendar list')
    parser.add_argument('--list-cached-calendars', action='store_true',
                        help='Print cached Google Calendar names and IDs')
    parser.add_argument('--ai', nargs='*', default=None,
                        help='Conversational AI mode (optionally pass initial message)')
    parser.add_argument('--config', default='settings.json', help='Path to configuration file')

    args = parser.parse_args()

    # Initialize the email processor
    processor = EmailProcessor(args.config, dry_run=args.dry_run)

    if args.test:
        # Test all connections
        logger.info("🔍 Testing all connections and configurations...")
        success = processor.test_connections()
        if success:
            logger.info("✅ All systems are ready!")
        else:
            logger.error("❌ Some systems have issues. Please check the logs.")
        return

    if args.test_email:
        # Send a test email and verify it arrives
        logger.info("📧 Testing email send/receive...")
        processor.test_email()
        return

    if args.status:
        # Show status summary
        status = processor.get_status_summary()
        logger.info("📊 System Status Summary:")
        for key, value in status.items():
            logger.info(f"  {key}: {value}")
        return

    if args.responses:
        # Process assignee responses
        logger.info("🔄 Processing assignee responses...")
        processor.process_assignee_responses()
        logger.info("✅ Response processing completed")
        return

    if args.inspect:
        # Inspect emails in a folder (read-only debug tool)
        logger.info(f"🔍 Inspecting folder: {args.inspect}")
        processor.inspect_folder(args.inspect, use_processor_account=args.use_processor_account)
        return

    if args.setup_meetings:
        processor.setup_meetings()
        return

    if args.set_meeting_calendar:
        processor.set_meeting_calendar(args.set_meeting_calendar)
        return

    if args.set_meeting_free_check_calendar:
        processor.set_meeting_free_check_calendar(args.set_meeting_free_check_calendar)
        return

    if args.remove_meeting_free_check_calendar:
        processor.remove_meeting_free_check_calendar(args.remove_meeting_free_check_calendar)
        return

    if args.add_date:
        processor.add_date(args.add_date)
        return

    if args.set_add_date_calendar:
        processor.set_add_date_calendar(args.set_add_date_calendar)
        return

    if args.tag_rules:
        processor.list_tag_rules()
        return

    if args.setup_tag_rules:
        processor.setup_tag_rules()
        return

    if args.add_sender_tag:
        pattern, tag = args.add_sender_tag
        processor.add_sender_tag(pattern, tag)
        return

    if args.remove_sender_tag:
        processor.remove_sender_tag(args.remove_sender_tag)
        return

    if args.add_keyword_tag:
        if len(args.add_keyword_tag) < 2:
            print("Usage: --add-keyword-tag TAG KEYWORD [KEYWORD...]")
            return
        tag = args.add_keyword_tag[0]
        keywords = args.add_keyword_tag[1:]
        processor.add_keyword_tag(tag, keywords, match="all")
        return

    if args.add_keyword_tag_any:
        if len(args.add_keyword_tag_any) < 2:
            print("Usage: --add-keyword-tag-any TAG KEYWORD [KEYWORD...]")
            return
        tag = args.add_keyword_tag_any[0]
        keywords = args.add_keyword_tag_any[1:]
        processor.add_keyword_tag(tag, keywords, match="any")
        return

    if args.remove_keyword_tag:
        processor.remove_keyword_tag(args.remove_keyword_tag)
        return

    if args.list_calendars:
        # List available Google Calendar IDs
        logger.info("Listing Google Calendars...")
        processor.list_calendars()
        return

    if args.update_calendars:
        logger.info("Updating cached Google Calendar list...")
        processor.update_calendar_cache()
        return

    if args.list_cached_calendars:
        processor.list_cached_calendars()
        return

    if args.process_invites:
        # Process meeting invites interactively
        processor.process_invites()
        return

    if args.cleanup_meetings:
        # Archive old meeting emails
        logger.info("🗓️ Starting meeting cleanup...")
        processor.cleanup_meetings()
        logger.info("✅ Meeting cleanup completed")
        return

    if args.meetings is not None:
        # List meetings for a specific date
        processor.meetings(args.meetings)
        return

    if args.todays_meeting is not None:
        # Show detail for a specific meeting
        processor.todays_meeting_detail(args.todays_meeting)
        return

    if args.todays_meetings:
        # List today's meetings
        processor.todays_meetings()
        return

    if args.workflow is not None:
        if args.workflow == '__list__':
            processor.list_workflows()
        else:
            processor.run_workflow(args.workflow)
        return

    if args.browse:
        processor.browse()
        return

    if args.inbox_zero:
        processor.inbox_zero(unread_only=args.unread_only)
        return

    if args.update_cache:
        processor.update_search_cache(folders=args.folders, fast=args.fast)
        return

    if args.search is not None:
        if args.search == '__wizard__':
            processor.search_wizard()
        else:
            processor.search_emails(
                search_term=args.search,
                body_term=args.body,
                date=args.date,
                date_after=args.date_after,
                date_before=args.date_before,
                path=args.path,
            )
        return

    if args.ai is not None:
        initial_message = " ".join(args.ai) if args.ai else None
        processor.ai_chat(initial_message=initial_message)
        return

    # No arguments: show help
    parser.print_help()


if __name__ == "__main__":
    main()
