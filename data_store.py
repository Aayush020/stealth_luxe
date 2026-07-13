"""
data_store.py
-------------
Thin SQLite persistence layer. No ORM — plain sqlite3 with small helper
functions, so the whole data model is easy to read in one file.
"""

import sqlite3
import json
import os
from datetime import date, datetime, timedelta
from contextlib import contextmanager

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "stealth_luxe.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    age INTEGER NOT NULL,
    gender TEXT NOT NULL,
    height_cm REAL NOT NULL DEFAULT 170,
    current_weight REAL NOT NULL,
    target_weight REAL NOT NULL,
    food_type TEXT NOT NULL,
    goal TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    start_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    log_date TEXT NOT NULL,
    weekday_index INTEGER NOT NULL,
    day_number INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    checklist_json TEXT NOT NULL DEFAULT '{}',
    completion_pct REAL NOT NULL DEFAULT 0,
    submitted INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(user_id, log_date)
);

CREATE TABLE IF NOT EXISTS weight_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    log_date TEXT NOT NULL,
    weight REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS water_logs (
    user_id INTEGER NOT NULL REFERENCES users(id),
    log_date TEXT NOT NULL,
    amount_ml INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, log_date)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(username, password_hash):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_user_by_username(username):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def save_profile(user_id, profile):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO profiles (user_id, age, gender, height_cm, current_weight, target_weight,
                                      food_type, goal, duration_days, start_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 age=excluded.age, gender=excluded.gender, height_cm=excluded.height_cm,
                 current_weight=excluded.current_weight, target_weight=excluded.target_weight,
                 food_type=excluded.food_type, goal=excluded.goal,
                 duration_days=excluded.duration_days, start_date=excluded.start_date""",
            (
                user_id, profile["age"], profile["gender"], profile.get("height_cm", 170),
                profile["current_weight"], profile["target_weight"], profile["food_type"],
                profile["goal"], profile["duration_days"], profile["start_date"],
            ),
        )


def get_profile(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Daily logs
# ---------------------------------------------------------------------------

def get_log(user_id, log_date):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_logs WHERE user_id = ? AND log_date = ?", (user_id, log_date)
        ).fetchone()
        return dict(row) if row else None


def upsert_plan(user_id, log_date, weekday_index, day_number, plan):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO daily_logs (user_id, log_date, weekday_index, day_number, plan_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, log_date) DO NOTHING""",
            (user_id, log_date, weekday_index, day_number, json.dumps(plan)),
        )


def update_checklist(user_id, log_date, checklist):
    with get_conn() as conn:
        conn.execute(
            "UPDATE daily_logs SET checklist_json = ? WHERE user_id = ? AND log_date = ?",
            (json.dumps(checklist), user_id, log_date),
        )


def submit_day(user_id, log_date, completion_pct, note=""):
    with get_conn() as conn:
        conn.execute(
            """UPDATE daily_logs SET submitted = 1, completion_pct = ?, submitted_at = ?, note = ?
               WHERE user_id = ? AND log_date = ?""",
            (completion_pct, datetime.utcnow().isoformat(), note.strip()[:280], user_id, log_date),
        )


def get_recent_logs(user_id, limit=7, before_date=None):
    with get_conn() as conn:
        if before_date:
            rows = conn.execute(
                """SELECT * FROM daily_logs WHERE user_id = ? AND log_date < ? AND submitted = 1
                   ORDER BY log_date DESC LIMIT ?""",
                (user_id, before_date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM daily_logs WHERE user_id = ? AND submitted = 1
                   ORDER BY log_date DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        logs = [dict(r) for r in rows]
        logs.reverse()
        for log in logs:
            plan = json.loads(log["plan_json"])
            checklist = json.loads(log["checklist_json"])
            items = []
            for slot, foods in plan["meals"].items():
                for idx, food in enumerate(foods):
                    key = f"meal:{slot}:{idx}"
                    items.append({"category": f"meal:{slot}", "name": food, "completed": bool(checklist.get(key))})
            for idx, ex in enumerate(plan["workout"]["exercises"]):
                key = f"workout:{idx}"
                items.append({"category": plan["category"], "name": ex["name"], "completed": bool(checklist.get(key))})
            log["items"] = items
        return logs


def get_all_submitted_dates(user_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT log_date, completion_pct FROM daily_logs WHERE user_id = ? AND submitted = 1 ORDER BY log_date",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_timeline(user_id, limit=10):
    """Most recent submitted days, newest first, with plan summary + note —
    powers the Progress page's "Recent Days" list."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT log_date, day_number, completion_pct, note, plan_json
               FROM daily_logs WHERE user_id = ? AND submitted = 1
               ORDER BY log_date DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            plan = json.loads(d.pop("plan_json"))
            d["workout_type"] = plan["workout"]["type"]
            out.append(d)
        return out


def export_all_data(user_id):
    """Full data-portability dump: everything the app knows about this user,
    in one JSON-serializable dict. Powers the 'Export My Data' button."""
    user = get_user_by_id(user_id)
    profile = get_profile(user_id)
    with get_conn() as conn:
        logs = [dict(r) for r in conn.execute(
            "SELECT log_date, day_number, weekday_index, plan_json, checklist_json, completion_pct, submitted, submitted_at, note FROM daily_logs WHERE user_id = ? ORDER BY log_date",
            (user_id,),
        ).fetchall()]
        weights = [dict(r) for r in conn.execute(
            "SELECT log_date, weight FROM weight_logs WHERE user_id = ? ORDER BY log_date", (user_id,)
        ).fetchall()]
        water = [dict(r) for r in conn.execute(
            "SELECT log_date, amount_ml FROM water_logs WHERE user_id = ? ORDER BY log_date", (user_id,)
        ).fetchall()]

    for log in logs:
        log["plan"] = json.loads(log.pop("plan_json"))
        log["checklist"] = json.loads(log.pop("checklist_json"))

    return {
        "username": user["username"] if user else None,
        "account_created_at": user["created_at"] if user else None,
        "profile": profile,
        "daily_logs": logs,
        "weight_logs": weights,
        "water_logs": water,
        "exported_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Weight logs
# ---------------------------------------------------------------------------

def add_weight_log(user_id, log_date, weight):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO weight_logs (user_id, log_date, weight) VALUES (?, ?, ?)",
            (user_id, log_date, weight),
        )


def get_weight_logs(user_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT log_date, weight FROM weight_logs WHERE user_id = ? ORDER BY log_date", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Water logs
# ---------------------------------------------------------------------------

def get_water(user_id, log_date):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT amount_ml FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, log_date)
        ).fetchone()
        return row["amount_ml"] if row else 0


def set_water(user_id, log_date, amount_ml):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO water_logs (user_id, log_date, amount_ml) VALUES (?, ?, ?)
               ON CONFLICT(user_id, log_date) DO UPDATE SET amount_ml = excluded.amount_ml""",
            (user_id, log_date, amount_ml),
        )


# ---------------------------------------------------------------------------
# Streak helper
# ---------------------------------------------------------------------------

def current_streak(user_id, today_str):
    dates = {d["log_date"] for d in get_all_submitted_dates(user_id)}
    streak = 0
    cursor = datetime.strptime(today_str, "%Y-%m-%d").date()
    while cursor.isoformat() in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------------------
# Account reset / delete (privacy)
# ---------------------------------------------------------------------------

def delete_all_user_data(user_id):
    """Wipes profile, logs, weight/water history — keeps the login itself
    so the user isn't locked out, but lets them restart onboarding fresh."""
    with get_conn() as conn:
        conn.execute("DELETE FROM daily_logs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM weight_logs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM water_logs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))


def delete_account(user_id):
    """Fully deletes the user and every trace of their data."""
    delete_all_user_data(user_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
