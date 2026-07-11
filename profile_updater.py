#!/usr/bin/env python3
"""Self-updating GitHub profile README generator.

Fetches recent public GitHub activity, generates light/dark-mode aware header
banners, and rewrites the dynamic sections of README.md in place. Designed to
run from GitHub Actions with no external server and minimal dependencies
(standard library + PyYAML).
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

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "data" / "config.yml"
README_PATH = ROOT / "README.md"
ASSETS_DIR = ROOT / "assets"
API_ROOT = "https://api.github.com"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def api_get(path: str) -> object | None:
    """GET a GitHub API endpoint. Uses GITHUB_TOKEN if present for rate limits."""
    url = f"{API_ROOT}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "self-updating-profile-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with urlopen(Request(url, headers=headers), timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        print(f"warning: API request to {path} failed: {exc}", file=sys.stderr)
        return None


def humanize_delta(then: datetime, now: datetime) -> str:
    seconds = int((now - then).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


# --------------------------------------------------------------------------- #
# Recent activity
# --------------------------------------------------------------------------- #
def describe_event(event: dict) -> str | None:
    """Turn a raw GitHub event into a short markdown line, or None to skip."""
    etype = event.get("type")
    repo_name = event.get("repo", {}).get("name", "")
    repo_link = f"[`{repo_name}`](https://github.com/{repo_name})" if repo_name else ""
    payload = event.get("payload", {}) or {}

    if etype == "PushEvent":
        n = payload.get("size", len(payload.get("commits", []))) or 1
        commits = "commit" if n == 1 else "commits"
        return f"Pushed {n} {commits} to {repo_link}"
    if etype == "PullRequestEvent":
        action = payload.get("action", "updated")
        pr = payload.get("pull_request", {}) or {}
        if action == "closed" and pr.get("merged"):
            action = "merged"
        num = pr.get("number")
        ref = f"#{num}" if num else "a pull request"
        return f"{action.capitalize()} PR {ref} in {repo_link}"
    if etype == "IssuesEvent":
        action = payload.get("action", "updated")
        num = (payload.get("issue", {}) or {}).get("number")
        ref = f"#{num}" if num else "an issue"
        return f"{action.capitalize()} issue {ref} in {repo_link}"
    if etype == "IssueCommentEvent":
        num = (payload.get("issue", {}) or {}).get("number")
        ref = f"#{num}" if num else "an issue"
        return f"Commented on {ref} in {repo_link}"
    if etype == "WatchEvent":
        return f"Starred {repo_link}"
    if etype == "ForkEvent":
        return f"Forked {repo_link}"
    if etype == "CreateEvent":
        ref_type = payload.get("ref_type", "repository")
        return f"Created {ref_type} in {repo_link}"
    if etype == "ReleaseEvent":
        tag = (payload.get("release", {}) or {}).get("tag_name", "")
        tag = f" `{tag}`" if tag else ""
        return f"Published release{tag} in {repo_link}"
    if etype == "PublicEvent":
        return f"Open-sourced {repo_link}"
    return None


def build_activity(username: str, count: int) -> str:
    events = api_get(f"/users/{username}/events/public")
    if not events:
        return "_No recent public activity to show right now — check back soon._"

    now = datetime.now(timezone.utc)
    lines: list[str] = []
    for event in events:
        text = describe_event(event)
        if not text:
            continue
        try:
            then = datetime.fromisoformat(
                event["created_at"].replace("Z", "+00:00")
            )
            when = humanize_delta(then, now)
        except (KeyError, ValueError):
            when = ""
        suffix = f" — <sub>{when}</sub>" if when else ""
        lines.append(f"- {text}{suffix}")
        if len(lines) >= count:
            break

    return "\n".join(lines) if lines else "_No recent public activity to show right now._"


# --------------------------------------------------------------------------- #
# "Now" section
# --------------------------------------------------------------------------- #
def build_now(now_cfg: dict) -> str:
    if not now_cfg:
        return ""
    rows = [
        ("🔭", "Working on", now_cfg.get("working_on")),
        ("🌱", "Learning", now_cfg.get("learning")),
        ("💬", "Ask me about", now_cfg.get("ask_me_about")),
    ]
    return "\n".join(
        f"- {icon} **{label}:** {value}"
        for icon, label, value in rows
        if value
    )


# --------------------------------------------------------------------------- #
# Theme-aware header banners (SVG)
# --------------------------------------------------------------------------- #
def _svg_banner(name: str, tagline: str, *, bg: str, fg: str, muted: str, accent: str) -> str:
    name = _escape(name)
    tagline = _escape(tagline)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="180" viewBox="0 0 900 180" role="img">
  <rect width="900" height="180" rx="16" fill="{bg}"/>
  <rect x="0" y="0" width="6" height="180" rx="3" fill="{accent}"/>
  <text x="48" y="82" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="40" font-weight="700" fill="{fg}">{name}</text>
  <text x="48" y="122" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="20" fill="{muted}">{tagline}</text>
  <circle cx="852" cy="48" r="6" fill="{accent}"/>
  <circle cx="852" cy="72" r="6" fill="{muted}" opacity="0.5"/>
  <circle cx="852" cy="96" r="6" fill="{muted}" opacity="0.3"/>
</svg>
"""


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def write_banners(name: str, tagline: str) -> None:
    ASSETS_DIR.mkdir(exist_ok=True)
    light = _svg_banner(
        name, tagline, bg="#f6f8fa", fg="#1f2328", muted="#57606a", accent="#0969da"
    )
    dark = _svg_banner(
        name, tagline, bg="#0d1117", fg="#e6edf3", muted="#8b949e", accent="#58a6ff"
    )
    (ASSETS_DIR / "header-light.svg").write_text(light, encoding="utf-8")
    (ASSETS_DIR / "header-dark.svg").write_text(dark, encoding="utf-8")


# --------------------------------------------------------------------------- #
# README rendering
# --------------------------------------------------------------------------- #
def replace_section(content: str, name: str, body: str) -> str:
    start = f"<!-- {name}:START -->"
    end = f"<!-- {name}:END -->"
    if start not in content or end not in content:
        print(f"warning: markers for section '{name}' not found", file=sys.stderr)
        return content
    pre = content.split(start)[0]
    post = content.split(end)[1]
    return f"{pre}{start}\n{body}\n{end}{post}"


def main() -> int:
    cfg = load_config()
    username = cfg.get("github_username", "").strip()
    if not username:
        print("error: github_username missing in config.yml", file=sys.stderr)
        return 1

    name = cfg.get("name") or username
    tagline = cfg.get("tagline") or ""
    count = int(cfg.get("activity_count", 5))

    write_banners(name, tagline)

    activity = build_activity(username, count)
    now_section = build_now(cfg.get("now", {}))

    tz_name = cfg.get("timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
        tz_name = "UTC"
    stamp = datetime.now(tz).strftime("%d %b %Y, %H:%M")
    updated = f"_Last updated: {stamp} ({tz_name}) — auto-generated._"

    content = README_PATH.read_text(encoding="utf-8")
    content = replace_section(content, "NOW", now_section)
    content = replace_section(content, "ACTIVITY", activity)
    content = replace_section(content, "UPDATED", updated)
    README_PATH.write_text(content, encoding="utf-8")

    print("README updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
