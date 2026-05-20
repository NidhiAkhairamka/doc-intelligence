"""
Orchestrator — pure Python, zero extra API calls.

Takes a user question, runs Q&A, then enriches the response with:
- Sources with file name + page number
- Relevant contradictions with page numbers (looked up from the vector store)
- Related pending actions
"""
from core import db
from core.store import DocumentStore
from agents import qa_agent


def ask(query: str, dept_id: str, store: DocumentStore, session_history: list = None) -> dict:
    # Step 1 — Q&A agent (the only API call in the entire pipeline)
    qa_result = qa_agent.answer(query, store, session_history or [])

    # Format sources clearly: filename + page
    formatted_sources = _format_sources(qa_result.get("sources", []))

    # If no documents found return early — nothing to enrich
    if not formatted_sources:
        return {
            "answer": qa_result["answer"],
            "sources": [],
            "contradictions": [],
            "related_actions": [],
            "usage": qa_result.get("usage", {}),
        }

    retrieved_filenames = {s["filename"] for s in formatted_sources}

    # Step 2 — contradictions relevant to this question, with page lookups
    contradiction_result = db.get_latest_contradictions(dept_id)
    relevant_contradictions = []
    if contradiction_result:
        for conflict in contradiction_result.get("conflicts", []):
            if _is_relevant(query, conflict, retrieved_filenames):
                # Look up page numbers for each quote from the vector store
                page_a = _find_page(store, conflict.get("quote_a", ""), conflict.get("doc_a", ""))
                page_b = _find_page(store, conflict.get("quote_b", ""), conflict.get("doc_b", ""))

                relevant_contradictions.append({
                    "severity": conflict.get("severity"),
                    "type": conflict.get("type"),
                    "summary": conflict.get("summary"),
                    "source_a": _cite(conflict.get("doc_a"), page_a),
                    "source_b": _cite(conflict.get("doc_b"), page_b),
                    "quote_a": conflict.get("quote_a"),
                    "quote_b": conflict.get("quote_b"),
                    "recommendation": conflict.get("recommendation"),
                    "action_required": _resolve_action(conflict.get("doc_a"), conflict.get("doc_b")),
                })

    # Step 3 — related pending actions
    all_actions = db.list_all_actions(dept_id)
    relevant_actions = [
        {
            "task": a["task"],
            "responsible": a["responsible"],
            "deadline": a["deadline"],
            "priority": a["priority"],
            "status": a["status"],
            "source": a["filename"],
        }
        for a in all_actions
        if _text_overlaps(query, a["task"]) and a["status"] != "completed"
    ][:5]

    return {
        "answer": qa_result["answer"],
        "sources": formatted_sources,
        "contradictions": relevant_contradictions,
        "related_actions": relevant_actions,
        "usage": qa_result.get("usage", {}),
    }


# ---------------------------------------------------------------------------
# Source formatting
# ---------------------------------------------------------------------------

def _format_sources(sources: list) -> list:
    """Add human-readable citation string to each source."""
    formatted = []
    for s in sources:
        page = s.get("page")
        citation = f"{s['filename']}, page {page}" if page else s["filename"]
        formatted.append({
            "filename": s["filename"],
            "page": page,
            "citation": citation,
            "relevance_score": s.get("relevance_score"),
        })
    return formatted


def _cite(filename: str | None, page: int | None) -> str:
    """Return a clean citation string e.g. 'contract.pdf, page 4'"""
    if not filename:
        return "Unknown source"
    if page:
        return f"{filename}, page {page}"
    return filename


# ---------------------------------------------------------------------------
# Page lookup — searches the store for the quote, returns page of best match
# ---------------------------------------------------------------------------

def _find_page(store: DocumentStore, quote: str, filename: str) -> int | None:
    """
    Search the vector store for the quote text, restricted to the given filename.
    Returns the page number of the best matching chunk, or None.
    No API call — uses the local BM25 index only.
    """
    if not quote or not filename:
        return None
    try:
        # Use BM25 scores directly — fast, no embedding call needed
        import numpy as np
        if not store._bm25 or not store._bm25_texts:
            return None

        scores = store._bm25.get_scores(quote.lower().split())
        top_indices = np.argsort(scores)[::-1][:10]

        for idx in top_indices:
            chunk_id = store._bm25_ids[idx]
            # Fetch this specific chunk's metadata
            result = store.collection.get(ids=[chunk_id], include=["metadatas"])
            if not result["metadatas"]:
                continue
            meta = result["metadatas"][0]
            if meta.get("filename") == filename:
                page = meta.get("page")
                return page if page and page > 0 else None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Resolve action — which doc needs updating?
# ---------------------------------------------------------------------------

# File types that are authoritative (regulatory/government docs)
AUTHORITATIVE_EXTENSIONS = {".pdf"}
AUTHORITATIVE_KEYWORDS = {"guide", "law", "decree", "fta", "vat", "regulation", "policy", "act"}


def _resolve_action(doc_a: str | None, doc_b: str | None) -> str:
    """
    Suggest which document needs to be updated based on doc type.
    Government/regulatory docs take precedence over contracts.
    """
    if not doc_a or not doc_b:
        return "Review both documents and align them manually."

    a_score = _authority_score(doc_a)
    b_score = _authority_score(doc_b)

    if a_score > b_score:
        return f"Update '{doc_b}' — '{doc_a}' is likely the authoritative source."
    elif b_score > a_score:
        return f"Update '{doc_a}' — '{doc_b}' is likely the authoritative source."
    else:
        return f"Review both '{doc_a}' and '{doc_b}' — could not determine which is authoritative."


def _authority_score(filename: str) -> int:
    name_lower = filename.lower()
    score = 0
    if any(kw in name_lower for kw in AUTHORITATIVE_KEYWORDS):
        score += 2
    if filename.endswith(".pdf"):
        score += 1
    return score


# ---------------------------------------------------------------------------
# Relevance helpers
# ---------------------------------------------------------------------------

def _is_relevant(query: str, conflict: dict, retrieved_filenames: set) -> bool:
    conflict_docs = {conflict.get("doc_a"), conflict.get("doc_b")}
    if conflict_docs & retrieved_filenames:
        return True
    return _text_overlaps(query, conflict.get("summary", ""))


def _text_overlaps(query: str, text: str, min_overlap: int = 2) -> bool:
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "to", "of", "in",
        "on", "at", "by", "for", "with", "about", "from", "what", "which",
        "who", "how", "when", "where", "and", "or", "but", "not", "no", "any",
        "all", "this", "that", "these", "those", "it", "its", "i", "my",
    }
    query_words = {w for w in query.lower().split() if w not in stopwords and len(w) > 3}
    text_words = {w for w in text.lower().split() if w not in stopwords and len(w) > 3}
    return len(query_words & text_words) >= min_overlap
