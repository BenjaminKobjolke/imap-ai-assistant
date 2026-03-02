# Meeting Cleanup

Automatically archives old meeting emails by moving them from the meetings folder to an archive folder. Uses the actual meeting date from ICS calendar data (not the email send date) to determine age.

## Configuration

Add a `meetings` section to `settings.json`:

```json
"meetings": {
    "folder": "Company/@Meetings",
    "age_limit_hours": 24,
    "archive_folder": "Company/@OldMeetings"
}
```

| Key | Description | Default |
|-----|-------------|---------|
| `folder` | IMAP folder containing meeting emails | `Company/@Meetings` |
| `age_limit_hours` | Hours after the meeting start time before archiving | `24` |
| `archive_folder` | IMAP folder to move old meetings to (auto-created) | `Company/@OldMeetings` |

## Usage

```bash
python main.py --cleanup-meetings
```

## How It Works

1. Connects to the main IMAP account (first entry in `accounts[]`)
2. Fetches all messages from the configured meetings folder
3. For each email, extracts the meeting start date from ICS calendar data:
   - First checks email attachments for `text/calendar` content (e.g., `invite.ics`)
   - Falls back to `text/calendar` MIME part embedded in the email
4. Compares the meeting date against the age limit threshold
5. Moves emails with past meetings (older than the threshold) to the archive folder
6. Emails without parseable calendar data are skipped with a warning

## Output

```
Meeting cleanup complete:
  Checked: 95 | Moved: 82 | Kept: 10 | Skipped: 3
```

- **Checked**: Total emails in the folder
- **Moved**: Emails archived (meeting date older than threshold)
- **Kept**: Emails with future or recent meetings
- **Skipped**: Emails without calendar data or processing errors
