# Email Inspection

A read-only debugging tool for inspecting emails in any IMAP folder. Prints a summary to the console and saves full email content to files in the `debug/` directory.

## Usage

```bash
# Inspect INBOX on the main account (first account in settings.json)
python main.py --inspect INBOX

# Inspect a specific folder
python main.py --inspect "Company/@BKToDo"

# Use the processor account (ai@summera.ai) instead of the main account
python main.py --inspect INBOX --use-processor-account
```

## Behavior

- Connects to the selected IMAP account
- Fetches all messages in the specified folder
- Displays the 10 most recent emails as a console summary
- Saves each email's full content to a timestamped text file in `debug/`
- **Read-only** — does not mark emails as read or modify anything

## Account Selection

| Flag | Account Used |
|------|-------------|
| _(default)_ | Main account — first entry in `accounts[]` |
| `--use-processor-account` | Processor account — derived from `smtp` config |

## Console Output

For each email, the summary includes:

```
--- Email 1/5 ---
  From:      sender@example.com
  Subject:   Example Subject
  Task ID:   <uuid or N/A>
  Body (first 200 chars): ...
  Saved to:  debug/20260302_105030_example_subject.txt
------────────────────---
```

## Saved File Format

Each file in `debug/` contains:

- **Subject** and **From** address
- **Date**
- **Custom headers** (`X-IMAP-Assistant-Task-ID`, `X-IMAP-Assistant-Original-Sender`, etc.)
- **Plain text body** (full content)
- **HTML body indicator** (present/absent)
- **Raw headers dump** (all headers from the original message)
