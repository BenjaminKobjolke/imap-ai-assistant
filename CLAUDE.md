# Version
2

# Coding Rules (Pointer)

This project's rules live in two files in the project root:

- `CODING_RULES.md` — code quality and conventions. BINDING for all code work in
  this repository, always.
- `IMPLEMENTATION_FLOW.md` — the end-to-end flow to follow when planning and
  implementing a change (checks, gates, Definition of Done).

MANDATORY: Before writing or editing ANY code, you MUST Read BOTH files in full
**in the current session**. Do not rely on memory of a previous session, a
summary, or partial reads.

If you are about to make a code change and have not read both files in this
session: STOP, read them, then continue.

An external tool may orchestrate the implementation itself. When a skill or run
states that the implementation is orchestrated, ignore `IMPLEMENTATION_FLOW.md`
entirely — the orchestrator runs those steps as its own phases. `CODING_RULES.md`
stays binding either way.

Do not inline rules back into this file and do not use `@import` for either file —
they are intentionally referenced, not imported.

This project's code directory is src/ (graphify graph scope; main.py is outside it).

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

### Project-specific rules
- Do not chain shell commands with `&&`, `||` or `;`, and never combine `cd` with another command.
- Centralize string constants in `src/constants.py`.
- Use `ApplicationLogger` (`src/logging/app_logger.py`); library code must not use bare `print()`.
- Keep `start.bat` and `tools/tests.bat` up to date.
- Use `from __future__ import annotations` in every module.
- Use f-strings only.
- Use `pathlib.Path` instead of `os.path`.

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
