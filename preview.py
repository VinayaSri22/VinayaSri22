#!/usr/bin/env python3
"""Dev-only: compose all panels into one dashboard SVG for local preview."""
import json
from pathlib import Path
import update as u

cfg = json.loads((Path(__file__).parent / "config.json").read_text())
stats = u.fetch_stats(cfg["github_username"], cfg.get("stats_fallback", {}))

layout = [
    ("banner", u.panel_banner(cfg), 0, 0),
    ("github_stats", u.panel_stats(cfg, stats), 636, 0),
    ("journal", u.panel_journal(cfg), 0, 262),
    ("currently_building", u.panel_building(cfg), 0, 360),
    ("tech_stack", u.panel_tech(cfg), 478, 360),
    ("learning", u.panel_learning(cfg), 0, 660),
    ("activity", u.panel_activity(cfg, stats), 316, 660),
    ("connect_quote", u.panel_connect_quote(cfg), 646, 660),
    ("footer", u.panel_footer(cfg), 0, 930),
]

import re
dark_style = re.sub(r"@media \(prefers-color-scheme:light\)\{:root\{[^}]*\}\}", "", u.STYLE)

W, H = 968, 996
parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" fill="none">{dark_style}',
         f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0a0a0a"/>']
for name, (inner, w, h), x, y in layout:
    parts.append(f'<g transform="translate({x},{y})">{inner}</g>')
parts.append("</svg>")
Path("preview.svg").write_text("".join(parts), encoding="utf-8")
print("wrote preview.svg")
