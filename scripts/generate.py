#!/usr/bin/env python3
"""Generate a fastfetch-style SVG card for the GitHub profile README.

Left side: the GitHub avatar rendered as colored ASCII art.
Right side: static "system info" lines plus live stats from the GitHub API.

Usage:  GITHUB_TOKEN=... python scripts/generate.py
Writes: assets/fetch-dark.svg and assets/fetch-light.svg
"""

import io
import json
import os
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from PIL import Image

USER = os.environ.get("GH_USER", "RMP-deb")

# ---- Edit these to change the static part of the card ----------------------
STATIC_INFO = [
    ("OS", "Debian GNU/Linux"),
    ("Host", f"github.com/{USER}"),
    ("Uptime", "{uptime}"),  # filled with account age
    ("Shell", "bash"),
    ("Interests", "Genomics, Bioinformatics, Herpetology"),
    ("Comfortable", "Linux, Git, Bash, R"),
    ("Learning", "Rust, C++"),
]

# ---- Layout -----------------------------------------------------------------
ASCII_COLS = 70
ASCII_ROWS = 34
ART_FONT = 9  # art uses a smaller font for more detail
ART_CHAR_W = ART_FONT * 0.6
ART_LINE_H = 11
RAMP = " .:-=+*#%@"  # light -> dense
FONT_SIZE = 14
CHAR_W = FONT_SIZE * 0.6  # typical monospace advance
LINE_H = 18
PAD = 24
TITLEBAR_H = 34
GAP = 32
INFO_COLS = 52

THEMES = {
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "bar": "#161b22",
        "text": "#c9d1d9",
        "key": "#ff4d6d",
        "dim": "#8b949e",
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "bar": "#f6f8fa",
        "text": "#24292f",
        "key": "#d70a53",
        "dim": "#57606a",
    },
}
PALETTE = ["#484f58", "#ff7b72", "#3fb950", "#d29922", "#58a6ff", "#bc8cff", "#39c5cf", "#b1bac4"]


# ---- GitHub API -------------------------------------------------------------
def gql(query, variables=None):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN (or GH_TOKEN) to query the GitHub API.")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-fetch-card"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch_stats():
    data = gql(
        """
        query($login: String!) {
          user(login: $login) {
            createdAt
            avatarUrl(size: 200)
            followers { totalCount }
            contributionsCollection { contributionYears contributionCalendar { totalContributions } }
            repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
              totalCount
              nodes {
                stargazerCount
                languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                  edges { size node { name } }
                }
              }
            }
          }
        }""",
        {"login": USER},
    )["user"]

    # All-time commits: one aliased contributionsCollection per year.
    years = data["contributionsCollection"]["contributionYears"]
    commits = 0
    if years:
        parts = [
            f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") '
            "{ totalCommitContributions restrictedContributionsCount }"
            for y in years
        ]
        yd = gql(f"query($login: String!) {{ user(login: $login) {{ {' '.join(parts)} }} }}", {"login": USER})["user"]
        commits = sum(v["totalCommitContributions"] for v in yd.values())

    langs = {}
    stars = 0
    for repo in data["repositories"]["nodes"]:
        stars += repo["stargazerCount"]
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    top = [n for n, _ in sorted(langs.items(), key=lambda kv: -kv[1])[:4]]

    return {
        "created": datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00")),
        "avatar": data["avatarUrl"],
        "followers": data["followers"]["totalCount"],
        "repos": data["repositories"]["totalCount"],
        "stars": stars,
        "commits": commits,
        "contribs_year": data["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "top_langs": top,
    }


def account_age(created):
    now = datetime.now(timezone.utc)
    months = (now.year - created.year) * 12 + now.month - created.month
    if now.day < created.day:
        months -= 1
    anchor_m = created.month - 1 + months
    anchor = created.replace(year=created.year + anchor_m // 12, month=anchor_m % 12 + 1, day=min(created.day, 28))
    days = (now - anchor).days
    y, m = divmod(months, 12)
    unit = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return ", ".join([unit(y, "year"), unit(m, "month"), unit(days, "day")])


# ---- ASCII art --------------------------------------------------------------
def avatar_ascii(url):
    """Return rows of [(char, '#rrggbb'), ...]. Dark pixels become spaces."""
    req = urllib.request.Request(url, headers={"User-Agent": "profile-fetch-card"})
    with urllib.request.urlopen(req) as r:
        img = Image.open(io.BytesIO(r.read())).convert("RGBA")
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    img = Image.alpha_composite(bg, img).convert("RGB").resize((ASCII_COLS, ASCII_ROWS), Image.LANCZOS)

    rows = []
    for y in range(ASCII_ROWS):
        row = []
        for x in range(ASCII_COLS):
            r, g, b = img.getpixel((x, y))
            v = max(r, g, b) / 255  # use brightest channel so saturated colors read as dense
            ch = RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))]
            # lift dim colors so they stay visible, quantize to keep the SVG small
            boost = 255 / max(r, g, b, 1)
            q = lambda c: min(255, int(c * min(boost, 1.6)) // 16 * 16)
            row.append((ch, f"#{q(r):02x}{q(g):02x}{q(b):02x}"))
        rows.append(row)
    return rows


# ---- SVG --------------------------------------------------------------------
def info_lines(stats):
    """Return list of lines; each line is a list of (text, role) segments."""
    host = f"{USER.lower()}@github"
    lines = [[(USER.lower(), "key"), ("@", "text"), ("github", "key")], [("-" * len(host), "text")]]
    for k, v in STATIC_INFO:
        lines.append([(f"{k}: ", "key"), (v.format(uptime=account_age(stats["created"])), "text")])
    lines.append([])
    title = "GitHub Stats "
    lines.append([("- ", "dim"), (title, "key"), ("-" * (INFO_COLS - len(title) - 2), "dim")])
    lines += [
        [("Repos: ", "key"), (str(stats["repos"]), "text"), ("  |  ", "dim"), ("Stars: ", "key"), (str(stats["stars"]), "text")],
        [("Followers: ", "key"), (str(stats["followers"]), "text")],
        [("Commits: ", "key"), (f"{stats['commits']:,}", "text"), (" (all time)", "dim")],
        [("Contributions: ", "key"), (f"{stats['contribs_year']:,}", "text"), (" (past year)", "dim")],
        [("Top Langs: ", "key"), (", ".join(stats["top_langs"]) or "n/a", "text")],
        [],
        "PALETTE",
    ]
    return lines


def spans(segs, x0, char_w=CHAR_W):
    """Emit tspans with explicit x so columns stay aligned in every SVG renderer."""
    out, col = [], 0
    for seg in segs:
        text, fill, cls = (seg + (None,))[:3]
        if text.strip():
            attr = f' fill="{fill}"' if fill else ""
            attr += f' class="{cls}"' if cls else ""
            lead = len(text) - len(text.lstrip(" "))
            out.append(f'<tspan x="{x0 + (col + lead) * char_w:.1f}"{attr}>{escape(text.strip())}</tspan>')
        col += len(text)
    return "".join(out)


def render(stats, art, theme):
    t = THEMES[theme]
    lines = info_lines(stats)
    art_w = ASCII_COLS * ART_CHAR_W
    art_h = ASCII_ROWS * ART_LINE_H
    info_x = PAD + art_w + GAP
    width = int(info_x + INFO_COLS * CHAR_W + PAD)
    body_h = max(art_h, len(lines) * LINE_H)
    height = int(TITLEBAR_H + PAD + body_h + PAD)
    top = TITLEBAR_H + PAD  # top of the body area

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>text{font-family:ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono','DejaVu Sans Mono',monospace;"
        f"font-size:{FONT_SIZE}px;white-space:pre}}"
        f".art{{font-size:{ART_FONT}px}}.key{{fill:{t['key']};font-weight:bold}}.text{{fill:{t['text']}}}.dim{{fill:{t['dim']}}}</style>",
        f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>',
        f'<path d="M0.5 {TITLEBAR_H} V10.5 a10 10 0 0 1 10 -10 H{width-10.5} a10 10 0 0 1 10 10 V{TITLEBAR_H} Z" fill="{t["bar"]}" stroke="{t["border"]}"/>',
    ]
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        out.append(f'<circle cx="{20 + i*20}" cy="{TITLEBAR_H/2}" r="6" fill="{c}"/>')
    out.append(
        f'<text x="{width/2}" y="{TITLEBAR_H/2 + 5}" text-anchor="middle" class="dim">{escape(USER.lower())}@github: ~ $ fastfetch</text>'
    )

    # ASCII art, merging runs of identical color into one tspan
    art_y0 = top + (body_h - art_h) / 2 + ART_FONT
    for y, row in enumerate(art):
        segs, cur, buf = [], None, ""
        for ch, col in row:
            # spaces are invisible, so they can join whatever run is open
            if ch != " " and col != cur:
                if buf:
                    segs.append((buf, cur))
                buf, cur = "", col
            buf += ch
        if buf:
            segs.append((buf, cur))
        out.append(f'<text class="art" y="{art_y0 + y*ART_LINE_H:.1f}" xml:space="preserve">{spans(segs, PAD, ART_CHAR_W)}</text>')

    # Info column
    info_y0 = top + (body_h - len(lines) * LINE_H) / 2 + FONT_SIZE
    for i, line in enumerate(lines):
        y = info_y0 + i * LINE_H
        if line == "PALETTE":
            for j, c in enumerate(PALETTE):
                out.append(f'<rect x="{info_x + j*3*CHAR_W:.1f}" y="{y - FONT_SIZE + 2:.1f}" width="{3*CHAR_W:.1f}" height="{LINE_H - 2}" fill="{c}"/>')
            continue
        if not line:
            continue
        segs = [(s, None, role) for s, role in line]
        out.append(f'<text y="{y:.1f}" xml:space="preserve">{spans(segs, info_x)}</text>')

    out.append("</svg>")
    return "\n".join(out)


def main():
    stats = fetch_stats()
    art = avatar_ascii(stats["avatar"])
    outdir = Path(__file__).resolve().parent.parent / "assets"
    outdir.mkdir(exist_ok=True)
    for theme in THEMES:
        (outdir / f"fetch-{theme}.svg").write_text(render(stats, art, theme))
    print(f"Wrote SVGs to {outdir}: {json.dumps({k: v for k, v in stats.items() if k not in ('created', 'avatar')})}")


if __name__ == "__main__":
    main()
