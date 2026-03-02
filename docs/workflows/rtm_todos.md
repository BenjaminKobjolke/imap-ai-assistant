# RTM Todos Workflow

Turns emails into Remember the Milk todos by forwarding them to the AI processor account.

## Quick Start

1. Forward an email to `ai@summera.ai`
2. Write your instruction in the **first line** of the forwarded email (before the forwarded content)
3. Run the workflow:

```bash
uv run python main.py --workflow rtm_todos
```

## First Line Format

The first line of your forwarded email controls **who** does the task, **how important** it is, and **when** it's due.

```
[assignee], [priority], [due date]
```

### Assignee

| Value | Meaning |
|-------|---------|
| `self` or omit | Your own task |
| `markus` | Assigned to Markus |
| `tamara` | Assigned to Tamara |

### Priority

| Keyword | RTM Importance |
|---------|---------------|
| `sehr wichtig` | !1 (very important) |
| `wichtig` | !2 (important) |
| `nicht so wichtig` / `nicht wichtig` | !3 (not so important) |
| *(omitted)* | !2 (medium, default) |

### Due Date

| Keyword | RTM Due Date |
|---------|-------------|
| `heute` | ^today |
| `morgen` | ^tomorrow |
| `nächste Woche` / `in einer Woche` | ^next week |
| specific date | ^DD.MM.YYYY |
| *(omitted)* | ^tomorrow (default) |

## Examples

| First Line | Result |
|-----------|--------|
| `Markus, heute, wichtig` | Assigned to Markus, !2, ^today |
| `Prüfen, nicht wichtig, morgen` | Self, !3, ^tomorrow |
| `Aufgabe für mich selbst, wichtig, heute` | Self, !2, ^today |
| `Tamara, nächste Woche` | Assigned to Tamara, !2 (default), ^next week |
| *(empty)* | Self, !2, ^tomorrow |

## What Happens After Processing

### Self-assigned tasks
- RTM todo is created and sent to your RTM inbox
- Original email is moved to `Company/@BKToDo`

### Tasks assigned to others (Markus, Tamara)
- RTM todo is created and sent to your RTM inbox
- Original email is **forwarded** to the assignee with a Task ID
- Original email is moved to `Company/@WaitsForTaskDone`

### Assignee responses
The workflow also checks for replies from assignees. When an assignee responds:
- AI analyzes whether the task is completed
- If completed: a draft client response is generated for your manual review

## Special Rules

- Emails originally from `@nuernbergmesse.de` automatically get the `#p_produktstrategie_deeps` tag
- The todo language matches the language of the email (German if unsure)
- Context from the email body (person names, company names) is added to the todo name

## Running the Workflow

```bash
# Run the full workflow (process emails + check responses)
uv run python main.py --workflow rtm_todos

# Or run individual steps
uv run python main.py              # Process unread emails only
uv run python main.py --responses  # Check assignee responses only
```
