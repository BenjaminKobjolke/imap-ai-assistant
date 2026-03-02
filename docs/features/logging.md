# Logging

The system uses `ApplicationLogger`, a universal rotating file logger that writes structured JSON log entries organized by category.

**Source file:** `src/logging/app_logger.py`

## Configuration

Set in the `logging` section of `settings.json`:

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Enable/disable application logging |
| `log_dir` | `"logs"` | Directory for log files |
| `max_file_size_mb` | `10` | Maximum size per log file in MB |
| `backup_count` | `5` | Number of rotated backup files to keep |
| `categories` | — | Per-category settings (enabled, level) |

## Log Categories

Each category writes to its own file:

| Category | File | Content |
|----------|------|---------|
| `ai` | `logs/ai.log` | All OpenAI API requests, responses, errors, and token usage |
| `email` | `logs/email.log` | Email processing events |
| `system` | `logs/system.log` | Application lifecycle events (startup, shutdown, config) |

Categories can be individually enabled/disabled and have their own log level:

```json
{
  "categories": {
    "ai": { "enabled": true, "level": "DEBUG" },
    "email": { "enabled": true, "level": "INFO" },
    "system": { "enabled": true, "level": "INFO" }
  }
}
```

## Rotating Files

Log files use Python's `RotatingFileHandler`:

- When a log file reaches the configured max size (default 10 MB), it is rotated
- Rotated files are named `<category>.log.1`, `<category>.log.2`, etc.
- Up to `backup_count` (default 5) backup files are kept
- Oldest backups are deleted automatically

## Structured JSON Logging

All log entries are written as JSON objects. The format varies by log type:

### AI Request

```json
{
  "timestamp": "2026-03-02T10:30:00",
  "request_id": "uuid",
  "type": "request",
  "request_type": "email_to_todo",
  "data": { "subject": "...", "user_prompt": "..." },
  "metadata": { "model": "gpt-4o", "max_tokens": 6000, "temperature": 0.1 }
}
```

### AI Response

```json
{
  "timestamp": "2026-03-02T10:30:01",
  "request_id": "uuid",
  "type": "response",
  "request_type": "email_to_todo",
  "data": "...",
  "processing_time": 1.23,
  "tokens_used": { "prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550 }
}
```

### AI Error

```json
{
  "timestamp": "2026-03-02T10:30:01",
  "request_id": "uuid",
  "type": "error",
  "request_type": "email_to_todo",
  "error": { "type": "APIError", "message": "..." },
  "request_data": { "subject": "..." }
}
```

### General Event

```json
{
  "timestamp": "2026-03-02T10:30:00",
  "event_type": "startup",
  "data": { "config_path": "settings.json" },
  "metadata": {}
}
```

## Request ID Tracking

Every AI interaction is assigned a UUID `request_id`. This ID links the request log entry to its corresponding response or error entry, making it easy to trace a full API call cycle.

## Viewing Logs

```bash
# View AI interaction logs
type logs\ai.log

# View system events
type logs\system.log

# View email processing logs
type logs\email.log
```
