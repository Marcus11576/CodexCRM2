# Standalone Transcript Intelligence Tool

This repo now exposes a separate transcript-intelligence API that can be called by other systems without depending on a CRM profile record.

## Endpoint

`POST /api/toolkit/transcripts/summarize`

## Authentication

Use either:

- an authenticated CRM session cookie, or
- `X-Tool-Api-Key: <value>` when `STANDALONE_TOOL_API_KEY` is configured

## Request

```json
{
  "title": "Brian WhatsApp exchange",
  "source_type": "whatsapp",
  "transcript": "full transcript text here",
  "guidance": "Keep commercial nuance and remove fluff.",
  "custom_sections": [],
  "max_points_per_section": 4,
  "examples": [
    {
      "transcript": "example transcript",
      "preferred_summary": "preferred style summary",
      "preferred_sections": {
        "business_focus": "preferred business treatment"
      },
      "notes": [
        "drop banter",
        "keep the strongest commercial language"
      ]
    }
  ]
}
```

If `custom_sections` is empty, the default schema is:

- `business_focus`
- `recruitment_talent`
- `family_personal`
- `obe_focus`

## Response

```json
{
  "executive_summary": "briefing-grade summary",
  "sections": [
    {
      "id": "business_focus",
      "label": "Business Focus",
      "summary": "section summary",
      "points": [
        {
          "text": "important point",
          "evidence": "supporting source wording",
          "speaker": "Brian Scholfield",
          "confidence": 0.92
        }
      ],
      "confidence": 0.9
    }
  ],
  "other_topics": [],
  "omitted_content": [
    {
      "text": "banter line",
      "reason": "not useful for future briefing"
    }
  ],
  "run_id": "ai run log id",
  "metadata": {
    "source_type": "whatsapp",
    "section_schema": [],
    "prompt_family": "standalone_transcript_intelligence_v1",
    "model": "gpt-4o",
    "example_count": 1
  }
}
```

## Environment

Add to `.env` when external callers should use an API key:

```env
STANDALONE_TOOL_API_KEY=replace-me
STANDALONE_TOOL_MODEL=gpt-4o
```

## Notes

- The endpoint uses the same audited OpenAI runtime as the CRM and writes `AI_RUN_LOG` entries.
- It does not write people, interactions, briefs, or CRM intelligence rows.
- The best quality comes from passing real examples of preferred summaries and keep/drop notes in the request.
