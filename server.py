#!/usr/bin/env python3
"""GT Seat Notifier: watches Georgia Tech course sections and sends an ntfy
push when a seat or waitlist spot opens. Stdlib only.

Run: python3 server.py, then open http://localhost:8080
"""

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "config.json"
CRAWLER = "https://gt-scheduler.github.io/crawler-v2/{term}.json"
SECTION = "https://gt-scheduler.azurewebsites.net/proxy/class_section?term={term}&crn={crn}"
UA = {"User-Agent": "gt-seat-notifier"}
FIELD = re.compile(r'<span class="status-bold">([^<]+):</span>\s*<span[^>]*>([^<]+)</span>')
RANK = {"OPEN": 0, "WAITLIST": 1, "FULL": 2}

config = {"ntfy_topic": "", "ntfy_server": "https://ntfy.sh", "term": "202702", "interval": 60, "courses": []}
if CONFIG_FILE.exists():
    config.update(json.loads(CONFIG_FILE.read_text()))

lock = threading.Lock()        # guards seats/status/config["courses"]
check_lock = threading.Lock()  # one check pass at a time
seats: dict[str, dict] = {}    # crn -> latest numbers
status: dict[str, str] = {}    # crn -> OPEN / WAITLIST / FULL
last_check: float | None = None
_terms: dict[str, dict] = {}


def get(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    req = Request(url, data=data, headers={**UA, **(headers or {})})
    with urlopen(req, timeout=20) as resp:
        return resp.read().decode()


def term_data(term: str) -> dict:
    # ponytail: cached for the life of the process; restart to pick up new sections
    if term not in _terms:
        _terms[term] = json.loads(get(CRAWLER.format(term=term)))
    return _terms[term]


def normalize(course_id: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"([A-Za-z]+)\s*(\d)", r"\1 \2", course_id.strip())).upper()


def clock(period: str) -> str:
    if " - " not in period:
        return "TBA"
    return "–".join(f"{t[:2]}:{t[2:]}" for t in period.split(" - "))


def sections_of(course_id: str) -> tuple[str | None, list[dict]]:
    data = term_data(config["term"])
    entry = data["courses"].get(course_id)
    if not entry:
        return None, []
    periods = data["caches"]["periods"]
    out = []
    for sid, tup in entry[1].items():
        meetings = [{"days": m[1] or "TBA", "time": clock(periods[m[0]]), "room": m[2] or ""}
                    for m in (tup[1] or []) if m]
        out.append({"id": sid, "crn": str(tup[0]), "meetings": meetings})
    return html.unescape(entry[0]), sorted(out, key=lambda s: s["id"])


def fetch_seats(crn: str) -> dict | None:
    try:
        page = get(SECTION.format(term=config["term"], crn=crn))
    except Exception:
        return None
    f = {k.strip(): v.strip() for k, v in FIELD.findall(page)}
    n = lambda k: int(f.get(k, "0")) if f.get(k, "0").lstrip("-").isdigit() else 0
    return {"enrolled": n("Enrollment Actual"), "max": n("Enrollment Maximum"),
            "open": n("Enrollment Seats Available"),
            "wlOpen": n("Waitlist Seats Available"), "wlCap": n("Waitlist Capacity")}


def notify(course_id: str, sid: str, crn: str, info: dict, new: str) -> None:
    if not config["ntfy_topic"]:
        return
    if new == "OPEN":
        title, msg, prio = f"{course_id} {sid}: seat open", f"{info['open']} seat(s) open", "urgent"
    else:
        title, msg, prio = f"{course_id} {sid}: waitlist open", f"{info['wlOpen']} waitlist spot(s)", "high"
    try:
        get(f"{config['ntfy_server']}/{config['ntfy_topic']}", data=f"{msg} · CRN {crn}".encode(),
            headers={"Title": title, "Priority": prio, "Tags": "school",
                     "Click": "https://gt-scheduler.github.io/"})
    except Exception as exc:
        print(f"ntfy failed: {exc}", flush=True)


def check_all() -> None:
    global last_check
    with check_lock:
        with lock:
            courses = list(config["courses"])
        targets = {s["crn"]: (cid, s["id"]) for cid in courses for s in sections_of(cid)[1]}
        # ponytail: 5 workers; the GT proxy times out at ~20 parallel requests
        with ThreadPoolExecutor(5) as pool:
            results = dict(zip(targets, pool.map(fetch_seats, targets)))
        for crn, info in results.items():
            if info is None:  # keep last known numbers on a failed fetch
                continue
            new = "OPEN" if info["open"] > 0 else "WAITLIST" if info["wlOpen"] > 0 else "FULL"
            with lock:
                old = status.get(crn)
                seats[crn], status[crn] = info, new
            # Only alert on a change we saw happen; the first pass just records state.
            if old and RANK[new] < RANK[old]:
                notify(*targets[crn], crn, info, new)
        last_check = time.time()


def loop() -> None:
    while True:
        try:
            check_all()
        except Exception as exc:
            print(f"check failed: {exc}", flush=True)
        time.sleep(config["interval"])


def state() -> dict:
    with lock:
        courses = list(config["courses"])
    out = []
    for cid in courses:
        name, secs = sections_of(cid)
        with lock:
            secs = [{**s, **seats.get(s["crn"], {}), "status": status.get(s["crn"], "CHECKING")} for s in secs]
        out.append({"id": cid, "name": name, "sections": secs})
    return {"term": config["term"], "topic": config["ntfy_topic"], "interval": config["interval"],
            "lastCheck": last_check, "courses": out}


def save_config() -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


class Handler(BaseHTTPRequestHandler):
    def reply(self, code: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json(self, code: int, obj) -> None:
        self.reply(code, json.dumps(obj).encode())

    def do_GET(self) -> None:
        if self.path == "/":
            return self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            try:
                return self.json(200, state())
            except Exception as exc:
                return self.json(502, {"error": f"Could not reach GT Scheduler: {exc}"})
        self.json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        self.edit(add=True)

    def do_DELETE(self) -> None:
        self.edit(add=False)

    def edit(self, add: bool) -> None:
        if self.path != "/api/courses":
            return self.json(404, {"error": "Not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            cid = normalize(str(body.get("id", "")))
        except (ValueError, AttributeError):
            return self.json(400, {"error": "Send JSON like {\"id\": \"CS 1332\"}"})
        if not re.fullmatch(r"[A-Z]{2,4} \d{4}[A-Z]?", cid):
            return self.json(400, {"error": "Use the format DEPT 1234, like CS 1332"})
        with lock:
            tracked = cid in config["courses"]
        if add:
            if tracked:
                return self.json(409, {"error": f"{cid} is already on the list"})
            try:
                found = sections_of(cid)[0]
            except Exception as exc:
                return self.json(502, {"error": f"Could not reach GT Scheduler: {exc}"})
            if not found:
                return self.json(404, {"error": f"{cid} has no sections in term {config['term']}"})
            with lock:
                config["courses"].append(cid)
                save_config()
            threading.Thread(target=check_all, daemon=True).start()
        else:
            with lock:
                if tracked:
                    config["courses"].remove(cid)
                    save_config()
        self.json(200, {"ok": True})

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    assert normalize("cs1332") == "CS 1332" and normalize(" math  2550 ") == "MATH 2550"
    assert clock("0800 - 0915") == "08:00–09:15" and clock("TBA") == "TBA"
    threading.Thread(target=loop, daemon=True).start()
    print(f"GT Seat Notifier on http://localhost:8080 (term {config['term']})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
