import sqlite3
import json
import hashlib
import secrets
from datetime import datetime

DB_PATH = "compliance_history.db"

VALID_ROLES = ("admin", "officer")


def _hash_password(password, salt):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def init_db():
    """Create tables if they don't exist, and seed default accounts on first run."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            score INTEGER NOT NULL,
            found_json TEXT NOT NULL,
            missing_json TEXT NOT NULL,
            image_blob BLOB,
            image_media_type TEXT,
            latitude REAL,
            longitude REAL,
            location_name TEXT,
            scanned_by TEXT
        )
    """)
    # Migration for databases created before scanned_by existed
    cur.execute("PRAGMA table_info(scans)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "scanned_by" not in existing_cols:
        cur.execute("ALTER TABLE scans ADD COLUMN scanned_by TEXT")
    # Migration for the calibrated Rule 7 numeral-height verification result
    # (font_height.py). NULL means "not verified with a physical reference".
    for col, coltype in [
        ("font_height_measured_mm", "REAL"),
        ("font_height_required_mm", "REAL"),
        ("font_height_verdict", "TEXT"),
        ("font_height_field", "TEXT"),
    ]:
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE scans ADD COLUMN {col} {coltype}")
    conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'officer')),
            created_at TEXT NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    # Migration for databases created before must_change_password existed
    cur.execute("PRAGMA table_info(users)")
    existing_user_cols = {row[1] for row in cur.fetchall()}
    if "must_change_password" not in existing_user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        conn.commit()

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        _create_user_raw(conn, "admin", "admin123", "admin", force_change=True)
        _create_user_raw(conn, "officer", "officer123", "officer", force_change=True)

    conn.close()


def _create_user_raw(conn, username, password, role, force_change=True):
    salt = secrets.token_hex(8)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password_hash, salt, role, created_at, must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
        (username, _hash_password(password, salt), salt, role, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 1 if force_change else 0),
    )
    conn.commit()


def create_user(username, password, role):
    """Returns True on success, False if username already exists or role invalid."""
    if role not in VALID_ROLES:
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        _create_user_raw(conn, username, password, role)
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def delete_user(username):
    """Delete a user account. Refuses to delete the last remaining admin."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    if row["role"] == "admin":
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cur.fetchone()[0] <= 1:
            conn.close()
            return False  # can't delete the last admin
    cur.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return True


def verify_user(username, password):
    """Check credentials. Returns {"role": str, "must_change_password": bool} if valid, else None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    expected = _hash_password(password, row["salt"])
    if secrets.compare_digest(expected, row["password_hash"]):
        return {"role": row["role"], "must_change_password": bool(row["must_change_password"])}
    return None


def set_user_password(username, new_password, clear_force_change=True):
    conn = sqlite3.connect(DB_PATH)
    salt = secrets.token_hex(8)
    cur = conn.cursor()
    if clear_force_change:
        cur.execute(
            "UPDATE users SET password_hash = ?, salt = ?, must_change_password = 0 WHERE username = ?",
            (_hash_password(new_password, salt), salt, username),
        )
    else:
        cur.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
            (_hash_password(new_password, salt), salt, username),
        )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, created_at, must_change_password FROM users ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_scan(filename, score, found, missing, image_bytes, media_type, latitude=None, longitude=None, location_name=None, scanned_by=None, font_height_result=None):
    """font_height_result, if provided, is a dict from the Rule 7 calibrated
    measurement flow: {"measured_mm": float, "required_mm": float, "verdict": "PASS"/"FAIL", "field": "net_quantity"/"mrp"}."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    fh = font_height_result or {}
    cur.execute("""
        INSERT INTO scans (filename, scan_time, score, found_json, missing_json, image_blob, image_media_type, latitude, longitude, location_name, scanned_by,
                            font_height_measured_mm, font_height_required_mm, font_height_verdict, font_height_field)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        filename,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        score,
        json.dumps(found),
        json.dumps(missing),
        image_bytes,
        media_type,
        latitude,
        longitude,
        location_name,
        scanned_by,
        fh.get("measured_mm"),
        fh.get("required_mm"),
        fh.get("verdict"),
        fh.get("field"),
    ))
    conn.commit()
    scan_id = cur.lastrowid
    conn.close()
    return scan_id


def get_all_scans(limit=200):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_scans_for_analytics(limit=2000):
    """Lightweight fetch (no image blobs) for dashboard charts/aggregation."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, filename, scan_time, score, found_json, missing_json, scanned_by
        FROM scans ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def search_scans(query):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM scans
        WHERE filename LIKE ? OR location_name LIKE ?
        ORDER BY id DESC
    """, (f"%{query}%", f"%{query}%"))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def search_scans_advanced(filename=None, scanned_by=None, date_from=None, date_to=None,
                           min_score=None, max_score=None, violation_label=None, limit=500):
    """Multi-filter search over inspection history. Every filter is optional and
    combined with AND, so an officer can narrow by any combination of:
      - filename (substring match)
      - scanned_by (exact officer/admin username)
      - date_from / date_to ("YYYY-MM-DD" — inclusive range on scan_time)
      - min_score / max_score (compliance score %, inclusive range)
      - violation_label (only scans where this declaration is among the missing/violations)
    Returns scans newest-first, capped at `limit`.
    """
    clauses = []
    params = []

    if filename:
        clauses.append("(filename LIKE ? OR location_name LIKE ?)")
        params.extend([f"%{filename}%", f"%{filename}%"])
    if scanned_by:
        clauses.append("scanned_by = ?")
        params.append(scanned_by)
    if date_from:
        clauses.append("scan_time >= ?")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        clauses.append("scan_time <= ?")
        params.append(f"{date_to} 23:59:59")
    if min_score is not None:
        clauses.append("score >= ?")
        params.append(min_score)
    if max_score is not None:
        clauses.append("score <= ?")
        params.append(max_score)
    if violation_label:
        # missing_json stores entries like {"label": "<declaration label>", ...} —
        # a substring match on the serialized JSON is enough for filtering without
        # requiring SQLite's json1 extension to be compiled in.
        clauses.append("missing_json LIKE ?")
        params.append(f'%"label": "{violation_label}%')

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM scans {where_sql} ORDER BY id DESC LIMIT ?", (*params, limit))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_distinct_scanners():
    """List of usernames that have performed at least one scan, for a filter dropdown."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT scanned_by FROM scans WHERE scanned_by IS NOT NULL ORDER BY scanned_by")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def get_summary_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), AVG(score) FROM scans")
    total, avg_score = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM scans WHERE score = 100")
    fully_compliant = cur.fetchone()[0]
    conn.close()
    return {
        "total_scans": total or 0,
        "avg_score": round(avg_score, 1) if avg_score else 0,
        "fully_compliant": fully_compliant or 0,
    }
