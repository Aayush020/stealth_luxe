"""
adaptive_engine.py
------------------
Rule-based adaptive planning engine for Stealth Luxe.

IMPORTANT — what this actually is:
This is a transparent, statistics-driven RULES ENGINE. It is NOT a trained
machine-learning model (no neural network, no gradient descent, nothing
"learned" from a dataset). It adapts day-to-day plans using simple,
explainable logic:

  1. Look at the user's last N logged days.
  2. For each category (a meal slot like "breakfast", or a workout group
     like "legs"), compute an adherence rate = completed / shown.
  3. If adherence is low (<50%)  -> serve an "easy" variant next time.
     If adherence is high (>85%) -> serve a "hard" / progressive variant.
     Otherwise                   -> serve a "medium" variant.
  4. Within whichever difficulty tier is chosen, rotate away from
     whatever was shown in the last 2-3 days so the plan doesn't repeat
     on a rigid 7-day loop.

This keeps the system fully explainable and debuggable, which matters more
for a real health-adjacent product than bolting on a black-box model that
nobody (including the user) can audit. If real ML is wanted later
(e.g. a scikit-learn classifier trained on adherence history across many
users), this module is the seam where it would plug in — see
`recommend_next_day()` at the bottom.
"""

import random

DIFFICULTIES = ["easy", "medium", "hard"]

# ---------------------------------------------------------------------------
# MEAL POOLS — tagged by goal, food type, meal slot, and difficulty tier.
# "difficulty" for meals = prep effort / calorie-density tier, not spice level.
# ---------------------------------------------------------------------------

MEAL_POOL = {
    "weight_loss": {
        "veg": {
            "breakfast": [
                {"name": "Moong dal chilla (2 pcs) + black coffee", "difficulty": "easy"},
                {"name": "Greek yogurt (150g) with chia seeds", "difficulty": "easy"},
                {"name": "Vegetable oats bowl + boiled sprouts", "difficulty": "medium"},
                {"name": "Besan cheela (2) + low-fat curd", "difficulty": "medium"},
                {"name": "Sprouts poha + skimmed milk", "difficulty": "medium"},
                {"name": "Idli (3) with sambar, no chutney", "difficulty": "hard"},
            ],
            "lunch": [
                {"name": "Grilled paneer salad bowl + buttermilk", "difficulty": "easy"},
                {"name": "Chickpea salad + millet roti (1)", "difficulty": "easy"},
                {"name": "Rajma (150g) + brown rice (3/4 cup)", "difficulty": "medium"},
                {"name": "Mixed dal + millet roti (2) + sabzi", "difficulty": "medium"},
                {"name": "Soya chunk curry + brown rice", "difficulty": "hard"},
                {"name": "Chole + brown rice + salad", "difficulty": "hard"},
            ],
            "snack": [
                {"name": "Green tea only", "difficulty": "easy"},
                {"name": "Cucumber + hummus (small)", "difficulty": "easy"},
                {"name": "Roasted chana (30g)", "difficulty": "medium"},
                {"name": "Roasted makhana (20g)", "difficulty": "medium"},
                {"name": "Fruit bowl (apple + papaya)", "difficulty": "hard"},
                {"name": "Handful almonds (10)", "difficulty": "hard"},
            ],
            "dinner": [
                {"name": "Clear vegetable soup only", "difficulty": "easy"},
                {"name": "Sauteed spinach + tomato soup", "difficulty": "easy"},
                {"name": "Tofu & vegetable stir-fry", "difficulty": "medium"},
                {"name": "Paneer bhurji (light oil) + beans", "difficulty": "medium"},
                {"name": "Grilled paneer skewers + greens", "difficulty": "hard"},
                {"name": "Tofu tikka masala (light) + salad", "difficulty": "hard"},
            ],
        },
        "nonveg": {
            "breakfast": [
                {"name": "Black coffee + 2 boiled egg whites", "difficulty": "easy"},
                {"name": "3 egg-white omelette + veggies", "difficulty": "easy"},
                {"name": "Boiled eggs (2) + multigrain toast", "difficulty": "medium"},
                {"name": "Egg bhurji (2 eggs, light oil)", "difficulty": "medium"},
                {"name": "Protein oats with egg whites", "difficulty": "hard"},
                {"name": "Chicken sausage + egg whites", "difficulty": "hard"},
            ],
            "lunch": [
                {"name": "Chicken salad bowl + buttermilk", "difficulty": "easy"},
                {"name": "Grilled fish (100g) + salad", "difficulty": "easy"},
                {"name": "Grilled chicken breast (150g) + quinoa", "difficulty": "medium"},
                {"name": "Chicken tikka (150g) + brown rice", "difficulty": "medium"},
                {"name": "Egg curry (2 eggs) + brown rice", "difficulty": "hard"},
                {"name": "Tandoori chicken (150g) + rice", "difficulty": "hard"},
            ],
            "snack": [
                {"name": "Green tea only", "difficulty": "easy"},
                {"name": "Greek yogurt (150g)", "difficulty": "easy"},
                {"name": "Roasted chana (30g)", "difficulty": "medium"},
                {"name": "Roasted makhana (20g)", "difficulty": "medium"},
                {"name": "Fruit bowl", "difficulty": "hard"},
                {"name": "Handful almonds (10)", "difficulty": "hard"},
            ],
            "dinner": [
                {"name": "Clear soup only", "difficulty": "easy"},
                {"name": "Steamed fish (120g) + greens", "difficulty": "easy"},
                {"name": "Grilled prawns + sauteed spinach", "difficulty": "medium"},
                {"name": "Chicken stir-fry with vegetables", "difficulty": "medium"},
                {"name": "Baked salmon / rohu + vegetables", "difficulty": "hard"},
                {"name": "Grilled chicken skewers + soup", "difficulty": "hard"},
            ],
        },
    },
    "muscle_gain": {
        "veg": {
            "breakfast": [
                {"name": "Peanut butter banana smoothie", "difficulty": "easy"},
                {"name": "Vegetable poha with peanuts + milk", "difficulty": "easy"},
                {"name": "Besan cheela (3) + paneer stuffing + milk", "difficulty": "medium"},
                {"name": "Sprouts & paneer bhurji + dates", "difficulty": "medium"},
                {"name": "Paneer paratha (2) + curd + milk", "difficulty": "hard"},
                {"name": "Stuffed aloo-paneer paratha + curd + milk", "difficulty": "hard"},
            ],
            "lunch": [
                {"name": "Chana masala (200g) + rice + salad", "difficulty": "easy"},
                {"name": "Mixed dal (200g) + rice + ghee", "difficulty": "easy"},
                {"name": "Rajma-chawal (large) + curd + ghee", "difficulty": "medium"},
                {"name": "Chole (200g) + rice + curd", "difficulty": "medium"},
                {"name": "Dal makhani (200g) + rice + ghee", "difficulty": "hard"},
                {"name": "Mixed vegetable dal + rice + curd (large)", "difficulty": "hard"},
            ],
            "snack": [
                {"name": "Banana + handful mixed nuts", "difficulty": "easy"},
                {"name": "Peanut butter toast", "difficulty": "easy"},
                {"name": "Protein shake (plant) + oats", "difficulty": "medium"},
                {"name": "Roasted makhana with ghee", "difficulty": "medium"},
                {"name": "Peanut chikki + banana", "difficulty": "hard"},
                {"name": "Trail mix + protein shake", "difficulty": "hard"},
            ],
            "dinner": [
                {"name": "Soya chunk curry + roti (2)", "difficulty": "easy"},
                {"name": "Tofu stir-fry (extra oil) + roti (2)", "difficulty": "easy"},
                {"name": "Palak paneer + roti (3) + dal", "difficulty": "medium"},
                {"name": "Tofu tikka masala + roti (3) + dal", "difficulty": "medium"},
                {"name": "Paneer butter masala + roti (3) + dal", "difficulty": "hard"},
                {"name": "Paneer bhurji (extra ghee) + roti (3)", "difficulty": "hard"},
            ],
        },
        "nonveg": {
            "breakfast": [
                {"name": "3 whole eggs + toast + milk", "difficulty": "easy"},
                {"name": "Egg paratha (1) + curd + milk", "difficulty": "easy"},
                {"name": "Egg bhurji (3 eggs) + paratha + milk", "difficulty": "medium"},
                {"name": "Omelette (3 eggs) + cheese toast + milk", "difficulty": "medium"},
                {"name": "4 whole eggs + toast + milk + dates", "difficulty": "hard"},
                {"name": "Peanut butter smoothie + eggs (2) + almonds", "difficulty": "hard"},
            ],
            "lunch": [
                {"name": "Chicken curry (200g) + rice + salad", "difficulty": "easy"},
                {"name": "Fish curry (200g) + rice + salad", "difficulty": "easy"},
                {"name": "Chicken tikka (200g) + rice + ghee", "difficulty": "medium"},
                {"name": "Chicken biryani (portion) + raita", "difficulty": "medium"},
                {"name": "Mutton / chicken curry (200g) + rice + curd", "difficulty": "hard"},
                {"name": "Tandoori chicken (200g) + rice + ghee", "difficulty": "hard"},
            ],
            "snack": [
                {"name": "Banana + boiled eggs (2)", "difficulty": "easy"},
                {"name": "Protein shake + banana", "difficulty": "easy"},
                {"name": "Peanut butter toast + eggs", "difficulty": "medium"},
                {"name": "Trail mix + protein shake", "difficulty": "medium"},
                {"name": "Peanut chikki + protein shake", "difficulty": "hard"},
                {"name": "Boiled eggs (2) + dates + nuts", "difficulty": "hard"},
            ],
            "dinner": [
                {"name": "Grilled chicken (200g) + roti (2)", "difficulty": "easy"},
                {"name": "Grilled fish (200g) + roti (2)", "difficulty": "easy"},
                {"name": "Fish curry (200g) + roti (3) + dal", "difficulty": "medium"},
                {"name": "Chicken stir-fry (extra oil) + roti (3)", "difficulty": "medium"},
                {"name": "Butter chicken (portion) + roti (3) + dal", "difficulty": "hard"},
                {"name": "Grilled mutton / paneer + roti (3) + dal", "difficulty": "hard"},
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# WORKOUT POOLS — tagged by goal, category, difficulty.
# ---------------------------------------------------------------------------

WORKOUT_POOL = {
    "weight_loss": {
        "rest": [
            {"name": "Brisk incline walk", "sets": 1, "reps": "20 min", "difficulty": "easy"},
            {"name": "Cat-cow mobility flow", "sets": 2, "reps": "10 reps", "difficulty": "easy"},
            {"name": "Plank hold", "sets": 3, "reps": "40 sec", "difficulty": "medium"},
            {"name": "Dead bug", "sets": 3, "reps": "15 reps", "difficulty": "medium"},
            {"name": "Foam roll + deep breathing", "sets": 1, "reps": "15 min", "difficulty": "hard"},
        ],
        "push": [
            {"name": "Wall push-ups", "sets": 3, "reps": "10 reps", "difficulty": "easy"},
            {"name": "Knee push-ups", "sets": 3, "reps": "12 reps", "difficulty": "easy"},
            {"name": "Push-ups", "sets": 4, "reps": "12 reps", "difficulty": "medium"},
            {"name": "Dumbbell shoulder press", "sets": 4, "reps": "12 reps", "difficulty": "medium"},
            {"name": "Decline push-ups", "sets": 4, "reps": "15 reps", "difficulty": "hard"},
            {"name": "Tricep dips", "sets": 4, "reps": "15 reps", "difficulty": "hard"},
        ],
        "pull": [
            {"name": "Band rows", "sets": 3, "reps": "12 reps", "difficulty": "easy"},
            {"name": "Bent-over rows (light)", "sets": 3, "reps": "12 reps", "difficulty": "easy"},
            {"name": "Bent-over rows", "sets": 4, "reps": "12 reps", "difficulty": "medium"},
            {"name": "Lat pulldown", "sets": 4, "reps": "12 reps", "difficulty": "medium"},
            {"name": "Assisted pull-ups", "sets": 4, "reps": "8 reps", "difficulty": "hard"},
            {"name": "Face pulls", "sets": 4, "reps": "15 reps", "difficulty": "hard"},
        ],
        "legs": [
            {"name": "Bodyweight squats", "sets": 3, "reps": "15 reps", "difficulty": "easy"},
            {"name": "Glute bridges", "sets": 3, "reps": "20 reps", "difficulty": "easy"},
            {"name": "Goblet squats", "sets": 4, "reps": "15 reps", "difficulty": "medium"},
            {"name": "Walking lunges", "sets": 3, "reps": "16 reps", "difficulty": "medium"},
            {"name": "Romanian deadlifts", "sets": 4, "reps": "12 reps", "difficulty": "hard"},
            {"name": "Jump squats", "sets": 4, "reps": "15 reps", "difficulty": "hard"},
        ],
        "core": [
            {"name": "Dead bug", "sets": 3, "reps": "15 reps", "difficulty": "easy"},
            {"name": "Bicycle crunches", "sets": 3, "reps": "20 reps", "difficulty": "easy"},
            {"name": "Plank hold", "sets": 3, "reps": "45 sec", "difficulty": "medium"},
            {"name": "Russian twists", "sets": 3, "reps": "20 reps", "difficulty": "medium"},
            {"name": "Hanging knee raises", "sets": 3, "reps": "15 reps", "difficulty": "hard"},
            {"name": "Side plank", "sets": 3, "reps": "30 sec / side", "difficulty": "hard"},
        ],
        "cardio": [
            {"name": "Easy 15-min walk", "sets": 1, "reps": "15 min", "difficulty": "easy"},
            {"name": "Steady jog", "sets": 1, "reps": "20 min", "difficulty": "easy"},
            {"name": "Cycling (moderate)", "sets": 1, "reps": "30 min", "difficulty": "medium"},
            {"name": "Jumping jacks intervals", "sets": 6, "reps": "40 sec", "difficulty": "medium"},
            {"name": "Sprint intervals", "sets": 8, "reps": "30 sec on / 30 off", "difficulty": "hard"},
            {"name": "High-knee sprints", "sets": 8, "reps": "30 sec", "difficulty": "hard"},
        ],
    },
    "muscle_gain": {
        "rest": [
            {"name": "Light stretching flow", "sets": 1, "reps": "15 min", "difficulty": "easy"},
            {"name": "Band pull-aparts", "sets": 3, "reps": "20 reps", "difficulty": "easy"},
            {"name": "Foam roll back & legs", "sets": 1, "reps": "10 min", "difficulty": "medium"},
            {"name": "Ankle & hip mobility drill", "sets": 2, "reps": "8 reps", "difficulty": "medium"},
            {"name": "Active recovery walk + stretch", "sets": 1, "reps": "20 min", "difficulty": "hard"},
        ],
        "push": [
            {"name": "Dumbbell bench press", "sets": 4, "reps": "8 reps", "difficulty": "easy"},
            {"name": "Incline dumbbell press", "sets": 4, "reps": "10 reps", "difficulty": "easy"},
            {"name": "Barbell bench press", "sets": 5, "reps": "6-8 reps", "difficulty": "medium"},
            {"name": "Overhead dumbbell press", "sets": 4, "reps": "8-10 reps", "difficulty": "medium"},
            {"name": "Weighted dips", "sets": 4, "reps": "10 reps", "difficulty": "hard"},
            {"name": "Push press", "sets": 5, "reps": "5 reps", "difficulty": "hard"},
        ],
        "pull": [
            {"name": "Lat pulldown", "sets": 4, "reps": "10 reps", "difficulty": "easy"},
            {"name": "Barbell rows (moderate)", "sets": 4, "reps": "10 reps", "difficulty": "easy"},
            {"name": "Barbell rows", "sets": 4, "reps": "10 reps", "difficulty": "medium"},
            {"name": "Pull-ups", "sets": 4, "reps": "8 reps", "difficulty": "medium"},
            {"name": "Weighted pull-ups", "sets": 4, "reps": "8 reps", "difficulty": "hard"},
            {"name": "Deadlift", "sets": 5, "reps": "5 reps", "difficulty": "hard"},
        ],
        "legs": [
            {"name": "Leg press", "sets": 4, "reps": "12 reps", "difficulty": "easy"},
            {"name": "Goblet squats (heavy)", "sets": 4, "reps": "12 reps", "difficulty": "easy"},
            {"name": "Back squat", "sets": 5, "reps": "6-8 reps", "difficulty": "medium"},
            {"name": "Romanian deadlift", "sets": 4, "reps": "10 reps", "difficulty": "medium"},
            {"name": "Front squat", "sets": 4, "reps": "8 reps", "difficulty": "hard"},
            {"name": "Bulgarian split squat", "sets": 3, "reps": "10 reps / leg", "difficulty": "hard"},
        ],
        "core": [
            {"name": "Weighted plank", "sets": 3, "reps": "40 sec", "difficulty": "easy"},
            {"name": "Cable crunches", "sets": 3, "reps": "15 reps", "difficulty": "easy"},
            {"name": "Hanging leg raises", "sets": 4, "reps": "12 reps", "difficulty": "medium"},
            {"name": "Cable woodchoppers", "sets": 3, "reps": "15 reps / side", "difficulty": "medium"},
            {"name": "Weighted hanging leg raises", "sets": 4, "reps": "12 reps", "difficulty": "hard"},
            {"name": "Ab wheel rollout", "sets": 3, "reps": "10 reps", "difficulty": "hard"},
        ],
        "cardio": [
            {"name": "Incline walk", "sets": 1, "reps": "15 min", "difficulty": "easy"},
            {"name": "Light cycling", "sets": 1, "reps": "15 min", "difficulty": "easy"},
            {"name": "Sled push / prowler", "sets": 4, "reps": "20 m", "difficulty": "medium"},
            {"name": "Farmer carry", "sets": 3, "reps": "40 m", "difficulty": "medium"},
            {"name": "Weighted sled push", "sets": 5, "reps": "25 m", "difficulty": "hard"},
            {"name": "Battle ropes", "sets": 5, "reps": "30 sec", "difficulty": "hard"},
        ],
    },
}

# Weekly skeleton: which workout category applies on which weekday (0=Sun).
# This just decides the *category* (push/pull/legs/etc) — the *specific
# exercise* within that category is chosen adaptively every time.
WEEKDAY_CATEGORY = {
    "weight_loss": ["rest", "push", "pull", "legs", "core", "cardio", "legs"],
    "muscle_gain": ["rest", "push", "pull", "legs", "core", "push", "legs"],
}

MEAL_SLOTS = ["breakfast", "lunch", "snack", "dinner"]


def _pick_variant(pool, adherence, seed, recent_names):
    """Pick one item from `pool` based on adherence rate, avoiding repeats.
    Returns (item, tier_used)."""
    if adherence is None:
        tier = "medium"
    elif adherence < 0.5:
        tier = "easy"
    elif adherence > 0.85:
        tier = "hard"
    else:
        tier = "medium"

    candidates = [it for it in pool if it["difficulty"] == tier and it["name"] not in recent_names]
    if not candidates:
        candidates = [it for it in pool if it["name"] not in recent_names]
    if not candidates:
        candidates = pool

    rng = random.Random(seed)
    return rng.choice(candidates), tier


def compute_adherence(recent_logs, lookback=7):
    """
    recent_logs: list of dicts, each: {"items": [{"category": str, "completed": bool}, ...]}
    Returns {category: completion_rate} across the trailing `lookback` days.
    """
    tally = {}
    for log in recent_logs[-lookback:]:
        for item in log.get("items", []):
            cat = item["category"]
            bucket = tally.setdefault(cat, {"done": 0, "total": 0})
            bucket["total"] += 1
            if item.get("completed"):
                bucket["done"] += 1
    return {cat: (v["done"] / v["total"] if v["total"] else None) for cat, v in tally.items()}


def recent_names_for_category(recent_logs, category, lookback=3):
    names = set()
    for log in recent_logs[-lookback:]:
        for item in log.get("items", []):
            if item["category"] == category and item.get("name"):
                names.add(item["name"])
    return names


def generate_day_plan(goal, food_type, weekday_index, day_number, recent_logs):
    """
    Build one day's adaptive plan.

    goal: "weight_loss" | "muscle_gain"
    food_type: "veg" | "nonveg"
    weekday_index: 0-6 (0 = Sunday)
    day_number: 1-based day count in the user's program
    recent_logs: prior daily logs (most recent last), used to compute adherence

    Returns: {"workout": {"category":..., "type":..., "exercises":[...]},
              "meals": {"breakfast":[...], "lunch":[...], ...}}
    """
    adherence = compute_adherence(recent_logs)
    notes = []

    category = WEEKDAY_CATEGORY[goal][weekday_index]
    workout_pool = WORKOUT_POOL[goal][category]
    recent_workout_names = recent_names_for_category(recent_logs, category)
    cat_adherence = adherence.get(category)
    ex1, tier1 = _pick_variant(workout_pool, cat_adherence, day_number * 7 + 1, recent_workout_names)
    ex2_pool = [it for it in workout_pool if it["name"] != ex1["name"]]
    ex2, _ = _pick_variant(ex2_pool or workout_pool, cat_adherence, day_number * 7 + 2, recent_workout_names | {ex1["name"]})
    exercises = [ex1, ex2]
    remaining = [it for it in workout_pool if it["name"] not in {ex1["name"], ex2["name"]}]
    rng = random.Random(day_number * 13 + hash(category) % 97)
    rng.shuffle(remaining)
    exercises += remaining[:2]

    category_label = {
        "rest": "Active Recovery & Mobility",
        "push": "Push — Chest, Shoulders, Triceps",
        "pull": "Pull — Back & Biceps",
        "legs": "Legs — Quads, Hams, Glutes",
        "core": "Core & Stability",
        "cardio": "Cardio Conditioning",
    }[category]

    if cat_adherence is not None:
        pct = round(cat_adherence * 100)
        if tier1 == "easy":
            notes.append(f"{category_label.split(' —')[0]} adherence was {pct}% recently, so today steps down to an easier variant.")
        elif tier1 == "hard":
            notes.append(f"{category_label.split(' —')[0]} adherence was {pct}% recently — today progresses to a harder variant.")

    meals = {}
    for slot in MEAL_SLOTS:
        slot_pool = MEAL_POOL[goal][food_type][slot]
        recent_meal_names = recent_names_for_category(recent_logs, f"meal:{slot}")
        slot_adherence = adherence.get(f"meal:{slot}")
        item, tier = _pick_variant(slot_pool, slot_adherence, day_number * 31 + hash(slot) % 17, recent_meal_names)
        meals[slot] = [item["name"]]
        if slot_adherence is not None and tier == "easy":
            notes.append(f"{slot.capitalize()} was often skipped recently, so today's option is simpler and quicker to prepare.")
        elif slot_adherence is not None and tier == "hard":
            notes.append(f"{slot.capitalize()} adherence has been strong, so today keeps variety with a richer option.")

    return {
        "category": category,
        "workout": {"type": category_label, "exercises": exercises},
        "meals": meals,
        "notes": notes,
    }


def recommend_next_day(*args, **kwargs):
    """
    Seam for a future real-ML upgrade. Today this just delegates to
    generate_day_plan(). If real ML is added later (e.g. a scikit-learn
    model trained on cross-user adherence data to predict which variant
    a specific user is most likely to complete), swap the body of this
    function to call that model instead, keeping the same signature so
    app.py doesn't need to change.
    """
    return generate_day_plan(*args, **kwargs)
