"""
Quick smoke test — run after `python api.py` is running.
Usage: python test_pipeline.py path/to/your_doc.pdf
"""
import sys
import requests

BASE = "http://localhost:5000"


def test(file_path: str):
    # 1. Health check
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200, f"Health check failed: {r.text}"
    print("✓ API is up")

    # 2. Ingest document
    with open(file_path, "rb") as f:
        r = requests.post(f"{BASE}/ingest", files={"file": f})
    assert r.status_code == 201, f"Ingest failed: {r.text}"
    result = r.json()
    print(f"✓ Ingested '{result['filename']}' → {result['chunks_created']} chunks")

    # 3. List documents
    r = requests.get(f"{BASE}/documents")
    docs = r.json()
    print(f"✓ Documents in store: {len(docs)}")

    # 4. Ask a question (no session)
    r = requests.post(f"{BASE}/ask", json={"question": "What is this document about?"})
    assert r.status_code == 200, f"Ask failed: {r.text}"
    result = r.json()
    print(f"\n✓ Answer:\n{result['answer']}")
    print(f"\n  Sources: {result['sources']}")
    print(f"  Chunks used: {result['chunks_used']}")
    print(f"  Tokens: {result['usage']}")

    # 5. Follow-up question using session memory
    session_id = "test-session-1"
    r = requests.post(
        f"{BASE}/ask",
        json={"question": "Can you summarise the key points?", "session_id": session_id},
    )
    assert r.status_code == 200
    print(f"\n✓ Follow-up answer:\n{r.json()['answer']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pipeline.py <path_to_document>")
        sys.exit(1)
    test(sys.argv[1])
