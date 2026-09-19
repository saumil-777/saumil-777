"""
common.py — shared constants and helpers for all SVG generators.

Design decisions captured here so every panel stays consistent:
  - BG / BORDER follow GitHub's dark-mode palette so the SVG looks the same
    in light and dark mode (an SVG behind <img> can't detect prefers-color-scheme).
  - FONT_STACK uses only faces that ship with Windows, macOS and Linux.
  - GLYPH_RAMP is ordered dark→bright so black pixels vanish into the panel
    and bright pixels get the densest glyph (inverted from white-bg pipelines).
"""

# -- Colours -------------------------------------------------------------------
BG       = "#0d1117"   # GitHub dark background
BORDER   = "#21262d"   # GitHub dark border
GREEN    = "#3fb950"   # terminal green (titles, labels)
DIM      = "#8b949e"   # muted grey (separators, dim text)
WHITE    = "#e6edf3"   # body text
AMBER    = "#d29922"   # accent (colon separators in card)

# Contribution heatmap colours (GitHub's exact palette)
HEAT = {
    0: "#161b22",
    1: "#0e4429",
    2: "#006d32",
    3: "#26a641",
    4: "#39d353",
}

# -- Typography ----------------------------------------------------------------
# Only OS-bundled monospace faces — no webfonts, no remote references.
FONT_STACK = (
    "'Cascadia Code', 'Fira Code', 'Consolas', "
    "'Menlo', 'Monaco', 'Courier New', monospace"
)

# -- ASCII glyph ramp (dark → bright) -----------------------------------------
# Index 0 = darkest (maps to near-black pixels) → vanishes into dark panel.
# Index -1 = brightest (maps to near-white pixels) → most prominent glyph.
# One colour only — rainbow colouring turns portraits into static.
GLYPH_RAMP = r" .`:-=+*csS#%@"
RAMP_LEN   = len(GLYPH_RAMP)          # 14


def brightness_to_glyph(b: float) -> str:
    """Map normalised brightness [0,1] to a glyph. b=0 → space, b=1 → '@'."""
    idx = int(b * (RAMP_LEN - 1) + 0.5)
    idx = max(0, min(RAMP_LEN - 1, idx))
    return GLYPH_RAMP[idx]


# -- SVG helpers ---------------------------------------------------------------
def svg_open(width: int, height: int, extra_css: str = "") -> str:
    """Return the SVG opening tag + defs with the shared CSS reset."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'<defs>\n'
        f'<style>\n'
        f'  text {{ font-family: {FONT_STACK}; fill: {WHITE}; }}\n'
        f'{extra_css}'
        f'</style>\n'
        f'</defs>\n'
    )


def svg_close() -> str:
    return '</svg>\n'


def panel_chrome(width: int, height: int, title: str) -> str:
    """
    Dark terminal panel: filled background rect + border rect + title bar.
    Returns SVG fragment (no opening/closing <svg> tags).
    """
    bar_h = 28
    dot_r = 5
    lines = []
    # Background
    lines.append(
        f'<rect width="{width}" height="{height}" '
        f'rx="8" ry="8" fill="{BG}" />'
    )
    # Border
    lines.append(
        f'<rect width="{width}" height="{height}" '
        f'rx="8" ry="8" fill="none" stroke="{BORDER}" stroke-width="1.5" />'
    )
    # Title bar background
    lines.append(
        f'<rect width="{width}" height="{bar_h}" '
        f'rx="8" ry="8" fill="{BORDER}" />'
    )
    # Cover bottom-rounded corners of title bar
    lines.append(
        f'<rect y="{bar_h - 8}" width="{width}" height="8" fill="{BORDER}" />'
    )
    # Traffic-light dots
    colours = ["#ff5f57", "#ffbd2e", "#28c840"]
    for i, c in enumerate(colours):
        cx = 14 + i * 18
        lines.append(
            f'<circle cx="{cx}" cy="{bar_h // 2}" r="{dot_r}" fill="{c}" />'
        )
    # Title text
    lines.append(
        f'<text x="{width // 2}" y="{bar_h // 2 + 5}" '
        f'text-anchor="middle" font-size="12" '
        f'font-family={FONT_STACK!r} fill="{GREEN}">'
        f'{title}</text>'
    )
    return '\n'.join(lines)


def validate_svg(path: str) -> list[str]:
    """
    Basic validation: parse as XML, check no <script>, no external refs.
    Returns list of error strings (empty = pass).
    """
    import xml.etree.ElementTree as ET
    import re

    errors = []
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        errors.append(f"Invalid XML: {exc}")
        return errors

    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}

    # No <script> elements (GitHub strips them, but let's be explicit)
    for script in root.iter():
        if script.tag.endswith("}script") or script.tag == "script":
            errors.append("<script> element found — not allowed in README SVGs")

    # No external references (href / xlink:href / src starting with http)
    ext_pat = re.compile(r"https?://")
    for elem in root.iter():
        for attr in ("href", "{http://www.w3.org/1999/xlink}href", "src"):
            val = elem.get(attr, "")
            if ext_pat.match(val):
                errors.append(
                    f"External reference in <{elem.tag} {attr}={val!r}>"
                )

    return errors


def check_bounds(path: str) -> list[str]:
    """
    Parse the SVG viewBox and walk every <text> and <rect> element.
    Warn if any x-coordinate falls outside [0, vb_width].
    Returns list of warning strings.
    """
    import xml.etree.ElementTree as ET

    warnings = []
    tree = ET.parse(path)
    root = tree.getroot()

    vb = root.get("viewBox", "")
    try:
        _, _, vb_w, vb_h = [float(v) for v in vb.split()]
    except ValueError:
        warnings.append(f"Cannot parse viewBox: {vb!r}")
        return warnings

    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag not in ("text", "rect", "circle"):
            continue
        for attr in ("x", "cx"):
            raw = elem.get(attr)
            if raw is None:
                continue
            try:
                val = float(raw)
            except ValueError:
                continue
            if val < 0 or val > vb_w:
                warnings.append(
                    f"<{tag} {attr}={val}> is outside viewBox width {vb_w}"
                )
        # For rect, also check x + width
        if tag == "rect":
            x   = float(elem.get("x",     "0") or "0")
            w   = float(elem.get("width", "0") or "0")
            if x + w > vb_w + 1:   # 1 px tolerance
                warnings.append(
                    f"<rect x={x} width={w}> right edge {x+w:.1f} > {vb_w}"
                )

    return warnings
