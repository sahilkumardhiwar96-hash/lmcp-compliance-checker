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


def save_scan(filename, score, found, missing, image_bytes, media_type, latitude=None, longitude=None, location_name=None, scanned_by=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO scans (filename, scan_time, score, found_json, missing_json, image_blob, image_media_type, latitude, longitude, location_name, scanned_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
