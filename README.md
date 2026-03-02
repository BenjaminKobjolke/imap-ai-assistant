# IMAP AI Assistant

An email automation system that monitors IMAP inboxes, processes incoming emails using OpenAI, and converts them into Remember the Milk (RTM) todos. The system detects task assignees from email content, routes tasks to the appropriate people, and can automatically generate professional client responses when tasks are completed.

Built for multi-account email environments, it handles the full lifecycle from email ingestion to task creation, assignee notification, response monitoring, and client follow-up — all with AI-powered intelligence.

## Key Features

- **Email-to-Todo Conversion** — AI extracts tasks from emails and formats them as RTM todos with importance and due dates
- **Task Assignment & Routing** — Automatically detects assignees and routes tasks to the right people via email forwarding
- **Response Processing** — Monitors assignee replies to detect task completion using AI analysis
- **Draft System** — Creates HTML draft emails for manual review instead of auto-sending client responses
- **Client Response Generation** — AI generates professional responses matching the original language and tone
- **Configurable Logging** — Rotating log files with separate categories for AI, email, and system events

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key (GPT-4o recommended)
- IMAP/SMTP email accounts
- Remember the Milk account with email import enabled

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
| `meetings` | Meeting cleanup folder paths and age limit |

See [Configuration Reference](docs/features/configuration.md) for full details.

## Usage

```bash
# Default: process unread emails AND assignee responses
call start.bat
# or: uv run python main.py

# Test all connections (IMAP, SMTP, OpenAI)
uv run python main.py --test

# Show system status summary
uv run python main.py --status

# Process only assignee responses
uv run python main.py --responses

# Inspect emails in an IMAP folder (read-only debug tool)
uv run python main.py --inspect INBOX
uv run python main.py --inspect "Company/@BKToDo" --use-processor-account

# List today's meetings with start/end times
uv run python main.py --todays-meetings

# Show details for a specific today's meeting (by index)
uv run python main.py --todays-meeting 2

# List meetings for any date (today, tomorrow, 5, 12.03, 12.03.2026)
uv run python main.py --meetings tomorrow
uv run python main.py --meetings 12.03

# Archive old meeting emails (based on ICS calendar date)
uv run python main.py --cleanup-meetings

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
- [Meeting Cleanup](docs/features/meeting-cleanup.md)
- [Configuration](docs/features/configuration.md)
