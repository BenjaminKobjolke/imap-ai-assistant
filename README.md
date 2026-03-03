# IMAP AI Assistant

An email automation system that monitors IMAP inboxes, processes incoming emails using OpenAI, and converts them into Remember the Milk (RTM) todos. The system detects task assignees from email content, routes tasks to the appropriate people, and can automatically generate professional client responses when tasks are completed.

Built for multi-account email environments, it handles the full lifecycle from email ingestion to task creation, assignee notification, response monitoring, and client follow-up — all with AI-powered intelligence.

## Key Features

- **Email-to-Todo Conversion** — AI extracts tasks from emails and formats them as RTM todos with importance and due dates
- **Task Assignment & Routing** — Automatically detects assignees and routes tasks to the right people via email forwarding
- **Response Processing** — Monitors assignee replies to detect task completion using AI analysis
- **Draft System** — Creates HTML draft emails for manual review instead of auto-sending client responses
- **Client Response Generation** — AI generates professional responses matching the original language and tone
- **Meeting Invite Processing** — Interactively review inbox invites, add to Google Calendar, and send RSVP acceptances
- **Configurable Logging** — Rotating log files with separate categories for AI, email, and system events

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key (GPT-4o recommended)
- IMAP/SMTP email accounts
- Remember the Milk account with email import enabled
- Google Cloud project with Calendar API enabled (for `--process-invites`)

## Installation

Using the install script:

```bash
call install.bat
```

Or manually:

```bash
uv sync --all-groups
```

## Configuration

Copy and edit `settings.json` with your credentials:

| Section | Purpose |
|---------|---------|
| `accounts` | Source IMAP accounts to monitor |
| `openai` | API key, model, temperature, max tokens |
| `remember_the_milk` | RTM email address for todo import |
| `processing` | Task routing rules for self and other assignees |
| `allowed_senders` | Email whitelist — only these senders are processed |
| `smtp` | Processor account credentials for sending emails |
| `logging` | Log directory, file sizes, rotation settings |
| `meetings` | Meeting cleanup folder paths, age limit, and Google Calendar settings |

See [Configuration Reference](docs/features/configuration.md) for full details.

## Google Calendar Setup

The `--process-invites` command requires a Google Cloud project with Calendar API access. Follow these steps:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project (or select an existing one)
2. Enable the **Google Calendar API** under *APIs & Services > Library*
3. Configure the **OAuth consent screen** under *APIs & Services > OAuth consent screen*
   - Choose "External" user type
   - Fill in the required app information
4. Create **OAuth 2.0 credentials** under *APIs & Services > Credentials*
   - Click *Create Credentials > OAuth client ID*
   - Application type: **Desktop app**
   - Download the JSON file and save it as `credentials.json` in the project root
5. Add an **Authorized redirect URI** in the OAuth client settings:
   - `http://localhost:51032/`
6. On first run of `--process-invites`, a browser window opens for Google account consent
7. After authorization, a `token.json` file is created automatically for subsequent runs

The credential and token paths are configurable in `settings.json` under `meetings.google_calendar`.

## Usage

```bash
# No arguments: shows help
uv run python main.py
```

### Command Line Arguments

| Argument | Description |
|----------|-------------|
| `--test` | Test all connections and configurations (IMAP, SMTP, OpenAI) |
| `--test-email` | Send a test email to self and verify it arrives via IMAP |
| `--status` | Show system status summary |
| `--responses` | Process only assignee responses |
| `--inspect FOLDER` | Inspect emails in an IMAP folder (read-only debug tool) |
| `--use-processor-account` | Use processor account instead of main account (for `--inspect`) |
| `--todays-meetings` | List today's meetings with start/end times |
| `--todays-meeting N` | Show details for today's meeting N (use `--todays-meetings` to see indices) |
| `--meetings DATE` | List meetings for a date. Accepts: `today`, `tomorrow`, `5`, `12.03`, `12.03.2026` |
| `--process-invites` | Interactively process meeting invites, add to Google Calendar, handle cancellations, send RSVP |
| `--cleanup-meetings` | Archive old meeting emails based on their ICS calendar date |
| `--setup-meetings` | Interactive setup for meeting calendar and conflict-check calendars |
| `--list-calendars` | List available Google Calendar IDs for configuration |
| `--set-meeting-calendar ID` | Set the Google Calendar ID used for adding events |
| `--set-meeting-free-check-calendar ID` | Add a Google Calendar ID to check for scheduling conflicts |
| `--remove-meeting-free-check-calendar ID` | Remove a Google Calendar ID from the conflict-check list |
| `--add-date TITLE [DATE] [START[-END]] [@CALENDAR]` | Create a calendar event (date defaults to today, time to current hour) |
| `--set-add-date-calendar ID` | Set default Google Calendar for `--add-date` events |
| `--tag-rules` | List all subject tag rules |
| `--setup-tag-rules` | Interactive wizard to manage subject tag rules |
| `--add-sender-tag PATTERN TAG` | Add a sender-based subject tag rule |
| `--remove-sender-tag PATTERN` | Remove a sender-based subject tag rule |
| `--add-keyword-tag TAG KEYWORD [...]` | Add keyword tag rule (match=all) |
| `--add-keyword-tag-any TAG KEYWORD [...]` | Add keyword tag rule (match=any) |
| `--remove-keyword-tag TAG` | Remove a keyword-based subject tag rule |
| `--search [TERM]` | Search emails (prefix with `to:`/`from:`/`s:` for field-specific; no arg = wizard) |
| `--body TERM` | Search body text (use with `--search`) |
| `--date DD.MM.YYYY` | Filter by exact date |
| `--date-after DATE` | Filter emails after date |
| `--date-before DATE` | Filter emails before date |
| `--path FOLDER` | Search in specific IMAP folder |
| `--update-cache` | Rebuild email search cache |
| `--folders FOLDERS` | Semicolon-separated folder list for `--update-cache` |
| `--dry-run` | Run without sending emails, moving messages, or marking as read |
| `--workflow [NAME]` | Run a workflow by name, or list available workflows if no name given |
| `--config PATH` | Path to configuration file (default: `settings.json`) |

### Examples

```bash
# Default workflow: process unread emails AND assignee responses
call start.bat
# or: uv run python main.py

# Test connections
uv run python main.py --test

# Inspect emails in a folder (read-only)
uv run python main.py --inspect INBOX
uv run python main.py --inspect "Company/@BKToDo" --use-processor-account

# Meetings
uv run python main.py --todays-meetings
uv run python main.py --todays-meeting 2
uv run python main.py --meetings tomorrow
uv run python main.py --meetings 12.03

# Process invites (accept/decline/handle cancellations)
uv run python main.py --process-invites

# Archive old meeting emails
uv run python main.py --cleanup-meetings

# Add a calendar event
call add_date.bat "Team Standup" 05.03.2026 9-10
uv run python main.py --add-date "Client Call" 10.03.2026 14-15 @Work

# Tag rules
uv run python main.py --tag-rules
uv run python main.py --add-sender-tag @nuernbergmesse.de NM

# Search emails
uv run python main.py --search "from:john@example.com"
uv run python main.py --search "project update" --date-after 01.01.2026

# Dry run (no side effects)
uv run python main.py --dry-run

# Use a custom config file
uv run python main.py --config path/to/settings.json

# Update all dependencies
call update.bat

# Run tests
call tools\tests.bat
```

## Project Structure

```
imap-ai-assistant/
├── main.py                          # CLI entry point
├── settings.json                    # Runtime configuration
├── src/
│   ├── ai/
│   │   └── openai_client.py         # OpenAI API integration
│   ├── calendar/
│   │   └── google_calendar_client.py # Google Calendar OAuth & API
│   ├── config/
│   │   └── settings.py              # Configuration manager
│   ├── email/
│   │   ├── imap_client.py           # IMAP client wrapper
│   │   └── smtp_client.py           # SMTP client wrapper
│   ├── logging/
│   │   └── app_logger.py            # Rotating file logger
│   └── processors/
│       ├── email_processor.py       # Main orchestrator
│       ├── task_processor.py        # Email-to-todo processing
│       ├── response_processor.py    # Assignee response handling
│       ├── client_response_generator.py  # Draft email creation
│       ├── email_inspector.py       # Email inspection/debug tool
│       ├── invite_processor.py      # Meeting invite processing
│       ├── meeting_cleanup.py       # Meeting email archival
│       └── relationship_analyzer.py # Tone/formality detection
├── prompts/                         # AI prompt templates
│   ├── system_prompt.txt
│   ├── user_prompt.txt
│   ├── task_completion_system_prompt.txt
│   ├── task_completion_user_prompt.txt
│   ├── client_response_system_prompt.txt
│   └── client_response_user_prompt.txt
├── data/
│   └── footer.html                  # Email footer template
├── logs/                            # Generated log files
└── docs/features/                   # Feature documentation
```

## Feature Documentation

Detailed documentation for each feature is available in [`docs/features/`](docs/features/):

- [Default Workflow](docs/features/default-workflow.md)
- [Email-to-Todo Conversion](docs/features/email-to-todo-conversion.md)
- [Task Assignment & Routing](docs/features/task-assignment-routing.md)
- [Response Processing](docs/features/response-processing.md)
- [Draft System](docs/features/draft-system.md)
- [Client Response Generation](docs/features/client-response-generation.md)
- [AI Integration](docs/features/ai-integration.md)
- [Logging](docs/features/logging.md)
- [Email Inspection](docs/features/email-inspection.md)
- [Meeting Invite Processing](docs/features/process-invites.md)
- [Meeting Cleanup](docs/features/meeting-cleanup.md)
- [Configuration](docs/features/configuration.md)
