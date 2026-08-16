#!/usr/bin/env python3
"""GT Course Seat Notifier — local daemon, stdlib only."""

import json
import os
import re
import select
import shutil
import ssl
import sys
import termios
import time
import threading
import tty
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

CRAWLER_URL = "https://gt-scheduler.github.io/crawler-v2/{term}.json"
SECTION_URL = "https://gt-scheduler.azurewebsites.net/proxy/class_section?term={term}&crn={crn}"
GT_SCHEDULER_SITE = "https://gt-scheduler.github.io/"
DEFAULT_NTFY_SERVER = "https://ntfy.sh"
DEFAULT_INTERVAL = 60


# ---------------------------------------------------------------------------
# ANSI helpers — luna palette
# ---------------------------------------------------------------------------

def _fg(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"

def _bg(r: int, g: int, b: int) -> str:
    return f"\033[48;2;{r};{g};{b}m"

RST   = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
REV   = "\033[7m"

# luna palette
C_YELLOW   = _fg(255, 230,  89)   # YJSP yellow — accent / headers
C_WHITE    = _fg(238, 238, 238)   # default text
C_GREY     = _fg(187, 187, 187)   # dim labels
C_DKGREY   = _fg( 68,  68,  68)  # very dim / separators
C_RED      = _fg(255,  89,  89)  # error text

# status badge backgrounds
BG_GREEN   = _bg(122, 255, 133)   # open seat
BG_RED     = _bg(255,  89,  89)   # full
BG_BLUE    = _bg(117, 168, 255)   # waitlist
BG_GREY    = _bg( 68,  68,  68)   # pending/unknown
FG_BLACK   = _fg(  0,   0,   0)

# box drawing
H  = "─"
V  = "│"
TL = "┌"; TR = "┐"; BL = "└"; BR = "┘"
LM = "├"; RM = "┤"; TM = "┬"; BM = "┴"; XX = "┼"


def badge(text: str, bg: str, width: int = 0) -> str:
    padded = f" {text} "
    if width:
        padded = padded.center(width)
    return f"{bg}{FG_BLACK}{BOLD}{padded}{RST}"


def hline(widths: list[int], left: str, mid: str, right: str, cross: str) -> str:
    segs = [H * w for w in widths]
    return left + cross.join(segs) + right


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
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    ntfy_topic: str
    term: str
    courses: list[str]
    ntfy_server: str = DEFAULT_NTFY_SERVER
    interval: int = DEFAULT_INTERVAL


def load_config(path: str = "config.json") -> Config:
    if not os.path.exists(path):
        print("[ERROR] config.json not found. Copy config.json.example.", flush=True)
        sys.exit(1)
    with open(path) as f:
        raw = json.load(f)
    for key in ("ntfy_topic", "term", "courses"):
        if not raw.get(key):
            print(f"[ERROR] Missing '{key}' in config.json", flush=True)
            sys.exit(1)
    return Config(
        ntfy_topic=raw["ntfy_topic"],
        term=str(raw["term"]),
        courses=raw["courses"],
        ntfy_server=raw.get("ntfy_server", DEFAULT_NTFY_SERVER).rstrip("/"),
        interval=int(raw.get("interval", DEFAULT_INTERVAL)),
    )


# ---------------------------------------------------------------------------
# Section discovery
# ---------------------------------------------------------------------------

@dataclass
class Section:
    crn: str
    course_id: str
    section_id: str
    course_name: str


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


def discover_sections(term: str, course_ids: list[str]) -> list[Section]:
    data = fetch_term_data(term)
    courses_data = data.get("courses", {})
    sections: list[Section] = []

    for course_id in course_ids:
        normalized = normalize_course_id(course_id)
        entry = courses_data.get(normalized) or courses_data.get(course_id)
        if entry is None:
            similar = [k for k in courses_data if course_id.replace(" ", "").upper() in k.replace(" ", "")]
            print(f"[WARN] '{normalized}' not found in term {term}", flush=True)
            if similar:
                print(f"       Similar: {', '.join(similar[:5])}", flush=True)
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

    return sections


# ---------------------------------------------------------------------------
# Seat info
# ---------------------------------------------------------------------------

SPAN_RE = re.compile(
    r'<span class="status-bold">([^<]+):</span>\s*<span[^>]*>([^<]+)</span>',
    re.DOTALL,
)


@dataclass
class SeatInfo:
    enrollment_actual: int = 0
    enrollment_maximum: int = 0
    enrollment_seats_available: int = 0
    waitlist_capacity: int = 0
    waitlist_actual: int = 0
    waitlist_seats_available: int = 0


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
        seat_line = f"{seats.enrollment_seats_available} vaga(s) | {seats.enrollment_actual}/{seats.enrollment_maximum} enrolled"
    else:
        seat_line = f"{seats.waitlist_seats_available} vaga(s) na fila | {seats.waitlist_actual}/{seats.waitlist_capacity} WL"

    payload = {
        "topic": ntfy_topic,
        "title": f"\U0001f7e2 {section.course_id} §{section.section_id} abriu!",
        "message": f"{section.course_name}\n{seat_line}\nCRN: {section.crn}",
        "priority": priority,
        "tags": tags,
        "click": GT_SCHEDULER_SITE,
    }

    data = json.dumps(payload).encode("utf-8")
    req = Request(f"{ntfy_server}/", data=data, method="POST",
                  headers={"Content-Type": "application/json", "User-Agent": "gt-seat-notifier/1.0"})
    with urlopen(req, timeout=15, context=_CTX) as resp:
        pass


# ---------------------------------------------------------------------------
# Fetch loop
# ---------------------------------------------------------------------------

_notified: dict[str, str] = {}
_state:    dict[str, SeatInfo] = {}
_errors:   dict[str, str] = {}
_render_lock = threading.Lock()


def _fetch_one(section: Section, config: Config) -> None:
    try:
        seats = fetch_seat_info(config.term, section.crn)
        _state[section.crn] = seats
        _errors.pop(section.crn, None)

        if seats.enrollment_seats_available > 0:
            if _notified.get(section.crn) != "seat":
                send_notification(config.ntfy_server, config.ntfy_topic, section, seats,
                                  priority="urgent", tags=["tada", "school"])
                _notified[section.crn] = "seat"
        elif seats.waitlist_seats_available > 0:
            if _notified.get(section.crn) not in ("seat", "waitlist"):
                send_notification(config.ntfy_server, config.ntfy_topic, section, seats,
                                  priority="high", tags=["hourglass_flowing_sand", "school"])
                _notified[section.crn] = "waitlist"
        else:
            _notified.pop(section.crn, None)
    except Exception as exc:
        _errors[section.crn] = str(exc)


def fetch_all(sections: list[Section], config: Config,
              on_progress: "Callable[[int,int],None] | None" = None) -> None:
    total = len(sections)
    done = 0
    with ThreadPoolExecutor(max_workers=min(total, 20)) as pool:
        futures = {pool.submit(_fetch_one, s, config): s for s in sections}
        for fut in as_completed(futures):
            fut.result()
            done += 1
            if on_progress:
                on_progress(done, total)


# ---------------------------------------------------------------------------
# Terminal / keyboard helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\033\[[^m]*m")

def vlen(s: str) -> int:
    return len(_ANSI_RE.sub("", s))

def rpad(s: str, width: int) -> str:
    return s + " " * max(0, width - vlen(s))

def truncate(s: str, width: int) -> str:
    """Truncate plain string to width."""
    return s[:width - 1] + "…" if len(s) > width else s


def read_key() -> str:
    """Read one keypress (raw). Returns escape sequences as-is."""
    ch = sys.stdin.read(1)
    if ch == "\033":
        # check for more bytes (arrow keys etc.)
        if select.select([sys.stdin], [], [], 0.05)[0]:
            ch += sys.stdin.read(1)
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch += sys.stdin.read(1)
    return ch


# ---------------------------------------------------------------------------
# Dashboard renderer  (split layout: left menu | right sections)
# ---------------------------------------------------------------------------

def _course_summary(secs: list[Section]) -> str:
    open_s = sum(1 for s in secs if _state.get(s.crn) and _state[s.crn].enrollment_seats_available > 0)
    open_w = sum(1 for s in secs if _state.get(s.crn) and _state[s.crn].waitlist_seats_available > 0
                 and _state[s.crn].enrollment_seats_available == 0)
    loading = sum(1 for s in secs if s.crn not in _state and s.crn not in _errors)
    if open_s:
        return badge(f" {open_s} OPEN ", BG_GREEN)
    if open_w:
        return badge(f" {open_w} WL ", BG_BLUE)
    if loading:
        return f"{DIM}loading…{RST}"
    return f"{C_DKGREY}full{RST}"


def render(
    sections: list[Section],
    config: Config,
    courses: list[str],
    by_course: dict[str, list[Section]],
    selected: int,
    last_update: str,
    next_in: int,
    loaded: int,
) -> None:
    sz        = shutil.get_terminal_size((120, 40))
    TW        = sz.columns
    TH        = sz.lines

    W_MENU    = 22   # left panel inner width
    # right panel: rest minus borders
    W_RIGHT   = TW - W_MENU - 3  # 3 = left border + divider + right border

    # right section table col widths
    W_SEC     = 5
    W_CRN     = 6
    W_ENR     = 11
    W_SEAT    = 6
    W_WL      = 10
    W_WLA     = 7
    W_STAT    = 12
    W_RTOTAL  = W_SEC + W_CRN + W_ENR + W_SEAT + W_WL + W_WLA + W_STAT + 6

    col_ws    = [W_SEC, W_CRN, W_ENR, W_SEAT, W_WL, W_WLA, W_STAT]

    total_sections = len(sections)
    fetching = loaded < total_sections

    # status string for header
    if fetching:
        status_str = f"{DIM} fetching {loaded}/{total_sections}… {RST}"
    else:
        status_str = f"{DIM} refreshing in {next_in}s  {last_update} {RST}"

    out: list[str] = []

    # ── header ──────────────────────────────────────────────────────────────
    header_inner = TW - 2
    htitle = f" {BOLD}{C_YELLOW}GT Seat Notifier{RST}  {C_GREY}term={RST}{C_WHITE}{config.term}{RST} "
    hgap   = header_inner - vlen(htitle) - vlen(status_str)
    out.append(f"{C_YELLOW}{BOLD}{TL}{H * header_inner}{TR}{RST}")
    out.append(
        f"{C_YELLOW}{BOLD}{V}{RST}"
        + htitle
        + " " * max(0, hgap)
        + status_str
        + f"{C_YELLOW}{BOLD}{V}{RST}"
    )

    # ── menu/content divider ─────────────────────────────────────────────────
    # ├──────────────────────┬──── ... ────┤
    out.append(
        f"{C_YELLOW}{BOLD}{LM}{RST}"
        f"{C_DKGREY}{H * (W_MENU + 2)}{RST}"
        f"{C_YELLOW}{BOLD}{TM}{RST}"
        f"{C_DKGREY}{H * (W_RIGHT + 1)}{RST}"
        f"{C_YELLOW}{BOLD}{RM}{RST}"
    )

    # ── body rows ────────────────────────────────────────────────────────────
    course_id   = courses[selected] if courses else ""
    secs_all    = by_course.get(course_id, [])

    def sort_key(s: Section) -> tuple:
        info = _state.get(s.crn)
        if info is None:
            return (3, 0)
        if info.enrollment_seats_available > 0:
            return (0, -info.enrollment_seats_available)
        if info.waitlist_seats_available > 0:
            return (1, -info.waitlist_seats_available)
        return (2, 0)

    secs_sorted = sorted(secs_all, key=sort_key)

    # build right-panel lines
    right_lines: list[str] = []

    # right header
    sel_name   = secs_sorted[0].course_name if secs_sorted else course_id
    sel_summary = _course_summary(secs_all)
    rh = f" {BOLD}{C_YELLOW}{course_id}{RST} {C_GREY}{truncate(sel_name, W_RIGHT - len(course_id) - 12)}{RST}  {sel_summary} "
    right_lines.append(rpad(rh, W_RIGHT + 1))

    # col headers
    def row_right(*cells: str) -> str:
        parts = [rpad(c, w) for c, w in zip(cells, col_ws)]
        return f"{C_DKGREY}{V}{RST}".join(parts)

    right_lines.append(
        f"{C_DKGREY}{H * (W_RIGHT + 1)}{RST}"
    )
    right_lines.append(row_right(
        f"{DIM} §{RST}", f"{DIM}CRN{RST}", f"{DIM}Enrolled{RST}",
        f"{DIM}Seats{RST}", f"{DIM}Waitlist{RST}", f"{DIM}WL Avl{RST}", f"{DIM}Status{RST}",
    ))
    right_lines.append(
        f"{C_DKGREY}{H * W_SEC}{XX}{H * W_CRN}{XX}{H * W_ENR}{XX}{H * W_SEAT}{XX}{H * W_WL}{XX}{H * W_WLA}{XX}{H * W_STAT}{RST}"
    )

    for s in secs_sorted:
        info = _state.get(s.crn)
        err  = _errors.get(s.crn)

        if info is None:
            msg = f"{C_RED}{err[:20]}{RST}" if err else f"{DIM}loading…{RST}"
            right_lines.append(row_right(
                f"{C_GREY} {s.section_id}{RST}", f"{C_GREY}{s.crn}{RST}",
                msg, "", "", "", "",
            ))
            continue

        enroll_str = f"{info.enrollment_actual}/{info.enrollment_maximum}"
        wl_str     = f"{info.waitlist_actual}/{info.waitlist_capacity}"

        if info.enrollment_seats_available > 0:
            stat     = badge("OPEN", BG_GREEN, W_STAT)
            seat_val = f"{BOLD}{_fg(122,255,133)}{info.enrollment_seats_available}{RST}"
            wla_val  = f"{C_GREY}{info.waitlist_seats_available}{RST}"
            sec_col  = f"{BOLD}{C_WHITE} {s.section_id}{RST}"
        elif info.waitlist_seats_available > 0:
            stat     = badge("WAITLIST", BG_BLUE, W_STAT)
            seat_val = f"{C_GREY}0{RST}"
            wla_val  = f"{BOLD}{_fg(117,168,255)}{info.waitlist_seats_available}{RST}"
            sec_col  = f"{C_WHITE} {s.section_id}{RST}"
        else:
            stat     = badge("FULL", BG_RED, W_STAT)
            seat_val = f"{DIM}0{RST}"
            wla_val  = f"{DIM}0{RST}"
            sec_col  = f"{C_GREY} {s.section_id}{RST}"

        right_lines.append(row_right(
            sec_col,
            f"{C_GREY}{s.crn}{RST}",
            f"{C_WHITE}{enroll_str:>{W_ENR-1}}{RST}",
            f" {seat_val}",
            f"{C_GREY}{wl_str:>{W_WL-1}}{RST}",
            f" {wla_val}",
            stat,
        ))

    # available body height = TH - header(2) - divider(1) - footer(2)
    body_h = max(1, TH - 5)

    for row_i in range(body_h):
        # left menu cell
        if row_i < len(courses):
            cid  = courses[row_i]
            csec = by_course.get(cid, [])
            summ = _course_summary(csec)
            is_sel = row_i == selected
            label  = truncate(cid, W_MENU - vlen(summ) - 3)
            if is_sel:
                menu_cell = (
                    f" {REV}{C_YELLOW}{BOLD}❯{RST} "
                    f"{REV}{C_WHITE}{BOLD}{rpad(label, W_MENU - vlen(summ) - 3)}{RST}"
                    f" {summ} "
                )
            else:
                menu_cell = (
                    f"   {C_GREY}{rpad(label, W_MENU - vlen(summ) - 3)}{RST}"
                    f" {summ} "
                )
        else:
            menu_cell = " " * (W_MENU + 2)

        # right panel cell
        if row_i < len(right_lines):
            right_cell = right_lines[row_i]
        else:
            right_cell = ""

        out.append(
            f"{C_YELLOW}{BOLD}{V}{RST}"
            + rpad(menu_cell, W_MENU + 2)
            + f"{C_DKGREY}{V}{RST}"
            + rpad(f" {right_cell}", W_RIGHT + 1)
            + f"{C_YELLOW}{BOLD}{V}{RST}"
        )

    # ── footer ───────────────────────────────────────────────────────────────
    out.append(
        f"{C_YELLOW}{BOLD}{LM}{RST}"
        f"{C_DKGREY}{H * (W_MENU + 2)}{RST}"
        f"{C_YELLOW}{BOLD}{BM}{RST}"
        f"{C_DKGREY}{H * (W_RIGHT + 1)}{RST}"
        f"{C_YELLOW}{BOLD}{RM}{RST}"
    )
    nav = f"  {DIM}↑↓ navigate   q quit{RST}"
    out.append(
        f"{C_YELLOW}{BOLD}{BL}{H * header_inner}{BR}{RST}"
        + nav
    )

    with _render_lock:
        print("\033[H\033[J" + "\n".join(out), end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()

    print(f"{C_YELLOW}{BOLD}GT Seat Notifier{RST}  term={config.term}", flush=True)
    print("Fetching section data...", flush=True)

    try:
        sections = discover_sections(config.term, config.courses)
    except Exception as exc:
        print(f"[ERROR] {exc}", flush=True)
        sys.exit(1)

    if not sections:
        print("[ERROR] No sections found.", flush=True)
        sys.exit(1)

    by_course: dict[str, list[Section]] = {}
    for s in sections:
        by_course.setdefault(s.course_id, []).append(s)
    courses = list(by_course.keys())

    # shared state for fetch thread communication
    state = {
        "selected":    0,
        "loaded":      0,
        "last_update": "–",
        "next_in":     config.interval,
        "running":     True,
    }
    state_lock = threading.Lock()

    def on_progress(done: int, total: int) -> None:
        with state_lock:
            state["loaded"] = done
            state["last_update"] = time.strftime("%H:%M:%S") if done == total else "–"

    def fetch_loop() -> None:
        while state["running"]:
            with state_lock:
                state["loaded"] = 0
            fetch_all(sections, config, on_progress=on_progress)
            deadline = time.time() + config.interval
            while state["running"]:
                remaining = int(deadline - time.time())
                if remaining <= 0:
                    break
                with state_lock:
                    state["next_in"] = remaining
                time.sleep(0.5)

    # start fetch thread
    t = threading.Thread(target=fetch_loop, daemon=True)
    t.start()

    # put terminal in raw mode for single-key input
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    print("\033[2J\033[H\033[?25l", end="", flush=True)  # clear + hide cursor

    try:
        tty.setcbreak(fd)  # cbreak: raw keys but keep Ctrl+C signal
        while True:
            # non-blocking key read (50ms poll)
            if select.select([sys.stdin], [], [], 0.05)[0]:
                key = read_key()
                if key in ("\033[A", "k"):   # up
                    state["selected"] = max(0, state["selected"] - 1)
                elif key in ("\033[B", "j"): # down
                    state["selected"] = min(len(courses) - 1, state["selected"] + 1)
                elif key in ("q", "\x03", "\x1b"):  # q / Ctrl+C / Esc
                    break

            with state_lock:
                sel      = state["selected"]
                loaded   = state["loaded"]
                lu       = state["last_update"]
                next_in  = state["next_in"]

            render(sections, config, courses, by_course, sel, lu, next_in, loaded)

    finally:
        state["running"] = False
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print(f"\033[2J\033[H\033[?25h{RST}Stopped.\n", flush=True)


if __name__ == "__main__":
    main()
