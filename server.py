#!/usr/bin/env python3
"""GT Seat Notifier: watches Georgia Tech course sections and sends an ntfy
push when a seat or waitlist spot opens. Stdlib only.

Run:   python3 server.py, then open http://localhost:8080
Tests: python3 -m unittest -v test_server

How the hard parts work:
- Every GT request goes through an adaptive limiter (AIMD). It allows one
  more request in flight after a run of clean replies and halves on a
  timeout, 429 or 5xx, so we back off when the GT proxy struggles. Failed
  requests retry with jittered exponential backoff.
- One checker thread runs every check pass. Adding a course only wakes it,
  so two passes never overlap.
- A push fires when a section reaches a better state than the last one we
  announced. It has to stay worse for REARM seconds before it can alert
  again, so a seat that flaps open/closed sends one push, not ten.
- Alert state lives in state.json, written atomically (temp file + rename).
  Pushes are at-least-once: until ntfy confirms, state.json keeps the old
  state, and a failed push rolls back so the next pass sends it again.
"""

import html
import json
import os
import queue
import random
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
CRAWLER = "https://gt-scheduler.github.io/crawler-v2/{term}.json"
SECTION = "https://gt-scheduler.azurewebsites.net/proxy/class_section?term={term}&crn={crn}"
UA = {"User-Agent": "gt-seat-notifier"}
FIELD = re.compile(r'<span class="status-bold">([^<]+):</span>\s*<span[^>]*>([^<]+)</span>')
RANK = {"OPEN": 0, "WAITLIST": 1, "FULL": 2}
DEFAULTS = {"ntfy_topic": "", "ntfy_server": "https://ntfy.sh", "term": "202702", "interval": 60, "courses": []}

TIMEOUT = 10    # seconds per GT request
ATTEMPTS = 4    # tries per section per pass
BACKOFF = 0.5   # base seconds for jittered exponential backoff
REARM = 600     # seconds a section must stay worse before it can alert again


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def get(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float | None = None) -> str:
    req = Request(url, data=data, headers={**UA, **(headers or {})})
    with urlopen(req, timeout=timeout or TIMEOUT) as resp:
        return resp.read().decode()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def save_json(path: Path, obj) -> None:
    """Write to a temp file in the same folder, fsync, then rename over the
    target. A crash mid-write leaves the old file intact, never a half file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def normalize(course_id: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"([A-Za-z]+)\s*(\d)", r"\1 \2", course_id.strip())).upper()


def clock(period: str) -> str:
    if " - " not in period:
        return "TBA"
    return "–".join(f"{t[:2]}:{t[2:]}" for t in period.split(" - "))


def parse_seats(page: str) -> dict:
    f = {k.strip(): v.strip() for k, v in FIELD.findall(page)}
    # A busy proxy sometimes answers 200 with an error page. Reading that as
    # zeros would mark the section FULL, and the next good read would fire a
    # false "seat open" push. So a page without the numbers is an error.
    if not all(k in f for k in ("Enrollment Actual", "Enrollment Maximum", "Enrollment Seats Available")):
        raise ValueError("GT returned a page without seat numbers")
    n = lambda k: int(f.get(k, "0"))
    return {"enrolled": n("Enrollment Actual"), "max": n("Enrollment Maximum"),
            "open": n("Enrollment Seats Available"),
            "wlOpen": n("Waitlist Seats Available"), "wlCap": n("Waitlist Capacity")}


def status_of(info: dict) -> str:
    return "OPEN" if info["open"] > 0 else "WAITLIST" if info["wlOpen"] > 0 else "FULL"


def retryable(exc: Exception) -> bool:
    """True when the failure means GT is overloaded or flaky (worth a retry)."""
    if isinstance(exc, HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, (OSError, ValueError))  # timeouts, resets, bad pages


def transition(rec: dict | None, new: str, now: float, rearm: float) -> tuple[dict, bool]:
    """Alert decision for one section. rec is {"announced", "worse_since"} or
    None if never seen. Returns (new record, whether to push)."""
    if rec is None:  # first sighting just records the state
        return {"announced": new, "worse_since": None}, False
    announced = rec["announced"]
    if RANK[new] < RANK[announced]:
        return {"announced": new, "worse_since": None}, True
    if RANK[new] == RANK[announced]:
        return {"announced": announced, "worse_since": None}, False
    since = rec["worse_since"] if rec["worse_since"] is not None else now
    if now - since >= rearm:  # stayed worse long enough: re-arm the alert
        return {"announced": new, "worse_since": None}, False
    return {"announced": announced, "worse_since": since}, False


class Limiter:
    """Caps in-flight requests. Grows by one after `limit` clean replies in a
    row, halves on overload (AIMD, like TCP congestion control)."""

    def __init__(self, start: int = 5, lo: int = 1, hi: int = 10):
        self.limit, self.lo, self.hi = start, lo, hi
        self.active = self.streak = 0
        self.cv = threading.Condition()

    def acquire(self) -> None:
        with self.cv:
            self.cv.wait_for(lambda: self.active < self.limit)
            self.active += 1

    def release(self, overloaded: bool) -> None:
        with self.cv:
            self.active -= 1
            if overloaded:
                self.limit, self.streak = max(self.lo, self.limit // 2), 0
            else:
                self.streak += 1
                if self.streak >= self.limit:
                    self.limit, self.streak = min(self.hi, self.limit + 1), 0
            self.cv.notify_all()


class Watcher:
    def __init__(self, config_file: Path, state_file: Path):
        self.config_file, self.state_file = Path(config_file), Path(state_file)
        self.config = {**DEFAULTS, **load_json(self.config_file, {})}
        self.config["interval"] = max(10, int(self.config["interval"]))
        try:
            saved = load_json(self.state_file, {})
        except ValueError:
            log("state.json is unreadable, starting fresh")
            saved = {}
        same_term = saved.get("term") == self.config["term"]
        self.records: dict[str, dict] = saved.get("records", {}) if same_term else {}
        self.pending: dict[str, dict] = {}  # crn -> last delivered record while a push is in flight
        self.seats: dict[str, dict] = {}    # crn -> latest numbers, status, course, section
        self.errors: dict[str, str] = {}    # crn -> last fetch error
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.version = 0
        self.last_check: float | None = None
        self.check_seconds: float | None = None
        self.limiter = Limiter()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.outbox: queue.Queue = queue.Queue()
        self._terms: dict[str, dict] = {}
        self._term_lock = threading.Lock()

    # --- GT data -----------------------------------------------------------

    def term_data(self) -> dict:
        # ponytail: cached for the life of the process; restart to pick up new sections
        term = self.config["term"]
        with self._term_lock:  # one download even if many threads ask at once
            if term not in self._terms:
                self._terms[term] = json.loads(get(CRAWLER.format(term=term), timeout=30))
            return self._terms[term]

    def sections_of(self, course_id: str) -> tuple[str | None, list[dict]]:
        data = self.term_data()
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

    def fetch_seats(self, crn: str) -> dict:
        last: Exception | None = None
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(random.uniform(0, BACKOFF * 2 ** attempt))
            self.limiter.acquire()
            try:
                info = parse_seats(get(SECTION.format(term=self.config["term"], crn=crn)))
            except Exception as exc:
                retry = retryable(exc)
                self.limiter.release(overloaded=retry)
                last = exc
                if not retry:
                    break
                continue
            self.limiter.release(overloaded=False)
            return info
        raise last

    # --- check pass ----------------------------------------------------------

    def check(self) -> None:
        started = time.time()
        with self.lock:
            courses = list(self.config["courses"])
            known = {crn: s["status"] for crn, s in self.seats.items()}
        targets = {s["crn"]: (cid, s["id"]) for cid in courses for s in self.sections_of(cid)[1]}
        # Full and waitlisted sections go first: only they can trigger a push.
        order = sorted(targets, key=lambda crn: -RANK[known.get(crn, "FULL")])
        with ThreadPoolExecutor(self.limiter.hi) as pool:
            futures = {pool.submit(self.fetch_seats, crn): crn for crn in order}
            for fut in as_completed(futures):  # handle each result as soon as it lands
                crn = futures[fut]
                try:
                    info = fut.result()
                except Exception as exc:
                    self.record_error(crn, targets[crn][0], str(exc) or type(exc).__name__)
                else:
                    self.record(crn, *targets[crn], info)
        with self.lock:
            self.last_check = time.time()
            self.check_seconds = round(self.last_check - started, 1)
            self._bump()
        self.save_state()

    def record(self, crn: str, course_id: str, section_id: str, info: dict) -> None:
        new = status_of(info)
        with self.lock:
            if course_id not in self.config["courses"]:
                return  # course was removed while this pass was running
            rec, alert = transition(self.records.get(crn), new, time.time(), REARM)
            if alert:
                self.pending.setdefault(crn, self.records[crn])
                self.outbox.put(crn)
            self.records[crn] = rec
            self.seats[crn] = {**info, "status": new, "course": course_id, "section": section_id}
            self.errors.pop(crn, None)
            self._bump()

    def record_error(self, crn: str, course_id: str, error: str) -> None:
        with self.lock:
            if course_id in self.config["courses"]:
                self.errors[crn] = error  # keep the last good numbers on screen
                self._bump()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                self.check()
            except Exception as exc:
                log(f"check failed: {exc}")
            self.wake.wait(self.config["interval"])
            self.wake.clear()

    # --- pushes ----------------------------------------------------------------

    def notify_worker(self) -> None:
        while True:
            crn = self.outbox.get()
            if crn is None:
                return
            with self.lock:
                if crn not in self.pending:
                    continue  # already sent, rolled back, or course removed
                sent = self.records[crn]["announced"]
                seat = dict(self.seats[crn])
                topic, server = self.config["ntfy_topic"], self.config["ntfy_server"]
            ok = self.send(server, topic, crn, seat, sent)
            with self.lock:
                if crn not in self.pending:
                    continue  # course removed while we were sending
                if not ok:
                    self.records[crn] = self.pending.pop(crn)  # next pass alerts again
                elif RANK[self.records[crn]["announced"]] < RANK[sent]:
                    # A better state arrived mid-send; its push is queued behind us.
                    self.pending[crn] = {"announced": sent, "worse_since": None}
                else:
                    del self.pending[crn]
                self._bump()
            self.save_state()

    def send(self, server: str, topic: str, crn: str, seat: dict, status: str) -> bool:
        if not topic or status == "FULL":
            return True
        if status == "OPEN":
            title, msg, prio = f"{seat['course']} {seat['section']}: seat open", f"{seat['open']} seat(s) open", "urgent"
        else:
            title, msg, prio = f"{seat['course']} {seat['section']}: waitlist open", f"{seat['wlOpen']} waitlist spot(s)", "high"
        last: Exception | None = None
        for attempt in range(3):
            if attempt:
                time.sleep(random.uniform(0, BACKOFF * 2 ** attempt))
            try:
                get(f"{server}/{topic}", data=f"{msg} · CRN {crn}".encode(),
                    headers={"Title": title, "Priority": prio, "Tags": "school",
                             "Click": "https://gt-scheduler.github.io/"})
                log(f"push sent: {title}")
                return True
            except Exception as exc:
                last = exc
        log(f"push failed, next pass retries it: {last}")
        return False

    # --- state, config, live updates -------------------------------------------

    def _bump(self) -> None:  # caller holds self.lock
        self.version += 1
        self.changed.notify_all()

    def wait_change(self, seen: int | None, timeout: float) -> int:
        with self.lock:
            self.changed.wait_for(lambda: self.version != seen, timeout)
            return self.version

    def save_state(self) -> None:
        with self.lock:
            # Pending pushes are saved in their pre-alert state, so a crash
            # before ntfy confirms re-sends instead of losing the alert.
            save_json(self.state_file, {"term": self.config["term"], "records": {**self.records, **self.pending}})

    def state(self) -> dict:
        with self.lock:
            courses = list(self.config["courses"])
        out = []
        for cid in courses:
            name, secs = self.sections_of(cid)
            with self.lock:
                rows = [{**s, **self.seats.get(s["crn"], {}), "error": self.errors.get(s["crn"]),
                         "status": self.seats.get(s["crn"], {}).get("status", "CHECKING")} for s in secs]
            out.append({"id": cid, "name": name, "sections": rows})
        with self.lock:
            return {"term": self.config["term"], "topic": self.config["ntfy_topic"],
                    "interval": self.config["interval"], "lastCheck": self.last_check,
                    "checkSeconds": self.check_seconds, "parallel": self.limiter.limit, "courses": out}

    def add_course(self, cid: str) -> tuple[int, dict]:
        with self.lock:
            if cid in self.config["courses"]:
                return 409, {"error": f"{cid} is already on the list"}
        if not self.sections_of(cid)[0]:
            return 404, {"error": f"{cid} has no sections in term {self.config['term']}"}
        with self.lock:
            if cid in self.config["courses"]:  # another request added it while we looked it up
                return 409, {"error": f"{cid} is already on the list"}
            self.config["courses"].append(cid)
            save_json(self.config_file, self.config)
            self._bump()
        self.wake.set()
        return 200, {"ok": True}

    def remove_course(self, cid: str) -> tuple[int, dict]:
        try:
            crns = [s["crn"] for s in self.sections_of(cid)[1]]
        except Exception:
            crns = []
        with self.lock:
            if cid not in self.config["courses"]:
                return 200, {"ok": True}
            self.config["courses"].remove(cid)
            save_json(self.config_file, self.config)
            for crn in crns:
                for d in (self.records, self.pending, self.seats, self.errors):
                    d.pop(crn, None)
            self._bump()
        self.save_state()
        return 200, {"ok": True}

    def start(self) -> None:
        for target in (self.run, self.notify_worker):
            threading.Thread(target=target, daemon=True).start()

    def close(self) -> None:
        self.stop.set()
        self.wake.set()
        self.outbox.put(None)


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
        w: Watcher = self.server.watcher
        if self.path == "/":
            return self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            try:
                return self.json(200, w.state())
            except Exception as exc:
                return self.json(502, {"error": f"Could not reach GT Scheduler: {exc}"})
        if self.path == "/api/events":
            return self.events(w)
        self.json(404, {"error": "Not found"})

    def events(self, w: Watcher) -> None:
        """Server-sent events: push a fresh snapshot whenever state changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        seen = None
        try:
            while not w.stop.is_set():
                if w.wait_change(seen, 15) == seen:
                    self.wfile.write(b": ping\n\n")  # keeps proxies from closing an idle stream
                else:
                    time.sleep(0.3)  # let a burst of updates land, then send one snapshot
                    seen = w.version
                    try:
                        body = json.dumps(w.state())
                    except Exception as exc:
                        body = json.dumps({"error": f"Could not reach GT Scheduler: {exc}"})
                    self.wfile.write(f"data: {body}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser closed the tab

    def do_POST(self) -> None:
        self.edit(add=True)

    def do_DELETE(self) -> None:
        self.edit(add=False)

    def edit(self, add: bool) -> None:
        if self.path != "/api/courses":
            return self.json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1024:
                return self.json(413, {"error": "Request too large"})
            cid = normalize(str(json.loads(self.rfile.read(length) or b"{}").get("id", "")))
        except (ValueError, AttributeError):
            return self.json(400, {"error": "Send JSON like {\"id\": \"CS 1332\"}"})
        if not re.fullmatch(r"[A-Z]{2,4} \d{4}[A-Z]?", cid):
            return self.json(400, {"error": "Use the format DEPT 1234, like CS 1332"})
        w: Watcher = self.server.watcher
        try:
            self.json(*(w.add_course(cid) if add else w.remove_course(cid)))
        except Exception as exc:
            self.json(502, {"error": f"Could not reach GT Scheduler: {exc}"})

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    watcher = Watcher(ROOT / "config.json", ROOT / "state.json")
    watcher.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", 8080), Handler)
    httpd.watcher = watcher
    log(f"GT Seat Notifier on http://localhost:8080 (term {watcher.config['term']})")
    httpd.serve_forever()
