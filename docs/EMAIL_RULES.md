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

## Default Assignee

A rule can name a default assignee with the optional `assignee` key. It works for sender and keyword rules:

```json
{ "pattern": "@nuernbergmesse.de", "tag": "#p_produktstrategie_deeps", "assignee": "markus" }
```

The value must be `self` or a name from `processing.others`.

The first line of the email wins. The rule assignee is used only when the AI returns `self`, which is the case when the first line names nobody. Typing `Tamara` in the first line still assigns the task to Tamara. When several matching rules have an assignee, the first one applies (sender rules before keyword rules).

The result is the preselected option of the `Assignee` prompt. With `--auto-accept` it is taken without asking.

There is no command for this key; edit the settings file. Adding a rule again with a command keeps the key. Changing the tag or pattern of a rule in `--setup-tag-rules` recreates the rule and drops it.

The default assignee applies to `--workflow rtm_todos` only. `--todo-from-email` always creates a task for yourself.

## Forwarded Emails

In the `rtm_todos` workflow you forward an email to the processor account, so its `From` field is **your** address. To still match the original sender, sender rules are checked against the `From` field and against the `From:` / `Von:` lines of the quoted message in the body.

Only the first 800 characters of the body are searched. That covers the header of the forwarded message, not older messages further down in the thread.

| Command | Checked by sender rules |
|---------|-------------------------|
| `--workflow rtm_todos` | forwarder and quoted `From:` / `Von:` lines |
| `--todo-from-email ID`, `--send-todo-from-email ...` | `From` field only (reads the main inbox directly) |
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
