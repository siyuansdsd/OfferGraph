You are creating a concise summary for research steering.

Today's date: {date}

<webpage_content>
{webpage_content}
</webpage_content>

Create a short summary that tells an agent:

1. The main topic.
2. The type of information collected.
3. The most important findings.

Keep the summary under 150 words and generate a descriptive markdown filename.

Return JSON with:

```json
{{
  "filename": "descriptive_filename.md",
  "summary": "Very brief summary under 150 words"
}}
```
