"""Core GT seat-checking logic — library form (no CLI)."""

import json
import os
import re
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from urllib.request import Request, urlopen

CRAWLER_URL = "https://gt-scheduler.github.io/crawler-v2/{term}.json"
SECTION_URL = "https://gt-scheduler.azurewebsites.net/proxy/class_section?term={term}&crn={crn}"
GT_SCHEDULER_SITE = "https://gt-scheduler.github.io/"
DEFAULT_NTFY_SERVER = "https://ntfy.sh"
DEFAULT_INTERVAL = 60


# ---------------------------------------------------------------------------
# SSL
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(path):
            try:
                ctx.load_verify_locations(path)
                return ctx
            except ssl.SSLError:
                pass
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

_CTX = _ssl_context()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class Section:
    crn: str
    course_id: str
    section_id: str
    course_name: str


@dataclass
class SeatInfo:
    enrollment_actual: int = 0
    enrollment_maximum: int = 0
    enrollment_seats_available: int = 0
    waitlist_capacity: int = 0
    waitlist_actual: int = 0
    waitlist_seats_available: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Section discovery
# ---------------------------------------------------------------------------

_term_cache: dict[str, dict] = {}


def fetch_term_data(term: str) -> dict:
    if term in _term_cache:
        return _term_cache[term]
    req = Request(CRAWLER_URL.format(term=term), headers={"User-Agent": "gt-seat-notifier/1.0"})
    with urlopen(req, timeout=30, context=_CTX) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    _term_cache[term] = data
    return data


def normalize_course_id(course_id: str) -> str:
    s = course_id.strip().upper()
    return re.sub(r"([A-Z]+)(\d)", r"\1 \2", s)


def discover_sections(term: str, course_ids: list[str]) -> tuple[list[Section], list[str]]:
    """Returns (sections, warnings)."""
    data = fetch_term_data(term)
    courses_data = data.get("courses", {})
    sections: list[Section] = []
    warnings: list[str] = []

    for course_id in course_ids:
        normalized = normalize_course_id(course_id)
        entry = courses_data.get(normalized) or courses_data.get(course_id)
        if entry is None:
            similar = [k for k in courses_data if course_id.replace(" ", "").upper() in k.replace(" ", "")]
            msg = f"'{normalized}' not found in term {term}"
            if similar:
                msg += f". Similar: {', '.join(similar[:5])}"
            warnings.append(msg)
            continue

        full_name = entry[0]
        sections_dict = entry[1] if len(entry) > 1 else {}
        if not isinstance(sections_dict, dict):
            continue

        for section_id, section_tuple in sections_dict.items():
            if section_tuple and isinstance(section_tuple, (list, tuple)):
                sections.append(Section(
                    crn=str(section_tuple[0]),
                    course_id=normalized,
                    section_id=section_id,
                    course_name=full_name,
                ))

    return sections, warnings


# ---------------------------------------------------------------------------
# Seat fetching
# ---------------------------------------------------------------------------

SPAN_RE = re.compile(
    r'<span class="status-bold">([^<]+):</span>\s*<span[^>]*>([^<]+)</span>',
    re.DOTALL,
)


def fetch_seat_info(term: str, crn: str) -> SeatInfo:
    req = Request(SECTION_URL.format(term=term, crn=crn), headers={"User-Agent": "gt-seat-notifier/1.0"})
    with urlopen(req, timeout=15, context=_CTX) as resp:
        html = resp.read().decode("utf-8")

    fields = {label.strip(): value.strip() for label, value in SPAN_RE.findall(html)}

    def i(label: str) -> int:
        try:
            return int(fields.get(label, "0"))
        except ValueError:
            return 0

    return SeatInfo(
        enrollment_actual=i("Enrollment Actual"),
        enrollment_maximum=i("Enrollment Maximum"),
        enrollment_seats_available=i("Enrollment Seats Available"),
        waitlist_capacity=i("Waitlist Capacity"),
        waitlist_actual=i("Waitlist Actual"),
        waitlist_seats_available=i("Waitlist Seats Available"),
    )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def send_notification(ntfy_server: str, ntfy_topic: str, section: Section,
                      seats: SeatInfo, priority: str, tags: list[str]) -> None:
    if seats.enrollment_seats_available > 0:
        seat_line = f"{seats.enrollment_seats_available} seat(s) open | {seats.enrollment_actual}/{seats.enrollment_maximum} enrolled"
    else:
        seat_line = f"{seats.waitlist_seats_available} waitlist spot(s) | {seats.waitlist_actual}/{seats.waitlist_capacity} WL"

    payload = {
        "topic": ntfy_topic,
        "title": f"\U0001f7e2 {section.course_id} §{section.section_id} opened!",
        "message": f"{section.course_name}\n{seat_line}\nCRN: {section.crn}",
        "priority": priority,
        "tags": tags,
        "click": GT_SCHEDULER_SITE,
    }

    data = json.dumps(payload).encode("utf-8")
    req = Request(f"{ntfy_server}/", data=data, method="POST",
                  headers={"Content-Type": "application/json", "User-Agent": "gt-seat-notifier/1.0"})
    with urlopen(req, timeout=15, context=_CTX):
        pass


# ---------------------------------------------------------------------------
# Parallel fetch
# ---------------------------------------------------------------------------

def fetch_all(sections: list[Section], term: str, ntfy_server: str, ntfy_topic: str,
              state: dict, errors: dict, notified: dict) -> None:
    def _fetch_one(section: Section) -> None:
        try:
            seats = fetch_seat_info(term, section.crn)
            state[section.crn] = seats
            errors.pop(section.crn, None)

            if seats.enrollment_seats_available > 0:
                if notified.get(section.crn) != "seat":
                    send_notification(ntfy_server, ntfy_topic, section, seats,
                                      priority="urgent", tags=["tada", "school"])
                    notified[section.crn] = "seat"
            elif seats.waitlist_seats_available > 0:
                if notified.get(section.crn) not in ("seat", "waitlist"):
                    send_notification(ntfy_server, ntfy_topic, section, seats,
                                      priority="high", tags=["hourglass_flowing_sand", "school"])
                    notified[section.crn] = "waitlist"
            else:
                notified.pop(section.crn, None)
        except Exception as exc:
            errors[section.crn] = str(exc)

    total = len(sections)
    with ThreadPoolExecutor(max_workers=min(total, 20)) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in sections}
        for fut in as_completed(futures):
            fut.result()
