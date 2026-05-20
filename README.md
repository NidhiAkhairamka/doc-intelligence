# 🧠 Doc Intelligence

**Multi-agent enterprise document intelligence system** — upload documents, ask questions with page citations, detect contradictions between files, track action items, and export deadlines to your calendar. Built with hard department-level data isolation so Finance can never access Marketing documents.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![Claude](https://img.shields.io/badge/Claude-Haiku%20%2B%20Sonnet-orange?logo=anthropic)](https://anthropic.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-vector%20store-green)](https://trychroma.com)
[![Flask](https://img.shields.io/badge/Flask-REST%20API-lightgrey?logo=flask)](https://flask.palletsprojects.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-red?logo=streamlit)](https://streamlit.io)
[![LangSmith](https://img.shields.io/badge/LangSmith-tracing-yellow)](https://smith.langchain.com)
[![MLflow](https://img.shields.io/badge/MLflow-observability-blue)](https://mlflow.org)

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │         Streamlit UI             │
                        │  Admin view │ Department view    │
                        └──────────────┬──────────────────┘
                                       │ HTTP
                        ┌──────────────▼──────────────────┐
                        │         Flask REST API           │
                        │  Auth · Rate limiting · MLflow   │
                        └──┬──────────┬────────────────┬──┘
                           │          │                │
              ┌────────────▼──┐  ┌────▼──────┐  ┌─────▼──────────┐
              │  /ingest      │  │  /ask     │  │ /contradictions │
              └────────────┬──┘  └────┬──────┘  └─────┬──────────┘
                           │          │                │
        ┌──────────────────▼──┐  ┌────▼──────────┐  ┌─▼──────────────────┐
        │   Ingestion Agent   │  │  Orchestrator  │  │ Contradiction Agent │
        │ chunk → embed → BM25│  │  (pure Python) │  │   Claude Sonnet     │
        └──┬───────────┬──────┘  └────┬───────────┘  └────────────────────┘
           │           │              │
    ┌──────▼──┐  ┌─────▼──────┐  ┌───▼──────────┐
    │Extraction│  │   Action   │  │   QA Agent   │
    │  Agent  │  │   Agent    │  │ Claude Sonnet │
    │  Haiku  │  │ pure Python│  │ + citations   │
    └──────┬──┘  └─────┬──────┘  └───────────────┘
           │           │
    ┌──────▼───────────▼───────────────────────────┐
    │              Storage Layer                    │
    │  ChromaDB (per-dept collection)  │  SQLite    │
    │  + BM25 index (in-memory)        │  + extractions, actions, contradictions│
    └───────────────────────────────────────────────┘
```

---

## Agents

| Agent | Model | Purpose |
|---|---|---|
| **Ingestion** | — | Chunks documents, embeds with local model, builds BM25 index |
| **Extraction** | Claude Haiku | Extracts parties, dates, obligations, amounts, conditions as structured JSON |
| **Action** | Pure Python | Zero LLM calls — keyword signal scoring generates prioritised task list |
| **Q&A** | Claude Sonnet | Answers questions strictly from retrieved context with page citations |
| **Contradiction** | Claude Sonnet | Pairwise document comparison, surfaces Critical/Warning/Info conflicts |
| **Orchestrator** | Pure Python | Routes queries, filters contradictions by relevance, merges related actions |
| **Calendar** | — | Generates `.ics` file with VALARM reminders from deadline tasks |

---

## Key Design Decisions

### Zero-cost embeddings
Local `BAAI/bge-small-en-v1.5` via sentence-transformers — downloads once (~90MB), runs on CPU, eliminates OpenAI embedding API cost entirely.

### Hard department isolation
Separate ChromaDB collection per department (`dept-{id}`). Finance documents are physically in a different collection from Marketing — not just filtered at query time. Deleting a department evicts its collection entirely.

### Two-tier Claude strategy
- **Haiku** → structured extraction (10× cheaper, fast, good at JSON)
- **Sonnet** → Q&A and contradiction analysis (quality-critical paths only)

### Pure Python Action Agent
Zero LLM calls. Obligations from extraction become High-priority tasks (deadline present) or Medium (signal words: *must, shall, penalty, submit*). Conditions with mandatory language become Low-priority verification tasks.

### Hybrid search
BM25 (40%) + semantic cosine similarity (60%), both normalised 0–1 before combining. BM25 handles exact keyword matches (contract numbers, dates); semantic handles meaning.

---

## Features

- 📄 **Upload** PDF, DOCX, TXT — chunked, embedded, indexed automatically
- 💬 **Ask questions** — answers strictly from your documents with filename + page citations
- ⚠️ **Contradiction detection** — finds conflicts between documents, severity-rated with source quotes
- 📋 **Action tracker** — deadlines and obligations extracted automatically, status tracking per task
- 📅 **Calendar export** — `.ics` file with VALARM reminders, works with Google Calendar / Outlook / Apple
- 🔐 **Department isolation** — admin creates departments, each gets a UUID API key, hard data separation
- 📊 **Observability** — LangSmith traces every agent call, MLflow logs every query (tokens, cost, timing)
- 🛡️ **Rate limiting** — per-route limits (5/min on `/ask`, 20/hour on `/ingest`)

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| LLM | Anthropic Claude (Haiku + Sonnet) | Two-tier cost strategy |
| Embeddings | sentence-transformers BAAI/bge-small | Zero API cost, runs local |
| Vector DB | ChromaDB (persistent, per-dept) | Hard isolation, no shared index |
| Keyword search | rank-bm25 (BM25Okapi) | Exact match complement to semantic |
| Database | SQLite | Extractions, actions, contradictions, departments |
| API | Flask + flask-limiter | REST, rate limiting, role-based auth |
| UI | Streamlit | Rapid multi-role dashboard |
| Tracing | LangSmith (@traceable) | Per-agent observability |
| Metrics | MLflow | Per-query cost + performance logging |
| PDF parsing | PyMuPDF (fitz) | Page-level text with `[Page N]` tags |
| DOCX parsing | python-docx | Native Word document support |
| Calendar | icalendar | RFC 5545 `.ics` with VALARM |
| Containers | Docker Compose | API + Streamlit + MLflow in one command |

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/NidhiAkhairamka/doc-intelligence.git
cd doc-intelligence
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

Required:
```
ANTHROPIC_API_KEY=sk-ant-...
ADMIN_API_KEY=choose-any-strong-string
```

Optional (for observability):
```
LANGCHAIN_API_KEY=lsv2_pt_...
```

### 3. Run

**Terminal 1 — API:**
```bash
python api.py
# Running on http://localhost:5000
```

**Terminal 2 — UI:**
```bash
streamlit run streamlit_app.py
# Opens at http://localhost:8501
```

**Or with Docker Compose:**
```bash
docker compose up
```

### 4. First use

1. Open `http://localhost:8501`
2. Click the **🔐 Admin** login → enter your `ADMIN_API_KEY`
3. Create a department (e.g. "Finance") — copy the API key shown
4. Log out of admin → paste the department key → upload documents → ask questions

---

## API Reference

All department endpoints require `X-API-Key: <dept-key>` header.  
Admin endpoints require `X-Admin-Key: <admin-key>` header.

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | Health check |
| POST | `/ingest` | Dept | Upload and process a document |
| POST | `/ask` | Dept | Ask a question (supports `session_id` for history) |
| GET | `/documents` | Dept | List uploaded documents |
| GET | `/extractions` | Dept | List all structured extractions |
| GET | `/extractions/<doc_id>` | Dept | Get extraction for one document |
| GET | `/actions` | Dept | All action items, sorted High→Low |
| PATCH | `/actions/<id>/status` | Dept | Update task status |
| GET | `/actions/export.ics` | Dept | Download calendar file |
| POST | `/contradictions/analyse` | Dept | Run contradiction analysis |
| GET | `/contradictions` | Dept | Get latest analysis results |
| GET | `/admin/departments` | Admin | List all departments |
| POST | `/admin/departments` | Admin | Create department |
| DELETE | `/admin/departments/<id>` | Admin | Delete department |
| GET | `/admin/departments/<id>/documents` | Admin | View dept files |

---

## Project Structure

```
doc-intelligence/
├── api.py                    # Flask REST API + rate limiting
├── config.py                 # Central config from .env
├── streamlit_app.py          # Multi-role Streamlit UI
├── docker-compose.yml        # API + Streamlit + MLflow
├── Dockerfile
├── requirements.txt
├── .env.example              # Config template (never commit .env)
│
├── agents/
│   ├── ingestion_agent.py    # Chunk → embed → BM25 → extract → actions
│   ├── extraction_agent.py   # Claude Haiku structured JSON extraction
│   ├── action_agent.py       # Pure Python priority task generation
│   ├── qa_agent.py           # Claude Sonnet Q&A with citations
│   ├── contradiction_agent.py# Pairwise document conflict detection
│   ├── orchestrator.py       # Routes queries, merges agent outputs
│   └── calendar_agent.py     # iCal .ics generation with VALARM
│
├── core/
│   ├── store.py              # ChromaDB + BM25 hybrid search per dept
│   ├── db.py                 # SQLite — depts, extractions, actions, contradictions
│   └── extractor.py          # PDF (PyMuPDF), DOCX, TXT text extraction
│
└── test_docs/
    └── vendor_contract_alpha.txt   # Fake contract with planted contradictions for testing
```

---

## Testing the Contradiction Agent

The repo includes a fake vendor contract (`test_docs/vendor_contract_alpha.txt`) with **6 deliberate contradictions** planted against a UAE VAT compliance guide — different payment terms, penalty rates, registration thresholds, etc. The contradiction agent detects all 6.

To test:
1. Upload both documents to the same department
2. Go to **⚠️ Contradictions** tab → Analyse
3. You should see 6 Critical/Warning conflicts with source quotes from both documents

---

## Observability

- **LangSmith** — traces every `extraction-agent` and `qa-agent` call with prompt, tokens, and timing
- **MLflow UI** — run `mlflow ui --backend-store-uri ./mlruns` or visit `localhost:5001` (Docker)
  - Tracks: `response_time_sec`, `input_tokens`, `output_tokens`, `chunks_used`, `contradictions_surfaced`

---

## Related Projects

- [uae-compliance-rag](https://github.com/NidhiAkhairamka/uae-compliance-rag) — Earlier, simpler RAG implementation using LangChain for UAE VAT documents. Doc Intelligence is the evolution of this — multi-agent, multi-department, production-grade.

---

## Author

**Nidhi Akhairamka** — AI Engineer, UAE  
[GitHub](https://github.com/NidhiAkhairamka) · nidhididwania@gmail.com
