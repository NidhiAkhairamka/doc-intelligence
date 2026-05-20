import json
import anthropic
from langsmith import traceable
import config

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# ~40k chars ≈ 10k tokens — enough for most documents, keeps cost low
MAX_TEXT_CHARS = 40_000

SYSTEM_PROMPT = """You are a document analyst. Extract structured information from the document text.

Return ONLY valid JSON matching this exact schema — no markdown, no explanation, just JSON:
{
  "document_type": "contract | policy | SOP | guide | report | invoice | other",
  "parties": ["list of organisation or person names mentioned"],
  "dates": [
    {"label": "what this date represents", "date": "YYYY-MM-DD or plain description"}
  ],
  "obligations": [
    {"party": "who must do it", "action": "what they must do", "deadline": "by when or null"}
  ],
  "amounts": [
    {"label": "what this amount is for", "value": "amount with currency"}
  ],
  "conditions": ["eligibility criteria, if/then rules, or key requirements"],
  "key_topics": ["3 to 5 main topics covered by the document"]
}

Rules:
- Return empty arrays [] when nothing is found for a category — never omit a key
- Never invent information not present in the text
- For dates use ISO format YYYY-MM-DD where possible
- Keep all strings concise (under 120 characters each)"""


@traceable(name="extraction-agent", run_type="llm")
def extract(doc_id: str, filename: str, raw_text: str) -> dict:
    text = raw_text[:MAX_TEXT_CHARS]
    if len(raw_text) > MAX_TEXT_CHARS:
        text += "\n\n[Document truncated for extraction]"

    response = client.messages.create(
        model=config.CLAUDE_FAST_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Document filename: {filename}\n\n{text}",
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if Claude wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        extraction = json.loads(raw)
    except json.JSONDecodeError:
        # Return a safe fallback so ingest doesn't fail
        extraction = {
            "document_type": "other",
            "parties": [],
            "dates": [],
            "obligations": [],
            "amounts": [],
            "conditions": [],
            "key_topics": [],
            "_parse_error": raw[:200],
        }

    extraction["doc_id"] = doc_id
    extraction["filename"] = filename
    return extraction
