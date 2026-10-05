# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IMAP AI Assistant is an email automation system that processes emails and converts them into Remember the Milk (RTM) todos using OpenAI. It monitors IMAP inboxes, applies AI processing to categorize and assign tasks, and can generate client responses automatically.

## Essential Commands

```bash
# Install dependencies (requires uv: https://docs.astral.sh/uv/)
call install.bat
# or manually:
uv sync --all-groups

# Run the application
call start.bat
# or manually:
uv run python main.py

# Main execution modes
uv run python main.py                # No arguments: prints help
uv run python main.py --workflow rtm_todos                # Process unread emails, then assignee responses
uv run python main.py --workflow rtm_todos --auto-accept  # Same, every prompt answered with its default
uv run python main.py --workflow rtm_todos --drafts-only  # Same, mails saved as drafts in the main account, nothing sent
call start_workflow.bat              # Workflow with settings_live.json
call start_workflow_debug.bat        # Workflow with settings_debug.json, auto-accept
uv run python main.py --test         # Test all connections
uv run python main.py --test-email   # Send test email to self, verify arrival via IMAP
uv run python main.py --status       # Show system status
uv run python main.py --responses    # Process only assignee responses

# Debug: inspect emails in an IMAP folder (read-only, saves to debug/)
uv run python main.py --inspect INBOX
uv run python main.py --inspect "Company/@BKToDo" --use-processor-account

# List today's meetings with start/end times
uv run python main.py --todays-meetings

# List available Google Calendar IDs for configuration
uv run python main.py --list-calendars

# Process meeting invites interactively (requires Google Calendar setup)
uv run python main.py --process-invites

# Archive old meeting emails (uses ICS calendar date, not email date)
uv run python main.py --cleanup-meetings

# Update all dependencies
call update.bat
# or manually:
uv lock --upgrade && uv sync --all-groups

# Run linter and type checker
uv run ruff check src/ main.py
uv run mypy src/ main.py

# Run tests
call tools\tests.bat
# or manually:
uv run pytest tests/ -v

# Test logging functionality
uv run python test_logger.py
```

## Coding Rules

### Shell & CLI Rules
- **No compound shell commands** — never chain commands with `&&`, `||`, or `;` (e.g., do NOT use `cd /d "..." && git log`). Run each command as a separate tool call instead.
- **Never combine `cd` with other commands** — do NOT use `cd path && git status` or similar. Use absolute paths or run `cd` as a separate tool call.

### Common Rules (All Languages)
- Use English for all code, comments, and documentation
- One file = one primary responsibility; split when a file exceeds ~300 lines
- No hardcoded secrets — use environment variables or config files excluded from VCS
- Every public function/method must have a docstring or doc-comment explaining *why*, not *what*
- Prefer composition over inheritance
- Delete dead code — do not comment it out
- Use string constants or enums instead of magic strings/numbers; centralize constants in `src/constants.py`
- Use structured logging (key-value pairs) instead of string interpolation in log messages
- Handle errors explicitly — no silent catches or bare `except:`
- Write small, focused functions (aim for < 30 lines per function)
- Naming: `snake_case` for files and directories, descriptive names for variables and functions
- **Use objects for related values** — bundle related values into DTOs/dataclasses instead of many parameters
- **Prefer type-safe values** — use typed DTOs, enums, generics over loosely typed values (e.g. `dict`)
- **DRY (Don't Repeat Yourself)** — extract shared logic into reusable functions
- **TDD** — write tests first, confirm they fail, implement, confirm they pass
- **Confirm dependency versions** — verify version with user before adding new packages

### Python-Specific Rules
- **Dependency management:** `uv` with `pyproject.toml` as single source of truth — no `requirements.txt`
- **Formatting & linting:** `ruff` (configured in `pyproject.toml`)
- **Type checking:** `mypy` (configured in `pyproject.toml`)
- **Testing:** `pytest` — all tests live under `tests/`
- **Imports:** Use `from __future__ import annotations` in every module for modern type syntax
- **Type hints:** Required on all new function signatures (params + return)
- **String formatting:** f-strings only — no `.format()` or `%`
- **Data classes:** `@dataclass` or `NamedTuple` for plain data objects
- **Path handling:** `pathlib.Path` — no `os.path`
- **Logging:** Use `ApplicationLogger` (src/logging/app_logger.py) — no bare `print()` in library code
- **Mocking:** Always use `spec=ClassName` with `MagicMock` to validate against the real interface
- **Required batch files:** `start.bat` and `tools/tests.bat` must exist and be kept up to date
- **Localization:** Use `python-localization` library for multi-language string support

## Architecture & Core Components

### Multi-Account Email Processing Flow
1. **EmailProcessor** (src/processors/email_processor.py) orchestrates the workflow
2. Monitors processor account (ai@summera.ai) for emails from allowed senders
3. Uses **OpenAIClient** to convert emails to RTM todos with assignee detection
4. Routes tasks based on assignee configuration in settings.json
5. Sends formatted emails with tasks to appropriate destinations

### AI Integration Architecture
- **OpenAIClient** (src/ai/openai_client.py): Central AI interface
  - `process_email_to_todo()`: Converts emails to RTM format with assignee
  - `check_task_completion()`: Analyzes responses to determine if tasks are done
  - `generate_client_response()`: Creates professional client responses
- Uses prompt templates from `prompts/` directory
- All AI interactions are logged via ApplicationLogger

### Task Assignment & Routing System
- **settings.json** defines routing rules:
  - `processing.my_own_tasks`: Configuration for self-assigned tasks
  - `processing.others`: Named assignees (markus, tamara) with their routing
- Each assignee has:
  - `target_folder`: IMAP folder for processed emails
  - `additional_subject_tag`: Tags added to subject line
  - `email_address`: Where to send their tasks

### Response Processing Pipeline
1. **ResponseProcessor** monitors assignee responses in main account
2. Uses AI to determine if tasks are completed (high confidence threshold)
3. **ClientResponseGenerator** creates professional responses for completed tasks
4. Maintains conversation context by searching sent emails

### Logging System
- **ApplicationLogger** (src/logging/app_logger.py): Universal rotating logger
- Logs all AI requests/responses with full prompts and tokens used
- Categories: ai, email, system - each with separate log files
- Automatic rotation at 10MB with 5 backup files

## Configuration Structure

**settings.json** contains:
- `accounts`: Source IMAP accounts to monitor
- `openai`: API key, model (gpt-4o), temperature, max_tokens
- `remember_the_milk.email_address`: RTM inbox address
- `processing`: Routing rules for different assignees
- `allowed_senders`: Email whitelist for processing
- `smtp`: Processor account credentials for sending
- `logging`: Log directory, file sizes, categories

## Key Implementation Details

### Email Processing Logic
- Only processes emails from allowed_senders list
- Extracts first line as primary instruction for AI
- Maintains draft/sent folder structure per account
- Handles forwarded emails intelligently

### RTM Todo Format
- Format: `TODONAME !importance ^duedate`
- Importance: !1 (very), !2 (important), !3 (not so)
- Due dates: ^today, ^tomorrow, ^DD.MM.YYYY
- AI determines assignee from email content

### Prompt Engineering
- System prompts inject current date dynamically
- User prompts use template substitution with email data
- Special rules for specific domains (e.g., @nuernbergmesse.de)
- Language detection from email content

### Error Handling
- Fallback todo creation when AI fails
- Connection testing for all services
- Comprehensive logging of errors with request IDs

## Testing & Debugging

```bash
# Check AI logging
type logs\ai.log

# View system events
type logs\system.log

# Inspect emails in any IMAP folder for debugging
# Fetches emails, prints summary to console, saves full content to debug/
uv run python main.py --inspect INBOX                          # Main account INBOX
uv run python main.py --inspect "Company/@BKToDo"              # Specific folder
uv run python main.py --inspect INBOX --use-processor-account  # Processor account

# Run tests
uv run pytest tests/ -v

# Test specific components
uv run python test_logger.py  # Tests ApplicationLogger with mock AI calls
```

## Important Files to Understand

- `pyproject.toml`: Dependency definitions, tool configuration (ruff, mypy, pytest)
- `uv.lock`: Pinned dependency versions (generated, do not edit manually)
- `main.py`: Entry point with command-line argument handling
- `src/processors/email_processor.py`: Main orchestration logic
- `src/ai/openai_client.py`: All AI interactions and prompt handling
- `src/config/settings.py`: Configuration management and validation
- `settings.json`: All runtime configuration
- `prompts/*.txt`: AI prompt templates (system and user prompts)
