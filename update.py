#!/usr/bin/env python3
"""GitHub Profile OS — a self-updating, dashboard-style GitHub profile.

Reads config.json, pulls live data from the GitHub REST + GraphQL APIs, and
renders the whole profile as a single composed SVG (in a dark and a light
variant). README.md embeds them with <picture> so the layout is pixel-perfect
and theme-correct on GitHub.

Design goals: no server, no database, single script, standard library only,
and NO fabricated statistics — in CI the run fails rather than commit fake data.
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

DASH_W, DASH_H = 976, 1058

# --------------------------------------------------------------------------- #
# Theme palettes.
# --------------------------------------------------------------------------- #
DARK = {
    "bg": "#0a0a0a", "panel": "#101014", "border": "#2a2a31", "fg": "#f4f4f6",
    "muted": "#8b909a", "accent": "#ff3d7f", "accent2": "#ff8fb3", "track": "#26262c",
    "skin": "#c9d1d9", "ink": "#0a0a0a", "g0": "#26262c", "g1": "#0e4429",
    "g2": "#006d32", "g3": "#26a641", "g4": "#39d353",
    "av_fill": "#1c1c24", "av_line": "#cfd3da", "av_face": "#e9ecef",
    "av_eye": "#14141a", "av_pink": "#ff6a9a",
}
LIGHT = {
    "bg": "#ffffff", "panel": "#ffffff", "border": "#e2e4e8", "fg": "#1f2328",
    "muted": "#57606a", "accent": "#d6336c", "accent2": "#c02a5b", "track": "#e6e8eb",
    "skin": "#6a7079", "ink": "#ffffff", "g0": "#ebedf0", "g1": "#9be9a8",
    "g2": "#40c463", "g3": "#30a14e", "g4": "#216e39",
    "av_fill": "#1f242b", "av_line": "#3a4048", "av_face": "#f3ede8",
    "av_eye": "#1f242b", "av_pink": "#d6336c",
}
PAL = DARK  # active palette; swapped per variant during rendering


def set_palette(pal):
    global PAL
    PAL = pal


# --------------------------------------------------------------------------- #
# SVG emit helpers.
# --------------------------------------------------------------------------- #
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rect(x, y, w, h, key="panel", rx=0, stroke=None, sw=1.4, dash=False):
    s = f' stroke="{PAL[stroke]}" stroke-width="{sw}"' if stroke else ""
    d = ' stroke-dasharray="4 4"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{PAL[key]}"{s}{d}/>')


def text(x, y, s, key="fg", size=13, weight=None, anchor=None, ls=None, italic=False):
    a = f' text-anchor="{anchor}"' if anchor else ""
    w = f' font-weight="{weight}"' if weight else ""
    l = f' letter-spacing="{ls}"' if ls else ""
    i = ' font-style="italic"' if italic else ""
    return (f'<text x="{x}" y="{y}" fill="{PAL[key]}" font-family="{MONO}" '
            f'font-size="{size}"{w}{a}{l}{i}>{esc(s)}</text>')


def line(x1, y1, x2, y2, key="muted", sw=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{PAL[key]}" stroke-width="{sw}"{d} stroke-linecap="round"/>')


def circle(cx, cy, r, key="accent", stroke=None, sw=1.4):
    if stroke:
        return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                f'stroke="{PAL[stroke]}" stroke-width="{sw}"/>')
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{PAL[key]}"/>'


def cw(size):
    return size * 0.6


def header(x, y, label):
    return text(x, y, label, key="accent", size=11, weight=700, ls=2)


def wrap(s, width):
    out, cur = [], []
    for word in s.split():
        if cur and sum(len(w) for w in cur) + len(cur) + len(word) > width:
            out.append(" ".join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        out.append(" ".join(cur))
    return out


# --------------------------------------------------------------------------- #
# Icons (minimal line glyphs in a 20x20 box).
# --------------------------------------------------------------------------- #
ICOL = "muted"  # active icon color key


def _s(d):
    return (f'<path d="{d}" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def _f(d):
    return f'<path d="{d}" fill="{PAL[ICOL]}"/>'


def _icons():
    return {
        "brain": circle(7, 10, 4.3, stroke=ICOL) + circle(13, 10, 4.3, stroke=ICOL)
                 + line(10, 5.6, 10, 14.4, ICOL, 1.6),
        "robot": f'<rect x="4" y="6" width="12" height="9" rx="2" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                 + line(10, 2.5, 10, 6, ICOL, 1.6) + circle(10, 2.2, 1.3, key=ICOL)
                 + circle(7.6, 10, 1.2, key=ICOL) + circle(12.4, 10, 1.2, key=ICOL),
        "bolt": _f("M11 2 L4 11 L9 11 L8 18 L15 8 L10 8 Z"),
        "code": _s("M7 6 L3 10 L7 14") + _s("M13 6 L17 10 L13 14"),
        "server": f'<rect x="3" y="4" width="14" height="5" rx="1.5" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                  + f'<rect x="3" y="11" width="14" height="5" rx="1.5" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                  + circle(6, 6.5, 1, key=ICOL) + circle(6, 13.5, 1, key=ICOL),
        "window": f'<rect x="3" y="4" width="14" height="12" rx="1.5" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                  + line(3, 8, 17, 8, ICOL, 1.6) + circle(6, 6, 0.9, key=ICOL),
        "database": f'<ellipse cx="10" cy="5" rx="6" ry="2.4" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                    + _s("M4 5 V15 c0 1.3 2.7 2.4 6 2.4 s6 -1.1 6 -2.4 V5")
                    + _s("M4 10 c0 1.3 2.7 2.4 6 2.4 s6 -1.1 6 -2.4"),
        "wrench": _s("M14.5 3.5 a3.4 3.4 0 0 0 -4.4 4.4 L4 14 l2 2 6.1 -6.1 a3.4 3.4 0 0 0 4.4 -4.4 l-2.1 2.1 -1.9 -1.9 Z"),
        "globe": circle(10, 10, 7, stroke=ICOL)
                 + f'<ellipse cx="10" cy="10" rx="3" ry="7" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                 + line(3, 10, 17, 10, ICOL, 1.6),
        "linkedin": f'<rect x="3" y="3" width="14" height="14" rx="2.5" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                    + circle(6.4, 6.6, 1.1, key=ICOL) + f'<rect x="5.5" y="8.8" width="1.8" height="5.4" fill="{PAL[ICOL]}"/>'
                    + _f("M9.6 14.2 V8.8 h1.7 v.8 c.4-.6 1-.9 1.9-.9 1.4 0 2.3 .9 2.3 2.8 v2.7 h-1.8 v-2.6 c0-.8-.3-1.3-1-1.3 -.7 0-1 .5-1 1.3 v2.6 Z"),
        "mail": f'<rect x="3" y="5" width="14" height="10" rx="1.8" fill="none" stroke="{PAL[ICOL]}" stroke-width="1.6"/>'
                + _s("M3.6 6.2 L10 11 L16.4 6.2"),
        "link": _s("M9 11 a3 3 0 0 1 0 -4 l1.5 -1.5 a3 3 0 0 1 4 4 L13 11")
                + _s("M11 9 a3 3 0 0 1 0 4 l-1.5 1.5 a3 3 0 0 1 -4 -4 L7 9"),
        "pin": _s("M10 2.5 a5 5 0 0 0 -5 5 c0 3.6 5 9 5 9 s5 -5.4 5 -9 a5 5 0 0 0 -5 -5 Z")
               + circle(10, 7.2, 1.7, stroke=ICOL),
        "pen": _s("M4 16 l1 -3 8 -8 2 2 -8 8 -3 1 Z") + line(11.5, 5.5, 13.5, 7.5, ICOL, 1.6),
    }


def icon(name, x, y, scale=1.0, color="muted"):
    global ICOL
    ICOL = color
    glyph = _icons().get(name, _icons()["code"])
    ICOL = "muted"
    return f'<g transform="translate({x},{y}) scale({scale})">{glyph}</g>'


# --------------------------------------------------------------------------- #
# Pixel-art avatar: a girl with long hair + hoodie, built geometrically so an
# outline can be auto-generated (keeps it legible on both dark and light bg).
# Fill codes: h=hair/hoodie, f=face, e=eye/mouth, z=zipper, p=pink fleck.
# --------------------------------------------------------------------------- #
AV_W, AV_H = 26, 32
_AV_COLOR = {"h": "av_fill", "f": "av_face", "e": "av_eye", "z": "av_pink", "p": "av_pink"}


def _avatar_grid():
    g = [[" "] * AV_W for _ in range(AV_H)]
    cx = 12.5

    def fill_ellipse(ex, ey, rx, ry, ch, only_empty=False, replace=None):
        for yy in range(AV_H):
            for xx in range(AV_W):
                if ((xx - ex) / rx) ** 2 + ((yy - ey) / ry) ** 2 <= 1:
                    if only_empty and g[yy][xx] != " ":
                        continue
                    if replace is not None and g[yy][xx] != replace:
                        continue
                    g[yy][xx] = ch

    # hair mass (behind), then hoodie, then face on top
    fill_ellipse(cx, 12, 10.5, 11.5, "h")
    # long hair drapes down the sides
    for yy in range(11, 27):
        span = 10 - max(0, (yy - 20)) * 0.5
        for xx in range(AV_W):
            if abs(xx - cx) > span - 3 and abs(xx - cx) <= span:
                g[yy][xx] = "h"
    # hoodie / shoulders (trapezoid, capped so it doesn't fill the whole width)
    for yy in range(22, AV_H):
        half = min(11.5, 5.5 + (yy - 22) * 1.25)
        for xx in range(AV_W):
            if abs(xx - cx) <= half:
                g[yy][xx] = "h"
    # face
    fill_ellipse(cx, 14, 6.4, 8.0, "f", replace="h")
    # bangs: turn upper face back into hair down to the brow line
    for yy in range(AV_H):
        for xx in range(AV_W):
            if g[yy][xx] == "f" and yy < 9:
                g[yy][xx] = "h"
    # neck
    for yy in range(21, 23):
        for xx in range(AV_W):
            if abs(xx - cx) <= 2.5:
                g[yy][xx] = "f"

    def block(x0, y0, w, h, ch):
        for yy in range(y0, y0 + h):
            for xx in range(x0, x0 + w):
                if 0 <= yy < AV_H and 0 <= xx < AV_W and g[yy][xx] not in (" ",):
                    g[yy][xx] = ch

    block(9, 12, 2, 2, "e")    # left eye
    block(15, 12, 2, 2, "e")   # right eye
    for xx in range(10, 16):   # smile
        g[17][xx] = "e"
    g[16][10] = "e"
    g[16][15] = "e"
    g[15][8] = "p"             # cheek blush
    g[15][17] = "p"
    # open-hoodie collar (subtle pink V) + center zipper
    for i in range(3):
        if 0 <= 22 + i < AV_H:
            if g[22 + i][11 - i] == "h":
                g[22 + i][11 - i] = "p"
            if g[22 + i][13 + i] == "h":
                g[22 + i][13 + i] = "p"
    for yy in range(25, AV_H):
        g[yy][12] = "z"
    for fx, fy in ((7, 3), (17, 2), (19, 6), (6, 6)):  # pink hair flecks
        if g[fy][fx] == "h":
            g[fy][fx] = "p"
    return g


def avatar(x, y, px=6):
    g = _avatar_grid()
    out = [f'<g transform="translate({x},{y})">']
    # auto outline: empty cells 4-adjacent to a filled cell
    for r in range(AV_H):
        for c in range(AV_W):
            if g[r][c] != " ":
                continue
            if any(0 <= r + dr < AV_H and 0 <= c + dc < AV_W and g[r + dr][c + dc] not in (" ",)
                   for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                out.append(f'<rect x="{c*px}" y="{r*px}" width="{px}" height="{px}" fill="{PAL["av_line"]}"/>')
    for r in range(AV_H):
        for c in range(AV_W):
            ch = g[r][c]
            if ch != " ":
                out.append(f'<rect x="{c*px}" y="{r*px}" width="{px}" height="{px}" fill="{PAL[_AV_COLOR[ch]]}"/>')
    out.append("</g>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# GitHub data.
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
        data = json.loads(r.read().decode())
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data


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


def synth_weeks(n=26):
    import hashlib
    today = datetime.now(timezone.utc).date().toordinal()
    start = today - n * 7
    weeks = []
    for w in range(n):
        days = []
        for d in range(7):
            o = start + w * 7 + d
            h = int(hashlib.md5(str(o).encode()).hexdigest(), 16)
            days.append({"weekday": d, "contributionCount": 0 if h % 5 == 0 else h % 14,
                         "date": datetime.fromordinal(o).strftime("%Y-%m-%d")})
        weeks.append({"contributionDays": days})
    return weeks


def fetch_sample(cfg):
    s = dict(cfg.get("sample_stats", {}))
    s["year"] = datetime.now().year
    s["weeks"] = synth_weeks()
    return s


def fetch_live(username):
    """Fetch real data. Raises on any failure so CI never commits fake stats."""
    now = datetime.now(timezone.utc)
    stats = {"year": now.year}

    u = rest(f"/users/{username}")
    stats["repos"] = u["public_repos"]
    stats["followers"] = u["followers"]
    stats["following"] = u["following"]
    created_year = int(u["created_at"][:4])

    stars, page = 0, 1
    while page <= 10:
        repos = rest(f"/users/{username}/repos?per_page=100&page={page}&type=owner")
        if not repos:
            break
        stars += sum(r.get("stargazers_count", 0) for r in repos)
        if len(repos) < 100:
            break
        page += 1
    stats["stars"] = stars

    if not _token():
        raise RuntimeError("GITHUB_TOKEN is required for contribution/commit stats.")

    frm = datetime(now.year, 1, 1, tzinfo=timezone.utc).isoformat()
    cc = graphql(CAL_QUERY, {"login": username, "from": frm, "to": now.isoformat()})
    cc = cc["data"]["user"]["contributionsCollection"]
    stats["contributions_year"] = cc["contributionCalendar"]["totalContributions"]
    stats["pull_requests"] = cc["totalPullRequestContributions"]
    stats["issues"] = cc["totalIssueContributions"]
    stats["weeks"] = cc["contributionCalendar"]["weeks"]

    commits = cc["totalCommitContributions"]
    for yr in range(created_year, now.year):
        f0 = datetime(yr, 1, 1, tzinfo=timezone.utc).isoformat()
        f1 = datetime(yr, 12, 31, 23, 59, tzinfo=timezone.utc).isoformat()
        r = graphql(YEAR_QUERY, {"login": username, "from": f0, "to": f1})
        commits += r["data"]["user"]["contributionsCollection"]["totalCommitContributions"]
    stats["commits_all"] = commits
    return stats


# --------------------------------------------------------------------------- #
# Quotes.
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
    ("Good programmers write code that humans can understand.", "Martin Fowler"),
    ("It always seems impossible until it's done.", "Nelson Mandela"),
    ("Deleted code is debugged code.", "Jeff Sickel"),
    ("Fix the cause, not the symptom.", "Steve Maguire"),
    ("Testing shows the presence, not the absence of bugs.", "Edsger Dijkstra"),
    ("Make the complex appear simple.", "Grady Booch"),
]


def quote_today():
    return QUOTES[datetime.now().timetuple().tm_yday % len(QUOTES)]


# --------------------------------------------------------------------------- #
# Panels — each returns (inner_svg, w, h).
# --------------------------------------------------------------------------- #
def frame(w, h):
    return rect(0, 0, w, h, key="panel", rx=14, stroke="border", sw=1.4)


def p_banner(cfg):
    w, h = 600, 250
    p = [frame(w, h), text(30, 58, cfg["name"], key="accent", size=30, weight=700),
         text(30, 90, cfg.get("role", ""), key="muted", size=14)]
    for i, ln in enumerate(cfg.get("tagline", "").split("\n")):
        p.append(text(30, 120 + i * 20, ln, key="fg", size=13))
    chips = cfg.get("hero_chips", [])
    if chips:
        p.append(icon("pin", 30, 188, 0.85))
        p.append(text(54, 202, "  •  ".join(chips), key="muted", size=11))
    p.append(avatar(432, 26, px=6))
    return "".join(p), w, h


def p_stats(cfg, s):
    w, h = 326, 250
    p = [frame(w, h), header(22, 38, "GITHUB STATS")]
    rows = [
        ("Repositories", s["repos"]), ("Followers", s["followers"]),
        ("Following", s["following"]), ("Stars", s["stars"]),
        (f"Contributions ({s['year']})", f"{s['contributions_year']:,}"),
        ("Commits (All Time)", f"{s['commits_all']:,}"),
        ("Pull Requests", s["pull_requests"]), ("Issues", s["issues"]),
    ]
    y = 64
    for label, val in rows:
        val = str(val)
        p.append(text(22, y, label, key="fg", size=12))
        p.append(text(w - 22, y, val, key="accent", size=12, weight=700, anchor="end"))
        lx = 22 + len(label) * cw(12) + 8
        rx = (w - 22) - len(val) * cw(12) - 8
        if rx > lx:
            p.append(line(lx, y - 4, rx, y - 4, "muted", 1, "1.5 4"))
        y += 20
    p.append(line(22, 216, w - 22, 216, "track", 1))
    ts = datetime.now(ZoneInfo(cfg.get("timezone", "UTC")))
    p.append(text(22, 236, f"Last updated {ts.strftime('%d %b %Y  •  %I:%M %p')}", key="muted", size=10))
    return "".join(p), w, h


def p_journal(cfg):
    w, h = 940, 92
    p = [frame(w, h), icon("pen", 26, 22, 0.95), header(54, 34, "ENGINEERING JOURNAL")]
    for i, ln in enumerate(wrap(cfg.get("engineering_journal", ""), 110)[:2]):
        p.append(text(54, 58 + i * 20, ln, key="fg", size=13))
    return "".join(p), w, h


def p_building(cfg):
    w, h = 463, 300
    p = [frame(w, h), header(22, 36, "CURRENTLY BUILDING")]
    items = cfg.get("building", [])[:3]
    y = 56
    for idx, it in enumerate(items):
        p.append(rect(22, y + 4, 40, 40, key="panel", rx=10, stroke="border", sw=1.2))
        p.append(icon(it.get("icon", "code"), 32, y + 14, 1.0))
        p.append(text(74, y + 16, it.get("name", ""), key="accent", size=13, weight=700))
        for i, ln in enumerate(it.get("desc", "").split("\n")[:2]):
            p.append(text(74, y + 34 + i * 15, ln, key="muted", size=10.5))
        p.append(text(w - 20, y + 16, "  •  ".join(it.get("tags", [])), key="accent2", size=10.5, anchor="end"))
        if idx < len(items) - 1:
            p.append(line(22, y + 74, w - 22, y + 74, "track", 1, "4 4"))
        y += 80
    return "".join(p), w, h


def p_tech(cfg):
    w, h = 463, 300
    p = [frame(w, h), header(22, 36, "TECH STACK")]
    y = 68
    for row in cfg.get("tech_stack", []):
        p.append(icon(row.get("icon", "code"), 22, y - 14, 0.95))
        p.append(text(54, y, row.get("label", ""), key="fg", size=12, weight=700))
        p.append(text(150, y, ":", key="muted", size=12))
        p.append(text(168, y, "   ".join(row.get("values", [])), key="muted", size=12))
        y += 37
    return "".join(p), w, h


def p_learning(cfg):
    w, h = 300, 268
    p = [frame(w, h), header(22, 36, "LEARNING JOURNEY")]
    items = list(cfg.get("learning", {}).items())[:6]
    y = 62
    bx, bw, gap = 134, 8, 2
    for name, pct in items:
        p.append(text(22, y, name, key="fg", size=10.5))
        filled = round(pct / 10)
        for b in range(10):
            p.append(rect(bx + b * (bw + gap), y - 9, bw, 11, key=("accent" if b < filled else "track"), rx=2))
        p.append(text(w - 16, y, f"{pct}%", key="accent", size=10.5, weight=700, anchor="end"))
        y += 26
    qy = 226
    for ln in wrap(cfg.get("learning_quote", ""), 46)[:2]:
        p.append(text(w / 2, qy, ln, key="muted", size=9.5, anchor="middle", italic=True))
        qy += 14
    return "".join(p), w, h


def p_activity(cfg, s):
    w, h = 312, 268
    weeks = s["weeks"][-26:]
    p = [frame(w, h), header(22, 36, "GITHUB ACTIVITY")]
    gx, gy, cell, step = 46, 70, 7, 9
    counts = [d["contributionCount"] for wk in weeks for d in wk["contributionDays"]]
    mx = max(counts) if counts else 0
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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
            p.append(rect(gx + wi * step, gy + d * step, cell, cell, key=lvl, rx=1.5))
    for wd, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        p.append(text(14, gy + wd * step + cell, lab, key="muted", size=8))
    ly = gy + 7 * step + 24
    p.append(text(gx, ly, "Less", key="muted", size=9))
    for i, lv in enumerate(["g0", "g1", "g2", "g3", "g4"]):
        p.append(rect(gx + 34 + i * 11, ly - 8, cell, cell, key=lv, rx=1.5))
    p.append(text(gx + 34 + 5 * 11 + 6, ly, "More", key="muted", size=9))
    p.append(text(w / 2, ly + 28, f"{s['contributions_year']:,} contributions in {s['year']}",
                  key="fg", size=11, anchor="middle"))
    return "".join(p), w, h


def p_connect(cfg):
    w, h = 300, 268
    p = [frame(w, h), header(22, 36, "CONNECT")]
    soc = cfg.get("socials", {})
    rows = [("linkedin", soc.get("linkedin")), ("mail", soc.get("email")),
            ("link", soc.get("website")), ("pin", soc.get("location"))]
    y = 60
    for ic, val in rows:
        if not val:
            continue
        p.append(icon(ic, 22, y - 14, 0.9))
        p.append(text(50, y, val, key="fg", size=11))
        y += 26
    p.append(line(18, 162, w - 18, 162, "track", 1, "4 4"))
    qx, qy, qw, qh = 14, 172, w - 28, 84
    p.append(rect(qx, qy, qw, qh, key="panel", rx=10, stroke="border", sw=1, dash=True))
    quote, author = quote_today()
    lines = wrap(quote, 32)[:3]
    ty = qy + 30 - (len(lines) - 1) * 7
    for ln in lines:
        p.append(text(w / 2, ty, ln, key="fg", size=10.5, anchor="middle", italic=True))
        ty += 15
    p.append(text(w / 2, qy + qh - 12, f"— {author}", key="accent", size=10, anchor="middle"))
    return "".join(p), w, h


def p_footer(cfg):
    w, h = 940, 56
    return frame(w, h) + text(w / 2, 34, cfg.get("footer", ""), key="fg", size=13, anchor="middle"), w, h


# --------------------------------------------------------------------------- #
# Compose the whole dashboard.
# --------------------------------------------------------------------------- #
def dashboard_svg(cfg, stats, pal):
    set_palette(pal)
    layout = [
        (p_banner(cfg), 18, 18),
        (p_stats(cfg, stats), 632, 18),
        (p_journal(cfg), 18, 282),
        (p_building(cfg), 18, 388),
        (p_tech(cfg), 495, 388),
        (p_learning(cfg), 18, 702),
        (p_activity(cfg, stats), 332, 702),
        (p_connect(cfg), 658, 702),
        (p_footer(cfg), 18, 984),
    ]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{DASH_W}" height="{DASH_H}" '
             f'viewBox="0 0 {DASH_W} {DASH_H}" fill="none" role="img" '
             f'aria-label="{esc(cfg.get("name",""))} — GitHub profile dashboard">',
             rect(0, 0, DASH_W, DASH_H, key="bg", rx=20)]
    for (inner, w, h), x, y in layout:
        parts.append(f'<g transform="translate({x},{y})">{inner}</g>')
    parts.append("</svg>\n")
    return "".join(parts)


def _https(value):
    v = value.strip()
    for prefix in ("https://", "http://"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    return f"https://{v}"


def social_links(cfg):
    soc = cfg.get("socials", {})
    parts = []
    gh = cfg.get("github_username")
    if gh:
        parts.append(f"[GitHub](https://github.com/{gh})")
    if soc.get("linkedin"):
        parts.append(f"[LinkedIn]({_https(soc['linkedin'])})")
    if soc.get("email"):
        parts.append(f"[Email](mailto:{soc['email']})")
    if soc.get("website"):
        parts.append(f"[Website]({_https(soc['website'])})")
    return "  ·  ".join(parts)


def build_readme(cfg):
    body = f"""<!-- ────────────────────────────────────────────────────────────── -->
<!--  GitHub Profile OS — generated by update.py. Do not edit by hand.  -->
<!--  Edit config.json instead; the daily GitHub Action rebuilds this.  -->
<!-- ────────────────────────────────────────────────────────────── -->

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/dashboard-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/dashboard-light.svg">
  <img alt="{esc(cfg.get('name',''))} — GitHub profile dashboard" src="assets/dashboard-dark.svg" width="{DASH_W}">
</picture>

{social_links(cfg)}

</div>
"""
    README_PATH.write_text(body, encoding="utf-8")


def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    username = cfg["github_username"]
    ASSETS_DIR.mkdir(exist_ok=True)

    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    use_sample = ("--sample" in sys.argv) or (not _token() and not in_ci)

    if use_sample:
        print("NOTE: using sample data (no token / local preview). CI uses live data.")
        stats = fetch_sample(cfg)
    else:
        stats = fetch_live(username)  # raises on failure -> CI fails, no fake commit

    (ASSETS_DIR / "dashboard-dark.svg").write_text(dashboard_svg(cfg, stats, DARK), encoding="utf-8")
    (ASSETS_DIR / "dashboard-light.svg").write_text(dashboard_svg(cfg, stats, LIGHT), encoding="utf-8")
    build_readme(cfg)

    # Remove stale v2 per-panel assets if present.
    for old in ["banner", "github_stats", "journal", "currently_building", "tech_stack",
                "learning", "activity", "connect_quote", "footer"]:
        f = ASSETS_DIR / f"{old}.svg"
        if f.exists():
            f.unlink()

    print(f"Profile rebuilt ({'sample' if use_sample else 'live'} data): dashboard-dark.svg, dashboard-light.svg, README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
