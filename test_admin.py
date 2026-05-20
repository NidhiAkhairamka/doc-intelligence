"""
Run this to test the full admin + department flow.
Usage: python test_admin.py
"""
import requests

BASE = "http://localhost:5000"
ADMIN_KEY = "nidhi@234"  # must match ADMIN_API_KEY in your .env


def get_or_create_dept(name: str) -> dict:
    """Create department, or return existing one if already present."""
    r = requests.post(
        f"{BASE}/admin/departments",
        headers={"X-Admin-Key": ADMIN_KEY},
        json={"name": name},
    )
    if r.status_code == 201:
        print(f"Created '{name}' → {r.json()}")
        return r.json()
    # Already exists — fetch from list
    depts = requests.get(
        f"{BASE}/admin/departments", headers={"X-Admin-Key": ADMIN_KEY}
    ).json()
    dept = next(d for d in depts if d["name"] == name)
    print(f"'{name}' already exists → using existing key")
    return dept


def main():
    # 1 & 2. Get or create departments
    finance = get_or_create_dept("Finance")
    marketing = get_or_create_dept("Marketing")
    finance_key = finance["api_key"]
    marketing_key = marketing["api_key"]

    # 3. List all departments
    r = requests.get(f"{BASE}/admin/departments", headers={"X-Admin-Key": ADMIN_KEY})
    print(f"\nAll departments: {[d['name'] for d in r.json()]}")

    # 4. Finance uploads a document
    pdf = r"C:\Users\DELL\Nidhi_work\uae-compliance-rag\docs\VAT-Refund-for-UAE-Nationals-Building-New-Residences-EN-10 04 2026.pdf"
    with open(pdf, "rb") as f:
        r = requests.post(
            f"{BASE}/ingest",
            headers={"X-API-Key": finance_key},
            files={"file": f},
        )
    ingest_result = r.json()
    print(f"\nFinance ingest → {r.status_code}")
    print(f"  chunks_created : {ingest_result.get('chunks_created')}")
    print(f"  doc_id         : {ingest_result.get('doc_id')}")

    extraction = ingest_result.get("extraction", {})
    print(f"\n--- Extraction ---")
    print(f"  document_type : {extraction.get('document_type')}")
    print(f"  parties       : {extraction.get('parties')}")
    print(f"  obligations   : {extraction.get('obligations')}")
    print(f"  key_topics    : {extraction.get('key_topics')}")
    if "_parse_error" in extraction:
        print(f"  PARSE ERROR   : {extraction['_parse_error']}")

    actions = ingest_result.get("actions", [])
    print(f"\n--- Action List ({len(actions)} tasks) ---")
    for i, t in enumerate(actions, 1):
        deadline = t.get("deadline") or "No deadline"
        print(f"  [{t.get('priority','?')}] {t.get('task')} | {deadline}")

    # 5. Finance asks a question — orchestrator enriches with contradictions + actions
    r = requests.post(
        f"{BASE}/ask",
        headers={"X-API-Key": finance_key},
        json={"question": "What are the VAT invoice requirements?"},
    )
    result = r.json()
    print(f"\nFinance ask →\n{result['answer']}")

    print(f"\n📄 Sources:")
    for s in result.get("sources", []):
        print(f"  → {s['citation']}")

    if result.get("contradictions"):
        print(f"\n⚠️  Contradictions ({len(result['contradictions'])}):")
        for c in result["contradictions"]:
            print(f"\n  [{c['severity']}] {c['summary']}")
            print(f"  Source A : {c['source_a']}")
            print(f"  Says     : {c['quote_a']}")
            print(f"  Source B : {c['source_b']}")
            print(f"  Says     : {c['quote_b']}")
            print(f"  Action   : {c['action_required']}")
    else:
        print(f"\n✅ No contradictions found for this question.")

    if result.get("related_actions"):
        print(f"\n📋 Related actions ({len(result['related_actions'])}):")
        for a in result["related_actions"]:
            deadline = f" | due: {a['deadline']}" if a['deadline'] else ""
            print(f"  [{a['priority']}] {a['task'][:80]}{deadline}")

    # 6. Marketing asks the same question — should get "no documents found"
    r = requests.post(
        f"{BASE}/ask",
        headers={"X-API-Key": marketing_key},
        json={"question": "What documents are needed for a VAT refund?"},
    )
    print(f"\nMarketing ask (should find nothing) → {r.json()['answer']}")

    # 7. Export calendar for Finance
    r = requests.get(
        f"{BASE}/actions/export.ics",
        headers={"X-API-Key": finance_key},
    )
    with open("finance_actions.ics", "wb") as f:
        f.write(r.content)
    print(f"\nCalendar exported → finance_actions.ics ({len(r.content)} bytes)")
    print("  Open this file to import all deadlines into Google Calendar / Outlook")

    # 8. Ingest second document (fake vendor contract)
    contract = r"C:\Users\DELL\doc-intelligence\test_docs\vendor_contract_alpha.txt"
    with open(contract, "rb") as f:
        r = requests.post(
            f"{BASE}/ingest",
            headers={"X-API-Key": finance_key},
            files={"file": f},
        )
    print(f"\nVendor contract ingest → {r.status_code}: chunks={r.json().get('chunks_created')}")

    # 9. Run contradiction analysis across both Finance documents
    r = requests.post(
        f"{BASE}/contradictions/analyse",
        headers={"X-API-Key": finance_key},
    )
    result = r.json()
    print(f"\n--- Contradiction Analysis ---")
    print(f"  Documents checked : {result.get('documents_checked')}")
    print(f"  Conflicts found   : {result.get('conflicts_found')}")
    for c in result.get("conflicts", []):
        print(f"\n  [{c.get('severity')}] {c.get('type')}")
        print(f"  Summary : {c.get('summary')}")
        print(f"  Doc A   : {c.get('doc_a')} → {c.get('quote_a')}")
        print(f"  Doc B   : {c.get('doc_b')} → {c.get('quote_b')}")
        print(f"  Fix     : {c.get('recommendation')}")

    # 11. List all actions and update first one to in_progress
    r = requests.get(f"{BASE}/actions", headers={"X-API-Key": finance_key})
    all_actions = r.json()
    print(f"\nAll actions ({len(all_actions)} total):")
    for a in all_actions[:3]:  # show first 3
        print(f"  [{a['priority']}] [{a['status']}] {a['task'][:80]}")

    if all_actions:
        first_id = all_actions[0]["id"]
        r = requests.patch(
            f"{BASE}/actions/{first_id}/status",
            headers={"X-API-Key": finance_key},
            json={"status": "in_progress"},
        )
        print(f"\nUpdated first task → {r.json()}")


if __name__ == "__main__":
    main()
