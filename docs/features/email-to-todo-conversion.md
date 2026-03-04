# Email-to-Todo Conversion

Incoming emails are processed by OpenAI and converted into Remember the Milk (RTM) todo format. The system extracts the task name, importance level, and due date from the email content.

## How It Works

1. `EmailProcessor` fetches unread emails from the processor account (IMAP)
2. Only emails from addresses listed in `allowed_senders` are processed
3. `EnhancedImapClient.extract_email_content()` extracts the subject, first line, and body excerpt
4. `OpenAIClient.process_email_to_todo()` sends the content to OpenAI with a system prompt and user prompt
5. OpenAI returns a structured JSON response with `title`, `assignee`, `priority`, `due_date`, and `tags` fields
6. The structured fields are returned as a `TodoResult` dataclass for field-level editing
7. The user edits each field individually (title, priority, due date, tags)
8. The fields are assembled into RTM format (`TODONAME !importance ^duedate`) via `TodoResult.rtm_text`
9. The todo is sent to the RTM email address via SMTP

**Source files:**
- `src/processors/task_processor.py` — orchestrates single-email processing
- `src/ai/openai_client.py` — `process_email_to_todo()` method

## OpenAI Response Format

OpenAI returns a structured JSON object:

```json
{
  "title": "Prepare team meeting",
  "assignee": "self",
  "priority": 2,
  "due_date": "today",
  "tags": []
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Concise todo name (max 50 chars, no dates) |
| `assignee` | string | `"self"` or a named person |
| `priority` | int | `1` (very important), `2` (important), `3` (not so important) |
| `due_date` | string | `"today"`, `"tomorrow"`, or `DD.MM.YYYY` |
| `tags` | array | Always `[]` (reserved for future use) |

These fields are returned as a `TodoResult` dataclass (`src/ai/openai_client.py`) and presented to the user for field-level editing before assembly into RTM format.

## Interactive Field-Level Editing

After AI generates the todo, each field is presented individually for editing:

```
Title: [Prepare team meeting]:
Priority:
  [0] 1 - very important
  [1] 2 - important *
  [2] 3 - not so important
Choice [1]:
Due date (today/tomorrow/DD.MM.YYYY): [today]:
Tags: [#HOME #urgent]:
```

The user can accept defaults by pressing Enter or modify any field. After editing, the fields are assembled into RTM format via `TodoResult.rtm_text`:

```
Prepare team meeting !2 ^today
```

## RTM Todo Format

```
TODONAME !importance ^duedate
```

### Importance Levels

| Value | Meaning |
|-------|---------|
| `1` | Very important |
| `2` | Important |
| `3` | Not so important |

### Due Date Values

| Value | Meaning |
|-------|---------|
| `today` | Due today |
| `tomorrow` | Due tomorrow |
| `DD.MM.YYYY` | Specific date (e.g. `15.03.2026`) |

### Examples

JSON response from OpenAI:
```json
{"title": "Respond to client inquiry", "assignee": "self", "priority": 1, "due_date": "today", "tags": []}
```

Assembled RTM output:
```
Respond to client inquiry !1 ^today
```

## First-Line Priority

The first line of the email body is treated as the primary instruction. It determines importance, due date, and assignee — not the subject line. The subject may contain settings from a previous recipient that should be ignored.

## Language Detection

The todo is written in the same language as the email subject and first line. If the language cannot be determined, German is used as the default.

## Special Rules

- Emails from `@nuernbergmesse.de` automatically get the tag `#p_produktstrategie_deeps` added to the todo name
- Email prefixes like `Re:`, `Fwd:`, `AW:` are stripped from fallback todo names

## Fallback Logic

When OpenAI fails or returns invalid structured fields, a fallback todo is created:

```
<subject or first line> !2 ^tomorrow
```

The fallback also:
- Strips common email prefixes (`Re:`, `Fwd:`, `AW:`)
- Adds the sender name/company as context (unless from XIDA)
- Truncates the todo name to 50 characters

## Validation

Each structured field is validated individually:

- **title**: Must be a non-empty string
- **priority**: Must be an integer: `1`, `2`, or `3`
- **due_date**: Must match `today`, `tomorrow`, or `DD.MM.YYYY` format

All three fields must pass validation for the todo to be accepted. If any field fails, the fallback logic is used.
