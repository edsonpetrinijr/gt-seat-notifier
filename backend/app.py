"""GT Seat Notifier — Flask API (REST)."""

import json
import os
import threading
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS

from core import fetch_seat_info, SeatInfo, discover_sections, normalize_course_id

app = Flask(__name__)
CORS(app)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
COURSES_FILE = os.path.join(DATA_DIR, "courses.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DEFAULT_SETTINGS: dict = {
    "ntfy_topic": "",
    "ntfy_server": "https://ntfy.sh",
    "term": "202702",
    "interval": 30,
    "notifications_enabled": True,
}

SEASON_CODE = {"spring": "02", "summer": "05", "fall": "08"}
SEASON_ORDER = {"spring": 0, "summer": 1, "fall": 2}

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_courses: list[dict] = _load_json(COURSES_FILE, [])   # [{courseId, term}]
_settings: dict = {**DEFAULT_SETTINGS, **_load_json(SETTINGS_FILE, {})}
_state:    dict[str, SeatInfo] = {}
_last_updated: dict[str, str] = {}
_errors:   dict[str, str] = {}
_notified: dict[str, str] = {}


def resolve_term(season: str) -> str:
    """season name -> term code, rolling forward from settings' base term."""
    base_term = _settings.get("term", "202702")
    base_year, base_code = int(base_term[:4]), base_term[4:]
    base_season = next((k for k, v in SEASON_CODE.items() if v == base_code), "fall")
    year = base_year if SEASON_ORDER[season] >= SEASON_ORDER[base_season] else base_year + 1
    return f"{year}{SEASON_CODE[season]}"


def section_status(crn: str) -> str:
    info = _state.get(crn)
    if info is None:
        return "LOADING"
    if info.enrollment_seats_available > 0:
        return "OPEN"
    if info.waitlist_seats_available > 0:
        return "WAITLIST"
    return "FULL"


_STATUS_RANK = {"OPEN": 0, "WAITLIST": 1, "LOADING": 2, "FULL": 3, "ERROR": 3}


def _sort_key(sec: dict) -> tuple:
    rank = _STATUS_RANK[sec["status"]]
    if sec["status"] == "OPEN":
        return (rank, -(sec["seatsAvailable"] or 0))
    if sec["status"] == "WAITLIST":
        return (rank, -(sec["waitlistAvailable"] or 0))
    return (rank, 0)


# ---------------------------------------------------------------------------
# Schedule preferences — no class before 9:30, protected lunch/rest
# 12:00-14:00, nothing running past 18:00.
# ---------------------------------------------------------------------------

EARLIEST_START = 9 * 60 + 30
LUNCH_START = 12 * 60
LUNCH_END = 14 * 60
LATEST_END = 18 * 60
GIVEUP_PENALTY = 10_000_000


def _to_min(t: str | None) -> int | None:
    if not t or t == "TBA":
        return None
    try:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _combo_meetings(combo: dict) -> list[dict]:
    meetings = list(combo["lecture"]["meetings"])
    if combo["lab"]:
        meetings += combo["lab"]["meetings"]
    return meetings


def _time_penalty(combo: dict) -> int:
    penalty = 0
    for m in _combo_meetings(combo):
        s, e = _to_min(m["start"]), _to_min(m["end"])
        if s is None or e is None:
            continue
        if s < EARLIEST_START:
            penalty += EARLIEST_START - s
        if e > LATEST_END:
            penalty += e - LATEST_END
        penalty += max(0, min(e, LUNCH_END) - max(s, LUNCH_START))
    return penalty


def _combos_overlap(a: dict, b: dict) -> bool:
    for m1 in _combo_meetings(a):
        days1 = set(m1["days"] or "")
        s1, e1 = _to_min(m1["start"]), _to_min(m1["end"])
        if not days1 or s1 is None or e1 is None:
            continue
        for m2 in _combo_meetings(b):
            days2 = set(m2["days"] or "")
            if not (days1 & days2):
                continue
            s2, e2 = _to_min(m2["start"]), _to_min(m2["end"])
            if s2 is None or e2 is None:
                continue
            if s1 < e2 and s2 < e1:
                return True
    return False


def _course_combos(course_id: str, term: str) -> tuple[str, list[dict], list[dict], list[str]]:
    """Returns (course_name, sec_list, combos, warnings)."""
    try:
        sections, warnings = discover_sections(term, [course_id])
    except Exception as exc:
        return course_id, [], [], [str(exc)]

    with _lock:
        sec_list = []
        for s in sections:
            info = _state.get(s.crn)
            status = section_status(s.crn)
            sec_list.append({
                "crn": s.crn,
                "sectionId": s.section_id,
                "parentId": s.parent_id,
                "credits": s.credits,
                "meetings": [m.to_dict() for m in s.meetings],
                "seatsAvailable": info.enrollment_seats_available if info else None,
                "waitlistAvailable": info.waitlist_seats_available if info else None,
                "enrollmentActual": info.enrollment_actual if info else None,
                "enrollmentMaximum": info.enrollment_maximum if info else None,
                "lastUpdated": _last_updated.get(s.crn, ""),
                "error": _errors.get(s.crn),
                "status": status,
            })

    # Group labs/studios (0-credit, parentId set) under their lecture; anything
    # without a parent is its own registration unit (lecture-with-labs,
    # or a standalone single-section course).
    labs_by_parent: dict[str, list] = {}
    for s in sec_list:
        if s["parentId"]:
            labs_by_parent.setdefault(s["parentId"], []).append(s)

    combos = []
    for s in sec_list:
        if s["parentId"]:
            continue
        labs = sorted(labs_by_parent.get(s["sectionId"], []), key=_sort_key)
        if labs:
            open_lab = next((l for l in labs if l["status"] == "OPEN"), None)
            wl_lab = next((l for l in labs if l["status"] == "WAITLIST"), None)
            if s["status"] == "OPEN" and open_lab:
                combo_status = "OPEN"
            elif s["status"] in ("OPEN", "WAITLIST") and (open_lab or wl_lab):
                combo_status = "WAITLIST"
            else:
                combo_status = "FULL"
            combos.append({
                "type": "lecture+lab",
                "lecture": s,
                "lab": open_lab or wl_lab or labs[0],
                "labOptions": labs,
                "status": combo_status,
            })
        else:
            combos.append({"type": "single", "lecture": s, "lab": None, "labOptions": [], "status": s["status"]})

    for c in combos:
        c["timePenalty"] = _time_penalty(c)

    combos.sort(key=lambda c: (_STATUS_RANK[c["status"]], c["timePenalty"], -(c["lecture"]["seatsAvailable"] or 0)))

    course_name = sections[0].course_name if sections else course_id
    return course_name, sec_list, combos, warnings


def _solve_schedule(feasible_lists: list[list[dict]]) -> list[dict | None]:
    """Picks one combo per course (or None) minimizing status + time-preference
    penalty, with zero meeting-time overlap between the chosen combos."""
    n = len(feasible_lists)
    order = sorted(range(n), key=lambda i: len(feasible_lists[i]))
    best_assignment: dict[int, dict | None] = {}
    best_score = [None]
    chosen: dict[int, dict | None] = {}

    def backtrack(pos: int, score: int) -> None:
        if best_score[0] is not None and score >= best_score[0]:
            return
        if pos == n:
            best_score[0] = score
            best_assignment.clear()
            best_assignment.update(chosen)
            return
        i = order[pos]
        for combo in feasible_lists[i] + [None]:
            if combo is None:
                cost = GIVEUP_PENALTY
            else:
                if any(chosen[j] is not None and _combos_overlap(combo, chosen[j]) for j in chosen):
                    continue
                cost = _STATUS_RANK[combo["status"]] * 100_000 + combo["timePenalty"]
            chosen[i] = combo
            backtrack(pos + 1, score + cost)
            del chosen[i]

    backtrack(0, 0)
    return [best_assignment.get(i) for i in range(n)]


def _view_dict(course_id: str, term: str, course_name: str, sec_list: list[dict],
                combos: list[dict], warnings: list[str], recommended: dict | None,
                schedule_conflict: bool) -> dict:
    return {
        "courseId": course_id,
        "courseName": course_name,
        "term": term,
        "sections": sec_list,
        "recommended": recommended,
        "scheduleConflict": schedule_conflict,
        "openCount": sum(1 for s in sec_list if s["status"] == "OPEN"),
        "waitlistCount": sum(1 for s in sec_list if s["status"] == "WAITLIST"),
        "error": warnings[0] if (warnings and not sec_list) else None,
    }


def _build_course_view(course_id: str, term: str) -> dict:
    course_name, sec_list, combos, warnings = _course_combos(course_id, term)
    recommended = combos[0] if combos and combos[0]["status"] in ("OPEN", "WAITLIST") else None
    return _view_dict(course_id, term, course_name, sec_list, combos, warnings, recommended, False)


# ---------------------------------------------------------------------------
# Background monitor
# ---------------------------------------------------------------------------

def _fetch_and_notify(section, term: str) -> None:
    crn = section.crn
    try:
        info = fetch_seat_info(term, crn)
        with _lock:
            _state[crn] = info
            _errors.pop(crn, None)
            _last_updated[crn] = datetime.now(timezone.utc).isoformat()

        ntfy_topic = _settings.get("ntfy_topic", "")
        ntfy_server = _settings.get("ntfy_server", "https://ntfy.sh")
        if not (ntfy_topic and _settings.get("notifications_enabled", True)):
            return

        if info.enrollment_seats_available > 0:
            if _notified.get(crn) != "seat":
                from core import send_notification
                try:
                    send_notification(ntfy_server, ntfy_topic, section, info,
                                      priority="urgent", tags=["tada", "school"])
                except Exception:
                    pass
                _notified[crn] = "seat"
        elif info.waitlist_seats_available > 0:
            if _notified.get(crn) not in ("seat", "waitlist"):
                from core import send_notification
                try:
                    send_notification(ntfy_server, ntfy_topic, section, info,
                                      priority="high", tags=["hourglass_flowing_sand", "school"])
                except Exception:
                    pass
                _notified[crn] = "waitlist"
        else:
            _notified.pop(crn, None)
    except Exception as exc:
        with _lock:
            _errors[crn] = str(exc)


def _monitor_loop() -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    while True:
        interval = _settings.get("interval", 30)
        with _lock:
            tracked = list(_courses)

        targets = []
        for tc in tracked:
            try:
                sections, _ = discover_sections(tc["term"], [tc["courseId"]])
                targets.extend((s, tc["term"]) for s in sections)
            except Exception:
                pass

        if targets:
            with ThreadPoolExecutor(max_workers=min(len(targets), 20)) as pool:
                futures = [pool.submit(_fetch_and_notify, s, term) for s, term in targets]
                for fut in as_completed(futures):
                    fut.result()

        time.sleep(interval)


_thread = threading.Thread(target=_monitor_loop, daemon=True)
_thread.start()

# ---------------------------------------------------------------------------
# Routes — Courses
# ---------------------------------------------------------------------------

@app.route("/courses", methods=["GET"])
def get_courses():
    with _lock:
        tracked = list(_courses)

    per_course = [(tc, *_course_combos(tc["courseId"], tc["term"])) for tc in tracked]
    feasible_lists = [[c for c in combos if c["status"] in ("OPEN", "WAITLIST")]
                       for _, _, _, combos, _ in per_course]
    picks = _solve_schedule(feasible_lists)

    result = []
    for (tc, course_name, sec_list, combos, warnings), feasible, picked in zip(per_course, feasible_lists, picks):
        if picked is not None:
            recommended, schedule_conflict = picked, False
        elif feasible:
            recommended, schedule_conflict = feasible[0], True
        else:
            recommended, schedule_conflict = None, False
        result.append(_view_dict(tc["courseId"], tc["term"], course_name, sec_list,
                                  combos, warnings, recommended, schedule_conflict))
    return jsonify(result)


@app.route("/courses", methods=["POST"])
def add_course():
    body = request.get_json(force=True)
    course_id = normalize_course_id(str(body.get("courseId", "")))
    season = str(body.get("season", "")).strip().lower()

    if not course_id or season not in SEASON_CODE:
        return jsonify({"error": "courseId and season (spring/summer/fall) required"}), 400

    term = resolve_term(season)

    with _lock:
        if any(c["courseId"] == course_id and c["term"] == term for c in _courses):
            return jsonify({"error": "Course already tracked"}), 409

    try:
        sections, warnings = discover_sections(term, [course_id])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    if not sections:
        return jsonify({"error": warnings[0] if warnings else "No sections found"}), 404

    with _lock:
        _courses.append({"courseId": course_id, "term": term})
        _save_json(COURSES_FILE, _courses)

    # immediate fetch so the UI isn't empty on add
    for s in sections:
        try:
            info = fetch_seat_info(term, s.crn)
            with _lock:
                _state[s.crn] = info
                _last_updated[s.crn] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            with _lock:
                _errors[s.crn] = str(exc)

    return jsonify(_build_course_view(course_id, term)), 201


@app.route("/courses/<course_id>", methods=["DELETE"])
def delete_course(course_id: str):
    term = request.args.get("term", "")
    with _lock:
        before = len(_courses)
        if term:
            _courses[:] = [c for c in _courses if not (c["courseId"] == course_id and c["term"] == term)]
        else:
            _courses[:] = [c for c in _courses if c["courseId"] != course_id]
        if len(_courses) == before:
            return jsonify({"error": "Not found"}), 404
        _save_json(COURSES_FILE, _courses)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — Settings
# ---------------------------------------------------------------------------

@app.route("/settings", methods=["GET"])
def get_settings():
    return jsonify(_settings)


@app.route("/settings", methods=["POST"])
def save_settings():
    body = request.get_json(force=True)
    allowed = {"ntfy_topic", "ntfy_server", "term", "interval", "notifications_enabled"}
    with _lock:
        for k, v in body.items():
            if k in allowed:
                _settings[k] = v
        _save_json(SETTINGS_FILE, _settings)
    return jsonify(_settings)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("GT Seat Notifier API — http://localhost:8080", flush=True)
    app.run(host="0.0.0.0", port=8080, debug=False)
