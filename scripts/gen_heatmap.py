#!/usr/bin/env python3
"""
gen_heatmap.py — Fetch and render the GitHub contribution heatmap SVG.

Usage:
    python scripts/gen_heatmap.py [output.svg]

Environment:
    STATIC=1          Emit a frozen frame (all cells visible, no animation).
    GH_USERNAME=xxx   Override the hard-coded username.

Dependencies: requests, beautifulsoup4

Data source:
    https://github.com/users/<username>/contributions
    - Day cells:  <td data-date="YYYY-MM-DD" data-level="0-4" id="...">
    - Exact counts live in: <tool-tip for="<cell-id>">N contributions ...</tool-tip>
      We join them by id.  Level 0 = no contributions; levels 1-4 = GitHub's
      four shades of green.

Animation:
    Diagonal reveal: cell at (col, row) gets delay = col*T_COL + row*T_ROW.
    This makes the calendar wipe from top-left to bottom-right.
    Each cell transitions from opacity 0 to 1 with fill-mode:forwards.
    No looping.

Legend:
    "Less □□□□□ More" in the bottom-right corner.
    Positions are computed so the rightmost element never exceeds svg_w - PAD.

Stats footer:
    Total contributions  ·  Longest streak  ·  Current streak
    All computed from the parsed data — no third-party API, no token.
"""

import os
import re
import sys
import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing: pip install requests beautifulsoup4")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    BG, BORDER, GREEN, DIM, WHITE, AMBER, HEAT,
    FONT_STACK,
    panel_chrome, svg_open, svg_close,
    validate_svg, check_bounds,
)

# -- Configuration -------------------------------------------------------------
USERNAME   = os.environ.get("GH_USERNAME", "saumil-777")
STATIC     = os.environ.get("STATIC", "0") == "1"

# -- Layout --------------------------------------------------------------------
SVG_W      = 860
TITLE_H    = 28
PAD        = 14        # inner padding (left, right, bottom, top-of-content)
CELL       = 11        # cell size px
GAP        = 3         # gap between cells px
STEP       = CELL + GAP  # = 14 px per cell

DAY_LABEL_W = 26       # px reserved for Mon/Wed/Fri labels on the left
MONTH_H     = 16       # px reserved for month labels above the grid

GRID_X     = PAD + DAY_LABEL_W   # x where the grid starts
GRID_Y     = TITLE_H + PAD + MONTH_H   # y where the grid starts
GRID_W     = 53 * STEP            # 742 px
GRID_H     = 7  * STEP            # 98  px

LEGEND_Y   = GRID_Y + GRID_H + 14   # y of the legend strip
STATS_Y    = LEGEND_Y + 20          # y of the stats footer

SVG_H      = STATS_Y + 22           # total SVG height

# Diagonal animation timing
T_COL      = 0.020   # seconds of extra delay per column
T_ROW      = 0.006   # seconds of extra delay per row
FADE_DUR   = 0.18    # fade-in duration per cell

# -- Fetch & parse -------------------------------------------------------------

def fetch_contributions(username: str) -> dict[str, dict]:
    """
    Fetch the GitHub contributions page and return a dict:
        { "YYYY-MM-DD": {"level": int, "count": int}, ... }
    """
    url = f"https://github.com/users/{username}/contributions"
    print(f"  Fetching {url}")
    try:
        resp = requests.get(
            url,
            headers={"Accept": "text/html", "User-Agent": "github-profile-readme-builder/1.0"},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ERROR fetching contributions: {exc}")
        sys.exit(1)

    soup = BeautifulSoup(resp.text, "html.parser")

    # -- Build cell id → date+level map ---------------------------------------
    cells: dict[str, dict] = {}   # id → {"date": str, "level": int, "count": 0}
    for td in soup.find_all("td", attrs={"data-date": True, "data-level": True}):
        cell_id = td.get("id", "")
        date    = td["data-date"]
        try:
            level = int(td["data-level"])
        except (ValueError, KeyError):
            level = 0
        cells[cell_id] = {"date": date, "level": level, "count": 0}

    # -- Join tooltip counts by cell id ----------------------------------------
    # GitHub uses <tool-tip for="..."> or <tooltip for="..."> depending on version.
    count_pat = re.compile(r"(\d+)\s+contribution", re.IGNORECASE)
    for tip in soup.find_all(re.compile(r"tool-tip|tooltip", re.IGNORECASE)):
        for_id = tip.get("for", "")
        if for_id in cells:
            m = count_pat.search(tip.get_text())
            if m:
                cells[for_id]["count"] = int(m.group(1))

    # Return keyed by date (more useful downstream)
    by_date: dict[str, dict] = {}
    for cell in cells.values():
        by_date[cell["date"]] = {"level": cell["level"], "count": cell["count"]}

    print(f"  Parsed {len(by_date)} days of contribution data.")
    return by_date


def build_grid(by_date: dict[str, dict]) -> list[list[dict | None]]:
    """
    Build a 53-column × 7-row grid (col=week, row=weekday Sun=0..Sat=6).
    Returns grid[col][row] = {"date": str, "level": int, "count": int} or None.
    """
    if not by_date:
        return [[None] * 7 for _ in range(53)]

    dates_sorted = sorted(by_date.keys())
    start = datetime.date.fromisoformat(dates_sorted[0])
    end   = datetime.date.fromisoformat(dates_sorted[-1])

    # Align start to the previous Sunday
    start_sun = start - datetime.timedelta(days=start.weekday() + 1)
    if start.weekday() == 6:   # already Sunday
        start_sun = start

    grid: list[list[dict | None]] = [[None] * 7 for _ in range(53)]
    cur  = start_sun
    col  = 0

    while cur <= end + datetime.timedelta(days=6) and col < 53:
        for row in range(7):
            d_str = cur.isoformat()
            if d_str in by_date:
                grid[col][row] = {"date": d_str, **by_date[d_str]}
            else:
                grid[col][row] = None
            cur += datetime.timedelta(days=1)
        col += 1

    return grid


def compute_stats(by_date: dict[str, dict]) -> dict:
    """Compute total, current streak, longest streak from the date dict."""
    total = sum(v["count"] for v in by_date.values())
    dates = sorted(by_date.keys())

    longest = cur_streak = streak = 0
    prev: datetime.date | None = None
    for d_str in dates:
        d   = datetime.date.fromisoformat(d_str)
        cnt = by_date[d_str]["count"]
        if cnt > 0:
            if prev is not None and (d - prev).days == 1:
                streak += 1
            else:
                streak = 1
            longest = max(longest, streak)
        else:
            streak = 0
        prev = d

    # Current streak: walk backwards from today
    today = datetime.date.today()
    cur_streak = 0
    for i in range(366):
        check = (today - datetime.timedelta(days=i)).isoformat()
        if check in by_date and by_date[check]["count"] > 0:
            cur_streak += 1
        elif i > 0:   # allow today to have 0 (day not over yet)
            break

    return {"total": total, "longest": longest, "current": cur_streak}


# -- SVG builder ---------------------------------------------------------------

def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(
    grid: list[list[dict | None]],
    stats: dict,
    title: str = "~/saumil-777/contributions.sh",
) -> str:

    # Verify legend fits: rightmost box must be < SVG_W - PAD
    # Legend: "Less" text + 5 boxes + "More" text
    # font approx 11px * 0.6 char_w
    legend_font = 11
    legend_char_w = legend_font * 0.62
    less_w  = int(len("Less") * legend_char_w)
    more_w  = int(len(" More") * legend_char_w)
    boxes_w = 5 * (CELL + 2) + 4 * 3   # 5 boxes each (CELL+2)x(CELL+2), 3px gap
    legend_total = less_w + 6 + boxes_w + 6 + more_w
    legend_x0 = SVG_W - PAD - legend_total

    # Safety assertion (catches legend overflow before writing)
    assert legend_x0 >= GRID_X, (
        f"Legend overflows: legend_x0={legend_x0} < GRID_X={GRID_X}. "
        f"Increase SVG_W or reduce legend size."
    )

    # -- CSS ------------------------------------------------------------------
    if STATIC:
        cell_css = "  .cell { opacity: 1; }\n"
    else:
        cell_css = (
            "  @keyframes cellon {\n"
            "    from { opacity: 0; }\n"
            "    to   { opacity: 1; }\n"
            "  }\n"
            "  .cell {\n"
            "    opacity: 0;\n"
            f"   animation: cellon {FADE_DUR:.2f}s ease forwards;\n"
            "  }\n"
        )

    out = [svg_open(SVG_W, SVG_H, extra_css=cell_css)]
    out.append(panel_chrome(SVG_W, SVG_H, title))

    # -- Month labels ----------------------------------------------------------
    month_y   = GRID_Y - 4
    prev_month = ""
    for col in range(53):
        # Find the first non-None cell in this column to get the month
        month_str = ""
        for row in range(7):
            cell = grid[col][row] if col < len(grid) else None
            if cell is not None:
                try:
                    d  = datetime.date.fromisoformat(cell["date"])
                    month_str = d.strftime("%b")
                except ValueError:
                    pass
                break
        if month_str and month_str != prev_month:
            mx = GRID_X + col * STEP
            out.append(
                f'<text x="{mx}" y="{month_y}" font-size="10"'
                f' fill="{DIM}" font-family={FONT_STACK!r}>{month_str}</text>'
            )
            prev_month = month_str

    # -- Day labels (Mon, Wed, Fri) --------------------------------------------
    day_labels = {1: "Mon", 3: "Wed", 5: "Fri"}
    for row, lbl in day_labels.items():
        dy = GRID_Y + row * STEP + CELL - 1
        out.append(
            f'<text x="{PAD}" y="{dy}" font-size="9"'
            f' fill="{DIM}" font-family={FONT_STACK!r}>{lbl}</text>'
        )

    # -- Clip path -------------------------------------------------------------
    out.append(
        f'<clipPath id="hc">'
        f'<rect x="{GRID_X}" y="{GRID_Y}" width="{GRID_W}" height="{GRID_H}" />'
        f'</clipPath>'
    )

    # -- Grid cells ------------------------------------------------------------
    out.append('<g clip-path="url(#hc)">')
    for col in range(min(53, len(grid))):
        for row in range(7):
            cell = grid[col][row]
            level = cell["level"] if cell else 0
            colour = HEAT.get(level, HEAT[0])
            cx = GRID_X + col * STEP
            cy = GRID_Y + row * STEP
            delay = col * T_COL + row * T_ROW
            tooltip = ""
            if cell:
                cnt  = cell["count"]
                date = cell["date"]
                tooltip = f'{cnt} contribution{"s" if cnt != 1 else ""} on {date}'

            if STATIC:
                style_attr = ""
            else:
                style_attr = f' style="animation-delay:{delay:.3f}s"'

            out.append(
                f'<rect x="{cx}" y="{cy}" width="{CELL}" height="{CELL}"'
                f' rx="2" fill="{colour}" class="cell"{style_attr}>'
                + (f'<title>{_xml_esc(tooltip)}</title>' if tooltip else "")
                + "</rect>"
            )
    out.append('</g>')   # /grid clip

    # -- Legend ----------------------------------------------------------------
    lx = legend_x0
    ly = LEGEND_Y + 1

    out.append(
        f'<text x="{lx}" y="{ly + CELL - 1}" font-size="{legend_font}"'
        f' fill="{DIM}" font-family={FONT_STACK!r}>Less</text>'
    )
    lx += less_w + 6

    for li in range(5):
        col  = HEAT.get(li, HEAT[0])
        out.append(
            f'<rect x="{lx}" y="{ly}" width="{CELL}" height="{CELL}"'
            f' rx="2" fill="{col}" />'
        )
        lx += CELL + 3

    lx += 3
    out.append(
        f'<text x="{lx}" y="{ly + CELL - 1}" font-size="{legend_font}"'
        f' fill="{DIM}" font-family={FONT_STACK!r}>More</text>'
    )

    # -- Stats footer ----------------------------------------------------------
    stats_items = [
        ("Total", f"{stats['total']:,}"),
        ("Longest streak", f"{stats['longest']} days"),
        ("Current streak", f"{stats['current']} days"),
    ]
    stats_font = 11
    stats_x    = GRID_X
    for label, value in stats_items:
        out.append(
            f'<text x="{stats_x}" y="{STATS_Y}" font-size="{stats_font}"'
            f' fill="{DIM}" font-family={FONT_STACK!r}>'
            f'<tspan fill="{GREEN}">{_xml_esc(label)}</tspan>'
            f' <tspan fill="{WHITE}">{_xml_esc(value)}</tspan>'
            f'</text>'
        )
        # Advance x by approximate text width
        stats_x += int((len(label) + len(value) + 4) * stats_font * 0.62)
        if stats_x > SVG_W - PAD:
            break   # don't overflow

    out.append(svg_close())
    return "".join(out)


# -- Entry point ---------------------------------------------------------------

def main() -> None:
    output_path = sys.argv[1] if len(sys.argv) > 1 else "contrib-heatmap.svg"
    print(f"\n[heatmap] {USERNAME} -> {output_path!r}")
    print("[heatmap] Fetching GitHub contribution data ...")
    by_date = fetch_contributions(USERNAME)

    print("[heatmap] Building grid ...")
    grid = build_grid(by_date)

    print("[heatmap] Computing stats ...")
    stats = compute_stats(by_date)
    print(
        f"  Total: {stats['total']:,}   "
        f"Longest streak: {stats['longest']} days   "
        f"Current streak: {stats['current']} days"
    )

    print("[heatmap] Building SVG ...")
    svg = build_svg(grid, stats)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[heatmap] Written -> {output_path}")

    errs  = validate_svg(output_path)
    warns = check_bounds(output_path)
    if errs:
        print("ERRORS:", errs); sys.exit(1)
    if warns:
        print("BOUNDS WARNINGS:", warns)
    print("[heatmap] OK Validation passed.")


if __name__ == "__main__":
    main()
