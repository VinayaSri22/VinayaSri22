#!/usr/bin/env python3
"""GitHub Profile OS — a self-updating, dashboard-style GitHub profile.

Reads config.json, pulls live data from the GitHub REST + GraphQL APIs,
renders a set of theme-adaptive SVG panels, and assembles README.md.

Design goals: no server, no database, single script, standard library only.
Every colored element carries an explicit dark-theme color attribute *and* a
CSS class, so the SVGs render correctly both in dumb rasterizers (attribute)
and on GitHub, where an embedded <style> media query swaps to a light palette
for viewers using a light system theme.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
README_PATH = ROOT / "README.md"
ASSETS_DIR = ROOT / "assets"
API = "https://api.github.com"
MONO = "'JetBrains Mono','SFMono-Regular',ui-monospace,Consolas,'Liberation Mono',Menlo,monospace"

# --------------------------------------------------------------------------- #
# Theme palettes. Keys are shared; values differ per system color scheme.
# --------------------------------------------------------------------------- #
DARK = {
    "panel": "#0d0d0f", "border": "#ff3d7f", "fg": "#f4f4f6", "muted": "#8b909a",
    "accent": "#ff3d7f", "accent2": "#ff8fb3", "track": "#26262c", "skin": "#c9d1d9",
    "ink": "#0a0a0a", "g0": "#26262c", "g1": "#0e4429", "g2": "#006d32",
    "g3": "#26a641", "g4": "#39d353",
}
LIGHT = {
    "panel": "#ffffff", "border": "#ff4d8d", "fg": "#1f2328", "muted": "#57606a",
    "accent": "#d6336c", "accent2": "#e8639a", "track": "#eaecef", "skin": "#57606a",
    "ink": "#ffffff", "g0": "#ebedf0", "g1": "#9be9a8", "g2": "#40c463",
    "g3": "#30a14e", "g4": "#216e39",
}
KEYS = list(DARK.keys())


def build_style() -> str:
    root_vars = ";".join(f"--{k}:{DARK[k]}" for k in KEYS)
    light_vars = ";".join(f"--{k}:{LIGHT[k]}" for k in KEYS)
    fills = " ".join(f".f-{k}{{fill:var(--{k})}}" for k in KEYS)
    strokes = " ".join(f".s-{k}{{stroke:var(--{k})}}" for k in KEYS)
    return (
        "<style>"
        f":root{{{root_vars}}}"
        f"@media (prefers-color-scheme:light){{:root{{{light_vars}}}}}"
        f"{fills} {strokes}"
        f"text{{font-family:{MONO};}}"
        ".ist{fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}"
        ".dash{fill:none;stroke-dasharray:4 4}"
        ".lead{stroke-dasharray:1.5 4;stroke-width:1}"
        "</style>"
    )


STYLE = build_style()


# --------------------------------------------------------------------------- #
# Tiny SVG emit helpers (each sets a concrete dark color + a themeable class).
# --------------------------------------------------------------------------- #
def esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rect(x, y, w, h, key="panel", rx=0, stroke=None, sw=1.4, extra=""):
    cls = f"f-{key}"
    s = ""
    if stroke:
        cls += f" s-{stroke}"
        s = f' stroke="{DARK[stroke]}" stroke-width="{sw}"'
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{DARK[key]}" class="{cls}"{s} {extra}/>')


def text(x, y, s, key="fg", size=13, weight=None, anchor=None, ls=None, italic=False):
    a = f' text-anchor="{anchor}"' if anchor else ""
    w = f' font-weight="{weight}"' if weight else ""
    l = f' letter-spacing="{ls}"' if ls else ""
    i = ' font-style="italic"' if italic else ""
    return (f'<text x="{x}" y="{y}" fill="{DARK[key]}" class="f-{key}" '
            f'font-size="{size}"{w}{a}{l}{i}>{esc(s)}</text>')


def line(x1, y1, x2, y2, key="muted", sw=1, cls=""):
    c = f"s-{key}" + (f" {cls}" if cls else "")
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{DARK[key]}" class="{c}" stroke-width="{sw}"/>')


def circle(cx, cy, r, key="accent", stroke=None, sw=1.4):
    if stroke:
        return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                f'stroke="{DARK[stroke]}" class="s-{stroke}" stroke-width="{sw}"/>')
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{DARK[key]}" class="f-{key}"/>'


def cw(size: float) -> float:
    return size * 0.6  # monospace advance width approximation


def header(x, y, label):
    return text(x, y, label, key="accent", size=11, weight=700, ls=2)


def wrap(s: str, width: int):
    out, line_words = [], []
    for word in s.split():
        if line_words and sum(len(w) for w in line_words) + len(line_words) + len(word) > width:
            out.append(" ".join(line_words))
            line_words = [word]
        else:
            line_words.append(word)
    if line_words:
        out.append(" ".join(line_words))
    return out


# --------------------------------------------------------------------------- #
# Icons — minimal line glyphs drawn in a 20x20 box, translated into place.
# --------------------------------------------------------------------------- #
def _ist(d):
    return f'<path class="ist s-accent" stroke="{DARK["accent"]}" d="{d}"/>'


def _if(d):
    return f'<path class="f-accent" fill="{DARK["accent"]}" d="{d}"/>'


ICONS = {
    "brain": lambda: (circle(7, 10, 4.3, stroke="accent") + circle(13, 10, 4.3, stroke="accent")
                      + line(10, 5.6, 10, 14.4, "accent", 1.6, "ist")),
    "robot": lambda: (f'<rect x="4" y="6" width="12" height="9" rx="2" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                      + line(10, 2.5, 10, 6, "accent", 1.6, "ist") + circle(10, 2.2, 1.3)
                      + circle(7.6, 10, 1.2) + circle(12.4, 10, 1.2)),
    "bolt": lambda: _if("M11 2 L4 11 L9 11 L8 18 L15 8 L10 8 Z"),
    "code": lambda: (_ist("M7 6 L3 10 L7 14") + _ist("M13 6 L17 10 L13 14")),
    "server": lambda: (f'<rect x="3" y="4" width="14" height="5" rx="1.5" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                       + f'<rect x="3" y="11" width="14" height="5" rx="1.5" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                       + circle(6, 6.5, 1) + circle(6, 13.5, 1)),
    "window": lambda: (f'<rect x="3" y="4" width="14" height="12" rx="1.5" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                       + line(3, 8, 17, 8, "accent", 1.6, "ist") + circle(6, 6, 0.9)),
    "database": lambda: (f'<ellipse cx="10" cy="5" rx="6" ry="2.4" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                         + _ist("M4 5 V15 c0 1.3 2.7 2.4 6 2.4 s6 -1.1 6 -2.4 V5")
                         + _ist("M4 10 c0 1.3 2.7 2.4 6 2.4 s6 -1.1 6 -2.4")),
    "wrench": lambda: _ist("M14.5 3.5 a3.4 3.4 0 0 0 -4.4 4.4 L4 14 l2 2 6.1 -6.1 a3.4 3.4 0 0 0 4.4 -4.4 l-2.1 2.1 -1.9 -1.9 Z"),
    "globe": lambda: (circle(10, 10, 7, stroke="accent")
                      + f'<ellipse cx="10" cy="10" rx="3" ry="7" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                      + line(3, 10, 17, 10, "accent", 1.6, "ist")),
    "linkedin": lambda: (f'<rect x="3" y="3" width="14" height="14" rx="2.5" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                         + circle(6.4, 6.6, 1.1) + f'<rect x="5.5" y="8.8" width="1.8" height="5.4" fill="{DARK["accent"]}" class="f-accent"/>'
                         + _if("M9.6 14.2 V8.8 h1.7 v.8 c.4-.6 1-.9 1.9-.9 1.4 0 2.3 .9 2.3 2.8 v2.7 h-1.8 v-2.6 c0-.8-.3-1.3-1-1.3 -.7 0-1 .5-1 1.3 v2.6 Z")),
    "mail": lambda: (f'<rect x="3" y="5" width="14" height="10" rx="1.8" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                     + _ist("M3.6 6.2 L10 11 L16.4 6.2")),
    "link": lambda: (_ist("M9 11 a3 3 0 0 1 0 -4 l1.5 -1.5 a3 3 0 0 1 4 4 L13 11")
                     + _ist("M11 9 a3 3 0 0 1 0 4 l-1.5 1.5 a3 3 0 0 1 -4 -4 L7 9")),
    "pin": lambda: (_ist("M10 2.5 a5 5 0 0 0 -5 5 c0 3.6 5 9 5 9 s5 -5.4 5 -9 a5 5 0 0 0 -5 -5 Z")
                    + circle(10, 7.2, 1.7, stroke="accent")),
    "coffee": lambda: (f'<rect x="4" y="7" width="9" height="8" rx="1.5" fill="none" stroke="{DARK["accent"]}" class="s-accent ist"/>'
                       + _ist("M13 9 h2 a2 2 0 0 1 0 4 h-2") + _ist("M6 3 v2 M9 3 v2")),
    "run": lambda: (circle(12, 4, 1.7) + _ist("M11 8 l-3 2 2 2 -1 4") + _ist("M11 10 l3 1 2 -1") + _ist("M8 10 l-3 1")),
    "pen": lambda: (_ist("M4 16 l1 -3 8 -8 2 2 -8 8 -3 1 Z") + line(11.5, 5.5, 13.5, 7.5, "accent", 1.6, "ist")),
}


def icon(name, x, y, scale=1.0):
    glyph = ICONS.get(name, ICONS["code"])()
    return f'<g transform="translate({x},{y}) scale({scale})">{glyph}</g>'


# --------------------------------------------------------------------------- #
# Pixel-art avatar (14 columns). Legend -> color key.
# --------------------------------------------------------------------------- #
AVATAR = [
    "    hhhhhh    ",
    "  hhhhhhhhhh  ",
    " hhhhhhhhhhhh ",
    " hhffffffffhh ",
    " hffffffffffh ",
    " hffeffffeffh ",
    " hffffffffffh ",
    " hffffffffffh ",
    " hfffeeeefffh ",
    " hhffffffffhh ",
    "  hffffffffh  ",
    "    ffffff    ",
    "   ssssssss   ",
    "  ssssssssss  ",
    " ssssssssssss ",
    " ss  ssss  ss ",
]
PIX = {"h": "accent", "f": "skin", "e": "ink", "s": "muted"}


def avatar(x, y, px=8):
    out = [f'<g transform="translate({x},{y})">']
    for r, row in enumerate(AVATAR):
        for c, ch in enumerate(row):
            key = PIX.get(ch)
            if key:
                out.append(f'<rect x="{c*px}" y="{r*px}" width="{px}" height="{px}" '
                           f'fill="{DARK[key]}" class="f-{key}"/>')
    # sparkles
    for sx, sy, s in ((-14, 26, 5), (128, 16, 6), (120, 96, 4)):
        out.append(f'<g transform="translate({sx},{sy})">'
                   + line(0, -s, 0, s, "accent2", 1.6, "ist")
                   + line(-s, 0, s, 0, "accent2", 1.6, "ist") + '</g>')
    out.append("</g>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# GitHub data fetching (graceful fallback to config's stats_fallback).
# --------------------------------------------------------------------------- #
def _token():
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def rest(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "github-profile-os",
               "X-GitHub-Api-Version": "2022-11-28"}
    if _token():
        headers["Authorization"] = f"Bearer {_token()}"
    with urlopen(Request(f"{API}{path}", headers=headers), timeout=30) as r:
        return json.loads(r.read().decode())


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    headers = {"Authorization": f"Bearer {_token()}", "User-Agent": "github-profile-os",
               "Content-Type": "application/json"}
    with urlopen(Request(f"{API}/graphql", data=body, headers=headers), timeout=30) as r:
        return json.loads(r.read().decode())


CAL_QUERY = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from,to:$to){
      totalCommitContributions totalPullRequestContributions totalIssueContributions
      contributionCalendar{ totalContributions weeks{ contributionDays{ weekday contributionCount date } } }
    }
  }
}"""

YEAR_QUERY = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){ contributionsCollection(from:$from,to:$to){ totalCommitContributions } }
}"""


def fetch_stats(username, fallback):
    stats = dict(fallback)
    stats["weeks"] = None
    now = datetime.now(timezone.utc)
    stats["year"] = now.year
    try:
        u = rest(f"/users/{username}")
        stats["repos"] = u.get("public_repos", stats["repos"])
        stats["followers"] = u.get("followers", stats["followers"])
        stats["following"] = u.get("following", stats["following"])
        created = u.get("created_at", "")
        created_year = int(created[:4]) if created else now.year
    except (HTTPError, URLError, KeyError, ValueError) as e:
        print(f"warning: user fetch failed: {e}", file=sys.stderr)
        created_year = now.year

    try:  # sum stars across repos
        stars, page = 0, 1
        while page <= 5:
            repos = rest(f"/users/{username}/repos?per_page=100&page={page}&type=owner")
            if not repos:
                break
            stars += sum(r.get("stargazers_count", 0) for r in repos)
            if len(repos) < 100:
                break
            page += 1
        stats["stars"] = stars
    except (HTTPError, URLError) as e:
        print(f"warning: repo fetch failed: {e}", file=sys.stderr)

    if _token():
        try:
            frm = datetime(now.year, 1, 1, tzinfo=timezone.utc).isoformat()
            res = graphql(CAL_QUERY, {"login": username, "from": frm, "to": now.isoformat()})
            cc = res["data"]["user"]["contributionsCollection"]
            stats["contributions_year"] = cc["contributionCalendar"]["totalContributions"]
            stats["pull_requests"] = cc["totalPullRequestContributions"]
            stats["issues"] = cc["totalIssueContributions"]
            stats["weeks"] = cc["contributionCalendar"]["weeks"]
            total_commits = cc["totalCommitContributions"]
            for yr in range(created_year, now.year):
                f0 = datetime(yr, 1, 1, tzinfo=timezone.utc).isoformat()
                f1 = datetime(yr, 12, 31, 23, 59, tzinfo=timezone.utc).isoformat()
                r = graphql(YEAR_QUERY, {"login": username, "from": f0, "to": f1})
                total_commits += r["data"]["user"]["contributionsCollection"]["totalCommitContributions"]
            stats["commits_all"] = total_commits
        except (HTTPError, URLError, KeyError, TypeError) as e:
            print(f"warning: graphql fetch failed: {e}", file=sys.stderr)

    if not stats["weeks"]:
        stats["weeks"] = synth_weeks(26)
    return stats


def synth_weeks(n):
    """Deterministic pseudo-activity so local previews look alive without a token."""
    import hashlib
    today = datetime.now(timezone.utc).date()
    start = today.toordinal() - n * 7
    weeks = []
    for w in range(n):
        days = []
        for d in range(7):
            o = start + w * 7 + d
            h = int(hashlib.md5(str(o).encode()).hexdigest(), 16)
            count = 0 if h % 5 == 0 else (h % 14)
            days.append({"weekday": d, "contributionCount": count,
                         "date": datetime.fromordinal(o).strftime("%Y-%m-%d")})
        weeks.append({"contributionDays": days})
    return weeks


# --------------------------------------------------------------------------- #
# Quotes
# --------------------------------------------------------------------------- #
QUOTES = [
    ("The best optimization is deleting unnecessary work.", "Donald Knuth"),
    ("Programs must be written for people to read.", "Harold Abelson"),
    ("Simplicity is prerequisite for reliability.", "Edsger Dijkstra"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Code is like humor. When you have to explain it, it's bad.", "Cory House"),
    ("The most damaging phrase is: we've always done it this way.", "Grace Hopper"),
    ("Any fool can write code a computer understands. Good programmers write code humans understand.", "Martin Fowler"),
    ("It always seems impossible until it's done.", "Nelson Mandela"),
    ("Deleted code is debugged code.", "Jeff Sickel"),
    ("Fix the cause, not the symptom.", "Steve Maguire"),
    ("Testing shows the presence, not the absence of bugs.", "Edsger Dijkstra"),
    ("The function of good software is to make the complex appear simple.", "Grady Booch"),
]


def quote_today():
    idx = datetime.now().timetuple().tm_yday % len(QUOTES)
    return QUOTES[idx]


# --------------------------------------------------------------------------- #
# Panel builders — each returns (inner_svg, width, height).
# --------------------------------------------------------------------------- #
def frame(w, h, pad=6):
    return rect(pad, pad, w - 2 * pad, h - 2 * pad, key="panel", rx=14, stroke="border", sw=1.4)


def panel_banner(cfg):
    w, h = 636, 262
    p = [frame(w, h)]
    p.append(text(34, 60, cfg["name"], key="accent", size=30, weight=700))
    p.append(text(34, 92, cfg.get("role", ""), key="muted", size=14))
    for i, ln in enumerate(cfg.get("tagline", "").split("\n")):
        p.append(text(34, 122 + i * 20, ln, key="fg", size=13))
    chips = cfg.get("hero_chips", [])
    if chips:
        p.append(icon("pin", 34, 190, 0.85))
        p.append(text(58, 204, "   ".join(chips) if False else "  •  ".join(chips),
                      key="muted", size=12))
    p.append(avatar(452, 46, px=8))
    return "".join(p), w, h


def panel_stats(cfg, stats):
    w, h = 330, 262
    p = [frame(w, h), header(24, 40, "GITHUB STATS")]
    rows = [
        ("Repositories", stats["repos"]),
        ("Followers", stats["followers"]),
        ("Following", stats["following"]),
        ("Stars", stats["stars"]),
        (f"Contributions ({stats['year']})", f"{stats['contributions_year']:,}"),
        ("Commits (All Time)", f"{stats['commits_all']:,}"),
        ("Pull Requests", stats["pull_requests"]),
        ("Issues", stats["issues"]),
    ]
    y = 66
    for label, val in rows:
        val = str(val)
        p.append(text(24, y, label, key="fg", size=12))
        p.append(text(w - 24, y, val, key="accent", size=12, weight=700, anchor="end"))
        lx = 24 + len(label) * cw(12) + 8
        rx = (w - 24) - len(val) * cw(12) - 8
        if rx > lx:
            p.append(line(lx, y - 4, rx, y - 4, "muted", 1, "lead"))
        y += 20.5
    p.append(line(24, 226, w - 24, 226, "track", 1))
    ts = datetime.now(ZoneInfo(cfg.get("timezone", "UTC"))) if cfg.get("timezone") else datetime.now()
    stamp = ts.strftime("%d %b %Y  •  %I:%M %p")
    p.append(text(24, 246, f"Last updated {stamp}", key="muted", size=10))
    return "".join(p), w, h


def panel_journal(cfg):
    w, h = 968, 98
    p = [frame(w, h)]
    p.append(icon("pen", 26, 22, 0.95))
    p.append(header(54, 34, "ENGINEERING JOURNAL"))
    lines = wrap(cfg.get("engineering_journal", ""), 112)[:2]
    for i, ln in enumerate(lines):
        p.append(text(54, 58 + i * 20, ln, key="fg", size=13))
    return "".join(p), w, h


def panel_building(cfg):
    w, h = 478, 300
    p = [frame(w, h), header(24, 36, "CURRENTLY BUILDING")]
    y = 56
    items = cfg.get("building", [])[:3]
    for idx, it in enumerate(items):
        p.append(rect(24, y + 4, 40, 40, key="panel", rx=10, stroke="border", sw=1.2))
        p.append(icon(it.get("icon", "code"), 34, y + 14, 1.0))
        p.append(text(78, y + 16, it.get("name", ""), key="accent", size=13, weight=700))
        for i, ln in enumerate(it.get("desc", "").split("\n")[:2]):
            p.append(text(78, y + 34 + i * 15, ln, key="muted", size=10.5))
        tags = "  •  ".join(it.get("tags", []))
        p.append(text(w - 24, y + 16, tags, key="accent2", size=10.5, anchor="end"))
        if idx < len(items) - 1:
            p.append(line(24, y + 74, w - 24, y + 74, "track", 1, "dash"))
        y += 80
    return "".join(p), w, h


def panel_tech(cfg):
    w, h = 486, 300
    p = [frame(w, h), header(24, 36, "TECH STACK")]
    y = 68
    for row in cfg.get("tech_stack", []):
        p.append(icon(row.get("icon", "code"), 24, y - 14, 0.95))
        p.append(text(56, y, row.get("label", ""), key="fg", size=12, weight=700))
        p.append(text(150, y, ":", key="muted", size=12))
        p.append(text(168, y, "   ".join(row.get("values", [])), key="muted", size=12))
        y += 37
    return "".join(p), w, h


def panel_learning(cfg):
    w, h = 316, 270
    p = [frame(w, h), header(24, 36, "LEARNING JOURNEY")]
    items = list(cfg.get("learning", {}).items())[:6]
    y = 62
    bx, blocks, bw, gap = 148, 10, 8, 2
    for name, pct in items:
        p.append(text(24, y, name, key="fg", size=10.5))
        filled = round(pct / 10)
        for b in range(blocks):
            key = "accent" if b < filled else "track"
            p.append(rect(bx + b * (bw + gap), y - 9, bw, 11, key=key, rx=2))
        p.append(text(w - 20, y, f"{pct}%", key="accent", size=10.5, weight=700, anchor="end"))
        y += 27
    q = wrap(cfg.get("learning_quote", ""), 48)[:2]
    qy = 232
    for ln in q:
        p.append(text(w / 2, qy, ln, key="muted", size=9.5, anchor="middle", italic=True))
        qy += 15
    return "".join(p), w, h


def _levels(weeks):
    counts = [d["contributionCount"] for wk in weeks for d in wk["contributionDays"]]
    mx = max(counts) if counts else 0
    return mx


def panel_activity(cfg, stats):
    w, h = 330, 270
    weeks = stats["weeks"][-26:]
    p = [frame(w, h), header(24, 36, "GITHUB ACTIVITY")]
    gx, gy, cell, gp = 52, 66, 8, 2
    step = cell + gp
    mx = _levels(weeks)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
              "Aug", "Sep", "Oct", "Nov", "Dec"]
    last_m = None
    for wi, wk in enumerate(weeks):
        days = {d["weekday"]: d for d in wk["contributionDays"]}
        first = wk["contributionDays"][0].get("date", "")
        if first:
            m = int(first[5:7])
            if m != last_m:
                p.append(text(gx + wi * step, gy - 8, months[m - 1], key="muted", size=9))
                last_m = m
        for d in range(7):
            day = days.get(d)
            c = day["contributionCount"] if day else 0
            if not mx or c == 0:
                lvl = "g0"
            else:
                r = c / mx
                lvl = "g1" if r <= 0.25 else "g2" if r <= 0.5 else "g3" if r <= 0.75 else "g4"
            p.append(rect(gx + wi * step, gy + d * step, cell, cell, key=lvl, rx=2))
    for wd, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        p.append(text(20, gy + wd * step + cell, lab, key="muted", size=8))
    # legend
    ly = gy + 7 * step + 22
    p.append(text(gx, ly, "Less", key="muted", size=9))
    for i, lv in enumerate(["g0", "g1", "g2", "g3", "g4"]):
        p.append(rect(gx + 34 + i * 12, ly - 9, cell, cell, key=lv, rx=2))
    p.append(text(gx + 34 + 5 * 12 + 6, ly, "More", key="muted", size=9))
    p.append(text(w / 2, ly + 26, f"{stats['contributions_year']:,} contributions in {stats['year']}",
                  key="fg", size=11, anchor="middle"))
    return "".join(p), w, h


def panel_connect_quote(cfg):
    w, h = 316, 270
    p = [frame(w, h), header(24, 36, "CONNECT")]
    soc = cfg.get("socials", {})
    rows = [("linkedin", soc.get("linkedin")), ("mail", soc.get("email")),
            ("link", soc.get("website")), ("pin", soc.get("location"))]
    y = 60
    for ic, val in rows:
        if not val:
            continue
        p.append(icon(ic, 24, y - 14, 0.9))
        p.append(text(52, y, val, key="fg", size=11))
        y += 28
    p.append(line(20, 170, w - 20, 170, "track", 1, "dash"))
    # quote box
    qx, qy, qw, qh = 16, 182, w - 32, 74
    p.append(rect(qx, qy, qw, qh, key="panel", rx=10, stroke="border", sw=1))
    p[-1] = p[-1].replace('class="f-panel s-border"', 'class="f-panel s-border dash"')
    quote, author = quote_today()
    lines = wrap(quote, 34)[:3]
    ty = qy + 26 - (len(lines) - 1) * 7
    for ln in lines:
        p.append(text(w / 2, ty, ln, key="fg", size=10.5, anchor="middle", italic=True))
        ty += 15
    p.append(text(w / 2, qy + qh - 12, f"— {author}", key="accent", size=10, anchor="middle"))
    return "".join(p), w, h


def panel_footer(cfg):
    w, h = 968, 60
    p = [frame(w, h)]
    p.append(text(w / 2, 36, cfg.get("footer", ""), key="fg", size=13, anchor="middle"))
    return "".join(p), w, h


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def svg_file(inner, w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" fill="none" role="img">{STYLE}{inner}</svg>\n')


def write_asset(name, built):
    inner, w, h = built
    (ASSETS_DIR / f"{name}.svg").write_text(svg_file(inner, w, h), encoding="utf-8")
    return name, w, h


def build_readme(panels, cfg):
    def img(name):
        return f'<img src="assets/{name}.svg" width="{panels[name][1]}" alt="{name}">'

    body = f"""<!-- ────────────────────────────────────────────────────────────── -->
<!--  GitHub Profile OS — generated by update.py. Do not edit by hand.  -->
<!--  Edit config.json instead; the daily GitHub Action rebuilds this.  -->
<!-- ────────────────────────────────────────────────────────────── -->

<div align="center">

{img('banner')}{img('github_stats')}

{img('journal')}

{img('currently_building')}{img('tech_stack')}

{img('learning')}{img('activity')}{img('connect_quote')}

{img('footer')}

</div>
"""
    README_PATH.write_text(body, encoding="utf-8")


def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    username = cfg["github_username"]
    ASSETS_DIR.mkdir(exist_ok=True)

    stats = fetch_stats(username, cfg.get("stats_fallback", {}))

    built = {}
    for name, panel in [
        ("banner", panel_banner(cfg)),
        ("github_stats", panel_stats(cfg, stats)),
        ("journal", panel_journal(cfg)),
        ("currently_building", panel_building(cfg)),
        ("tech_stack", panel_tech(cfg)),
        ("learning", panel_learning(cfg)),
        ("activity", panel_activity(cfg, stats)),
        ("connect_quote", panel_connect_quote(cfg)),
        ("footer", panel_footer(cfg)),
    ]:
        n, w, h = write_asset(name, panel)
        built[n] = (n, w, h)

    build_readme(built, cfg)
    print("Profile rebuilt: 9 panels + README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
