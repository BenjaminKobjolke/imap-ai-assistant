# Meetings

Features for listing, inspecting, and archiving meeting emails based on ICS calendar data.

## List Today's Meetings

```bash
uv run python main.py --todays-meetings
# or shortcut:
call todays_meetings.bat
```

Shows a numbered list of today's meetings with start/end times:

```
Today's meetings (2026-03-02):

   1.  08:30 - 09:00  NR Status
   2.  10:00 - 10:30  Abstimmung Benny, Andi, Nadine, Tom
   3.  12:00 - 12:30  S62_250207_Schulungsvideo_Produktsicherheit

Total: 3 meeting(s)
```

## Meeting Detail View

```bash
uv run python main.py --todays-meeting 3
# or shortcut:
call todays_meetings.bat 3
```

Shows full details for a specific meeting by its index number:

```
Meeting #3: S62_250207_Schulungsvideo_Produktsicherheit

  Time:       12:00 - 12:30
  Organizer:  Silke Hufsky
  Location:   Microsoft Teams-Besprechung

  Links:
    1. Teams: https://teams.microsoft.com/meet/3663675895731?p=E95AVd0UKzIcNOjoL8

  [c] Copy link to clipboard
  [o] Open link in browser
  [a] Abort
```

Meeting links are extracted from:
1. ICS `X-MICROSOFT-SKYPETEAMSMEETINGURL` field
2. Email body (Teams, Zoom, Google Meet URLs)
3. ICS `LOCATION` field (if it contains a URL)

Generic base-path URLs without meeting identifiers are filtered out.

## List Meetings for Any Date

```bash
uv run python main.py --meetings tomorrow
# or shortcut:
call meetings.bat tomorrow
```

Supports flexible date formats:

| Format | Example | Interpretation |
|--------|---------|---------------|
| `today` | `--meetings today` | Today's date |
| `tomorrow` | `--meetings tomorrow` | Tomorrow's date |
| Day number | `--meetings 5` | 5th of current month |
| `DD.MM` | `--meetings 12.03` | March 12, current year |
| `DD.MM.YYYY` | `--meetings 12.03.2026` | March 12, 2026 |

## Meeting Cleanup

Automatically archives old meeting emails by moving them from the meetings folder to an archive folder. Uses the actual meeting date from ICS calendar data (not the email send date) to determine age.

```bash
uv run python main.py --cleanup-meetings
# or shortcut:
call cleanup_old_meetings.bat
```

### Configuration

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

### How It Works

1. Connects to the main IMAP account (first entry in `accounts[]`)
2. Fetches all messages from the configured meetings folder
3. For each email, extracts the meeting start date from ICS calendar data:
   - First checks email attachments for `text/calendar` content (e.g., `invite.ics`)
   - Falls back to `text/calendar` MIME part embedded in the email
4. Compares the meeting date against the age limit threshold
5. Moves emails with past meetings (older than the threshold) to the archive folder
6. Emails without parseable calendar data are skipped with a warning

### Output

```
Meeting cleanup complete:
  Checked: 95 | Moved: 82 | Kept: 10 | Skipped: 3
```

- **Checked**: Total emails in the folder
- **Moved**: Emails archived (meeting date older than threshold)
- **Kept**: Emails with future or recent meetings
- **Skipped**: Emails without calendar data or processing errors
