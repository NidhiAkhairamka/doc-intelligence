import json
import anthropic
import config

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a document conflict analyst. You receive extracted structured data from multiple documents belonging to the same organisation.

Your job is to find genuine conflicts — places where following one document would contradict or violate another.

Return ONLY valid JSON — an array of conflict objects, no markdown, no explanation:
[
  {
    "type": "direct_conflict | missing_reciprocity | overlapping_obligation | date_conflict | amount_conflict",
    "severity": "Critical | Warning | Info",
    "summary": "one sentence plain English description of the conflict",
    "detail": "explain exactly what conflicts and why it matters practically",
    "doc_a": "filename of first document",
    "doc_b": "filename of second document",
    "quote_a": "the specific obligation/condition/amount from doc_a",
    "quote_b": "the specific obligation/condition/amount from doc_b",
    "recommendation": "what should be done to resolve this"
  }
]

Conflict types:
- direct_conflict: two docs say opposite or incompatible things about the same topic
- missing_reciprocity: doc A obligates a party but doc B (which should acknowledge it) does not
- overlapping_obligation: two docs impose the same obligation with different terms
- date_conflict: timelines or deadlines contradict each other
- amount_conflict: monetary values or rates differ across documents

Severity:
- Critical: creates legal risk, financial exposure, or operational failure if ignored
- Warning: creates ambiguity or inefficiency that should be resolved
- Info: minor inconsistency worth noting but low impact

Rules:
- Only flag genuine conflicts — do not flag documents that simply cover different topics
- Do not flag the same conflict twice
- If no conflicts exist, return an empty array []
- Maximum 10 conflicts — prioritise the most severe"""


def analyse(extractions: list[dict]) -> list[dict]:
    """
    extractions: list of extraction dicts from db.list_extractions()
    Each item has: filename, doc_id, extraction (with obligations, conditions, amounts, dates)
    Returns: list of conflict dicts
    """
    if len(extractions) < 2:
        return []

    # Condense each extraction to only the fields useful for contradiction detection
    # Avoids sending full text and keeps token usage low
    condensed = []
    for item in extractions:
        ex = item.get("extraction", {})
        condensed.append({
            "doc_id": item["doc_id"],
            "filename": item["filename"],
            "document_type": ex.get("document_type"),
            "parties": ex.get("parties", []),
            "obligations": ex.get("obligations", []),
            "conditions": ex.get("conditions", []),
            "amounts": ex.get("amounts", []),
            "dates": ex.get("dates", []),
        })

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Analyse these {len(condensed)} documents for conflicts:\n\n"
                    + json.dumps(condensed, indent=2)
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        conflicts = json.loads(raw)
    except json.JSONDecodeError:
        conflicts = [{"_parse_error": raw[:300]}]

    return conflicts
