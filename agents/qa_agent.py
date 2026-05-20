import os
from typing import List, Dict, Any

import anthropic
from langsmith import traceable

import config
from core.store import DocumentStore

# Set LangSmith env vars before first trace
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_API_KEY", config.LANGCHAIN_API_KEY)
os.environ.setdefault("LANGCHAIN_PROJECT", config.LANGCHAIN_PROJECT)

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a document Q&A assistant. You answer questions strictly from the retrieved document chunks provided to you.

Rules:
- Answer ONLY from the provided context. Never use your training knowledge to fill gaps.
- Always cite the source: filename and page number when available, e.g. (contract.pdf, page 3).
- If the answer is not in the context, say exactly: "I couldn't find this in the uploaded documents."
- If multiple documents give different answers, report all of them with their respective sources.
- Be concise: lead with the direct answer, then cite the source."""


@traceable(name="qa-agent", run_type="llm")
def answer(
    query: str,
    store: DocumentStore,
    session_history: List[Dict] | None = None,
) -> Dict[str, Any]:
    chunks = store.hybrid_search(query)

    if not chunks:
        return {
            "answer": "No documents have been ingested yet. Please upload documents first.",
            "sources": [],
            "chunks_used": 0,
        }

    context = _format_context(chunks)
    messages = _build_messages(query, context, session_history or [])

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return {
        "answer": response.content[0].text,
        "sources": _extract_sources(chunks),
        "chunks_used": len(chunks),
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


def _format_context(chunks: List[Dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        meta = chunk["metadata"]
        page_info = f", page {meta['page']}" if meta.get("page") else ""
        parts.append(f"[Source {i}: {meta['filename']}{page_info}]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def _build_messages(query: str, context: str, history: List[Dict]) -> List[Dict]:
    # Replay prior turns so Claude understands follow-up questions
    messages = list(history)
    messages.append(
        {
            "role": "user",
            "content": f"Context from documents:\n\n{context}\n\nQuestion: {query}",
        }
    )
    return messages


def _extract_sources(chunks: List[Dict]) -> List[Dict]:
    seen = set()
    sources = []
    for chunk in chunks:
        meta = chunk["metadata"]
        key = (meta["filename"], meta.get("page"))
        if key not in seen:
            seen.add(key)
            page = meta.get("page")
            sources.append(
                {
                    "filename": meta["filename"],
                    "page": page if page else None,  # convert 0 back to null for display
                    "relevance_score": chunk["score"],
                }
            )
    return sources
