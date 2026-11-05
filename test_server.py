"""Tests for server.py against a fake GT Scheduler + fake ntfy running locally.

Run: python3 -m unittest -v test_server

FakeGT lets a test control what the real services do badly: cap parallel
requests (503 above the cap), hang one request past the client timeout,
return a 200 page with no numbers, fail ntfy pushes, slow every reply.
"""

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import server

TERM = "202702"


class FakeGT:
    def __init__(self, courses: dict[str, list[str]]):
        # courses: {"CS 1332": ["A", "B"]} -> CRNs assigned 10000, 10001, ...
        self.courses: dict[str, dict[str, str]] = {}
        self.seats: dict[str, list[int]] = {}  # crn -> [enrolled, max, wl_actual, wl_cap]
        crn = 10000
        for cid, sids in courses.items():
            self.courses[cid] = {}
            for sid in sids:
                self.courses[cid][sid] = str(crn)
                self.seats[str(crn)] = [30, 30, 0, 0]  # full, no waitlist
                crn += 1
        self.cap = 1000
        self.delay = 0.0
        self.hang: set[str] = set()     # these CRNs hang once, past the client timeout
        self.garbage: set[str] = set()  # these CRNs return a page without numbers once
        self.ntfy_fail = 0              # next N pushes get a 500
        self.pushes: list[dict] = []
        self.active = self.peak = self.rejected = 0
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path.startswith("/crawler/"):
                    return self.send(200, json.dumps(fake.crawler()).encode())
                crn = parse_qs(url.query)["crn"][0]
                with fake.lock:
                    fake.active += 1
                    fake.peak = max(fake.peak, fake.active)
                    over = fake.active > fake.cap
                    if over:
                        fake.rejected += 1
                    hang = crn in fake.hang
                    garbage = crn in fake.garbage
                    fake.hang.discard(crn)
                    fake.garbage.discard(crn)
                    nums = list(fake.seats[crn])
                try:
                    if over:
                        return self.send(503, b"busy")
                    time.sleep(1.0 if hang else fake.delay)
                    if garbage:
                        return self.send(200, b"<html>Service temporarily unavailable</html>")
                    self.send(200, fake.page(*nums).encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client gave up on a hung request
                finally:
                    with fake.lock:
                        fake.active -= 1

            def do_POST(self):  # ntfy
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                with fake.lock:
                    if fake.ntfy_fail > 0:
                        fake.ntfy_fail -= 1
                        return self.send(500, b"down")
                    fake.pushes.append({"topic": self.path.strip("/"), "title": self.headers["Title"], "body": body})
                self.send(200, b"{}")

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def crawler(self) -> dict:
        return {"caches": {"periods": ["0930 - 1045"]},
                "courses": {cid: [f"{cid} &amp; Friends", {sid: [crn, [[0, "MW", "Klaus 1443"]], 3]
                                                            for sid, crn in secs.items()}]
                            for cid, secs in self.courses.items()}}

    @staticmethod
    def page(enrolled, cap, wl_actual, wl_cap) -> str:
        rows = {"Enrollment Actual": enrolled, "Enrollment Maximum": cap,
                "Enrollment Seats Available": cap - enrolled, "Waitlist Capacity": wl_cap,
                "Waitlist Actual": wl_actual, "Waitlist Seats Available": wl_cap - wl_actual}
        return "".join(f'<span class="status-bold">{k}:</span> <span dir="ltr">{v}</span>\n' for k, v in rows.items())

    def crn(self, cid: str, sid: str) -> str:
        return self.courses[cid][sid]

    def set(self, crn: str, enrolled: int, cap: int = 30, wl_actual: int = 0, wl_cap: int = 0) -> None:
        with self.lock:
            self.seats[crn] = [enrolled, cap, wl_actual, wl_cap]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def wait_until(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


class Base(unittest.TestCase):
    courses = {"CS 1332": ["A", "B", "C"], "MATH 2550": ["A01", "A02", "A03"]}

    def setUp(self):
        self.fake = FakeGT(self.courses)
        self.addCleanup(self.fake.close)
        patcher = mock.patch.multiple(server, CRAWLER=f"{self.fake.url}/crawler/{{term}}.json",
                                      SECTION=f"{self.fake.url}/section?term={{term}}&crn={{crn}}",
                                      TIMEOUT=0.3, BACKOFF=0.01, REARM=60, ATTEMPTS=6, log=lambda msg: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dir = Path(tempfile.mkdtemp())
        self.config = self.dir / "config.json"
        self.state_file = self.dir / "state.json"
        self.config.write_text(json.dumps({"ntfy_topic": "t", "ntfy_server": self.fake.url, "term": TERM,
                                           "interval": 30, "courses": list(self.courses)}))

    def watcher(self, notifier=True) -> server.Watcher:
        w = server.Watcher(self.config, self.state_file)
        self.addCleanup(w.close)
        if notifier:
            threading.Thread(target=w.notify_worker, daemon=True).start()
        return w

    def settle(self, w):
        """Wait until every queued push is sent or rolled back."""
        wait_until(lambda: w.outbox.empty() and not w.pending)

    def saved(self, crn):
        return json.loads(self.state_file.read_text())["records"].get(crn)


class PureLogic(unittest.TestCase):
    def test_first_sighting_never_alerts(self):
        for st in server.RANK:
            self.assertEqual(server.transition(None, st, 0, 60), ({"announced": st, "worse_since": None}, False))

    def test_better_state_alerts(self):
        full = {"announced": "FULL", "worse_since": None}
        self.assertTrue(server.transition(full, "OPEN", 0, 60)[1])
        self.assertTrue(server.transition(full, "WAITLIST", 0, 60)[1])
        self.assertTrue(server.transition({"announced": "WAITLIST", "worse_since": None}, "OPEN", 0, 60)[1])

    def test_flap_inside_rearm_window_is_silent(self):
        rec = {"announced": "OPEN", "worse_since": None}
        rec, alert = server.transition(rec, "FULL", 100, 60)
        self.assertEqual((rec, alert), ({"announced": "OPEN", "worse_since": 100}, False))
        rec, alert = server.transition(rec, "FULL", 130, 60)
        self.assertEqual(rec["worse_since"], 100)  # keeps the first time it went worse
        self.assertFalse(server.transition(rec, "OPEN", 140, 60)[1])

    def test_rearm_after_staying_worse(self):
        rec, _ = server.transition({"announced": "OPEN", "worse_since": None}, "FULL", 100, 60)
        rec, alert = server.transition(rec, "FULL", 160, 60)
        self.assertEqual((rec, alert), ({"announced": "FULL", "worse_since": None}, False))
        self.assertTrue(server.transition(rec, "OPEN", 170, 60)[1])

    def test_same_state_clears_worse_since(self):
        rec = {"announced": "OPEN", "worse_since": 100}
        self.assertEqual(server.transition(rec, "OPEN", 110, 60)[0]["worse_since"], None)

    def test_parse_rejects_page_without_numbers(self):
        with self.assertRaises(ValueError):
            server.parse_seats("<html>Service temporarily unavailable</html>")

    def test_parse_over_enrolled_section_is_full(self):
        info = server.parse_seats(FakeGT.page(32, 30, 0, 0))
        self.assertEqual((info["open"], server.status_of(info)), (-2, "FULL"))

    def test_normalize_and_clock(self):
        self.assertEqual(server.normalize("cs1332"), "CS 1332")
        self.assertEqual(server.normalize(" math  2550 "), "MATH 2550")
        self.assertEqual(server.clock("0800 - 0915"), "08:00–09:15")
        self.assertEqual(server.clock("TBA"), "TBA")

    def test_retryable(self):
        from urllib.error import HTTPError, URLError
        self.assertTrue(server.retryable(HTTPError("u", 503, "busy", {}, None)))
        self.assertTrue(server.retryable(HTTPError("u", 429, "slow down", {}, None)))
        self.assertFalse(server.retryable(HTTPError("u", 404, "missing", {}, None)))
        self.assertTrue(server.retryable(TimeoutError()))
        self.assertTrue(server.retryable(URLError("reset")))


class AtomicWrite(unittest.TestCase):
    def test_crash_mid_write_keeps_old_file(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        server.save_json(path, {"courses": ["CS 1332"]})
        with mock.patch.object(server.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                server.save_json(path, {"courses": []})
        self.assertEqual(json.loads(path.read_text()), {"courses": ["CS 1332"]})
        self.assertEqual([p.name for p in path.parent.iterdir()], ["config.json"])  # no temp file left


class LimiterTest(unittest.TestCase):
    def test_never_exceeds_limit(self):
        lim = server.Limiter(start=3, lo=1, hi=3)
        active = peak = 0
        lock = threading.Lock()

        def work():
            nonlocal active, peak
            lim.acquire()
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            lim.release(overloaded=False)

        threads = [threading.Thread(target=work) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertLessEqual(peak, 3)
        self.assertGreaterEqual(peak, 2)

    def test_halves_on_overload_and_grows_back(self):
        lim = server.Limiter(start=8, lo=1, hi=10)
        lim.acquire()
        lim.release(overloaded=True)
        self.assertEqual(lim.limit, 4)
        for _ in range(4):
            lim.acquire()
            lim.release(overloaded=False)
        self.assertEqual(lim.limit, 5)
        for _ in range(5):
            lim.acquire()
            lim.release(overloaded=True)
        self.assertEqual(lim.limit, 1)  # floor


class Fetching(Base):
    courses = {"CS 1332": [f"A{i:02}" for i in range(8)], "MATH 2550": [f"B{i:02}" for i in range(8)]}

    def test_overloaded_proxy_still_loads_everything(self):
        self.fake.cap, self.fake.delay = 3, 0.03
        w = self.watcher()
        w.check()
        self.assertGreater(self.fake.rejected, 0)  # the proxy did push back
        self.assertEqual(w.errors, {})
        self.assertEqual(len(w.seats), 16)

    def test_timeout_and_garbage_page_are_retried(self):
        hung, junk = self.fake.crn("CS 1332", "A00"), self.fake.crn("CS 1332", "A01")
        self.fake.hang.add(hung)
        self.fake.garbage.add(junk)
        self.fake.set(junk, 10)  # open: a misread as zeros would show FULL
        w = self.watcher()
        w.check()
        self.assertEqual(w.errors, {})
        self.assertEqual(w.seats[hung]["status"], "FULL")
        self.assertEqual(w.seats[junk]["status"], "OPEN")

    def test_failure_keeps_last_numbers(self):
        crn = self.fake.crn("CS 1332", "A00")
        w = self.watcher()
        w.check()
        self.fake.cap = 0  # everything 503s now
        w.check()
        self.assertIn(crn, w.errors)
        self.assertEqual(w.seats[crn]["status"], "FULL")  # old numbers still shown


class Alerts(Base):
    def test_one_push_when_seat_opens(self):
        crn = self.fake.crn("CS 1332", "B")
        w = self.watcher()
        w.check()
        self.settle(w)
        self.assertEqual(self.fake.pushes, [])  # first pass only records
        self.fake.set(crn, 28)
        w.check()
        self.settle(w)
        w.check()
        self.settle(w)
        self.assertEqual(len(self.fake.pushes), 1)
        self.assertEqual(self.fake.pushes[0]["title"], "CS 1332 B: seat open")
        self.assertIn(f"2 seat(s) open · CRN {crn}", self.fake.pushes[0]["body"])

    def test_already_open_at_startup_is_silent(self):
        self.fake.set(self.fake.crn("CS 1332", "A"), 10)
        w = self.watcher()
        w.check()
        self.settle(w)
        self.assertEqual(self.fake.pushes, [])

    def test_waitlist_then_seat(self):
        crn = self.fake.crn("MATH 2550", "A02")
        w = self.watcher()
        w.check()
        self.fake.set(crn, 30, wl_actual=3, wl_cap=5)
        w.check()
        self.settle(w)
        self.fake.set(crn, 29)
        w.check()
        self.settle(w)
        self.assertEqual([p["title"] for p in self.fake.pushes],
                         ["MATH 2550 A02: waitlist open", "MATH 2550 A02: seat open"])

    def test_flapping_sends_one_push(self):
        crn = self.fake.crn("CS 1332", "A")
        w = self.watcher()
        w.check()
        for enrolled in (29, 30, 29, 30, 29):
            self.fake.set(crn, enrolled)
            w.check()
            self.settle(w)
        self.assertEqual(len(self.fake.pushes), 1)

    def test_reopens_after_rearm_window(self):
        crn = self.fake.crn("CS 1332", "A")
        w = self.watcher()
        w.check()
        with mock.patch.object(server, "REARM", 0):
            for enrolled in (29, 30, 29):
                self.fake.set(crn, enrolled)
                w.check()
                self.settle(w)
        self.assertEqual(len(self.fake.pushes), 2)

    def test_ntfy_down_retries_next_pass(self):
        crn = self.fake.crn("CS 1332", "C")
        w = self.watcher()
        w.check()
        self.fake.ntfy_fail = 3  # every attempt this pass fails
        self.fake.set(crn, 25)
        w.check()
        self.settle(w)
        self.assertEqual(self.fake.pushes, [])
        self.assertEqual(w.records[crn]["announced"], "FULL")  # rolled back
        w.check()
        self.settle(w)
        self.assertEqual(len(self.fake.pushes), 1)
        self.assertEqual(self.saved(crn)["announced"], "OPEN")

    def test_no_topic_means_no_push(self):
        data = json.loads(self.config.read_text())
        data["ntfy_topic"] = ""
        self.config.write_text(json.dumps(data))
        w = self.watcher()
        w.check()
        self.fake.set(self.fake.crn("CS 1332", "A"), 1)
        w.check()
        self.settle(w)
        self.assertEqual(self.fake.pushes, [])


class Restart(Base):
    def test_restart_does_not_repeat_push(self):
        crn = self.fake.crn("CS 1332", "A")
        w = self.watcher()
        w.check()
        self.fake.set(crn, 20)
        w.check()
        self.settle(w)
        w.close()
        w2 = self.watcher()
        w2.check()
        self.settle(w2)
        self.assertEqual(len(self.fake.pushes), 1)

    def test_seat_opened_while_down_alerts_after_restart(self):
        crn = self.fake.crn("CS 1332", "A")
        w = self.watcher()
        w.check()
        w.close()
        self.fake.set(crn, 20)
        w2 = self.watcher()
        w2.check()
        self.settle(w2)
        self.assertEqual(len(self.fake.pushes), 1)

    def test_crash_before_push_resends(self):
        crn = self.fake.crn("CS 1332", "A")
        w = self.watcher(notifier=False)  # pushes queue up but never send: a crash
        w.check()
        self.fake.set(crn, 20)
        w.check()
        self.assertEqual(self.saved(crn)["announced"], "FULL")  # disk keeps the pre-alert state
        w2 = self.watcher()
        w2.check()
        self.settle(w2)
        self.assertEqual(len(self.fake.pushes), 1)

    def test_corrupt_state_file_starts_fresh(self):
        self.state_file.write_text("{not json")
        w = self.watcher()
        self.assertEqual(w.records, {})

    def test_new_term_ignores_old_state(self):
        self.state_file.write_text(json.dumps({"term": "202608", "records": {"10000": {"announced": "OPEN", "worse_since": None}}}))
        self.assertEqual(self.watcher().records, {})


class Races(Base):
    courses = {f"CS {1000 + i}": ["A", "B"] for i in range(10)}

    def test_concurrent_adds_keep_config_valid(self):
        data = json.loads(self.config.read_text())
        data["courses"] = []
        self.config.write_text(json.dumps(data))
        w = self.watcher()
        real = w.sections_of

        def slow_lookup(cid):  # widen the window between "is it tracked?" and "append"
            time.sleep(0.05)
            return real(cid)

        w.sections_of = slow_lookup
        results = []
        ids = list(self.courses) * 3  # every course added three times at once
        threads = [threading.Thread(target=lambda c=c: results.append(w.add_course(c)[0])) for c in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        saved = json.loads(self.config.read_text())["courses"]
        self.assertEqual(sorted(saved), sorted(self.courses))
        self.assertEqual(results.count(200), 10)
        self.assertEqual(results.count(409), 20)

    def test_remove_during_pass(self):
        self.fake.delay = 0.2
        w = self.watcher()
        last = list(self.courses)[-1]
        crns = list(self.fake.courses[last].values())
        t = threading.Thread(target=w.check)
        t.start()
        time.sleep(0.1)
        w.remove_course(last)
        t.join()
        for crn in crns:
            self.assertNotIn(crn, w.seats)
            self.assertNotIn(crn, w.records)
            self.assertNotIn(crn, w.errors)

    def test_passes_never_overlap(self):
        w = self.watcher()
        real, active, peak, runs = w.check, 0, 0, 0
        lock = threading.Lock()

        def tracked():
            nonlocal active, peak, runs
            with lock:
                active += 1
                runs += 1
                peak = max(peak, active)
            try:
                real()
            finally:
                with lock:
                    active -= 1

        w.check = tracked
        threading.Thread(target=w.run, daemon=True).start()
        for _ in range(50):
            w.wake.set()
            time.sleep(0.005)
        wait_until(lambda: runs >= 2)
        self.assertEqual(peak, 1)


class HttpApi(Base):
    def setUp(self):
        super().setUp()
        self.w = self.watcher()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.watcher = self.w
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, method, path, body=None):
        req = Request(self.base + path, method=method, data=None if body is None else body.encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read() or b"{}")
        except Exception as e:  # HTTPError carries the status
            return e.code, json.loads(e.read())

    def test_course_edits(self):
        self.fake.courses["CS 3510"] = {"A": "20000"}
        self.fake.seats["20000"] = [1, 30, 0, 0]
        self.w._terms.clear()
        self.assertEqual(self.call("POST", "/api/courses", '{"id": "cs3510"}')[0], 200)
        self.assertEqual(self.call("POST", "/api/courses", '{"id": "CS 3510"}')[0], 409)
        self.assertEqual(self.call("POST", "/api/courses", '{"id": "XX 9999"}')[0], 404)
        self.assertEqual(self.call("POST", "/api/courses", '{"id": "bad"}')[0], 400)
        self.assertEqual(self.call("POST", "/api/courses", "not json")[0], 400)
        self.assertEqual(self.call("POST", "/api/courses", json.dumps({"id": "x" * 2000}))[0], 413)
        self.assertEqual(self.call("DELETE", "/api/courses", '{"id": "CS 3510"}')[0], 200)
        self.assertNotIn("CS 3510", json.loads(self.config.read_text())["courses"])

    def test_state_and_live_events(self):
        code, state = self.call("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(state["courses"][0]["name"], "CS 1332 & Friends")
        with urlopen(self.base + "/api/events", timeout=3) as stream:
            first = json.loads(stream.readline().decode().removeprefix("data: "))
            self.assertEqual(first["courses"][0]["sections"][0]["status"], "CHECKING")
            stream.readline()  # blank line between events
            threading.Thread(target=self.w.check, daemon=True).start()
            for _ in range(20):  # the next events should carry real numbers
                line = stream.readline().decode()
                if line.startswith("data: ") and json.loads(line[6:])["lastCheck"]:
                    break
            else:
                self.fail("no update after the check pass")
        self.w.close()  # lets the server's event loop exit


if __name__ == "__main__":
    unittest.main()
