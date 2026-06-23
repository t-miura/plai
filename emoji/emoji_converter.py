#!/usr/bin/env python3
"""
Plai Emoji Converter
====================
Converts emoji glyphs into 12x12 monochrome XBM bitmaps suitable for the
Plai firmware's built-in emoji renderer (builtin_emojis.cpp / builtin_emojis.h).

Primary source: NotoEmoji-Regular.ttf (SIL OFL 1.1)
  - Renders clean monochrome vector glyphs at any size
  - Covers ~99% of the emoji PNG set

Fallback source: color PNG files (u<CODEPOINT>.png) in the same directory
  - Used for the ~14 ultra-new Unicode 16+ codepoints not yet in the font
  - Uses luminance + Otsu binarization (original algorithm)

Usage:
  python3 emoji_converter.py             # generate builtin_emojis.cpp/.h
  python3 emoji_converter.py --preview   # print ASCII art for all glyphs (QA)
"""

import os
import re
import sys
import argparse
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))

FONT_PATH    = os.path.join(SCRIPT_DIR, "NotoEmoji-Regular.ttf")
EMOJI_DIR    = SCRIPT_DIR

OUTPUT_CPP   = os.path.join(SCRIPT_DIR, "..", "main", "hal", "builtin_emojis.cpp")
OUTPUT_H     = os.path.join(SCRIPT_DIR, "..", "main", "hal", "builtin_emojis.h")

TARGET_SIZE  = 12    # final XBM bitmap size in pixels (square)
RENDER_PX    = 192   # intermediate rasterisation size; larger = better quality
THRESHOLD    = 200   # luminance threshold: pixel < THRESHOLD → foreground (0=black, 255=white)

# ---------------------------------------------------------------------------
# Font-based rendering (primary path)
# ---------------------------------------------------------------------------

def _load_font():
    """Load the NotoEmoji TTF. Returns (font_obj, cmap_dict) or (None, {})."""
    if not os.path.exists(FONT_PATH):
        print(f"[WARN] Font not found at {FONT_PATH}, falling back to PNG-only mode.")
        return None, {}
    try:
        from fontTools.ttLib import TTFont as TTFontTools
        tt = TTFontTools(FONT_PATH)
        cmap = tt.getBestCmap() or {}
        font_obj = ImageFont.truetype(FONT_PATH, RENDER_PX)
        print(f"[INFO] Loaded {os.path.basename(FONT_PATH)}: {len(cmap)} codepoints")
        return font_obj, cmap
    except ImportError:
        # fontTools not installed – we can still render but can't check cmap
        print("[WARN] fonttools not installed; skipping cmap check, will try to render all.")
        font_obj = ImageFont.truetype(FONT_PATH, RENDER_PX)
        return font_obj, None  # None = "try rendering anyway"
    except Exception as e:
        print(f"[WARN] Could not load font ({e}), falling back to PNG-only mode.")
        return None, {}


def _render_from_font(char, font_obj):
    """
    Rasterise a single character from the TTF font.
    Returns a list of XBM bytes (TARGET_SIZE * ceil(TARGET_SIZE/8) bytes).
    """
    w = h = TARGET_SIZE
    byte_width = (w + 7) // 8

    canvas_size = RENDER_PX * 3
    img = Image.new('L', (canvas_size, canvas_size), 255)
    draw = ImageDraw.Draw(img)

    # Measure the glyph bounding box
    bbox = draw.textbbox((0, 0), char, font=font_obj)
    glyph_w = max(1, bbox[2] - bbox[0])
    glyph_h = max(1, bbox[3] - bbox[1])

    # Center in the canvas
    cx = (canvas_size - glyph_w) // 2
    cy = (canvas_size - glyph_h) // 2
    draw.text((cx - bbox[0], cy - bbox[1]), char, font=font_obj, fill=0)

    # Crop to glyph bounds with a small margin so nothing is clipped
    margin = RENDER_PX // 8
    cropped = img.crop((cx - margin, cy - margin,
                        cx + glyph_w + margin, cy + glyph_h + margin))

    # Downsample to target size
    final = cropped.resize((w, h), Image.LANCZOS)

    # Contrast-stretch: normalise to full 0-255 range first so Otsu works
    # correctly regardless of whether the glyph uses the full dynamic range.
    pix_raw = list(final.getdata())
    p_min = min(pix_raw)
    p_max = max(pix_raw)
    if p_max > p_min:
        scale = 255.0 / (p_max - p_min)
        pix_raw = [int((v - p_min) * scale) for v in pix_raw]
        final = Image.new('L', (w, h))
        final.putdata(pix_raw)

    # Adaptive Smart Clamp thresholding
    # 1. Compute overall image mean
    pix_vals = list(final.getdata())
    mean_val = sum(pix_vals) / len(pix_vals)
    
    # 2. Compute base Otsu threshold
    otsu_val = _otsu_threshold(pix_vals)
    
    # 3. Dynamic clamp based on mean to preserve thin outlines vs gaps
    if mean_val <= 140:
        min_t, max_t = 115, 125
    elif mean_val >= 200:
        min_t, max_t = 180, 210
    else:
        f = (mean_val - 140) / 60.0
        min_t = 115 + f * (180 - 115)
        max_t = 125 + f * (210 - 125)
        
    threshold = max(int(min_t), min(int(max_t), otsu_val))
    
    # If the glyph is essentially empty (very low contrast) treat entire
    # opaque area as foreground to avoid blank output.
    if threshold <= 10:
        threshold = THRESHOLD

    # Binarise and pack as XBM bytes (LSB-first per row)
    pix = final.load()
    result = []
    for y in range(h):
        for bx in range(byte_width):
            b = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < w and pix[x, y] < threshold:
                    b |= (1 << bit)
            result.append(b)
    return result

# ---------------------------------------------------------------------------
# PNG-based rendering (fallback path — original algorithm)
# ---------------------------------------------------------------------------

def _otsu_threshold(lums):
    best_thresh = 128
    best_variance = -1
    min_l = int(min(lums))
    max_l = int(max(lums))
    if max_l - min_l <= 2:
        return min_l
    for t in range(min_l + 1, max_l):
        left  = [x for x in lums if x <  t]
        right = [x for x in lums if x >= t]
        if not left or not right:
            continue
        w0 = len(left)  / len(lums)
        w1 = len(right) / len(lums)
        m0 = sum(left)  / len(left)
        m1 = sum(right) / len(right)
        variance = w0 * w1 * ((m0 - m1) ** 2)
        if variance > best_variance:
            best_variance = variance
            best_thresh = t
    return best_thresh


def _render_from_png(png_path):
    """
    Convert a color emoji PNG to a 12x12 XBM bitmap.
    Uses luminance analysis + Otsu's method (original algorithm).
    """
    w = h = TARGET_SIZE
    byte_width = (w + 7) // 8

    try:
        img = Image.open(png_path)
    except Exception as e:
        print(f"[WARN] Cannot open {png_path}: {e}")
        return [0] * (byte_width * h)

    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    if img.size != (w, h):
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.ANTIALIAS  # type: ignore
        img = img.resize((w, h), resample=resample)

    pix = img.load()

    # Collect luminance of opaque pixels
    opaque_lums = []
    for py in range(h):
        for px in range(w):
            r, g, b, a = pix[px, py]
            if a >= 128:
                opaque_lums.append(0.299 * r + 0.587 * g + 0.114 * b)

    if not opaque_lums:
        return [0] * (byte_width * h)

    contrast = max(opaque_lums) - min(opaque_lums)

    if contrast < 80:
        # Low-contrast (monochromatic color) emoji → outline only
        # Full silhouette of these looks like an unrecognisable blob;
        # drawing just the border gives a recognisable shape.
        use_outline = True
    else:
        use_outline = False
        threshold = _otsu_threshold(opaque_lums)

    result = []
    for py in range(h):
        for bx in range(byte_width):
            b = 0
            for bit in range(8):
                px = bx * 8 + bit
                if px >= w:
                    break
                r, g, bl, a = pix[px, py]
                is_fg = False
                if a >= 128:
                    if use_outline:
                        # Foreground = boundary pixel (opaque pixel adjacent to transparent)
                        is_fg = False
                        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nx, ny = px + dx, py + dy
                            if 0 <= nx < w and 0 <= ny < h:
                                if pix[nx, ny][3] < 128:
                                    is_fg = True
                                    break
                            else:
                                is_fg = True
                                break
                    else:
                        is_boundary = any(
                            (0 <= px + dx < w and 0 <= py + dy < h
                             and pix[px + dx, py + dy][3] < 128) or
                            not (0 <= px + dx < w and 0 <= py + dy < h)
                            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                        )
                        if is_boundary:
                            is_fg = True
                        else:
                            lum = 0.299 * r + 0.587 * g + 0.114 * bl
                            is_fg = (lum < threshold)
                if is_fg:
                    b |= (1 << bit)
            result.append(b)
    return result

# ---------------------------------------------------------------------------
# ASCII preview helper
# ---------------------------------------------------------------------------

def _xbm_to_ascii(xbm_bytes, w=TARGET_SIZE, h=TARGET_SIZE):
    byte_width = (w + 7) // 8
    rows = []
    for y in range(h):
        row = ""
        for x in range(w):
            b = xbm_bytes[y * byte_width + (x >> 3)]
            row += "█" if (b >> (x & 7)) & 1 else "."
        rows.append(row)
    return rows

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert emoji to Plai XBM bitmaps")
    parser.add_argument("--preview", action="store_true",
                        help="Print ASCII art preview for all glyphs (QA mode, no file output)")
    args = parser.parse_args()

    # Discover all emoji PNG files in the emoji directory
    pattern = re.compile(r"^u([0-9A-Fa-f]+)\.png$")
    emoji_files = []
    for fn in os.listdir(EMOJI_DIR):
        m = pattern.match(fn)
        if m:
            code = int(m.group(1), 16)
            emoji_files.append((code, fn))
    emoji_files.sort()

    print(f"[INFO] Found {len(emoji_files)} emoji PNG files")

    # Load font
    font_obj, cmap = _load_font()
    font_available = font_obj is not None

    # Process each emoji
    results = []  # list of (code, xbm_bytes, source)

    font_count = 0
    png_count  = 0

    for code, filename in emoji_files:
        char = chr(code)
        png_path = os.path.join(EMOJI_DIR, filename)

        use_font = False
        if font_available:
            if cmap is None:
                # fontTools not available – try rendering blindly
                use_font = True
            elif code in cmap:
                use_font = True

        if use_font:
            try:
                xbm = _render_from_font(char, font_obj)
                results.append((code, xbm, "font"))
                font_count += 1
            except Exception as e:
                print(f"[WARN] Font render failed for U+{code:05X} ({e}), falling back to PNG")
                xbm = _render_from_png(png_path)
                results.append((code, xbm, "png-fallback"))
                png_count += 1
        else:
            xbm = _render_from_png(png_path)
            results.append((code, xbm, "png"))
            png_count += 1

    print(f"[INFO] Rendered: {font_count} from font, {png_count} from PNG")

    # ── Preview mode ─────────────────────────────────────────────────────────
    if args.preview:
        for code, xbm, source in results:
            char = chr(code)
            print(f"\nU+{code:05X} {char}  [{source}]")
            for row in _xbm_to_ascii(xbm):
                print("  " + row)
        return

    # ── Generate C++ files ───────────────────────────────────────────────────
    cpp_lines = [
        "// This file is auto-generated by emoji_converter.py. Do not edit directly.",
        "// Source: NotoEmoji-Regular.ttf (SIL OFL 1.1) with PNG fallback.",
        '#include "builtin_emojis.h"',
        '#include <esp_attr.h>',
        "",
    ]

    for code, xbm, _source in results:
        byte_strs = [f"0x{b:02X}" for b in xbm]
        cpp_lines.append(
            f"static const uint8_t emoji_{code:X}[] = {{{', '.join(byte_strs)}}};"
        )

    cpp_lines += [
        "",
        "const BuiltinEmoji BUILTIN_EMOJIS[] = {",
    ]
    for code, _xbm, _source in results:
        cpp_lines.append(f"    {{ 0x{code:X}, emoji_{code:X} }},")
    cpp_lines += [
        "};",
        "",
        "const size_t BUILTIN_EMOJIS_NUM = sizeof(BUILTIN_EMOJIS) / sizeof(BUILTIN_EMOJIS[0]);",
        "",
        "const uint8_t* builtin_emoji_lookup(uint32_t code) {",
        "    if (BUILTIN_EMOJIS_NUM == 0) return nullptr;",
        "    size_t low = 0;",
        "    size_t high = BUILTIN_EMOJIS_NUM - 1;",
        "    while (low <= high) {",
        "        size_t mid = low + (high - low) / 2;",
        "        if (BUILTIN_EMOJIS[mid].code == code) {",
        "            return BUILTIN_EMOJIS[mid].bitmap;",
        "        } else if (BUILTIN_EMOJIS[mid].code < code) {",
        "            low = mid + 1;",
        "        } else {",
        "            if (mid == 0) break;",
        "            high = mid - 1;",
        "        }",
        "    }",
        "    return nullptr;",
        "}",
        "",
    ]

    output_cpp = os.path.normpath(OUTPUT_CPP)
    with open(output_cpp, "w") as f:
        f.write("\n".join(cpp_lines))
    print(f"[INFO] Written: {output_cpp}")

    h_content = """\
// This file is auto-generated by emoji_converter.py. Do not edit directly.
#pragma once
#include <stdint.h>
#include <stddef.h>

struct BuiltinEmoji {
    uint32_t code;
    const uint8_t* bitmap; // 12x12 monochrome XBM format bitmap
};

extern const BuiltinEmoji BUILTIN_EMOJIS[];
extern const size_t BUILTIN_EMOJIS_NUM;

// Returns 12x12 monochrome XBM bitmap if found, otherwise nullptr
const uint8_t* builtin_emoji_lookup(uint32_t code);
"""
    output_h = os.path.normpath(OUTPUT_H)
    with open(output_h, "w") as f:
        f.write(h_content)
    print(f"[INFO] Written: {output_h}")
    print("[INFO] Generation complete!")


if __name__ == "__main__":
    main()
