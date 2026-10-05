#!/usr/bin/env python3
"""ESPN-style live NFL scoreboard for your terminal.

Score cards in a grid (adapts to terminal width), LIVE games pinned on top,
then upcoming, then final. Redraws in place; polls every 5s while games are
live, 30s otherwise. Recent scoring is flagged with ▲ for 45 seconds.

Usage:
  ./nfl_live.py              # all games this NFL week
  ./nfl_live.py --sunday     # only Sunday games
  ./nfl_live.py -i 3         # fixed refresh interval (seconds)
  ./nfl_live.py --once       # print once and exit
Ctrl+C to quit. Data: ESPN public scoreboard API (no key needed).
"""
import argparse
import json
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
LIVE_INTERVAL, IDLE_INTERVAL, FLAG_SECONDS = 5, 30, 45
INNER = 34  # card inner width

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
GREEN, YELLOW, RED, CYAN, WHITE = "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[97m"
ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")

# game id -> {team abbr: (last score, time of last change, points scored)}
score_memory = {}


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "nfl-live-cli"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r)


def vlen(s):
    return len(ANSI.sub("", s))


def pad(s, w):
    return s + " " * max(0, w - vlen(s))


def local_start(event):
    return datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone()


def state_of(event):
    return event["status"]["type"]["state"]  # pre | in | post


def chip(team):
    """Team abbreviation on a background of the team's own color."""
    abbr = team.get("abbreviation", "???")
    try:
        r, g, b = (int(team["color"][i:i + 2], 16) for i in (0, 2, 4))
        return f"\033[48;2;{r};{g};{b}m{WHITE}{BOLD} {abbr:<3} {RESET}"
    except (KeyError, ValueError):
        return f"{BOLD} {abbr:<3} {RESET}"


def track_scores(event):
    mem = score_memory.setdefault(event["id"], {})
    for c in event["competitions"][0]["competitors"]:
        abbr, score = c["team"].get("abbreviation", "?"), int(c.get("score") or 0)
        prev = mem.get(abbr)
        if prev is None:
            mem[abbr] = (score, 0.0, 0)  # first sighting: don't flag
        elif score != prev[0]:
            mem[abbr] = (score, time.time(), score - prev[0])
    return mem


def card(event):
    """One ESPN-style score card as a list of equal-width lines."""
    comp, status, state = event["competitions"][0], event["status"], state_of(event)
    teams = {c["homeAway"]: c for c in comp["competitors"]}
    mem = track_scores(event)
    sit = comp.get("situation") or {}
    border = GREEN if state == "in" else DIM

    if state == "in":
        detail = "Halftime" if status["type"].get("name") == "STATUS_HALFTIME" else status["type"]["shortDetail"]
        head = f"{GREEN}{BOLD}● {detail}{RESET}"
    elif state == "post":
        head = f"{BOLD}{status['type']['shortDetail']}{RESET}"
    else:
        head = f"{CYAN}{local_start(event).strftime('%a %-I:%M %p')}{RESET}"
    net = next((n for b in comp.get("broadcasts", []) for n in b.get("names", [])), "")
    head = pad(head, INNER - len(net)) + f"{DIM}{net}{RESET}"

    rows = []
    for side in ("away", "home"):
        t = teams[side]
        team = t["team"]
        rec = next((r["summary"] for r in t.get("records", []) if r.get("type") == "total"), "")
        has_ball = state == "in" and sit.get("possession") == t.get("id")
        won = state == "post" and t.get("winner")
        lost = state == "post" and not t.get("winner")
        score = str(t.get("score", 0)) if state != "pre" else ""
        flag = ""
        last = mem.get(team.get("abbreviation", "?"))
        if state == "in" and last and last[2] > 0 and time.time() - last[1] < FLAG_SECONDS:
            flag = f"{YELLOW}▲+{last[2]} {RESET}"
        name_style = DIM if lost else (BOLD if won or state == "in" else "")
        left = f"{YELLOW}▸{RESET}" if has_ball else " "
        left += f"{chip(team)} {name_style}{team.get('shortDisplayName', '')}{RESET} {DIM}{rec}{RESET}"
        right = f"{flag}{name_style}{score:>3}{RESET}"
        rows.append(pad(left, INNER - vlen(right)) + right)

    if state == "in":
        foot = sit.get("downDistanceText") or ""
        if sit.get("isRedZone"):
            foot += f"  {RED}{BOLD}RED ZONE{RESET}"
    elif state == "pre":
        odds = (comp.get("odds") or [{}])[0].get("details")
        foot = f"{DIM}{odds}{RESET}" if odds else ""
    else:
        foot = ""

    body = [head, *rows, foot]
    top, bot = f"{border}┌{'─' * (INNER + 2)}┐{RESET}", f"{border}└{'─' * (INNER + 2)}┘{RESET}"
    return [top] + [f"{border}│{RESET} {pad(l, INNER)} {border}│{RESET}" for l in body] + [bot]


def section(title, events, cols, color):
    if not events:
        return []
    out = [f"{color}{BOLD}{title}{RESET} {DIM}({len(events)}){RESET}"]
    cards = [card(e) for e in events]
    for i in range(0, len(cards), cols):
        chunk = cards[i:i + cols]
        out += ["  ".join(c[n] for c in chunk) for n in range(len(chunk[0]))]
    return out + [""]


def build_screen(data, sunday_only):
    events = data.get("events", [])
    if sunday_only:
        events = [e for e in events if local_start(e).weekday() == 6]
    events.sort(key=lambda e: e["date"])
    groups = {s: [e for e in events if state_of(e) == s] for s in ("in", "pre", "post")}

    width = shutil.get_terminal_size((100, 40)).columns
    cols = max(1, (width + 2) // (INNER + 4 + 2))

    live = len(groups["in"])
    status = f"{GREEN}{BOLD}● {live} LIVE{RESET}" if live else f"{DIM}no live games{RESET}"
    week = data.get("week", {}).get("number", "?")
    title = f"{BOLD}NFL SCOREBOARD{RESET} {DIM}· Week {week}{' · Sunday' if sunday_only else ''}{RESET}"
    out = [f"{title}   {status}   {DIM}updated {datetime.now().strftime('%-I:%M:%S %p')}{RESET}", ""]
    if not events:
        out.append("No games found." if not sunday_only else "No Sunday games found (try without --sunday).")
    out += section("LIVE", groups["in"], cols, GREEN)
    out += section("UPCOMING", groups["pre"], cols, CYAN)
    out += section("FINAL", groups["post"], cols, "")
    return out, live > 0


def draw(lines, footer):
    """Redraw in place; clip to terminal height so it never scrolls."""
    height = shutil.get_terminal_size((100, 40)).lines
    lines = lines[:height - 1]
    buf = ["\033[H"] + [l + "\033[K\n" for l in lines] + [footer + "\033[K", "\033[J"]
    sys.stdout.write("".join(buf))
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="ESPN-style live NFL scoreboard")
    ap.add_argument("-i", "--interval", type=int, help="fixed refresh seconds (default: 5 live / 30 idle)")
    ap.add_argument("-s", "--sunday", action="store_true", help="only show Sunday games")
    ap.add_argument("--once", action="store_true", help="print once and exit")
    args = ap.parse_args()

    if args.once:
        lines, _ = build_screen(fetch(), args.sunday)
        print("\n".join(lines))
        return

    sys.stdout.write("\033[?1049h\033[?25l")  # alt screen, hide cursor
    lines, any_live, err = ["Loading..."], False, ""
    try:
        while True:
            try:
                lines, any_live = build_screen(fetch(), args.sunday)
                err = ""
            except Exception as ex:  # network hiccup: keep last good data
                err = f"{RED}Fetch failed ({ex}) — showing last data{RESET}"
            end = time.time() + (args.interval or (LIVE_INTERVAL if any_live else IDLE_INTERVAL))
            while (left := end - time.time()) > 0:
                draw(lines, f"{err or DIM}Next update in {int(left) + 1}s · Ctrl+C to quit{RESET}")
                time.sleep(min(1, left))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")  # restore cursor + screen


if __name__ == "__main__":
    main()
