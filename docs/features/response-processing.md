# Response Processing

The system monitors the main email account for replies from assignees and uses AI to determine whether tasks have been completed.

## How It Works

1. `ResponseProcessor.process_assignee_responses()` connects to the main IMAP account
2. Fetches all unread messages
3. For each message, checks if the sender matches a known assignee's `email_address`
4. If matched, searches for the original task using the task ID
5. Uses OpenAI to analyze whether the task is completed
6. If completed, triggers [client response generation](client-response-generation.md)
7. Marks the response email as read (regardless of completion status)

**Source files:**
- `src/processors/response_processor.py` — main response processing logic

## Task ID Extraction

The system uses two methods to find the task ID linking a response to its original task:

1. **Email headers** — looks for `X-IMAP-Assistant-Task-ID` in the response email's `raw_message`
2. **Body fallback** — if no header is found, scans the email body for the pattern `Task ID: <uuid>` (the text appended when forwarding to assignees)

The body extraction strips HTML tags and decodes HTML entities before searching.

## Task Lookup

Once a task ID is extracted, `_find_task_by_id()`:

1. Gets the assignee's `target_folder` from processing rules
2. Connects to the main account and reads all messages in that folder
3. Searches for a message with a matching `X-IMAP-Assistant-Task-ID` header
4. Returns the original task details (subject, body, message ID, email object)

## AI Completion Detection

`OpenAIClient.check_task_completion()` analyzes the original task and the assignee's response. It returns a JSON object:

```json
{
  "status": "completed",
  "confidence": 9,
  "reason": "Assignee confirmed task is done and provided results"
}
```

### Status Categories

| Status | Meaning |
|--------|---------|
| `completed` | Task is fully done and delivered |
| `in_progress` | Task is being worked on but not finished |
| `not_completed` | Task has not been done or was rejected |
| `unclear` | Cannot determine status from the response |

### Completion Indicators

The AI looks for explicit completion signals in both German and English:
- "done", "finished", "completed"
- "erledigt", "fertig", "abgeschlossen"
- Presence of deliverables or results

The system is conservative — when uncertain, it assumes the task is NOT completed.

## What Happens After Detection

- **Completed**: triggers [client response generation](client-response-generation.md), which creates a draft reply for manual review
- **Not completed / in progress / unclear**: logged but no further action taken

In all cases, the assignee's response email is marked as read to prevent re-processing.
