# Draft System

When a task is completed and a client response is generated, the system creates a draft email in the user's mailbox instead of sending it automatically. This allows manual review before sending.

## How It Works

1. `ClientResponseGenerator.generate_and_create_draft()` receives the AI-generated response
2. Builds an HTML-formatted email with the response, footer, and quoted original message
3. Saves the draft to the configured drafts folder using `save_draft()`

**Source file:** `src/processors/client_response_generator.py`

## Draft Format

The draft subject is prefixed with `[DRAFT-RESPONSE]`:

```
[DRAFT-RESPONSE] Re: Original Subject
```

### HTML Structure

The draft body is structured as:

1. **Response text** — the AI-generated response, converted to HTML (`\n` → `<br>`)
2. **Footer** — loaded from `data/footer.html` (company signature, etc.)
3. **Horizontal rule** separator
4. **Quoted original message** — styled with grey text, light background, and a left border

```html
<div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6;">
    <div>AI-generated response</div>
    <!-- footer.html content -->
    <hr>
    <div style="color: #666; background-color: #f9f9f9; border-left: 3px solid #ddd;">
        -----Original Message-----
        From: sender@example.com
        Subject: Original Subject
        ...original content...
    </div>
</div>
```

## Task Tracking Headers

Each draft includes custom headers for traceability:

| Header | Value |
|--------|-------|
| `X-IMAP-Assistant-Task-ID` | UUID of the original task |
| `X-IMAP-Assistant-Original-Sender` | The client's email address |
| `X-IMAP-Assistant-Draft-Created` | ISO timestamp when the draft was created |

## Footer

The email footer is loaded from `data/footer.html`. If the file doesn't exist, the draft is created without a footer (with a warning logged).

## Drafts Folder

The target folder is determined by `ConfigManager.get_drafts_folder()`, which reads the `drafts_folder` field from the account configuration. Defaults to `"Drafts"` if not specified.
