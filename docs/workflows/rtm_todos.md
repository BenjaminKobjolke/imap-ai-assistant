# RTM Todos Workflow

Turns emails into Remember the Milk todos by forwarding them to the AI processor account.

## Quick Start

1. Forward an email to `ai@summera.ai`
2. Write your instruction in the **first line** of the forwarded email (before the forwarded content)
3. Run the workflow:

```bash
start_workflow.bat
# or: uv run python main.py --config settings_live.json --workflow rtm_todos
```

Nothing runs on its own. The tool processes mail only when the workflow is started, then exits.

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

Only the very first line of the email body is read as the instruction. When it names nobody, a matching [email rule](../EMAIL_RULES.md#default-assignee) with an `assignee` decides; without such a rule the task is yours.

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

### Finding the original email

The original is searched in the inbox of the account that forwarded the email, by subject (`Fwd:`, `Re:`, `AW:`, `WG:` prefixes ignored). The first match is used. At most 100 inbox messages are searched.

If no email with that subject is in the inbox any more, the RTM todo is still created, but nothing is forwarded to the assignee and nothing is moved. The log shows `Could not find original email with subject`.

### Assignee responses
The workflow also checks for replies from assignees. When an assignee responds:
- AI analyzes whether the task is completed
- If completed: a draft client response is generated for your manual review

## Special Rules

- [Email rules](../EMAIL_RULES.md) add project tags and can set a default assignee, based on the original sender or on keywords in the subject. Example: emails originally from `@nuernbergmesse.de` get the `#p_produktstrategie_deeps` tag
- A rule can also [add instructions to the AI prompt](../EMAIL_RULES.md#prompt-addition), for example to keep the sender's name out of the title
- The todo language matches the language of the email (German if unsure)
- Context from the email body (person names, company names) is added to the todo name

## Running the Workflow

The workflow has two steps: process unread emails, then check assignee responses.

| Command | Settings file | Prompts |
|---------|---------------|---------|
| `start_workflow.bat` | `settings_live.json` | asks before every step |
| `start_workflow_debug.bat` | `settings_debug.json` | auto-accept |

Both pass extra arguments on, e.g. `start_workflow_debug.bat --dry-run`.

```bash
# Same thing without the bat files
uv run python main.py --config settings_live.json --workflow rtm_todos

# Check assignee responses only
uv run python main.py --responses
```

Running `main.py` or `start.bat` without arguments only prints the help. Processing unread emails has no command of its own; it runs as the first step of the workflow.

### Debug Settings

`settings_debug.json` is a copy of the live settings where the assignee points to yourself and to a debug RTM tag, so a test run reaches neither the real assignee nor their todo list:

```json
"markus": {
  "target_folder": "Company/@WaitsForTaskDone",
  "additional_subject_tag": "#XIDA - Debug #IMAP-Assistant",
  "email_address": "you@example.com"
}
```

A debug run without `--dry-run` still sends the todo to RTM, forwards the email to that address and moves the original email. Both settings files hold credentials and are excluded from git.

### Unattended Runs

`--auto-accept` answers every prompt with its default and prints the choice as `[auto: ...]`. Use it when a scheduler starts the workflow:

```bash
start_workflow.bat --auto-accept
```

What that means:

- Title, priority, due date and assignee are taken from the AI (or from an email rule) without review. A wrong assignee sends a real email to that person.
- Assignee responses: the AI verdict is accepted and the client response is saved as a draft. It is never sent.
- Prompts without a default and selection menus (for example a missing salutation) still wait for an answer.

`--dry-run` sends, moves and marks nothing, and logs the final subject instead.

### Drafts Only

`--drafts-only` sends nothing. The RTM todo mail and the forward to the assignee are saved in the Drafts folder of the main account (the first entry in `accounts`), and you send each one by hand:

```bash
start_workflow.bat --drafts-only
```

- The todo exists in RTM only after you send its draft. The forward draft carries the original text or HTML, the attachments and the Task ID.
- Everything else runs as usual: the forwarded email is marked read and the original is moved to its target folder, so a second run does not create the drafts again.
- A draft that could not be saved counts like a failed send: the email stays unread and is picked up by the next run.
- To make it the default for a settings file, set `"drafts_only": true` under `processing`. `--no-drafts-only` switches it off for one run.
- `--dry-run` wins: with both flags no drafts are written.

Only this workflow honors the switch. Todos created from the inbox commands or the AI chat are still sent directly.
