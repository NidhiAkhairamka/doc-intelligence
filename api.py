import os
import time
import traceback
import tempfile
from functools import wraps
from pathlib import Path

import mlflow
from flask import Flask, request, jsonify, g, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from core.store import StoreManager
from core import db
from agents import ingestion_agent, qa_agent, calendar_agent, contradiction_agent, orchestrator
import config

# Configure MLflow
mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
mlflow.set_experiment("doc-intelligence-queries")

app = Flask(__name__)

# Rate limiter — keyed by IP address
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)
db.init_db()

store_manager = StoreManager()
sessions: dict = {}  # session_id -> list of message dicts


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Admin-Key")
        if not key or key != config.ADMIN_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def require_dept(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        dept = db.get_by_api_key(key) if key else None
        if not dept:
            return jsonify({"error": "Invalid or missing X-API-Key header"}), 401
        g.dept = dept
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Max upload size — 20 MB hard cap
# ---------------------------------------------------------------------------
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB


@app.errorhandler(413)
def request_entity_too_large(_e):
    return jsonify({"error": "File too large. Maximum upload size is 20 MB."}), 413


# ---------------------------------------------------------------------------
# Admin — department management
# ---------------------------------------------------------------------------

@app.route("/admin/departments", methods=["GET"])
@require_admin
@limiter.limit("30 per minute")
def admin_list_departments():
    return jsonify(db.list_departments())


@app.route("/admin/departments", methods=["POST"])
@require_admin
def admin_create_department():
    body = request.get_json(silent=True)
    if not body or not body.get("name", "").strip():
        return jsonify({"error": "Provide a department name: {\"name\": \"Finance\"}"}), 400
    try:
        dept = db.create_department(body["name"].strip())
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(dept), 201


@app.route("/admin/departments/<dept_id>", methods=["DELETE"])
@require_admin
def admin_delete_department(dept_id):
    deleted = db.delete_department(dept_id)
    if not deleted:
        return jsonify({"error": "Department not found"}), 404
    store_manager.evict(dept_id)
    return jsonify({"deleted": dept_id})


@app.route("/admin/departments/<dept_id>/documents", methods=["GET"])
@require_admin
def admin_list_dept_documents(dept_id):
    dept = db.get_by_id(dept_id)
    if not dept:
        return jsonify({"error": "Department not found"}), 404
    # SQLite extractions table is the reliable source of truth for file metadata.
    # ChromaDB can return empty on a fresh API start even if documents exist on disk.
    extractions = db.list_extractions(dept_id)
    return jsonify([
        {
            "doc_id":     e["doc_id"],
            "filename":   e["filename"],
            "ingested_at": e["extracted_at"],
            "total_chunks": "—",
        }
        for e in extractions
    ])


# ---------------------------------------------------------------------------
# Department routes — scoped to the caller's department via X-API-Key
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@app.route("/ingest", methods=["POST"])
@require_dept
@limiter.limit("20 per hour")   # uploads are expensive — restrict per IP
def ingest():
    if "file" not in request.files:
        return jsonify({"error": "No file attached. Send as multipart/form-data with key 'file'."}), 400

    file = request.files["file"]
    suffix = Path(file.filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported type '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}"}), 400

    dept = g.dept
    store = store_manager.get(dept["id"])
    original_filename = file.filename

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        t0 = time.time()
        result = ingestion_agent.ingest(tmp_path, store, dept_id=dept["id"], original_filename=original_filename)
        elapsed = round(time.time() - t0, 3)
        result["department"] = dept["name"]
        try:
            with mlflow.start_run():
                mlflow.log_param("event", "ingest")
                mlflow.log_param("department", dept["name"])
                mlflow.log_param("filename", original_filename)
                mlflow.log_metric("chunks_created", result.get("chunks_created", 0))
                mlflow.log_metric("ingest_time_sec", elapsed)
        except Exception:
            pass
    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return jsonify(result), 201


@app.route("/ask", methods=["POST"])
@require_dept
@limiter.limit("30 per hour; 5 per minute")   # LLM calls cost money
def ask():
    body = request.get_json(silent=True)
    if not body or not body.get("question", "").strip():
        return jsonify({"error": "Request body must be JSON with a non-empty 'question' field."}), 400

    dept = g.dept
    store = store_manager.get(dept["id"])
    query = body["question"].strip()
    session_id = body.get("session_id")
    history = sessions.get(session_id, []) if session_id else []

    t0 = time.time()
    result = orchestrator.ask(query, dept["id"], store, history)
    elapsed = round(time.time() - t0, 3)

    result["department"] = dept["name"]

    # MLflow — log every query as a run for cost + performance tracking
    try:
        with mlflow.start_run():
            mlflow.log_param("department", dept["name"])
            mlflow.log_param("question", query[:200])
            mlflow.log_metric("response_time_sec", elapsed)
            mlflow.log_metric("chunks_used", result.get("chunks_used", 0))
            mlflow.log_metric("contradictions_surfaced", len(result.get("contradictions", [])))
            mlflow.log_metric("actions_surfaced", len(result.get("related_actions", [])))
            usage = result.get("usage", {})
            mlflow.log_metric("input_tokens", usage.get("input_tokens", 0))
            mlflow.log_metric("output_tokens", usage.get("output_tokens", 0))
    except Exception:
        pass  # observability must never break the response

    if session_id:
        updated = history + [
            {"role": "user", "content": query},
            {"role": "assistant", "content": result["answer"]},
        ]
        sessions[session_id] = updated[-20:]

    return jsonify(result)


@app.route("/documents", methods=["GET"])
@require_dept
def list_documents():
    dept = g.dept
    store = store_manager.get(dept["id"])
    return jsonify(store.list_documents())


@app.route("/extractions", methods=["GET"])
@require_dept
def list_extractions():
    return jsonify(db.list_extractions(g.dept["id"]))


@app.route("/extractions/<doc_id>", methods=["GET"])
@require_dept
def get_extraction(doc_id):
    extraction = db.get_extraction(doc_id, g.dept["id"])
    if not extraction:
        return jsonify({"error": "Not found"}), 404
    return jsonify(extraction)


@app.route("/actions", methods=["GET"])
@require_dept
def list_actions():
    """All actions across all docs for this department, sorted High→Low then by deadline."""
    return jsonify(db.list_all_actions(g.dept["id"]))


@app.route("/actions/<doc_id>", methods=["GET"])
@require_dept
def get_actions(doc_id):
    actions = db.get_actions(doc_id, g.dept["id"])
    if actions is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(actions)


@app.route("/actions/<action_id>/status", methods=["PATCH"])
@require_dept
def update_action_status(action_id):
    body = request.get_json(silent=True)
    if not body or "status" not in body:
        return jsonify({"error": "Provide {\"status\": \"pending|in_progress|completed|overdue\"}"}), 400
    try:
        updated = db.update_action_status(action_id, g.dept["id"], body["status"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not updated:
        return jsonify({"error": "Action not found"}), 404
    return jsonify({"id": action_id, "status": body["status"]})


@app.route("/contradictions/analyse", methods=["POST"])
@require_dept
@limiter.limit("10 per hour")   # Sonnet call on every document pair
def run_contradiction_analysis():
    """
    Analyse all documents in this department for contradictions.
    Optionally pass {"doc_ids": ["id1","id2"]} to check specific documents only.
    """
    dept_id = g.dept["id"]
    body = request.get_json(silent=True) or {}
    doc_ids_filter = body.get("doc_ids")

    extractions = db.list_extractions(dept_id)

    if doc_ids_filter:
        extractions = [e for e in extractions if e["doc_id"] in doc_ids_filter]

    if len(extractions) < 2:
        return jsonify({
            "error": "Need at least 2 documents with extractions to check for contradictions.",
            "documents_found": len(extractions),
        }), 400

    conflicts = contradiction_agent.analyse(extractions)
    analysis_id = db.store_contradictions(
        dept_id,
        [e["doc_id"] for e in extractions],
        conflicts,
    )

    return jsonify({
        "analysis_id": analysis_id,
        "documents_checked": len(extractions),
        "conflicts_found": len(conflicts),
        "conflicts": conflicts,
    })


@app.route("/contradictions", methods=["GET"])
@require_dept
def get_contradictions():
    result = db.get_latest_contradictions(g.dept["id"])
    if not result:
        return jsonify({"error": "No analysis run yet. POST to /contradictions/analyse first."}), 404
    return jsonify(result)


@app.route("/actions/export.ics", methods=["GET"])
@require_dept
def export_calendar():
    dept = g.dept
    tasks = db.get_actions_for_export(dept["id"])
    ics_bytes = calendar_agent.generate_ics(dept["name"], tasks)
    return Response(
        ics_bytes,
        mimetype="text/calendar",
        headers={"Content-Disposition": f"attachment; filename={dept['name']}-actions.ics"},
    )


if __name__ == "__main__":
    # use_reloader=False stops Flask watching site-packages (transformers triggers endless restarts)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
