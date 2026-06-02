import uuid
import requests
import streamlit as st

import os
API_BASE  = os.environ.get("API_BASE", "http://localhost:5000")
DEMO_KEY  = os.environ.get("DEMO_API_KEY", "demo-doc-intelligence")

st.set_page_config(
    page_title="Doc Intelligence",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",   # sidebar not needed on landing
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
for key, default in {
    "api_key": "",
    "dept_name": "",
    "messages": [],
    "session_id": str(uuid.uuid4()),
    "documents": [],
    "admin_key": "",
    "admin_verified": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def api(method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    if st.session_state.api_key:
        headers["X-API-Key"] = st.session_state.api_key
    try:
        r = requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=120, **kwargs)
        return r
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot reach the API. Make sure `python api.py` is running on port 5000.")
        return None


def admin_api(method: str, path: str, **kwargs):
    try:
        return requests.request(
            method,
            f"{API_BASE}{path}",
            headers={"X-Admin-Key": st.session_state.admin_key},
            timeout=15,
            **kwargs,
        )
    except Exception:
        return None


def severity_icon(s):
    return {"Critical": "🔴", "Warning": "🟡", "Info": "🟢"}.get(s, "⚪")

def priority_icon(p):
    return {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(p, "⚪")

def status_badge(s):
    return {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "overdue": "🚨"}.get(s, "❓")


# ===========================================================================
# ROUTING — three completely separate views, no tab bleed-through
# ===========================================================================

# ── VIEW A: Admin dashboard ─────────────────────────────────────────────────
if st.session_state.admin_verified:

    # Minimal top bar
    bar_l, bar_r = st.columns([8, 1])
    with bar_l:
        st.markdown("## 🧠 Doc Intelligence — Admin Panel")
    with bar_r:
        if st.button("🔓 Logout", use_container_width=True):
            st.session_state.admin_key = ""
            st.session_state.admin_verified = False
            st.rerun()

    st.divider()

    # ── Create department ────────────────────────────────────────────────────
    st.subheader("➕ Create new department")
    cr1, cr2 = st.columns([4, 1])
    new_name = cr1.text_input(
        "name", placeholder="e.g. Finance, Legal, HR, Marketing",
        label_visibility="collapsed",
    )
    if cr2.button("Create", type="primary", use_container_width=True):
        if new_name.strip():
            r = admin_api("POST", "/admin/departments", json={"name": new_name.strip()})
            if r and r.status_code == 201:
                created = r.json()
                st.success(f"✅ **{created['name']}** created!")
                st.markdown("**Share this API key with the team:**")
                st.code(created["api_key"], language=None)
                st.rerun()
            elif r:
                st.error(r.json().get("error"))
        else:
            st.warning("Enter a department name.")

    st.divider()

    # ── Department cards ─────────────────────────────────────────────────────
    r_depts = admin_api("GET", "/admin/departments")
    if not r_depts or r_depts.status_code != 200:
        st.error("Could not load departments. Is the API running?")
        st.stop()

    depts = r_depts.json()
    st.subheader(f"📁 Departments ({len(depts)})")

    if not depts:
        st.info("No departments yet. Create one above.")
    else:
        for d in depts:
            with st.container(border=True):
                h_left, h_right = st.columns([7, 1])
                with h_left:
                    st.markdown(f"### 📁 {d['name']}")
                    st.caption(f"Created {d['created_at'][:10]}  ·  ID: `{d['id'][:8]}…`")
                with h_right:
                    if st.button("🗑️ Delete", key=f"del_{d['id']}", use_container_width=True):
                        admin_api("DELETE", f"/admin/departments/{d['id']}")
                        st.rerun()

                # API key — full width, easy to copy
                st.markdown("**Department API Key** *(share with team so they can log in)*")
                st.code(d["api_key"], language=None)

                # Files — lazy load inside expander
                with st.expander("📄 View uploaded files", expanded=True):
                    r_files = admin_api("GET", f"/admin/departments/{d['id']}/documents")
                    files = r_files.json() if r_files and r_files.status_code == 200 else []
                    if files:
                        fh1, fh2, fh3 = st.columns([5, 2, 2])
                        fh1.caption("Filename")
                        fh2.caption("Chunks")
                        fh3.caption("Uploaded")
                        st.divider()
                        for f in files:
                            fname = f["filename"]
                            ext   = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                            ficon = {"pdf": "📕", "docx": "📘", "txt": "📄", "pptx": "📊"}.get(ext, "📄")
                            fc1, fc2, fc3 = st.columns([5, 2, 2])
                            fc1.markdown(f"{ficon} **{fname}**")
                            fc2.caption(str(f.get("total_chunks", "?")))
                            fc3.caption(f.get("ingested_at", "")[:10])
                    else:
                        st.caption("No files uploaded yet — share the API key above so the team can upload.")


# ── VIEW B: Department user dashboard ───────────────────────────────────────
elif st.session_state.api_key:

    # Slim sidebar for dept users only
    with st.sidebar:
        st.markdown("### 🧠 Doc Intelligence")
        st.caption(f"Signed in to: **{st.session_state.dept_name or 'Your Department'}**")
        st.divider()

        r = api("GET", "/documents")
        if r and r.status_code == 200:
            st.session_state.documents = r.json()
        st.metric("Documents", len(st.session_state.documents))

        st.divider()
        if st.button("🔄 Clear chat", help="Clears conversation history only. Documents are kept."):
            st.session_state.messages = []
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()

        st.divider()
        if st.button("🚪 Sign out", use_container_width=True):
            st.session_state.api_key = ""
            st.session_state.dept_name = ""
            st.session_state.documents = []
            st.session_state.messages = []
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()

    # Department tabs — no Admin tab here
    tab_ask, tab_upload, tab_actions, tab_contradictions, tab_calendar = st.tabs([
        "💬 Ask", "📤 Upload", "📋 Actions", "⚠️ Contradictions", "📅 Calendar",
    ])

    # ── Ask ──────────────────────────────────────────────────────────────────
    with tab_ask:
        st.header("Ask your documents")

        if not st.session_state.documents:
            st.warning("No documents yet — go to the **📤 Upload** tab first.")
        else:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    # Only show sources — contradictions & actions live in their own tabs
                    if msg["role"] == "assistant" and msg.get("meta"):
                        sources = msg["meta"].get("sources", [])
                        if sources:
                            with st.expander(f"📄 {len(sources)} source(s)"):
                                for s in sources:
                                    st.caption(f"→ {s['citation']}")
                        # Subtle hint if related data exists in other tabs
                        hints = []
                        if msg["meta"].get("contradictions"):
                            hints.append(f"⚠️ {len(msg['meta']['contradictions'])} contradiction(s) found")
                        if msg["meta"].get("related_actions"):
                            hints.append(f"📋 {len(msg['meta']['related_actions'])} related action(s)")
                        if hints:
                            st.caption("  ·  ".join(hints) + " — see tabs above")

            if prompt := st.chat_input("Ask anything about your documents..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Searching documents..."):
                        r = api("POST", "/ask", json={
                            "question": prompt,
                            "session_id": st.session_state.session_id,
                        })

                    if r and r.status_code == 200:
                        data = r.json()
                        answer = data["answer"]
                        st.markdown(answer)

                        # Sources only — clean and focused
                        if data.get("sources"):
                            with st.expander(f"📄 {len(data['sources'])} source(s)"):
                                for s in data["sources"]:
                                    st.caption(f"→ {s['citation']}")

                        # Subtle hints pointing to other tabs — no data dump
                        hints = []
                        if data.get("contradictions"):
                            hints.append(f"⚠️ {len(data['contradictions'])} contradiction(s) found")
                        if data.get("related_actions"):
                            hints.append(f"📋 {len(data['related_actions'])} related action(s)")
                        if hints:
                            st.caption("  ·  ".join(hints) + " — see tabs above")

                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": answer,
                            "meta": data,
                        })
                    else:
                        st.error("Failed to get an answer. Try again.")

    # ── Upload ───────────────────────────────────────────────────────────────
    with tab_upload:
        st.header("Upload documents")
        st.caption("PDF, Word (.docx), PowerPoint (.pptx), plain text (.txt) · Max 20 MB per file")

        uploaded = st.file_uploader(
            "Drop files here",
            type=["pdf", "docx", "txt", "pptx"],
            accept_multiple_files=True,
        )
        if uploaded:
            if st.button("⬆️ Ingest all files", type="primary"):
                for f in uploaded:
                    with st.spinner(f"Ingesting {f.name}..."):
                        r = api("POST", "/ingest", files={"file": (f.name, f.getvalue(), f.type)})
                    if r and r.status_code == 201:
                        data = r.json()
                        st.success(f"✅ **{f.name}** — {data['chunks_created']} chunks created")
                        ex = data.get("extraction", {})
                        if ex and not ex.get("error"):
                            with st.expander("🔍 Extraction preview"):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.markdown(f"**Type:** {ex.get('document_type', '—')}")
                                    st.markdown(f"**Parties:** {', '.join(ex.get('parties', [])) or '—'}")
                                with c2:
                                    st.markdown(f"**Key topics:** {', '.join(ex.get('key_topics', [])) or '—'}")
                                if ex.get("obligations"):
                                    st.markdown(f"**Obligations found:** {len(ex['obligations'])}")
                        if data.get("actions"):
                            st.info(f"📋 {len(data['actions'])} action items generated automatically.")
                    elif r:
                        st.error(f"❌ {f.name}: {r.json().get('error', 'Unknown error')}")
                st.rerun()

        st.divider()
        st.subheader("Your documents")
        r = api("GET", "/documents")
        if r and r.status_code == 200:
            docs = r.json()
            if not docs:
                st.info("No documents yet. Upload your first file above.")
            else:
                st.markdown(f"📁 **{st.session_state.dept_name or 'Your Department'}** — {len(docs)} file(s)")
                h1, h2, h3 = st.columns([5, 2, 2])
                h1.caption("File"); h2.caption("Chunks"); h3.caption("Uploaded")
                st.divider()
                for doc in docs:
                    fname = doc["filename"]
                    ext   = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                    icon  = {"pdf": "📕", "docx": "📘", "txt": "📄", "pptx": "📊"}.get(ext, "📄")
                    c1, c2, c3 = st.columns([5, 2, 2])
                    c1.markdown(f"{icon} **{fname}**")
                    c2.caption(str(doc.get("total_chunks", "?")))
                    c3.caption(doc.get("ingested_at", "")[:10])

    # ── Actions ──────────────────────────────────────────────────────────────
    with tab_actions:
        st.header("Action tracker")
        r = api("GET", "/actions")
        if r and r.status_code == 200:
            actions = r.json()
            if not actions:
                st.info("No actions yet. Upload documents to generate them automatically.")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total tasks", len(actions))
                c2.metric("🔴 High priority", sum(1 for a in actions if a["priority"] == "High"))
                c3.metric("⏳ Pending",       sum(1 for a in actions if a["status"] == "pending"))
                c4.metric("✅ Completed",     sum(1 for a in actions if a["status"] == "completed"))
                st.divider()

                fc1, fc2 = st.columns(2)
                filter_priority = fc1.selectbox("Priority", ["All", "High", "Medium", "Low"])
                filter_status   = fc2.selectbox("Status",   ["All", "pending", "in_progress", "completed", "overdue"])

                filtered = [
                    a for a in actions
                    if (filter_priority == "All" or a["priority"] == filter_priority)
                    and (filter_status   == "All" or a["status"]   == filter_status)
                ]
                st.caption(f"Showing {len(filtered)} of {len(actions)} tasks")

                for action in filtered:
                    with st.expander(f"{priority_icon(action['priority'])} {status_badge(action['status'])}  {action['task'][:80]}"):
                        d1, d2 = st.columns(2)
                        with d1:
                            st.markdown(f"**Task:** {action['task']}")
                            st.markdown(f"**Responsible:** {action.get('responsible') or '—'}")
                            st.markdown(f"**Deadline:** {action.get('deadline') or '—'}")
                        with d2:
                            st.markdown(f"**Source:** 📄 {action['filename']}")
                            st.markdown(f"**Priority:** {action['priority']}")
                            st.markdown(f"**Status:** {action['status']}")
                        new_status = st.selectbox(
                            "Update status",
                            ["pending", "in_progress", "completed", "overdue"],
                            index=["pending", "in_progress", "completed", "overdue"].index(action["status"]),
                            key=f"status_{action['id']}",
                        )
                        if new_status != action["status"]:
                            if st.button("💾 Save", key=f"save_{action['id']}"):
                                r2 = api("PATCH", f"/actions/{action['id']}/status", json={"status": new_status})
                                if r2 and r2.status_code == 200:
                                    st.success("Updated!")
                                    st.rerun()

    # ── Contradictions ───────────────────────────────────────────────────────
    with tab_contradictions:
        st.header("Contradiction analysis")
        st.caption("Detects conflicts between your uploaded documents.")

        docs = st.session_state.documents
        if len(docs) < 2:
            st.warning("Upload at least 2 documents to run contradiction analysis.")
        else:
            if st.button("🔍 Analyse all documents for conflicts", type="primary"):
                with st.spinner("Comparing documents — may take 20–30 seconds..."):
                    r = api("POST", "/contradictions/analyse")
                if r and r.status_code == 200:
                    data = r.json()
                    st.success(f"Done — {data['conflicts_found']} conflict(s) found across {data['documents_checked']} documents.")
                    st.rerun()
                elif r:
                    st.error(r.json().get("error"))

        r = api("GET", "/contradictions")
        if r and r.status_code == 200:
            data     = r.json()
            conflicts = data.get("conflicts", [])
            st.caption(f"Last analysed: {data.get('analysed_at', '—')[:19]}")
            if not conflicts:
                st.success("✅ No conflicts found.")
            else:
                m1, m2, m3 = st.columns(3)
                m1.metric("🔴 Critical", sum(1 for c in conflicts if c.get("severity") == "Critical"))
                m2.metric("🟡 Warning",  sum(1 for c in conflicts if c.get("severity") == "Warning"))
                m3.metric("🟢 Info",     sum(1 for c in conflicts if c.get("severity") == "Info"))
                st.divider()
                for c in conflicts:
                    with st.expander(f"{severity_icon(c['severity'])} [{c['severity']}] {c['summary']}"):
                        q1, q2 = st.columns(2)
                        with q1:
                            st.error(f"**📄 {c.get('source_a') or c.get('doc_a')}**\n\n{c.get('quote_a','')}")
                        with q2:
                            st.success(f"**📄 {c.get('source_b') or c.get('doc_b')}**\n\n{c.get('quote_b','')}")
                        st.info(f"🔧 **Recommendation:** {c.get('recommendation','')}")
                        if c.get("action_required"):
                            st.warning(f"📌 **Action:** {c['action_required']}")
        elif r and r.status_code == 404:
            st.info("No analysis run yet. Click the button above to start.")

    # ── Calendar ─────────────────────────────────────────────────────────────
    with tab_calendar:
        st.header("Export to calendar")
        st.caption("Downloads a .ics file — works with Google Calendar, Outlook, Apple Calendar.")

        r = api("GET", "/actions")
        if r and r.status_code == 200:
            actions      = r.json()
            with_deadline = [a for a in actions if a.get("deadline") and "-" in str(a.get("deadline", ""))]
            pending       = [a for a in with_deadline if a["status"] != "completed"]

            m1, m2 = st.columns(2)
            m1.metric("Tasks with deadlines", len(with_deadline))
            m2.metric("Pending (will export)", len(pending))
            st.divider()

            if pending:
                st.subheader("Tasks to be exported")
                for a in pending:
                    st.markdown(f"{priority_icon(a['priority'])} **{a['deadline']}** — {a['task'][:80]}")
                st.divider()
                r_ics = api("GET", "/actions/export.ics")
                if r_ics and r_ics.status_code == 200:
                    st.download_button(
                        "📅 Download .ics file",
                        data=r_ics.content,
                        file_name="doc-intelligence-actions.ics",
                        mime="text/calendar",
                        type="primary",
                    )
                    st.caption("Double-click the downloaded file to import into your calendar app.")
            else:
                st.info("No pending tasks with fixed deadlines to export.")


# ── VIEW C: Landing page — no key, no admin ──────────────────────────────────
else:
    st.markdown("<h1 style='text-align:center'>🧠 Doc Intelligence</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:gray'>Enterprise document Q&A with AI agents</p>", unsafe_allow_html=True)
    st.divider()

    # ── Demo banner ────────────────────────────────────────────────────
    with st.container(border=True):
        dc1, dc2 = st.columns([5, 2])
        with dc1:
            st.markdown("#### 🎮 Try the live demo")
            st.markdown(
                "A **Demo** department is pre-loaded. Click the button to log in instantly — "
                "no key needed. Upload any PDF, DOCX, PPTX or TXT and start asking questions."
            )
            st.code(f"Demo API key: {DEMO_KEY}", language=None)
        with dc2:
            st.write("")
            st.write("")
            if st.button("▶ Enter Demo", type="primary", use_container_width=True):
                try:
                    r = requests.get(
                        f"{API_BASE}/documents",
                        headers={"X-API-Key": DEMO_KEY},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        st.session_state.api_key = DEMO_KEY
                        st.session_state.dept_name = "Demo"
                        st.session_state.documents = r.json()
                        st.session_state.messages = []
                        st.session_state.session_id = str(uuid.uuid4())
                        st.rerun()
                    else:
                        st.error("Demo unavailable — API not reachable.")
                except Exception:
                    st.error("❌ Cannot reach the API.")

    st.divider()

    # Two login cards side by side — credentials at the TOP
    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.markdown("### 👤 Department login")
            st.caption("Paste the API key your admin shared with you.")
            dept_key = st.text_input("Department API Key", type="password", placeholder="e.g. e3f594b2-...", key="landing_dept_key")
            if st.button("Sign in →", type="primary", use_container_width=True):
                if dept_key.strip():
                    # Validate key against API
                    try:
                        r = requests.get(
                            f"{API_BASE}/documents",
                            headers={"X-API-Key": dept_key.strip()},
                            timeout=10,
                        )
                        if r.status_code == 200:
                            st.session_state.api_key = dept_key.strip()
                            st.session_state.documents = r.json()
                            st.session_state.messages = []
                            st.session_state.session_id = str(uuid.uuid4())
                            st.rerun()
                        else:
                            st.error("❌ Invalid API key. Ask your admin for the correct key.")
                    except Exception:
                        st.error("❌ Cannot reach the API. Make sure `python api.py` is running.")
                else:
                    st.warning("Paste your department key first.")

    with right:
        with st.container(border=True):
            st.markdown("### 🔐 Admin login")
            st.caption("Only for the system administrator.")
            admin_key = st.text_input("Admin key", type="password", placeholder="Admin key", key="landing_admin_key")
            if st.button("Login as admin →", use_container_width=True):
                if admin_key.strip():
                    st.session_state.admin_key = admin_key.strip()
                    try:
                        r = requests.get(
                            f"{API_BASE}/admin/departments",
                            headers={"X-Admin-Key": admin_key.strip()},
                            timeout=10,
                        )
                        if r.status_code == 200:
                            st.session_state.admin_verified = True
                            st.rerun()
                        else:
                            st.session_state.admin_key = ""
                            st.error("❌ Wrong admin key.")
                    except Exception:
                        st.error("❌ Cannot reach the API. Make sure `python api.py` is running.")
                else:
                    st.warning("Enter the admin key first.")

    st.divider()
    # What it does — below the login cards
    f1, f2, f3 = st.columns(3)
    with f1:
        st.markdown("#### 💬 Ask questions")
        st.caption("Get instant answers from your documents with exact page citations.")
    with f2:
        st.markdown("#### ⚠️ Detect conflicts")
        st.caption("Automatically surface contradictions between documents across your team.")
    with f3:
        st.markdown("#### 📋 Track actions")
        st.caption("Every deadline and obligation extracted automatically — export to your calendar.")
