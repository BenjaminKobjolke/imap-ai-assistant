# Email Search

Search emails across cached folders and live IMAP folders. Supports both CLI arguments for scripted use and an interactive wizard for ad-hoc searches.

## Usage

```bash
# Interactive wizard (recommended)
python main.py --search

# Direct search with a term
python main.py --search "project update"

# Field-specific search (from, to, subject)
python main.py --search "from:alice@example.com"
python main.py --search "to:team@company.com"
python main.py --search "s:invoice"

# Combine with body, date, and folder filters
python main.py --search "from:alice" --body "budget" --date 15.01.2026
python main.py --search "meeting" --date-after 2026 --path "Company/Sales"

# Rebuild the search cache
python main.py --update-cache
python main.py --update-cache --fast              # skip unchanged folders
python main.py --update-cache --folders "INBOX;Sent"  # specific folders only
```

## Interactive Wizard

When `--search` is used without a search term, the wizard guides you through five steps:

### 1. Where to search?

| Option | Behavior |
|--------|----------|
| **Default** | Searches cached folders + live folders (current behavior) |
| **All IMAP folders** | Searches every folder via IMAP SEARCH with progress output |
| **Inbox only** | Restricts search to `INBOX` |
| **Sent only** | Restricts search to the configured sent folder |
| **Search for a folder** | Partial-name folder picker — type part of a folder name, see matches, pick one |

### 2. Search scope

Choose which header fields to search: all (from + to + subject), from only, to only, or subject only.

### 3. Search term

Free-text search term applied to the selected scope.

### 4. Body contains

Optional body-text filter. Leave empty to skip.

### 5. Date filter

Choose from: no filter, exact date, after date, or before date. Dates are entered as `DD.MM.YYYY` or `YYYY` (year-only).

## Search Architecture

### Data sources

- **Cache** — SQLite database (`data/email_cache.db`) built by `--update-cache`. Contains headers and body previews for configured folders.
- **Live folders** — Folders listed in `search.live_folders` (default: `INBOX`) are always searched via IMAP SEARCH in real time, never served from cache.

### Search flow (default mode)

1. Search the cache with the provided filters
2. Search live folders via IMAP SEARCH
3. Merge results, sort by date descending, limit to 9

### Folder-specific modes

When the wizard targets a specific folder (Inbox, Sent, or a user-picked folder):

1. If the folder is a live folder → search via IMAP directly
2. Otherwise → search cache with `folder=` filter
3. If cache returns nothing → fall back to direct IMAP search

### All-folders mode

Iterates every IMAP folder, running IMAP SEARCH on each with progress output (`Searching 1/42: INBOX`). Results are merged and sorted.

## Result Actions

After results are displayed, you can:

- **Select a result** to see its detail view (folder, from, to, subject, date)
- **Show body** — fetches the full email body from IMAP
- **Copy to search-results** — copies the email to the `search-results` IMAP folder

## Configuration

Relevant keys in `settings.json` under the `search` section:

| Key | Default | Description |
|-----|---------|-------------|
| `live_folders` | `["INBOX"]` | Folders searched live via IMAP (never cached) |
| `results_folder` | `"search-results"` | IMAP folder for copied search results |
| `cache_db` | `"data/email_cache.db"` | Path to the SQLite cache |
| `cache_validity_days` | `30` | Days before cached data is considered stale |
| `exclude_folders` | `[]` | Folders excluded from cache building |

## Key Files

| File | Responsibility |
|------|---------------|
| `src/search/email_search.py` | Search logic, wizard, result display, IMAP search |
| `src/search/folder_picker.py` | Shared folder partial-name search and picker |
| `src/search/search_cache.py` | SQLite cache read/write operations |
| `src/search/cache_builder.py` | Cache building from IMAP folders |
