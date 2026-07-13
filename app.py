"""
app.py
------
Flask backend for Stealth Luxe — 4-in-1 configurable body transformation
tracker (custom duration, weight-loss OR muscle-gain, adaptive daily plans).
"""

import os
import json
from datetime import date, datetime, timedelta

from flask import Flask, request, jsonify, session, render_template, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import data_store as store
from adaptive_engine import recommend_next_day, MEAL_SLOTS, compute_adherence

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"

store.init_db()


# ---------------------------------------------------------------------------
# Minimal in-memory rate limiter for auth endpoints.
# Deliberately simple (no Redis / extra dependency) — good enough to blunt
# naive brute-force attempts on a small deployment. Resets on process
# restart; for a multi-instance production deployment, swap this for
# Flask-Limiter backed by Redis.
# ---------------------------------------------------------------------------

_RATE_LIMIT_WINDOW_SECONDS = 300
_RATE_LIMIT_MAX_ATTEMPTS = 10
_rate_limit_hits = {}


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limited(bucket):
    now = datetime.utcnow().timestamp()
    key = f"{bucket}:{_client_ip()}"
    hits = [t for t in _rate_limit_hits.get(key, []) if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    hits.append(now)
    _rate_limit_hits[key] = hits
    return len(hits) > _RATE_LIMIT_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def today_str():
    return date.today().isoformat()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return store.get_user_by_id(uid)


def require_login():
    user = current_user()
    if not user:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return user, None


def build_item_list(plan):
    """Flatten a plan dict into a list of {key, label, meta, category} rows."""
    items = []
    for slot in MEAL_SLOTS:
        for idx, food in enumerate(plan["meals"].get(slot, [])):
            items.append({
                "key": f"meal:{slot}:{idx}",
                "label": food,
                "meta": slot.upper(),
                "category": f"meal:{slot}",
                "kind": "meal",
            })
    for idx, ex in enumerate(plan["workout"]["exercises"]):
        items.append({
            "key": f"workout:{idx}",
            "label": f"{ex['name']} — {ex['sets']} × {ex['reps']}",
            "meta": plan["workout"]["type"],
            "category": plan["category"],
            "kind": "workout",
        })
    return items


def ensure_plan_for_date(user_id, profile, log_date):
    existing = store.get_log(user_id, log_date)
    if existing:
        return existing

    start = datetime.strptime(profile["start_date"], "%Y-%m-%d").date()
    target = datetime.strptime(log_date, "%Y-%m-%d").date()
    day_number = (target - start).days + 1
    weekday_index = (target.weekday() + 1) % 7  # convert Mon=0 -> Sun=0 scheme

    recent_logs = store.get_recent_logs(user_id, limit=7, before_date=log_date)
    plan = recommend_next_day(profile["goal"], profile["food_type"], weekday_index, day_number, recent_logs)

    store.upsert_plan(user_id, log_date, weekday_index, day_number, plan)
    return store.get_log(user_id, log_date)


# ---------------------------------------------------------------------------
# Static page routes
# ---------------------------------------------------------------------------

@app.route("/")
def route_index():
    return render_template("index.html")


@app.route("/onboarding.html")
def route_onboarding():
    return render_template("onboarding.html")


@app.route("/dashboard.html")
def route_dashboard():
    return render_template("dashboard.html")


@app.route("/progress.html")
def route_progress():
    return render_template("progress.html")


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def api_register():
    if rate_limited("register"):
        return jsonify({"error": "Too many attempts. Please wait a few minutes and try again."}), 429
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Enter a username and password to continue."}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters."}), 400
    if store.get_user_by_username(username):
        return jsonify({"error": "That username is already taken."}), 400

    user_id = store.create_user(username, generate_password_hash(password))
    session["user_id"] = user_id
    return jsonify({"ok": True, "has_profile": False})


@app.route("/api/login", methods=["POST"])
def api_login():
    if rate_limited("login"):
        return jsonify({"error": "Too many attempts. Please wait a few minutes and try again."}), 429
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = store.get_user_by_username(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Incorrect username or password."}), 401

    session["user_id"] = user["id"]
    profile = store.get_profile(user["id"])
    return jsonify({"ok": True, "has_profile": profile is not None})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False})
    profile = store.get_profile(user["id"])
    return jsonify({"authenticated": True, "username": user["username"], "profile": profile})


# ---------------------------------------------------------------------------
# Onboarding API
# ---------------------------------------------------------------------------

@app.route("/api/onboarding", methods=["POST"])
def api_onboarding():
    user, err = require_login()
    if err:
        return err
    data = request.get_json(force=True)

    try:
        age = int(data["age"])
        gender = data["gender"]
        height_cm = float(data.get("height_cm", 170))
        current_weight = float(data["current_weight"])
        target_weight = float(data["target_weight"])
        food_type = data["food_type"]
        goal = data.get("goal") or ("weight_loss" if target_weight < current_weight else "muscle_gain")
        duration_days = int(data["duration_days"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Missing or invalid onboarding fields."}), 400

    if food_type not in ("veg", "nonveg"):
        return jsonify({"error": "Invalid food type."}), 400
    if goal not in ("weight_loss", "muscle_gain"):
        return jsonify({"error": "Invalid goal."}), 400
    if duration_days < 7 or duration_days > 365:
        return jsonify({"error": "Program length must be between 7 and 365 days."}), 400
    if age < 14 or age > 90:
        return jsonify({"error": "Enter a valid age."}), 400
    if height_cm < 100 or height_cm > 250:
        return jsonify({"error": "Enter a valid height in cm."}), 400
    if current_weight <= 0 or target_weight <= 0:
        return jsonify({"error": "Enter valid weights."}), 400

    profile = {
        "age": age, "gender": gender, "height_cm": height_cm, "current_weight": current_weight,
        "target_weight": target_weight, "food_type": food_type, "goal": goal,
        "duration_days": duration_days, "start_date": today_str(),
    }
    store.save_profile(user["id"], profile)
    store.add_weight_log(user["id"], today_str(), current_weight)

    return jsonify({"ok": True, "profile": profile})


# ---------------------------------------------------------------------------
# Daily plan / checklist API
# ---------------------------------------------------------------------------

@app.route("/api/today")
def api_today():
    user, err = require_login()
    if err:
        return err
    profile = store.get_profile(user["id"])
    if not profile:
        return jsonify({"error": "No profile yet."}), 400

    log_date = request.args.get("date") or today_str()
    log = ensure_plan_for_date(user["id"], profile, log_date)
    plan = json.loads(log["plan_json"])
    checklist = json.loads(log["checklist_json"])
    items = build_item_list(plan)

    start = datetime.strptime(profile["start_date"], "%Y-%m-%d").date()
    target = datetime.strptime(log_date, "%Y-%m-%d").date()
    day_number = (target - start).days + 1

    done_count = sum(1 for it in items if checklist.get(it["key"]))
    pct = round((done_count / len(items)) * 100) if items else 0

    notes = plan.get("notes") or []
    adaptive_note = " ".join(notes[:2]) if notes else None

    return jsonify({
        "date": log_date,
        "day_number": day_number,
        "duration_days": profile["duration_days"],
        "weekday_index": log["weekday_index"],
        "plan": plan,
        "items": items,
        "checklist": checklist,
        "completion_pct": pct,
        "submitted": bool(log["submitted"]),
        "streak": store.current_streak(user["id"], today_str()),
        "goal": profile["goal"],
        "adaptive_note": adaptive_note,
        "days_remaining": max(0, profile["duration_days"] - day_number),
        "note": log["note"] or "",
    })


@app.route("/api/checklist", methods=["POST"])
def api_checklist():
    user, err = require_login()
    if err:
        return err
    data = request.get_json(force=True)
    log_date = data.get("date") or today_str()
    item_key = data.get("item_key")
    value = bool(data.get("value"))

    log = store.get_log(user["id"], log_date)
    if not log:
        return jsonify({"error": "No plan generated for that date yet."}), 400
    if log["submitted"]:
        return jsonify({"error": "That day is already submitted."}), 400

    checklist = json.loads(log["checklist_json"])
    checklist[item_key] = value
    store.update_checklist(user["id"], log_date, checklist)

    return jsonify({"ok": True})


@app.route("/api/submit-day", methods=["POST"])
def api_submit_day():
    """
    Submits the day REGARDLESS of completion percentage — missed items are
    simply logged as not completed. This log then feeds the adaptive engine
    for tomorrow's plan.
    """
    user, err = require_login()
    if err:
        return err
    data = request.get_json(force=True)
    log_date = data.get("date") or today_str()
    note = (data.get("note") or "").strip()[:280]

    log = store.get_log(user["id"], log_date)
    if not log:
        return jsonify({"error": "No plan found for that date."}), 400
    if log["submitted"]:
        return jsonify({"error": "Already submitted."}), 400

    plan = json.loads(log["plan_json"])
    checklist = json.loads(log["checklist_json"])
    items = build_item_list(plan)
    done_count = sum(1 for it in items if checklist.get(it["key"]))
    pct = round((done_count / len(items)) * 100) if items else 0

    store.submit_day(user["id"], log_date, pct, note)

    return jsonify({
        "ok": True,
        "completion_pct": pct,
        "streak": store.current_streak(user["id"], today_str()),
    })


# ---------------------------------------------------------------------------
# Water API
# ---------------------------------------------------------------------------

WATER_TARGET_ML = 3500
WATER_STEP_ML = 250


@app.route("/api/water", methods=["GET", "POST"])
def api_water():
    user, err = require_login()
    if err:
        return err
    log_date = today_str()

    if request.method == "GET":
        return jsonify({"amount_ml": store.get_water(user["id"], log_date), "target_ml": WATER_TARGET_ML})

    data = request.get_json(force=True)
    delta = int(data.get("delta", 0))
    current = store.get_water(user["id"], log_date)
    next_amount = max(0, min(WATER_TARGET_ML, current + delta))
    store.set_water(user["id"], log_date, next_amount)
    return jsonify({"amount_ml": next_amount, "target_ml": WATER_TARGET_ML})


# ---------------------------------------------------------------------------
# Progress API
# ---------------------------------------------------------------------------

BADGE_DEFS = [
    {"id": "week1", "name": "Week 1 Anchor", "icon": "◆", "threshold": 7},
    {"id": "week2", "name": "Fortnight Forged", "icon": "◆◆", "threshold": 14},
    {"id": "month1", "name": "Month 1 Iron", "icon": "▲", "threshold": 30},
    {"id": "month2", "name": "Month 2 Titanium", "icon": "▲▲", "threshold": 60},
    {"id": "month3", "name": "Month 3 Obsidian", "icon": "●", "threshold": 90},
]


@app.route("/api/weight", methods=["GET", "POST"])
def api_weight():
    user, err = require_login()
    if err:
        return err

    if request.method == "GET":
        return jsonify({"logs": store.get_weight_logs(user["id"])})

    data = request.get_json(force=True)
    try:
        weight = float(data.get("weight"))
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a valid weight."}), 400
    if weight <= 0:
        return jsonify({"error": "Enter a valid weight."}), 400

    logs = store.get_weight_logs(user["id"])
    if logs:
        last = datetime.strptime(logs[-1]["log_date"], "%Y-%m-%d").date()
        days_since = (date.today() - last).days
        if days_since < 7:
            return jsonify({"error": f"Weekly check-in opens in {7 - days_since} day(s)."}), 400

    store.add_weight_log(user["id"], today_str(), weight)
    return jsonify({"ok": True, "logs": store.get_weight_logs(user["id"])})


@app.route("/api/progress")
def api_progress():
    user, err = require_login()
    if err:
        return err
    profile = store.get_profile(user["id"])
    if not profile:
        return jsonify({"error": "No profile yet."}), 400

    submitted = store.get_all_submitted_dates(user["id"])
    days_secured = len(submitted)
    streak = store.current_streak(user["id"], today_str())

    badges = []
    for b in BADGE_DEFS:
        badges.append({**b, "unlocked": days_secured >= b["threshold"]})
    duration_badge = {
        "id": "complete", "name": f"{profile['duration_days']}-Day Transformation Complete",
        "icon": "✦", "threshold": profile["duration_days"],
        "unlocked": days_secured >= profile["duration_days"],
    }
    badges.append(duration_badge)

    start = datetime.strptime(profile["start_date"], "%Y-%m-%d").date()
    heatmap = []
    submitted_map = {d["log_date"]: d["completion_pct"] for d in submitted}
    for i in range(profile["duration_days"]):
        d = start + timedelta(days=i)
        key = d.isoformat()
        heatmap.append({
            "date": key,
            "completion_pct": submitted_map.get(key, 0),
            "filled": key in submitted_map,
            "is_today": key == today_str(),
        })

    day_number = (date.today() - start).days + 1
    finish_date = start + timedelta(days=profile["duration_days"] - 1)

    weight_logs = store.get_weight_logs(user["id"])
    latest_weight = weight_logs[-1]["weight"] if weight_logs else profile["current_weight"]

    height_m = (profile.get("height_cm") or 170) / 100
    bmi = round(latest_weight / (height_m ** 2), 1) if height_m > 0 else None
    if bmi is None:
        bmi_category = None
    elif bmi < 18.5:
        bmi_category = "Underweight"
    elif bmi < 25:
        bmi_category = "Normal"
    elif bmi < 30:
        bmi_category = "Overweight"
    else:
        bmi_category = "Obese"

    recent_logs = store.get_recent_logs(user["id"], limit=14)
    adherence_breakdown = compute_adherence(recent_logs, lookback=14)
    adherence_pct = {
        k: (round(v * 100) if v is not None else None) for k, v in adherence_breakdown.items()
    }

    timeline = store.get_timeline(user["id"], limit=10)

    return jsonify({
        "profile": profile,
        "days_secured": days_secured,
        "streak": streak,
        "day_number": max(1, min(day_number, profile["duration_days"])),
        "duration_days": profile["duration_days"],
        "finish_date": finish_date.isoformat(),
        "badges": badges,
        "heatmap": heatmap,
        "weight_logs": weight_logs,
        "latest_weight": latest_weight,
        "bmi": bmi,
        "bmi_category": bmi_category,
        "adherence_breakdown": adherence_pct,
        "timeline": timeline,
    })


@app.route("/api/export")
def api_export():
    """Data-portability endpoint — downloads everything the app knows about
    the current user as a single JSON file."""
    user, err = require_login()
    if err:
        return err
    data = store.export_all_data(user["id"])
    payload = json.dumps(data, indent=2)
    filename = f"stealth-luxe-export-{user['username']}-{today_str()}.json"
    return app.response_class(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/account/reset", methods=["POST"])
def api_account_reset():
    """Wipes profile & program history so the user can start a fresh
    protocol, without losing their login."""
    user, err = require_login()
    if err:
        return err
    store.delete_all_user_data(user["id"])
    return jsonify({"ok": True})


@app.route("/api/account/delete", methods=["POST"])
def api_account_delete():
    """Permanently deletes the account and every trace of its data."""
    user, err = require_login()
    if err:
        return err
    store.delete_account(user["id"])
    session.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
