"""Centralized string constants used across the application."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Custom email headers
# ---------------------------------------------------------------------------
HEADER_TASK_ID = "X-IMAP-Assistant-Task-ID"
HEADER_ORIGINAL_SENDER = "X-IMAP-Assistant-Original-Sender"
HEADER_CREATED = "X-IMAP-Assistant-Created"
HEADER_DRAFT_CREATED = "X-IMAP-Assistant-Draft-Created"
HEADER_INVITE_RSVP = "X-IMAP-Assistant-Invite-RSVP"

# ---------------------------------------------------------------------------
# MIME content types
# ---------------------------------------------------------------------------
MIME_TEXT_PLAIN = "text/plain"
MIME_TEXT_HTML = "text/html"
MIME_TEXT_CALENDAR = "text/calendar"

# ---------------------------------------------------------------------------
# AI status strings
# ---------------------------------------------------------------------------
STATUS_COMPLETED = "completed"
STATUS_UNCLEAR = "unclear"
KEY_STATUS = "status"
KEY_CONFIDENCE = "confidence"
KEY_REASON = "reason"
KEY_RESPONSE = "response"
KEY_SUBJECT = "subject"
KEY_SUCCESS = "success"

# ---------------------------------------------------------------------------
# Task data keys
# ---------------------------------------------------------------------------
KEY_TASK_SUBJECT = "task_subject"
KEY_TASK_BODY = "task_body"
KEY_TASK_ID = "task_id"
KEY_EMAIL_MESSAGE = "email_message"
KEY_MESSAGE_ID = "message_id"

# ---------------------------------------------------------------------------
# Config keys
# ---------------------------------------------------------------------------
CFG_EMAIL_ADDRESS = "email_address"
CFG_TARGET_FOLDER = "target_folder"
CFG_ADDITIONAL_SUBJECT_TAG = "additional_subject_tag"

# ---------------------------------------------------------------------------
# Markers and prefixes
# ---------------------------------------------------------------------------
MARKER_DRY_RUN = "[DRY RUN]"
PREFIX_DRAFT_RESPONSE = "[DRAFT-RESPONSE]"
PREFIX_REPLY = "Re: "

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "gpt-4o"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 100
DEFAULT_TODO_FOLDER = "@BKToDo"
DEFAULT_TODO_TAG = "#BKToDo"

# ---------------------------------------------------------------------------
# IMAP folder defaults
# ---------------------------------------------------------------------------
FOLDER_INBOX = "INBOX"
FOLDER_DRAFTS = "Drafts"
FOLDER_SENT = "Sent"
FOLDER_TRASH = "Trash"

# ---------------------------------------------------------------------------
# Inbox-zero action keys
# ---------------------------------------------------------------------------
ACTION_DRAFT_REPLY = "draft_reply"
ACTION_SHOW_BODY = "show_body"

# ---------------------------------------------------------------------------
# Invite action keys (used by InviteProcessor / inbox-zero)
# ---------------------------------------------------------------------------
ACTION_ADD_CALENDAR = "add_calendar"
ACTION_ARCHIVE_INVITE = "archive_invite"
ACTION_DELETE_CALENDAR = "delete_calendar"
ACTION_MOVE_MEETINGS = "move_meetings"

# ---------------------------------------------------------------------------
# Greeting constants
# ---------------------------------------------------------------------------
GREETING_MORNING = "Guten Morgen"
GREETING_DEFAULT = "Hallo"
GREETING_MORNING_HOUR_LIMIT = 10

# ---------------------------------------------------------------------------
# Salutation AI response keys
# ---------------------------------------------------------------------------
KEY_SALUTATION = "salutation"
KEY_FORMAL = "formal"

# ---------------------------------------------------------------------------
# Draft reply header
# ---------------------------------------------------------------------------
HEADER_DRAFT_REPLY = "X-IMAP-Assistant-Draft-Reply"

# ---------------------------------------------------------------------------
# Search mode constants (wizard folder selection)
# ---------------------------------------------------------------------------
SEARCH_MODE_DEFAULT = "default"
SEARCH_MODE_ALL = "all"
SEARCH_MODE_INBOX = "inbox"
SEARCH_MODE_SENT = "sent"
SEARCH_MODE_FOLDER = "folder"
