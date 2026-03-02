# Task Assignment & Routing

The system automatically detects who a task should be assigned to and routes emails accordingly. Tasks can be assigned to yourself or to named assignees configured in `settings.json`.

## Assignee Detection

OpenAI analyzes the email content (especially the first line) and returns an `assignee` field in its JSON response. Available assignees are passed to the AI prompt as a list (e.g. `self, markus, tamara`).

- `"self"` — the task is for the user (processed with `my_own_tasks` rules)
- Any other name — matched against the `processing.others` configuration

## Routing Rules

Each assignee has a set of routing rules defined in `settings.json` under `processing`:

| Field | Purpose |
|-------|---------|
| `target_folder` | IMAP folder where the original email is moved after processing |
| `additional_subject_tag` | Tags appended to the RTM todo subject (e.g. `#BKToDo #IMAP-Assistant`) |
| `email_address` | Assignee's email address (used for forwarding) |
| `bcc` | Optional BCC address when forwarding |

### Example Configuration

```json
{
  "processing": {
    "my_own_tasks": {
      "target_folder": "Company/@BKToDo",
      "additional_subject_tag": "#BKToDo #IMAP-Assistant"
    },
    "others": {
      "markus": {
        "target_folder": "Company/@WaitsForTaskDone",
        "additional_subject_tag": "#mit_markus_besprechen #IMAP-Assistant",
        "email_address": "markus@example.com"
      }
    }
  }
}
```

## Processing Flow

1. AI determines the assignee from email content
2. `ConfigManager.get_processing_rules(assignee)` returns the routing rules
3. The RTM todo is sent with the assignee's `additional_subject_tag`
4. The original email is moved to the assignee's `target_folder` in the sender's account

### Self-Assigned Tasks

- Todo sent to RTM with `#BKToDo #IMAP-Assistant` tags
- Original email moved to `Company/@BKToDo`

### Other-Assigned Tasks

- Todo sent to RTM with assignee-specific tags
- Original email forwarded to the assignee's `email_address`
- The forwarded email uses the todo text as the new subject
- A message is appended: "This task has been assigned to you" with the task ID
- Original email moved to `Company/@WaitsForTaskDone`

## Task Tracking

Each processed email gets a unique task ID (UUID) embedded as custom email headers:

| Header | Purpose |
|--------|---------|
| `X-IMAP-Assistant-Task-ID` | Unique task identifier |
| `X-IMAP-Assistant-Original-Sender` | Original email sender |
| `X-IMAP-Assistant-Created` | ISO timestamp when the task was created |

These headers are added to the RTM email, the forwarded email, and the moved original — enabling the [response processing](response-processing.md) pipeline to track task completion.

**Source files:**
- `src/processors/task_processor.py` — routing logic and email forwarding
- `src/config/settings.py` — `get_processing_rules()`, `get_other_people_names()`
