# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IMAP AI Assistant is an email automation system that processes emails and converts them into Remember the Milk (RTM) todos using OpenAI. It monitors IMAP inboxes, applies AI processing to categorize and assign tasks, and can generate client responses automatically.

## Essential Commands

```bash
# Install dependencies
call install.bat
# or manually:
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
pip install openai  # Not in requirements.txt but needed

# Run the application
call run.bat
# or manually:
call venv\Scripts\activate.bat
python main.py

# Main execution modes
python main.py                # Process unread emails and responses
python main.py --test         # Test all connections
python main.py --status       # Show system status
python main.py --responses    # Process only assignee responses

# Debug: inspect emails in an IMAP folder (read-only, saves to debug/)
python main.py --inspect INBOX
python main.py --inspect "Company/@BKToDo" --use-processor-account

# List today's meetings with start/end times
python main.py --todays-meetings

# Archive old meeting emails (uses ICS calendar date, not email date)
python main.py --cleanup-meetings

# Test logging functionality
python test_logger.py
```

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
python main.py --inspect INBOX                          # Main account INBOX
python main.py --inspect "Company/@BKToDo"              # Specific folder
python main.py --inspect INBOX --use-processor-account  # Processor account

# Test specific components
python test_logger.py  # Tests ApplicationLogger with mock AI calls
```

## Important Files to Understand

- `main.py`: Entry point with command-line argument handling
- `src/processors/email_processor.py`: Main orchestration logic
- `src/ai/openai_client.py`: All AI interactions and prompt handling
- `src/config/settings.py`: Configuration management and validation
- `settings.json`: All runtime configuration
- `prompts/*.txt`: AI prompt templates (system and user prompts)