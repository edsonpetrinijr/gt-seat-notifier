"""GT Seat Notifier — Flask API (REST)."""

import json
import os
import threading
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS

from core import fetch_seat_info, SeatInfo, discover_sections

app = Flask(__name__)
CORS(app)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
COURSES_FILE = os.path.join(DATA_DIR, "courses.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DEFAULT_SETTINGS: dict = {
    "ntfy_topic": "",
    "ntfy_server": "https://ntfy.sh",
    "term": "202608",
    "interval": 30,
    "notifications_enabled": True,
}

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_json(path: str, default) -> any:
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
_courses: list[dict] = _load_json(COURSES_FILE, [])   # [{crn, term, name}]
_settings: dict = {**DEFAULT_SETTINGS, **_load_json(SETTINGS_FILE, {})}
_state: dict[str, SeatInfo] = {}
_last_updated: dict[str, str] = {}
_errors: dict[str, str] = {}
_notified: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Background monitor
# ---------------------------------------------------------------------------

def _monitor_loop() -> None:
    while True:
        interval = _settings.get("interval", 30)
        with _lock:
            snapshot = list(_courses)

        for course in snapshot:
            crn = course["crn"]
            term = course["term"]
            try:
                info = fetch_seat_info(term, crn)
                with _lock:
                    _state[crn] = info
                    _errors.pop(crn, None)
                    _last_updated[crn] = datetime.now(timezone.utc).isoformat()

                # Notifications
                ntfy_topic = _settings.get("ntfy_topic", "")
                ntfy_server = _settings.get("ntfy_server", "https://ntfy.sh")
                if ntfy_topic and _settings.get("notifications_enabled", True):
                    _maybe_notify(course, info, ntfy_server, ntfy_topic)
            except Exception as exc:
                with _lock:
                    _errors[crn] = str(exc)

        time.sleep(interval)


def _maybe_notify(course: dict, seats: SeatInfo, ntfy_server: str, ntfy_topic: str) -> None:
    from core import send_notification, Section
    crn = course["crn"]
    section = Section(crn=crn, course_id="", section_id="", course_name=course["name"])

    if seats.enrollment_seats_available > 0:
        if _notified.get(crn) != "seat":
            try:
                send_notification(ntfy_server, ntfy_topic, section, seats,
                                  priority="urgent", tags=["tada", "school"])
            except Exception:
                pass
            _notified[crn] = "seat"
    elif seats.waitlist_seats_available > 0:
        if _notified.get(crn) not in ("seat", "waitlist"):
            try:
                send_notification(ntfy_server, ntfy_topic, section, seats,
                                  priority="high", tags=["hourglass_flowing_sand", "school"])
            except Exception:
                pass
            _notified[crn] = "waitlist"
    else:
        _notified.pop(crn, None)


_thread = threading.Thread(target=_monitor_loop, daemon=True)
_thread.start()

# ---------------------------------------------------------------------------
# Routes — Courses
# ---------------------------------------------------------------------------

@app.route("/courses", methods=["GET"])
def get_courses():
    with _lock:
        result = []
        for c in _courses:
            crn = c["crn"]
            info = _state.get(crn)
            result.append({
                "crn": crn,
                "term": c["term"],
                "name": c["name"],
                "seatsAvailable": info.enrollment_seats_available if info else None,
                "waitlistAvailable": info.waitlist_seats_available if info else None,
                "enrollmentActual": info.enrollment_actual if info else None,
                "enrollmentMaximum": info.enrollment_maximum if info else None,
                "lastUpdated": _last_updated.get(crn, ""),
                "error": _errors.get(crn),
            })
    return jsonify(result)


@app.route("/courses", methods=["POST"])
def add_course():
    body = request.get_json(force=True)
    crn  = str(body.get("crn",  "")).strip()
    term = str(body.get("term", "")).strip()
    name = body.get("name", "").strip()

    if not crn or not term or not name:
        return jsonify({"error": "crn, term, name required"}), 400

    with _lock:
        if any(c["crn"] == crn for c in _courses):
            return jsonify({"error": "Course already tracked"}), 409
        course = {"crn": crn, "term": term, "name": name}
        _courses.append(course)
        _save_json(COURSES_FILE, _courses)

    return jsonify({
        "crn": crn, "term": term, "name": name,
        "seatsAvailable": None, "waitlistAvailable": None,
        "lastUpdated": "", "error": None,
    }), 201


@app.route("/courses/<crn>", methods=["DELETE"])
def delete_course(crn: str):
    with _lock:
        before = len(_courses)
        _courses[:] = [c for c in _courses if c["crn"] != crn]
        if len(_courses) == before:
            return jsonify({"error": "Not found"}), 404
        _state.pop(crn, None)
        _errors.pop(crn, None)
        _notified.pop(crn, None)
        _last_updated.pop(crn, None)
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


@app.route("/sections", methods=["GET"])
def get_sections():
    term   = request.args.get("term",   "").strip()
    course = request.args.get("course", "").strip()
    if not term or not course:
        return jsonify({"error": "term and course required"}), 400
    try:
        sections, warnings = discover_sections(term, [course])
        return jsonify({
            "sections": [
                {
                    "crn":         s.crn,
                    "section_id":  s.section_id,
                    "course_id":   s.course_id,
                    "course_name": s.course_name,
                }
                for s in sections
            ],
            "warnings": warnings,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    print(f"GT Seat Notifier API — http://localhost:8080", flush=True)
    app.run(host="0.0.0.0", port=8080, debug=False)
