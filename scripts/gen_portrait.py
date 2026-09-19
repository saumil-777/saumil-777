#!/usr/bin/env python3
"""
gen_portrait.py — Convert a photo to terminal-style ASCII art SVG.

Usage:
    python scripts/gen_portrait.py <photo_path> [output.svg]

Environment:
    STATIC=1   Emit a frozen frame (all rows already visible, no animation).
               Use this to preview the finished result.  An animation that has
               not yet played looks like an empty panel.

Dependencies: rembg[cpu], opencv-python-headless, Pillow, numpy

Design decisions:
  - rembg removes the background so the clothing silhouette is well-defined.
  - CLAHE (local histogram equalisation) prevents a flatly-lit face from
    rendering as one undifferentiated grey blob.
  - Levels curve (lo=55, hi=225) crushes dark clothing to black so it falls
    into the panel background and vanishes.
  - Crop is measured from the ALPHA silhouette (not brightness), using the
    MEDIAN row-width over the upper 60 % so dark hair is included and a wide
    shoulder doesn't push the face to the side.
  - Crop height is capped at 1.45 × measured head-width so only head+neck
    appear; bright clothing below is excluded.
  - No spaces emitted inside <text>.  Each row is split into runs of non-space
    glyphs; each run gets its own <text> with absolute x and explicit
    textLength + lengthAdjust="spacingAndGlyphs" so alignment holds in every
    renderer, regardless of which monospace face the viewer has installed.
  - Single colour (#3fb950) for ALL glyphs.  Per-glyph rainbow colouring
    turns portraits into static noise.
  - A <clipPath> prevents any glyph from bleeding outside the panel border.
"""

import os
import sys
from io import BytesIO
from pathlib import Path

# -- dependency check ----------------------------------------------------------
MISSING = []
try:
    from PIL import Image
    import numpy as np
except ImportError:
    MISSING.append("Pillow numpy")
try:
    import cv2
except ImportError:
    MISSING.append("opencv-python-headless")
try:
    from rembg import remove as rembg_remove
except ImportError:
    MISSING.append("rembg[cpu]")

if MISSING:
    print("Missing dependencies:", " ".join(MISSING))
    print("Run:  pip install rembg[cpu] opencv-python-headless Pillow numpy")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    BG, BORDER, GREEN, WHITE,
    FONT_STACK, GLYPH_RAMP, RAMP_LEN,
    brightness_to_glyph, panel_chrome, svg_open, svg_close,
    validate_svg, check_bounds,
)

# -- Layout constants ----------------------------------------------------------
COLS      = 58          # character columns
FONT_SIZE = 11          # px
CHAR_W    = round(FONT_SIZE * 0.603, 3)  # ≈ 6.633 px  (empirical mono width)
CHAR_H    = round(FONT_SIZE * 1.18,  3)  # ≈ 12.98 px  (line height)
TITLE_H   = 28          # px — macOS-style title bar
PAD_SIDE  = 12          # px — left and right inner padding
PAD_BOT   = 12          # px — bottom inner padding
GLYPH_COL = GREEN       # single glyph colour — no rainbow noise

STATIC = os.environ.get("STATIC", "0") == "1"


# -- Image processing ----------------------------------------------------------

def load_image(path: str) -> "Image.Image":
    """
    Open an image file.  PIL sniffs the format from magic bytes, so a JPEG
    file mis-named '.pdf' still opens correctly.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
        img = Image.open(BytesIO(data))
        img.load()
        print(f"  Opened: {img.size}  mode={img.mode}  ({Path(path).name})")
        return img.convert("RGBA")
    except Exception as exc:
        print(f"\nERROR: Cannot open image at {path!r}")
        print(f"  PIL says: {exc}")
        print("  Make sure the file is a JPEG, PNG, or WebP image.")
        sys.exit(1)


def remove_background(rgba: "Image.Image") -> "Image.Image":
    """Remove background with rembg (u2net model, downloads on first run)."""
    # Use u2netp: ~4 MB model (vs u2net's 1 GB) — quality is equivalent for portraits.
    from rembg import new_session
    session = new_session("u2netp")
    print("  Removing background with u2netp (downloads ~4 MB on first run) ...")
    result = rembg_remove(rgba, session=session)
    print("  Background removed.")
    return result


def crop_to_head(rgba: "Image.Image") -> "Image.Image":
    """
    Crop to head + neck using the alpha silhouette.

    Why median row-width, not max?
      Max catches a wide shoulder and leaves the face adrift in whitespace.
      Median over the upper 60 % of the silhouette gives the actual head width.

    Why cap height at 1.45 × head_width?
      The face is the subject.  A white shirt below reads as very bright glyphs
      and competes with the face.  Cropping it out focuses the portrait.
    """
    alpha = np.array(rgba)[:, :, 3]
    H, W  = alpha.shape

    # Bounding box of the non-transparent region
    row_mask = np.any(alpha > 10, axis=1)
    col_mask = np.any(alpha > 10, axis=0)
    if not row_mask.any() or not col_mask.any():
        print("  WARNING: no foreground pixels after background removal.")
        return rgba
    r0 = int(np.argmax(row_mask))
    r1 = int(H - np.argmax(row_mask[::-1]) - 1)

    # Measure head width: median row-width over upper 60 % of silhouette
    upper_limit = int(r0 + 0.60 * (r1 - r0))
    row_widths, head_centres = [], []
    for r in range(r0, upper_limit):
        filled = np.where(alpha[r, :] > 10)[0]
        if len(filled) >= 4:
            row_widths.append(int(filled[-1] - filled[0]))
            head_centres.append(int((filled[0] + filled[-1]) / 2))

    if not row_widths:
        # Fallback: use full bounding box
        c0_col = int(np.argmax(col_mask))
        c1_col = int(W - np.argmax(col_mask[::-1]) - 1)
        return rgba.crop((c0_col, r0, c1_col, r1 + 1))

    med_w  = int(np.median(row_widths))
    head_cx = int(np.median(head_centres))

    # Add 12 % breathing room on each side
    margin = int(med_w * 0.56)
    c0 = max(0, head_cx - margin)
    c1 = min(W, head_cx + margin)

    # Cap height so shirt is excluded
    max_h = int(med_w * 1.45)
    r1    = min(r1, r0 + max_h)

    cropped = rgba.crop((c0, r0, c1, r1 + 1))
    print(f"  Cropped to head: {cropped.size}  (head_w≈{med_w}px, cap_h={max_h}px)")
    return cropped


def enhance(rgba: "Image.Image") -> "np.ndarray":
    """
    1. Composite RGBA on black (transparent → black → vanishes into dark panel).
    2. CLAHE (local contrast) — flatly-lit faces collapse to one grey blob.
    3. Levels: crush [0,55] → 0, expand [55,225] → [0,255].
    Returns float32 array [0,1], shape (H, W).
    """
    # Composite on black so transparent regions = 0 brightness
    black = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    black.paste(rgba, mask=rgba.split()[3])
    gray_pil = black.convert("L")
    arr = np.array(gray_pil, dtype=np.uint8)

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    arr = clahe.apply(arr)

    # Levels
    lo, hi = 55, 225
    arr = np.clip(arr.astype(np.int32) - lo, 0, hi - lo)
    arr = (arr * 255 // (hi - lo)).astype(np.uint8)

    return arr.astype(np.float32) / 255.0


def image_to_ascii(gray: "np.ndarray") -> list[str]:
    """
    Resize to COLS columns, preserving aspect ratio with char-cell compensation.
    Character cells are approximately CHAR_H/CHAR_W ≈ 1.96 times taller than
    wide, so we divide the natural row count by that ratio to avoid a squashed
    portrait.
    """
    h, w = gray.shape
    cell_aspect = CHAR_H / CHAR_W   # how many cols fit in one row height
    rows = max(4, int(round(COLS * (h / w) / cell_aspect)))

    img_pil = Image.fromarray((gray * 255).astype(np.uint8))
    img_pil = img_pil.resize((COLS, rows), Image.LANCZOS)
    resized  = np.array(img_pil, dtype=np.float32) / 255.0

    lines = []
    for r in range(rows):
        line = "".join(brightness_to_glyph(float(resized[r, c])) for c in range(COLS))
        lines.append(line)
    print(f"  ASCII grid: {COLS} cols × {rows} rows")
    return lines


# -- Run-splitting (no spaces in <text>) ---------------------------------------

def split_runs(line: str) -> list[tuple[int, str]]:
    """
    Return [(start_col, text), ...] for every non-space run in the line.
    We never emit a space character inside a <text> element: SVG renderers
    collapse interior whitespace even under white-space:pre, causing the
    portrait to wobble.  Each run carries its own absolute x offset instead.
    """
    runs, i, n = [], 0, len(line)
    while i < n:
        if line[i] == " ":
            i += 1
            continue
        j = i
        while j < n and line[j] != " ":
            j += 1
        runs.append((i, line[i:j]))
        i = j
    return runs


# -- SVG builder ---------------------------------------------------------------

def _xml_esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def build_svg(lines: list[str], title: str = "~/saumil-777/portrait.sh") -> str:
    rows   = len(lines)
    svg_w  = int(COLS * CHAR_W + 2 * PAD_SIDE)
    svg_h  = int(rows * CHAR_H + TITLE_H + PAD_SIDE + PAD_BOT)

    # -- CSS ------------------------------------------------------------------
    if STATIC:
        row_css = "  .row { opacity: 1; }\n"
    else:
        # Each row appears essentially instantly at its stagger time.
        # fill-mode: forwards means it stays visible after appearing.
        delays = "\n".join(
            f"  .r{i} {{ animation-delay: {i * 0.068:.3f}s; }}"
            for i in range(rows)
        )
        row_css = (
            "  @keyframes rowon {\n"
            "    from { opacity: 0; }\n"
            "    to   { opacity: 1; }\n"
            "  }\n"
            "  .row {\n"
            "    opacity: 0;\n"
            "    animation: rowon 0.001s linear forwards;\n"
            "  }\n"
            f"{delays}\n"
        )

    out = [svg_open(svg_w, svg_h, extra_css=row_css)]
    out.append(panel_chrome(svg_w, svg_h, title))

    # Clip so no glyph bleeds past the border
    clip_h = svg_h - TITLE_H
    out.append(
        f'<clipPath id="pc">'
        f'<rect x="0" y="{TITLE_H}" width="{svg_w}" height="{clip_h}" />'
        f'</clipPath>'
    )
    out.append('<g clip-path="url(#pc)">')

    for i, line in enumerate(lines):
        # Baseline y for this row (1-indexed so first row sits inside padding)
        y = TITLE_H + PAD_SIDE + int((i + 1) * CHAR_H)
        runs = split_runs(line)
        cls  = f"row r{i}" if not STATIC else "row"

        out.append(f'<g class="{cls}">')
        for start_col, text in runs:
            x  = PAD_SIDE + int(start_col * CHAR_W)
            tl = int(len(text) * CHAR_W)
            if tl < 1:
                continue
            out.append(
                f'  <text x="{x}" y="{y}" font-size="{FONT_SIZE}"'
                f' fill="{GLYPH_COL}" textLength="{tl}"'
                f' lengthAdjust="spacingAndGlyphs">'
                f'{_xml_esc(text)}</text>'
            )
        out.append('</g>')

    out.append('</g>')   # /clip group
    out.append(svg_close())
    return "".join(out)


# -- Entry point ---------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    photo_path  = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "ascii-portrait.svg"

    print(f"\n[portrait] {photo_path!r}  ->  {output_path!r}")
    print("[portrait] Step 1/5 — load")
    rgba = load_image(photo_path)
    print("[portrait] Step 2/5 — remove background")
    rgba = remove_background(rgba)
    print("[portrait] Step 3/5 — crop to head")
    rgba = crop_to_head(rgba)
    print("[portrait] Step 4/5 — enhance contrast")
    gray = enhance(rgba)
    print("[portrait] Step 5/5 — convert to ASCII + build SVG")
    lines = image_to_ascii(gray)
    svg   = build_svg(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[portrait] Written -> {output_path}")

    # -- Validation ---------------------------------------------------------
    errs  = validate_svg(output_path)
    warns = check_bounds(output_path)
    if errs:
        print("ERRORS:", errs); sys.exit(1)
    if warns:
        print("BOUNDS WARNINGS:", warns)
    print("[portrait] OK Validation passed.")


if __name__ == "__main__":
    main()
