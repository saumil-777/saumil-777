#!/usr/bin/env python3
"""
gen_card.py — Generate a neofetch-style info card SVG.

Usage:
    python scripts/gen_card.py [output.svg]

Environment:
    STATIC=1   Emit a frozen frame (all lines visible, no animation).

Design decisions:
  - Each line is a separate <g> element so the whole row (label + colon + value)
    animates together.
  - CSS @keyframes with animation-fill-mode:forwards keeps lines visible after
    they fade in — no looping.
  - Labels in green, colons in amber, values in white — the standard neofetch
    colour grammar.
  - The 8-colour swatch at the bottom is built from <rect> elements (no text
    or emoji) so it renders identically on every OS.
  - SVG dimensions are computed from the content so gen_readme.py can read the
    viewBox and calculate display widths that make portrait and card the same
    height when placed side-by-side.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    BG, BORDER, GREEN, DIM, WHITE, AMBER,
    FONT_STACK,
    panel_chrome, svg_open, svg_close,
    validate_svg, check_bounds,
)

STATIC = os.environ.get("STATIC", "0") == "1"

# -- Card content --------------------------------------------------------------
# Each tuple: (label, value)  — use None for separator lines, "" for blank.
USERNAME = "saumil-777"
HOST     = "github"

CARD_LINES: list[tuple[str | None, str]] = [
    # (label, value)   label=None → dim separator line, label="" → blank
    (None,   "\u2500" * 38),
    ("OS",   "Human v21  ·  India 🇮🇳"),
    ("Role",  "CSE (AIML)  ·  MERN + ML Dev"),
    ("Build", "RAG systems  ·  AI-powered apps"),
    ("Stack", "Python  ·  Java  ·  React  ·  Node.js"),
    ("DB",    "MongoDB  ·  Firebase"),
    ("Tools", "Git  ·  VSCode  ·  LangChain"),
    ("OSS",   "GSSoC '24 Contributor"),
    ("School","VIT Bhopal University"),
    ("Links", "linkedin/saumil-singhal  ·  lc/Saumil_Singhal"),
    ("Email", "singhalsaumil2005@gmail.com"),
    (None,   "\u2500" * 38),
]

# -- Layout --------------------------------------------------------------------
FONT_SIZE  = 13      # px
LINE_H     = 24      # px — line height (generous for breathing room)
TITLE_H    = 28      # px — title bar
PAD_TOP    = 18      # px — gap between title bar and first line
PAD_SIDE   = 18      # px
PAD_BOT    = 18      # px
LABEL_W    = 52      # px — fixed-width label column

# Swatch row at the bottom
SWATCH_COLOURS = [
    "#ff5f57", "#ffbd2e", "#28c840",
    "#007aff", "#af52de", "#ff375f",
    "#30d158", "#636366",
]
SWATCH_SIZE = 13    # px square
SWATCH_GAP  = 6     # px between swatches


def _xml_esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def build_svg(title: str = "~/saumil-777/info-card.sh") -> str:
    # Total lines: header + sep + content + sep + blank + swatches
    n_content_lines = len(CARD_LINES)
    swatch_row_h    = SWATCH_SIZE + 4
    total_h_content = (
        LINE_H             # username@host header
        + n_content_lines * LINE_H
        + LINE_H           # blank spacer before swatches
        + swatch_row_h     # colour swatches
    )

    svg_w = 420
    svg_h = TITLE_H + PAD_TOP + total_h_content + PAD_BOT

    # -- CSS ------------------------------------------------------------------
    total_anim_lines = 1 + n_content_lines + 1  # header + content + swatches
    if STATIC:
        anim_css = "  .ln { opacity: 1; }\n"
    else:
        delays = "\n".join(
            f"  .l{i} {{ animation-delay: {0.12 + i * 0.10:.2f}s; }}"
            for i in range(total_anim_lines)
        )
        anim_css = (
            "  @keyframes lnfade {\n"
            "    from { opacity: 0; }\n"
            "    to   { opacity: 1; }\n"
            "  }\n"
            "  .ln {\n"
            "    opacity: 0;\n"
            "    animation: lnfade 0.35s ease forwards;\n"
            "  }\n"
            f"{delays}\n"
        )

    out = [svg_open(svg_w, svg_h, extra_css=anim_css)]
    out.append(panel_chrome(svg_w, svg_h, title))

    # Clip path
    out.append(
        f'<clipPath id="cc">'
        f'<rect x="0" y="{TITLE_H}" width="{svg_w}" height="{svg_h - TITLE_H}" />'
        f'</clipPath>'
    )
    out.append('<g clip-path="url(#cc)">')

    y   = TITLE_H + PAD_TOP
    idx = 0   # animation line index

    def line_g(content_nodes: list[str], idx: int) -> list[str]:
        cls = f"ln l{idx}" if not STATIC else "ln"
        return [f'<g class="{cls}">'] + content_nodes + ['</g>']

    # -- Header: username@host -------------------------------------------------
    y += LINE_H
    header_nodes = [
        f'<text x="{PAD_SIDE}" y="{y}" font-size="{FONT_SIZE + 1}"'
        f' font-weight="bold" fill="{GREEN}"'
        f' font-family={FONT_STACK!r}>'
        f'{_xml_esc(USERNAME)}</text>',
        f'<text x="{PAD_SIDE + (FONT_SIZE + 1) * len(USERNAME) * 0.62:.0f}" y="{y}"'
        f' font-size="{FONT_SIZE + 1}" fill="{DIM}"'
        f' font-family={FONT_STACK!r}>@{_xml_esc(HOST)}</text>',
    ]
    out.extend(line_g(header_nodes, idx)); idx += 1

    # -- Content lines ---------------------------------------------------------
    for label, value in CARD_LINES:
        y += LINE_H
        if label is None:
            # Separator
            nodes = [
                f'<text x="{PAD_SIDE}" y="{y}" font-size="{FONT_SIZE}"'
                f' fill="{DIM}" font-family={FONT_STACK!r}>'
                f'{_xml_esc(value)}</text>'
            ]
        elif label == "":
            nodes = []  # blank line — still advances y
        else:
            lbl_x  = PAD_SIDE
            col_x  = PAD_SIDE + LABEL_W
            val_x  = col_x + int(FONT_SIZE * 0.65)

            nodes = [
                # Label
                f'<text x="{lbl_x}" y="{y}" font-size="{FONT_SIZE}"'
                f' fill="{GREEN}" font-family={FONT_STACK!r}>{_xml_esc(label)}</text>',
                # Colon
                f'<text x="{col_x}" y="{y}" font-size="{FONT_SIZE}"'
                f' fill="{AMBER}" font-family={FONT_STACK!r}>:</text>',
                # Value
                f'<text x="{val_x}" y="{y}" font-size="{FONT_SIZE}"'
                f' fill="{WHITE}" font-family={FONT_STACK!r}>{_xml_esc(value)}</text>',
            ]
        out.extend(line_g(nodes, idx)); idx += 1

    # -- Colour swatches -------------------------------------------------------
    y += LINE_H  # blank spacer
    swatch_y = y + 2
    sw_nodes = []
    for si, colour in enumerate(SWATCH_COLOURS):
        sx = PAD_SIDE + si * (SWATCH_SIZE + SWATCH_GAP)
        sw_nodes.append(
            f'<rect x="{sx}" y="{swatch_y}" width="{SWATCH_SIZE}" height="{SWATCH_SIZE}"'
            f' rx="2" fill="{colour}" />'
        )
    out.extend(line_g(sw_nodes, idx)); idx += 1

    out.append('</g>')   # /clip
    out.append(svg_close())
    return "".join(out)


def main() -> None:
    output_path = sys.argv[1] if len(sys.argv) > 1 else "info-card.svg"
    print(f"\n[card] Building info card -> {output_path!r}")
    svg = build_svg()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[card] Written -> {output_path}")

    errs  = validate_svg(output_path)
    warns = check_bounds(output_path)
    if errs:
        print("ERRORS:", errs); sys.exit(1)
    if warns:
        print("BOUNDS WARNINGS:", warns)
    print("[card] OK Validation passed.")


if __name__ == "__main__":
    main()
