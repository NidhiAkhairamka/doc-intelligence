import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import config
from core.extractor import extract_text
from core.store import DocumentStore
from core import db
from agents import extraction_agent, action_agent


def ingest(
    file_path: str,
    store: DocumentStore,
    dept_id: str,
    original_filename: str | None = None,
) -> Dict[str, Any]:
    filename = original_filename or Path(file_path).name
    doc_id = str(uuid.uuid4())
    ingested_at = datetime.utcnow().isoformat()

    raw_text = extract_text(file_path)
    chunks_text = _chunk_text(raw_text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)

    chunks = []
    for i, text in enumerate(chunks_text):
        page_match = re.search(r"\[Page (\d+)\]", text)
        page_num = int(page_match.group(1)) if page_match else 0

        chunks.append(
            {
                "id": f"{doc_id}__chunk_{i}",
                "text": text,
                "metadata": {
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": i,
                    "page": page_num,
                    "ingested_at": ingested_at,
                    "total_chunks": len(chunks_text),
                },
            }
        )

    store.add_chunks(chunks)

    # Run extraction first (action agent depends on its output)
    try:
        extraction = extraction_agent.extract(doc_id, filename, raw_text)
        db.store_extraction(doc_id, dept_id, filename, extraction)
    except Exception as e:
        extraction = {"error": str(e)}

    # Action agent — pure Python, no API call, instant
    actions = []
    try:
        actions = action_agent.generate(doc_id, filename, extraction)
        db.store_actions(doc_id, dept_id, filename, actions)
    except Exception as e:
        actions = [{"error": str(e)}]

    return {
        "doc_id": doc_id,
        "filename": filename,
        "chunks_created": len(chunks),
        "ingested_at": ingested_at,
        "extraction": extraction,
        "actions": actions,
    }


def _chunk_text(text: str, chunk_size: int, overlap: int):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if end < len(text):
            last_period = chunk.rfind(". ")
            if last_period > chunk_size * 0.5:
                end = start + last_period + 1
                chunk = text[start:end]

        chunk = chunk.strip()
        if len(chunk) > 20:
            chunks.append(chunk)

        start = end - overlap

    return chunks
