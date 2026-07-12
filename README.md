# Stealth Luxe — Adaptive Body Transformation Tracker

A configurable, self-adapting body transformation tracker. Pick **your own
program length**, choose **weight loss or muscle gain**, log what you
actually did each day (even if it's incomplete), and the plan for tomorrow
adjusts based on your real adherence — not a rigid 7-day loop that repeats
forever.

Full-stack: Flask backend + SQLite storage + a vanilla HTML/CSS/JS frontend
("Stealth Luxe" dark-luxury theme), ready to deploy on Render, Railway,
Fly.io, or any host that runs a Python web service.

---

## What makes the "adaptive" part honest

This app **does not use a trained machine-learning model** — no neural
network, no scikit-learn classifier, nothing "learned" from a dataset.
What it actually does, in `adaptive_engine.py`, is a transparent **rules +
statistics engine**:

1. It looks at your last 7–14 *submitted* days.
2. For each category (a meal slot like breakfast, or a workout group like
   Legs), it computes `completed / shown` — your adherence rate.
3. If adherence is low (< 50%), tomorrow serves an **easier** variant of
   that category. If it's high (> 85%), tomorrow serves a **harder /
   progressive** variant. Otherwise it stays at a medium tier.
4. Within whichever tier gets picked, it rotates away from whatever you
   were shown in the last 2–3 days, so you don't get the same Tuesday
   every Tuesday.

This is deliberately explainable — you can read every line of
`adaptive_engine.py` and know exactly why tomorrow's plan looks the way it
does. The dashboard also surfaces a short plain-language note (e.g. *"Legs
adherence was 40% recently, so today steps down to an easier variant"*)
so the logic isn't a black box to the user either.

If you want to upgrade this to *real* ML later (e.g. a model trained on
adherence patterns across many users to predict which specific variant a
given user is most likely to complete), the seam is
`adaptive_engine.recommend_next_day()` — it currently just calls the rules
engine, but `app.py` only ever calls this one function, so swapping the
implementation behind it doesn't require touching the rest of the app.

---

## Feature list

- **Custom program length** — 30/60/90/120-day presets or any custom
  number of days from 7–365, set once at onboarding.
- **Dual goal mode** — Weight Loss or Muscle Gain, auto-suggested from
  your current vs. target weight, overridable with one tap.
- **Adaptive daily plans** — meals and workouts generated per-day from
  category-tagged pools (easy/medium/hard), chosen using your real
  adherence history (see above).
- **Submit-anytime logging** — the "Submit Day" button is never hard-locked
  behind 100% completion. Miss half your meals? Submit anyway — the
  tracker logs exactly what happened and adapts tomorrow accordingly.
- **Fluid water tracker** — tap-to-log 250ml increments toward a 3.5L
  daily target, with an animated fill.
- **Streak + completion ring** — live daily completion percentage and a
  consecutive-day streak counter.
- **Weekly weight thermometer** — log your weight (gated to once every 7
  days) and see a visual distance-to-target readout.
- **BMI** — computed from height + your latest logged weight.
- **Consistency badges** — unlock tiers at 7 / 14 / 30 / 60 / 90 days and
  at your own custom program length.
- **Completion heatmap** — a full-program calendar view, shaded by that
  day's completion percentage.
- **Adaptive Insights panel** — a transparent, per-category adherence
  breakdown so you can see exactly what's driving tomorrow's plan.
- **Account controls** — restart your protocol, export a full JSON copy of
  your data, or fully delete your account, all from the Progress page.
- **Day journal notes** — an optional free-text note attached to each
  submitted day (e.g. "traveled, low on time"), surfaced in a Recent Days
  timeline so you can look back at what actually happened, not just a
  completion percentage.
- **Weight trend chart** — a lightweight inline SVG line chart of your
  logged weights against your target, alongside the thermometer.
- **Basic login rate-limiting** — a simple in-memory limiter (10 attempts
  per 5 minutes per IP) on `/api/login` and `/api/register` to blunt naive
  brute-force attempts. Documented in "Known limitations" below since it
  resets on process restart and isn't a substitute for a proper
  Redis-backed limiter at scale.

---

## Project structure

```
stealth-luxe-pro/
├── app.py                 # Flask routes + API endpoints
├── adaptive_engine.py      # Rule-based adaptive plan generator (see above)
├── data_store.py           # SQLite persistence layer (plain sqlite3, no ORM)
├── requirements.txt
├── Procfile                 # for Render/Heroku-style process hosts
├── .env.example              # copy to .env and fill in
├── .gitignore
├── static/
│   ├── style.css           # "Stealth Luxe" dark-luxury design system
│   └── app.js               # frontend API client + shared UI helpers
└── templates/
    ├── index.html           # login / register
    ├── onboarding.html       # goal, food type, duration, body stats
    ├── dashboard.html        # today's adaptive plan, checklist, submit
    └── progress.html         # stats, thermometer, insights, badges, heatmap
```

---

## Data model (SQLite)

| Table | Purpose |
|---|---|
| `users` | username + hashed password |
| `profiles` | age, gender, height, weights, food type, goal, duration, start date |
| `daily_logs` | one row per calendar date: the generated plan, checklist state, completion %, submitted flag |
| `weight_logs` | weekly weight check-ins |
| `water_logs` | daily water intake in ml |

Passwords are hashed with Werkzeug's `generate_password_hash` /
`check_password_hash` — plaintext passwords are never stored.

---

## Running it locally

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# open .env and set a real SECRET_KEY (see the comment in that file)

# 4. Run it
python app.py
```

The app will be running at `http://localhost:5000`. The SQLite database
(`stealth_luxe.db`) is created automatically on first run — no manual
migration step needed.

---

## Deploying (Render, as an example)

1. Push this folder to a GitHub repo.
2. On Render: **New → Web Service**, connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT` (already in the
   `Procfile`, Render picks it up automatically if you use "Native
   Environment" with a Procfile detected).
5. Add environment variables under **Environment**: at minimum `SECRET_KEY`
   (generate one, don't reuse the example value) and `FLASK_ENV=production`.
6. **Important — persistent storage:** SQLite writes to a file on disk.
   Render's default filesystem is ephemeral (wiped on redeploy). Add a
   **Render Disk** (Render dashboard → your service → Disks) mounted at,
   say, `/data`, and set `DATABASE_PATH=/data/stealth_luxe.db` in your
   environment variables so your users' data survives deploys. The same
   caution applies on Railway/Fly.io — check whether your plan includes a
   persistent volume.

The same steps work near-identically on Railway or Fly.io: install
dependencies, run `gunicorn app:app`, set `SECRET_KEY`, and mount a
persistent volume for the database file.

---

## API reference (all JSON, session-cookie authenticated)

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/register` | Create account, starts session |
| POST | `/api/login` | Log in, starts session |
| POST | `/api/logout` | Clear session |
| GET | `/api/me` | Current auth state + profile |
| POST | `/api/onboarding` | Save profile (goal, duration, body stats) |
| GET | `/api/today` | Today's adaptive plan + checklist + streak |
| POST | `/api/checklist` | Toggle one item's completion |
| POST | `/api/submit-day` | Submit the day at whatever completion % it's at |
| GET/POST | `/api/water` | Read / adjust today's water intake |
| GET/POST | `/api/weight` | Read weight history / log a new weekly weight |
| GET | `/api/progress` | Stats, BMI, badges, heatmap, adherence breakdown, Recent Days timeline |
| GET | `/api/export` | Downloads a full JSON export of the account's data |
| POST | `/api/account/reset` | Wipe profile & history, keep login |
| POST | `/api/account/delete` | Permanently delete account + all data |

---

## Important disclaimer

The meal and workout content in `adaptive_engine.py` is illustrative
sample content for a fitness-tracking demo — it is **not personalized
medical, dietary, or training advice** and hasn't been reviewed by a
doctor, dietitian, or certified trainer. Anyone with an existing health
condition, injury, eating disorder history, or specific medical dietary
need should talk to a qualified professional before following any fixed
calorie or exercise program, including this one.

---

## Known limitations / good next steps

- No password-reset flow (forgot-password email) — out of scope for a
  single-file SQLite demo, but would be the first thing to add before any
  real public users.
- Login/register now have a basic in-memory rate limiter (10 attempts /
  5 min / IP), but it resets on process restart and doesn't coordinate
  across multiple server instances — swap for Flask-Limiter + Redis before
  a larger or multi-instance deployment.
- The adaptive engine's meal/workout pools are intentionally compact
  (6 variants per slot) to stay readable — expanding these pools (and
  adding true macro/calorie tracking rather than fixed text descriptions)
  would be the natural next step for a more serious nutrition feature.
#   s t e a l t h _ l u x e  
 