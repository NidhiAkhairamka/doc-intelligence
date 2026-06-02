import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import config

DB_PATH = Path(config.DB_PATH)

VALID_STATUSES = {"pending", "in_progress", "completed", "overdue"}


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id          TEXT PRIMARY KEY,
                name        TEXT UNIQUE NOT NULL,
                api_key     TEXT UNIQUE NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extractions (
                doc_id          TEXT PRIMARY KEY,
                dept_id         TEXT NOT NULL,
                filename        TEXT NOT NULL,
                extraction_json TEXT NOT NULL,
                extracted_at    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contradictions (
                id              TEXT PRIMARY KEY,
                dept_id         TEXT NOT NULL,
                conflicts_json  TEXT NOT NULL,
                doc_ids         TEXT NOT NULL,
                analysed_at     TEXT NOT NULL
            )
        """)
        # One row per task — enables per-task status tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id          TEXT PRIMARY KEY,
                doc_id      TEXT NOT NULL,
                dept_id     TEXT NOT NULL,
                filename    TEXT NOT NULL,
                task        TEXT NOT NULL,
                responsible TEXT,
                deadline    TEXT,
                priority    TEXT NOT NULL DEFAULT 'Medium',
                notes       TEXT,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  TEXT NOT NULL
            )
        """)


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

def seed_demo_department(demo_key: str) -> dict:
    """
    Ensure a 'Demo' department with a fixed API key exists.
    Called at every startup so the demo dept survives container restarts.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name, api_key, created_at FROM departments WHERE name = 'Demo'"
        ).fetchone()
        if row:
            # Update key if it changed (e.g. env var was changed)
            conn.execute(
                "UPDATE departments SET api_key = ? WHERE name = 'Demo'",
                (demo_key,),
            )
            return _dept_row(row)
        dept_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO departments (id, name, api_key, created_at) VALUES (?, 'Demo', ?, ?)",
            (dept_id, demo_key, created_at),
        )
        return {"id": dept_id, "name": "Demo", "api_key": demo_key, "created_at": created_at}


def create_department(name: str) -> dict:
    dept_id = str(uuid.uuid4())
    api_key = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    with _conn() as conn:
        try:
            conn.execute(
                "INSERT INTO departments (id, name, api_key, created_at) VALUES (?, ?, ?, ?)",
                (dept_id, name, api_key, created_at),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Department '{name}' already exists.")
    return {"id": dept_id, "name": name, "api_key": api_key, "created_at": created_at}


def get_by_api_key(api_key: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name, api_key, created_at FROM departments WHERE api_key = ?",
            (api_key,),
        ).fetchone()
    return _dept_row(row) if row else None


def get_by_id(dept_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name, api_key, created_at FROM departments WHERE id = ?",
            (dept_id,),
        ).fetchone()
    return _dept_row(row) if row else None


def list_departments() -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, api_key, created_at FROM departments ORDER BY created_at"
        ).fetchall()
    return [_dept_row(r) for r in rows]


def delete_department(dept_id: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM departments WHERE id = ?", (dept_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Extractions
# ---------------------------------------------------------------------------

def store_contradictions(dept_id: str, doc_ids: list, conflicts: list) -> str:
    analysis_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """INSERT INTO contradictions (id, dept_id, conflicts_json, doc_ids, analysed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                analysis_id,
                dept_id,
                json.dumps(conflicts),
                json.dumps(doc_ids),
                datetime.utcnow().isoformat(),
            ),
        )
    return analysis_id


def get_latest_contradictions(dept_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            """SELECT id, conflicts_json, doc_ids, analysed_at
               FROM contradictions WHERE dept_id = ?
               ORDER BY analysed_at DESC LIMIT 1""",
            (dept_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "analysis_id": row[0],
        "conflicts": json.loads(row[1]),
        "doc_ids": json.loads(row[2]),
        "analysed_at": row[3],
    }


def store_extraction(doc_id: str, dept_id: str, filename: str, extraction: dict):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO extractions
               (doc_id, dept_id, filename, extraction_json, extracted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, dept_id, filename, json.dumps(extraction), datetime.utcnow().isoformat()),
        )


def get_extraction(doc_id: str, dept_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT extraction_json FROM extractions WHERE doc_id = ? AND dept_id = ?",
            (doc_id, dept_id),
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_extractions(dept_id: str) -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, filename, extraction_json, extracted_at FROM extractions WHERE dept_id = ? ORDER BY extracted_at DESC",
            (dept_id,),
        ).fetchall()
    return [
        {"doc_id": r[0], "filename": r[1], "extraction": json.loads(r[2]), "extracted_at": r[3]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def store_actions(doc_id: str, dept_id: str, filename: str, actions: list):
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        # Replace all tasks for this doc
        conn.execute("DELETE FROM actions WHERE doc_id = ? AND dept_id = ?", (doc_id, dept_id))
        for task in actions:
            if "_parse_error" in task or "error" in task:
                continue
            conn.execute(
                """INSERT INTO actions
                   (id, doc_id, dept_id, filename, task, responsible, deadline, priority, notes, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    str(uuid.uuid4()),
                    doc_id,
                    dept_id,
                    filename,
                    task.get("task", ""),
                    task.get("responsible"),
                    task.get("deadline"),
                    task.get("priority", "Medium"),
                    task.get("notes"),
                    now,
                ),
            )


def get_actions(doc_id: str, dept_id: str) -> list | None:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, task, responsible, deadline, priority, notes, status FROM actions WHERE doc_id = ? AND dept_id = ? ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, deadline",
            (doc_id, dept_id),
        ).fetchall()
    if rows is None:
        return None
    return [_action_row(r) for r in rows]


def list_all_actions(dept_id: str) -> list:
    """All tasks across all docs for a department, sorted High→Low then deadline."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, doc_id, filename, task, responsible, deadline, priority, notes, status
               FROM actions WHERE dept_id = ?
               ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,
                        CASE WHEN deadline IS NULL THEN 1 ELSE 0 END, deadline""",
            (dept_id,),
        ).fetchall()
    return [_action_row_full(r) for r in rows]


def update_action_status(action_id: str, dept_id: str, status: str) -> bool:
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of: {sorted(VALID_STATUSES)}")
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE actions SET status = ? WHERE id = ? AND dept_id = ?",
            (status, action_id, dept_id),
        )
    return cur.rowcount > 0


def get_actions_for_export(dept_id: str) -> list:
    """Only tasks with parseable YYYY-MM-DD deadlines, for calendar export."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, filename, task, responsible, deadline, priority, notes, status
               FROM actions WHERE dept_id = ? AND deadline LIKE '____-__-__%'
               AND status != 'completed'""",
            (dept_id,),
        ).fetchall()
    return [
        {
            "id": r[0], "filename": r[1], "task": r[2], "responsible": r[3],
            "deadline": r[4], "priority": r[5], "notes": r[6], "status": r[7],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _dept_row(row) -> dict:
    return {"id": row[0], "name": row[1], "api_key": row[2], "created_at": row[3]}


def _action_row(row) -> dict:
    return {
        "id": row[0], "task": row[1], "responsible": row[2],
        "deadline": row[3], "priority": row[4], "notes": row[5], "status": row[6],
    }


def _action_row_full(row) -> dict:
    return {
        "id": row[0], "doc_id": row[1], "filename": row[2], "task": row[3],
        "responsible": row[4], "deadline": row[5], "priority": row[6],
        "notes": row[7], "status": row[8],
    }
