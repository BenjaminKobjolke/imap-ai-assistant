# AI Integration

All AI capabilities are powered by OpenAI's API via the `OpenAIClient` class. The system uses prompt templates loaded from files and communicates with the API in JSON mode.

**Source file:** `src/ai/openai_client.py`

## Configuration

Set in the `openai` section of `settings.json`:

| Field | Default | Description |
|-------|---------|-------------|
| `api_key` | — | OpenAI API key (required) |
| `model` | `gpt-4o` | Model to use |
| `max_tokens` | `100` | Max tokens for email-to-todo (overridden per capability) |
| `temperature` | `0.3` | Creativity level (lower = more deterministic) |

## Three AI Capabilities

### 1. Email-to-Todo Conversion

Converts email content into RTM todo format.

| Parameter | Value |
|-----------|-------|
| Max tokens | Configured in `settings.json` |
| Temperature | Configured in `settings.json` |
| Response format | JSON mode |
| Prompts | `system_prompt.txt`, `user_prompt.txt` |

Returns: `{"todo": "...", "assignee": "..."}`

### 2. Task Completion Check

Analyzes assignee responses to determine if a task is done.

| Parameter | Value |
|-----------|-------|
| Max tokens | 150 |
| Temperature | 0.3 |
| Response format | JSON mode |
| Prompts | `task_completion_system_prompt.txt`, `task_completion_user_prompt.txt` |

Returns: `{"status": "...", "confidence": N, "reason": "..."}`

### 3. Client Response Generation

Creates professional email responses for completed tasks.

| Parameter | Value |
|-----------|-------|
| Max tokens | 500 |
| Temperature | 0.7 (higher for more natural text) |
| Response format | JSON mode |
| Prompts | `client_response_system_prompt.txt`, `client_response_user_prompt.txt` |

Returns: `{"response": "...", "subject": "..."}`

## Prompt Template System

Prompts are loaded from the `prompts/` directory at initialization. There are two types:

### System Prompts

Define the AI's role and response format. The email-to-todo system prompt supports dynamic date injection:

```
Today's date is: {current_date} (DD.MM.YYYY format)
```

This is replaced at runtime with the actual current date using Python's `str.format()`.

### User Prompts

Contain placeholders for email data, filled at runtime using Python's `string.Template` with `safe_substitute()`:

| Prompt | Variables |
|--------|-----------|
| `user_prompt.txt` | `$subject`, `$first_line`, `$body_excerpt`, `$assignees` |
| `task_completion_user_prompt.txt` | `$original_task`, `$assignee_response` |
| `client_response_user_prompt.txt` | `$original_subject`, `$original_content`, `$assigned_task`, `$assignee_response`, `$last_sent_context` |

## JSON Mode

All API calls use `response_format={"type": "json_object"}` to ensure the model returns valid JSON. Responses are parsed with `json.loads()` and validated.

## Token Logging

Every AI request/response is logged via `ApplicationLogger` with:

- Request ID (UUID) for correlation
- Full prompt content (system + user)
- Model parameters (model, max_tokens, temperature)
- Response content
- Token usage (prompt_tokens, completion_tokens, total_tokens)
- Processing time in seconds

See [Logging](logging.md) for details on the logging system.

## Connection Testing

`test_connection()` sends a minimal API call (`"Hello"`, max 10 tokens) to verify the OpenAI API key and connectivity. Used by `python main.py --test`.
