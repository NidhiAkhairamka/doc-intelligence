"""
Action Agent — pure Python, zero API calls.

Converts structured extraction output (obligations + conditions) into a
prioritised task list. The extraction already contains everything needed:
party, action, deadline. No LLM required.
"""

# Keywords that signal a legally or financially significant obligation
HIGH_SIGNAL_WORDS = {
    "penalty", "fine", "legal", "mandatory", "must", "shall", "required",
    "comply", "compliance", "liable", "liability", "repay", "refund",
    "deadline", "within", "by", "before", "submit", "notify", "disclose",
}

# Keywords that suggest a condition worth flagging as a verification task
CONDITION_SIGNAL_WORDS = {
    "must", "required", "mandatory", "only", "eligible", "not eligible",
    "shall", "cannot", "prohibited", "restricted",
}


def generate(doc_id: str, filename: str, extraction: dict) -> list:
    obligations = extraction.get("obligations", [])
    conditions = extraction.get("conditions", [])
    actions = []

    # --- Convert each obligation directly to a task ---
    for ob in obligations:
        action_text = ob.get("action", "").strip()
        if not action_text:
            continue

        deadline = ob.get("deadline") or None
        responsible = ob.get("party") or "Not specified"
        priority = _priority_from_obligation(action_text, deadline)

        actions.append({
            "task": action_text,
            "responsible": responsible,
            "deadline": deadline,
            "priority": priority,
            "source_doc": filename,
            "notes": None,
        })

    # --- Convert significant conditions into verification tasks ---
    for condition in conditions:
        if not condition.strip():
            continue
        words = condition.lower().split()
        if any(w in CONDITION_SIGNAL_WORDS for w in words):
            actions.append({
                "task": f"Verify eligibility: {condition}",
                "responsible": "Not specified",
                "deadline": None,
                "priority": "Low",
                "source_doc": filename,
                "notes": "Eligibility condition from document",
            })

    # Sort: High → Medium → Low, deadline present before no deadline, then alphabetical
    priority_order = {"High": 0, "Medium": 1, "Low": 2}
    actions.sort(key=lambda x: (
        priority_order.get(x["priority"], 1),
        0 if x["deadline"] else 1,
        x["deadline"] or "",
    ))

    return actions


def _priority_from_obligation(action_text: str, deadline: str | None) -> str:
    """
    High  — has a deadline, or contains financial/legal consequence keywords
    Medium — clear obligation but no specific deadline
    Low   — informational or optional
    """
    if deadline:
        return "High"

    words = action_text.lower().split()
    if any(w in HIGH_SIGNAL_WORDS for w in words):
        return "Medium"

    return "Low"
