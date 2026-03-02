# Email-to-Todo Conversion

Incoming emails are processed by OpenAI and converted into Remember the Milk (RTM) todo format. The system extracts the task name, importance level, and due date from the email content.

## How It Works

1. `EmailProcessor` fetches unread emails from the processor account (IMAP)
2. Only emails from addresses listed in `allowed_senders` are processed
3. `EnhancedImapClient.extract_email_content()` extracts the subject, first line, and body excerpt
4. `OpenAIClient.process_email_to_todo()` sends the content to OpenAI with a system prompt and user prompt
5. OpenAI returns a JSON response with `todo` (formatted text) and `assignee` (who should do it)
6. The todo is sent to the RTM email address via SMTP

**Source files:**
- `src/processors/task_processor.py` — orchestrates single-email processing
- `src/ai/openai_client.py` — `process_email_to_todo()` method

## RTM Todo Format

```
TODONAME !importance ^duedate
```

### Importance Levels

| Syntax | Meaning |
|--------|---------|
| `!1` | Very important |
| `!2` | Important |
| `!3` | Not so important |

### Due Date Syntax

| Syntax | Meaning |
|--------|---------|
| `^today` | Due today |
| `^tomorrow` | Due tomorrow |
| `^DD.MM.YYYY` | Specific date (e.g. `^15.03.2026`) |

### Examples

```
Respond to client inquiry !1 ^today
Write blog article !3 ^tomorrow
Apple Altersfreigabe prüfen !3 ^tomorrow
Rechnungs ToDo für Völk Orthopädie an Tamara senden !1 ^today
```

## First-Line Priority

The first line of the email body is treated as the primary instruction. It determines importance, due date, and assignee — not the subject line. The subject may contain settings from a previous recipient that should be ignored.

## Language Detection

The todo is written in the same language as the email subject and first line. If the language cannot be determined, German is used as the default.

## Special Rules

- Emails from `@nuernbergmesse.de` automatically get the tag `#p_produktstrategie_deeps` added to the todo name
- Email prefixes like `Re:`, `Fwd:`, `AW:` are stripped from fallback todo names

## Fallback Logic

When OpenAI fails or returns an invalid format (missing `!importance` or `^duedate`), a fallback todo is created:

```
<subject or first line> !2 ^tomorrow
```

The fallback also:
- Strips common email prefixes (`Re:`, `Fwd:`, `AW:`)
- Adds the sender name/company as context (unless from XIDA)
- Truncates the todo name to 50 characters

## Validation

The returned todo is validated against two regex patterns:
- Importance: `![123]`
- Due date: `\^(today|tomorrow|\d{1,2}\.\d{1,2}\.\d{4})`

Both must be present for the todo to be accepted.
