# Configuration

All runtime configuration is stored in `settings.json`. The `ConfigManager` class (`src/config/settings.py`) loads and validates it at startup.

Another file can be selected with `--config PATH`. The workflow bat files use this: `start_workflow.bat` reads `settings_live.json`, `start_workflow_debug.bat` reads `settings_debug.json`. Commands that change settings write to the selected file.

## Required Sections

The following sections must be present for the application to start:

- `accounts`
- `openai`
- `remember_the_milk`
- `processing`
- `smtp`

Additionally, `allowed_senders` must be non-empty.

## Full Reference

### `accounts`

List of source IMAP accounts to monitor for original emails.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name for the account |
| `email_address` | string | Account email address |
| `server` | string | IMAP server hostname |
| `username` | string | IMAP login username |
| `password` | string | IMAP login password |
| `port` | int | IMAP port (typically `993` for SSL) |
| `use_ssl` | bool | Use SSL connection |
| `drafts_folder` | string | Folder name for draft emails (default: `"Drafts"`) |
| `sent_folder` | string | Folder name for sent emails (default: `"Sent"`) |

### `openai`

OpenAI API configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `api_key` | string | — | OpenAI API key (required) |
| `model` | string | `"gpt-4o"` | Model name |
| `max_tokens` | int | `100` | Max tokens for email-to-todo conversion |
| `temperature` | float | `0.3` | Temperature for email-to-todo conversion |

### `remember_the_milk`

| Field | Type | Description |
|-------|------|-------------|
| `email_address` | string | RTM inbox address for email-based task import |

### `processing`

Task routing rules. See [Task Assignment & Routing](task-assignment-routing.md) for details.

| Field | Type | Description |
|-------|------|-------------|
| `drafts_only` | bool | The `rtm_todos` workflow saves the todo and forward mails as drafts in the main account instead of sending them (default: `false`). `--drafts-only` / `--no-drafts-only` override it. See [Drafts Only](../workflows/rtm_todos.md#drafts-only) |

#### `processing.my_own_tasks`

| Field | Type | Description |
|-------|------|-------------|
| `target_folder` | string | IMAP folder for processed self-assigned emails |
| `additional_subject_tag` | string | Tags added to RTM todo subject |

#### `processing.others`

A map of assignee names to their routing configuration:

| Field | Type | Description |
|-------|------|-------------|
| `target_folder` | string | IMAP folder for emails assigned to this person |
| `additional_subject_tag` | string | Tags added to RTM todo subject |
| `email_address` | string | Assignee's email address for forwarding |
| `bcc` | string | Optional BCC address when forwarding |

#### `processing.subject_tag_rules`

Optional rules that add tags to the todo subject and can set a default assignee. See [Email Rules](../EMAIL_RULES.md) for how matching works.

`sender_rules`:

| Field | Type | Description |
|-------|------|-------------|
| `pattern` | string | Substring of the sender address, e.g. `@example.com` |
| `tag` | string | Tag added when the rule matches |
| `assignee` | string | Optional default assignee (`self` or a name from `processing.others`) |

`keyword_rules`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `keywords` | array | — | Substrings searched in the subject |
| `tag` | string | — | Tag added when the rule matches |
| `match` | string | `"all"` | `all` keywords required, or `any` |
| `assignee` | string | — | Optional default assignee |

### `allowed_senders`

Array of email addresses. Only emails from these senders are processed. All other emails are ignored.

```json
"allowed_senders": ["user@example.com"]
```

### `smtp`

SMTP configuration for the processor account (used for sending RTM todos and forwarding emails).

| Field | Type | Description |
|-------|------|-------------|
| `server` | string | SMTP server hostname |
| `port` | int | SMTP port (typically `587` for TLS) |
| `use_tls` | bool | Use TLS encryption |
| `username` | string | SMTP login username |
| `password` | string | SMTP login password |
| `from_email` | string | Sender email address for outgoing mail |

The `from_email` is also used to construct the processor's IMAP account configuration (same server, port 993, SSL).

### `sent_search_limit`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sent_search_limit` | int | `100` | Max number of sent emails to search for relationship context |

### `logging`

See [Logging](logging.md) for details.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable application logging |
| `log_dir` | string | `"logs"` | Log file directory |
| `max_file_size_mb` | int | `10` | Max log file size in MB |
| `backup_count` | int | `5` | Number of rotated backup files |
| `categories` | object | — | Per-category settings |

## Validation

`ConfigManager.is_valid()` checks that all essential fields are present and non-empty:

- At least one account in `accounts`
- `openai.api_key` is set
- `remember_the_milk.email_address` is set
- `smtp` configuration exists
- `allowed_senders` is non-empty

Run `python main.py --test` to validate the configuration and test all connections.
