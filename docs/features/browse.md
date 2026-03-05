# Browse — Interactive IMAP Folder & Email Browser

An interactive tool for navigating IMAP folder trees, viewing emails, and acting on them (show body, draft reply).

## Usage

```bash
# Start the interactive folder browser
python main.py --browse
```

## Folder Navigation

The browser starts at the root level showing top-level folders:

```
Found 12 folder(s).

📁 Root — folders (1–5 of 7):
  [0] INBOX
  [1] Company
  [2] Drafts
  [3] Sent
  [4] Trash
  [5] Next →
  [6] Back
```

- Select a folder number to enter it
- **Next →** / **← Previous** — paginate through folders (5 at a time)
- **Back** — go up one level, or exit at root

Subfolders are shown hierarchically. Selecting `Company` navigates into its children:

```
📁 Company — folders (1–3 of 3):
  [0] Sales
  [1] HR
  [2] Archive
  [3] Back
```

## Email Listing

When entering a leaf folder (no subfolders), emails are listed with sender, subject, and date:

```
📧 Sales — emails (1–5 of 23):
  [0] alice@example.com | Q1 Report | 2026-03-04
  [1] bob@corp.com | Meeting notes | 2026-03-03
  [2] carol@example.com | Invoice | 2026-03-02
  [3] dave@corp.com | Proposal | 2026-03-01
  [4] eve@example.com | Follow-up | 2026-02-28
  [5] Next →
  [6] Back
```

Pagination works the same way — 5 emails per page, sorted by date descending.

## Email Actions

Selecting an email shows an action menu:

```
What would you like to do?
  [0] Show body
  [1] Draft reply
  [2] Back
```

- **Show body** — fetches and displays the full email body
- **Draft reply** — starts the AI-assisted draft reply flow (salutation detection, greeting, compose, grammar check, save to Drafts)
- **Back** — return to the email list

## Features

- Hierarchical folder browsing with display of leaf names only
- Paginated navigation for both folders and emails (5 items per page)
- Full email body viewing with plain-text and HTML fallback
- AI-powered draft reply with salutation caching
- Read-only browsing — does not modify emails or folders
