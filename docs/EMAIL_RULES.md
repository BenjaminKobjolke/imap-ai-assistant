# Email Rules (Subject Tags)

Email rules add extra tags, such as a project tag, to the subject of an RTM todo. They are plain lookups in the settings file. No AI is involved.

## How the Todo Subject Is Built

```
<title> !<priority> ^<due date> <assignee tag> <rule tags>
```

| Part | Source |
|------|--------|
| title, priority, due date | AI, from the email and its first line |
| assignee tag | `additional_subject_tag` of the assignee in `processing` |
| rule tags | every matching rule in `processing.subject_tag_rules` |

Example:

```
DeePS Anpassungen !2 ^tomorrow #XIDA - Markus #IMAP-Assistant #p_produktstrategie_deeps
```

In interactive runs the complete tag string is shown at the `Tags:` prompt and can be edited before sending.

## Configuration

Rules live in the settings file under `processing.subject_tag_rules`:

```json
"processing": {
  "subject_tag_rules": {
    "sender_rules": [
      { "pattern": "@nuernbergmesse.de", "tag": "#p_produktstrategie_deeps" }
    ],
    "keyword_rules": [
      { "keywords": ["deeps"], "tag": "#p_produktstrategie_deeps", "match": "all" }
    ]
  }
}
```

## Sender Rules

A sender rule matches when `pattern` is contained in the `From` field of the email. The comparison is case-insensitive and a plain substring check, so `@example.com` matches every address of that domain and `john@example.com` matches one person.

There is one rule per pattern. Adding a rule with an existing pattern replaces its tag.

## Keyword Rules

A keyword rule matches against the email **subject**. Keywords are case-insensitive substrings.

| `match` | Rule matches when |
|---------|-------------------|
| `all` (default) | every keyword is in the subject |
| `any` | at least one keyword is in the subject |

There is one rule per tag. Adding a rule with an existing tag replaces its keywords and match mode.

## Multiple Matches

All matching rules apply. Their tags are appended in order: sender rules first, then keyword rules.

## Forwarded Emails

In the `rtm_todos` workflow you forward an email to the processor account. The `From` field of that forwarded email is **your** address, not the address of the original sender. Sender rules are checked against that field, so a rule for the original sender's domain does not match.

Use a keyword rule for forwarded emails. The forwarded subject still contains the original subject text.

| Command | `From` checked by sender rules |
|---------|--------------------------------|
| `--workflow rtm_todos` | the person who forwarded the email |
| `--todo-from-email ID`, `--send-todo-from-email ...` | the original sender (reads the main inbox directly) |
| `--add-todo` | rules are not applied |

## Commands

```bash
# List all rules
uv run python main.py --tag-rules

# Interactive wizard: add, edit, delete
uv run python main.py --setup-tag-rules

# Sender rules
uv run python main.py --add-sender-tag @example.com "#project_tag"
uv run python main.py --remove-sender-tag @example.com

# Keyword rules: tag first, then keywords
uv run python main.py --add-keyword-tag "#project_tag" keyword1 keyword2      # all keywords required
uv run python main.py --add-keyword-tag-any "#project_tag" keyword1 keyword2  # one keyword is enough
uv run python main.py --remove-keyword-tag "#project_tag"
```

## Multiple Settings Files

The commands write to the file given by `--config` (default `settings.json`). When you use several settings files, add the rule to each one:

```bash
uv run python main.py --config settings_live.json --add-keyword-tag "#project_tag" keyword
uv run python main.py --config settings_debug.json --add-keyword-tag "#project_tag" keyword
```
