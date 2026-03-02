# Client Response Generation

When an assignee completes a task, the system generates a professional response email to send back to the original client. The response matches the language and tone of the original communication.

## How It Works

1. `ResponseProcessor._generate_client_response()` is triggered after a task is detected as completed
2. `RelationshipAnalyzer` determines the appropriate tone (formal vs. informal)
3. `OpenAIClient.generate_client_response()` creates the response text
4. `ClientResponseGenerator` saves it as a [draft email](draft-system.md)

**Source files:**
- `src/processors/client_response_generator.py` — draft creation
- `src/processors/relationship_analyzer.py` — tone analysis
- `src/ai/openai_client.py` — `generate_client_response()` method

## Relationship Analysis

Before generating a response, the system analyzes the relationship with the client to set the right tone.

### Team Member Detection

If the client's email matches any assignee's `email_address` in the configuration, the tone is always informal (`"CLIENT IS TEAM MEMBER - USE INFORMAL TONE"`).

### Sent Email Context

For external clients, the system searches the Sent folder for the most recent email to that address. The first 500 characters of that email are passed to OpenAI as relationship context, allowing the AI to match the formality level:

- Informal indicators: first names, casual tone, "Du" (German informal)
- Formal indicators: "Sie" (German formal), titles, full names

If no previous emails are found, the AI defaults to professional-but-friendly.

## AI Response Generation

`OpenAIClient.generate_client_response()` receives:

| Input | Description |
|-------|-------------|
| `original_subject` | Subject of the client's original email |
| `original_content` | Body of the client's original email |
| `assigned_task` | The task that was created from the email |
| `assignee_response` | What the assignee replied when completing the task |
| `last_sent_context` | Relationship context from sent folder analysis |

The AI returns a JSON object:

```json
{
  "response": "Das Problem wurde erfolgreich behoben.",
  "subject": "Re: Dokumentenanfrage - erledigt"
}
```

### Response Guidelines

The prompt instructs the AI to:
- Match the language of the original request (German/English)
- Use informal tone for team members
- Be brief and solution-focused (e.g. "haben wir behoben")
- Not include greetings, closings, or signatures (added by the user)
- Not include thank-you statements or follow-up offers

## Output

The generated response is saved as a draft email via the [draft system](draft-system.md), not sent automatically.
