# Workflow System

Workflows are configurable JSON-based pipelines that define sequences of actions. Each workflow is a `.json` file in the `workflows/` directory.

## Usage

```bash
# List available workflows
uv run python main.py --workflow

# Run a specific workflow
uv run python main.py --workflow rtm_todos

# Show help (no arguments)
uv run python main.py
```

## Workflow JSON Format

Each workflow file defines a name, description, and a list of steps:

```json
{
  "name": "Task E-Mails to Remember the Milk ToDos",
  "description": "Process unread emails into RTM todos, then check assignee responses",
  "steps": [
    {"action": "process_unread_emails"},
    {"action": "process_assignee_responses"}
  ]
}
```

The filename (minus `.json`) is the workflow ID used with `--workflow`.

## Available Actions

| Action | Description |
|--------|-------------|
| `process_unread_emails` | Convert incoming emails to RTM todos |
| `process_assignee_responses` | Check assignee replies for task completions |
| `cleanup_meetings` | Archive old meeting emails |
| `todays_meetings` | List today's meetings |

## Creating a Custom Workflow

1. Create a new `.json` file in the `workflows/` directory
2. Define the `name`, `description`, and `steps` array
3. Each step needs an `action` key matching one of the available actions
4. Steps execute in order; errors in one step are logged but don't stop subsequent steps

Example — a meetings-only workflow:

```json
{
  "name": "Daily Meetings Overview",
  "description": "Show today's meetings and clean up old ones",
  "steps": [
    {"action": "todays_meetings"},
    {"action": "cleanup_meetings"}
  ]
}
```

Save as `workflows/meetings.json`, then run with:

```bash
uv run python main.py --workflow meetings
```

## Built-in Workflow: rtm_todos

The `rtm_todos` workflow replicates the original default behavior:

1. **Process Unread Emails** — Email → AI → RTM Todo → Forward → Move
2. **Process Assignee Responses** — Response → AI Completion Check → Draft Reply

### Phase 1: Process Unread Emails

Converts incoming emails from allowed senders into Remember the Milk todos.

1. **Connect** to the processor account (IMAP, configured via `smtp` section)
2. **Fetch unread emails** filtered by `allowed_senders` whitelist
3. **For each email:**
   - Extract subject, first line, and body excerpt
   - Call OpenAI to generate an RTM todo (`todo_text` + `assignee`)
   - Send the todo to RTM via SMTP (to `remember_the_milk.email_address`)
   - Mark the email as read on the processor account
   - Find the original email in the source account
   - If assignee is not "self": forward to the assignee with a Task ID
   - Move the original email to the assignee's `target_folder`
4. **Disconnect** and log summary

### Phase 2: Process Assignee Responses

Monitors the main account for replies from assignees and checks if tasks are completed.

1. **Connect** to the main account (first entry in `accounts[]`)
2. **Fetch unread emails** from the main account inbox
3. **For each email:**
   - Check if the sender is a known assignee (from `processing.others` config)
   - If not a known assignee, skip
   - Extract the response content
   - Find the original task by Task ID (from email headers or body text)
   - Call OpenAI to check if the task is completed (returns status + confidence)
   - If completed: generate a draft client response for manual review
   - Mark the response email as read
4. **Disconnect**

## Configuration

Workflows use these settings from `settings.json`:

| Setting | Purpose |
|---------|---------|
| `accounts` | Source IMAP accounts to monitor |
| `allowed_senders` | Email whitelist for processing |
| `smtp` | Processor account credentials |
| `openai` | API key, model, temperature, max tokens |
| `remember_the_milk.email_address` | RTM inbox for todos |
| `processing.my_own_tasks` | Routing for self-assigned tasks |
| `processing.others.*` | Routing per assignee (folder, email, tags) |
