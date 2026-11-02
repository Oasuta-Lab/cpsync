#!/usr/bin/env python3
"""Generate the CpSync logo masters (symbol, small-size symbol, wordmark, lockups).

Run: python3 assets/logo/build.py   -> writes SVGs next to this file.
Wordmark glyphs come from Adwaita Sans (SIL OFL 1.1) at weight 700, outlined to paths.
"""
from pathlib import Path

INK = "#14161F"      # devices + wordmark
SIGNAL = "#FF6A3D"   # the clipboard piece (the thing that moves)
FONT = "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf"
OUT = Path(__file__).parent


def rr(x, y, w, h, r):
    """Rounded rectangle as a closed path (clockwise)."""
    return (f"M{x+r:g} {y:g} H{x+w-r:g} A{r:g} {r:g} 0 0 1 {x+w:g} {y+r:g} V{y+h-r:g} "
            f"A{r:g} {r:g} 0 0 1 {x+w-r:g} {y+h:g} H{x+r:g} A{r:g} {r:g} 0 0 1 {x:g} {y+h-r:g} "
            f"V{y+r:g} A{r:g} {r:g} 0 0 1 {x+r:g} {y:g} Z")


def symbol(ink=INK, signal=SIGNAL):
    """Master symbol, 256 grid. Phone (solid, hole on its right) -> laptop (hollow, piece on its left)."""
    return (f'<g id="symbol" fill-rule="evenodd">'
            f'<path fill="{ink}" d="{rr(16,52,80,152,20)} {rr(48,92,32,32,8)}"/>'
            f'<path fill="{ink}" d="{rr(128,52,112,112,18)} {rr(144,68,80,80,6)}"/>'
            f'<path fill="{ink}" d="{rr(120,180,128,24,12)}"/>'
            f'<path id="piece" fill="{signal}" d="{rr(160,92,32,32,8)}"/>'
            f'</g>')


def symbol_small(ink=INK, signal=SIGNAL):
    """Small-size cut (favicon 16-32 px, tray): thicker walls, bigger hole/piece, wider gaps."""
    return (f'<g id="symbol" fill-rule="evenodd">'
            f'<path fill="{ink}" d="{rr(8,48,88,160,22)} {rr(44,84,36,36,10)}"/>'
            f'<path fill="{ink}" d="{rr(128,48,120,108,20)} {rr(148,68,80,68,6)}"/>'
            f'<path fill="{ink}" d="{rr(120,176,128,32,16)}"/>'
            f'<path id="piece" fill="{signal}" d="{rr(164,84,36,36,10)}"/>'
            f'</g>')


def wordmark_paths(text="CpSync", size=150, tracking=-0.025, weight=700):
    """Outline `text` with Adwaita Sans Bold. Returns (list of (dx, pathdata), total_width) in px units
    where 1 em = size, origin at the baseline."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen

    font = instantiateVariableFont(TTFont(FONT), {"wght": weight, "opsz": 32})
    upem = font["head"].unitsPerEm
    s = size / upem
    cmap, glyphs, hmtx = font.getBestCmap(), font.getGlyphSet(), font["hmtx"]
    out, x = [], 0.0
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}")
        glyphs[name].draw(TransformPen(pen, (s, 0, 0, -s, x, 0)))  # flip y, shift x
        out.append(pen.getCommands())
        x += hmtx[name][0] * s + tracking * size
    x -= tracking * size
    return out, x


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}" '
            f'role="img" aria-labelledby="t"><title id="t">{title}</title>\n{body}\n</svg>\n')


def main():
    (OUT / "cpsync-symbol.svg").write_text(svg(256, 256, symbol(), "CpSync symbol"))
    (OUT / "cpsync-symbol-small.svg").write_text(svg(256, 256, symbol_small(), "CpSync symbol (small sizes)"))

    size = 150
    paths, width = wordmark_paths(size=size)
    cap = 1490 / 2048 * size                      # Adwaita Sans cap height
    baseline = 128 + cap / 2                      # caps optically centred on the symbol's centre line
    word = ''.join(f'<path d="{p}"/>' for p in paths)
    wm = f'<g id="wordmark" fill="{INK}" transform="translate(0,{baseline:.1f})">{word}</g>'
    # standalone wordmark: tight box with 16 px side padding, baseline at 128+cap/2
    (OUT / "cpsync-wordmark.svg").write_text(svg(round(width + 32), 256,
        f'<g transform="translate(16,0)">{wm}</g>', "CpSync wordmark"))

    # horizontal lockup: symbol (232 wide, x 16..248), gap 40, wordmark
    gap = 40
    tw = 248 + gap + width + 16
    (OUT / "cpsync-horizontal.svg").write_text(svg(round(tw), 256,
        symbol() + f'<g transform="translate({248 + gap:.1f},0)">{wm}</g>', "CpSync logo"))

    # stacked lockup: symbol centred above a smaller wordmark, 480 x 360
    sp, sw = wordmark_paths(size=110)
    sword = ''.join(f'<path d="{q}"/>' for q in sp)
    stack_w = 480
    (OUT / "cpsync-stacked.svg").write_text(svg(stack_w, 360,
        f'<g transform="translate({(stack_w - 232) / 2 - 16:.1f},-28)">{symbol()}</g>'
        f'<g id="wordmark" fill="{INK}" transform="translate({(stack_w - sw) / 2:.1f},312)">{sword}</g>',
        "CpSync logo (stacked)"))

    # reversed artwork for dark surfaces: white devices, orange piece
    wm_white = wm.replace(f'fill="{INK}"', 'fill="#FFFFFF"')
    (OUT / "cpsync-symbol-ondark.svg").write_text(svg(256, 256, symbol("#FFFFFF"), "CpSync symbol (on dark)"))
    (OUT / "cpsync-horizontal-ondark.svg").write_text(svg(round(tw), 256,
        symbol("#FFFFFF") + f'<g transform="translate({248 + gap:.1f},0)">{wm_white}</g>', "CpSync logo (on dark)"))

    # app icons: ink tile, white devices, orange piece. Mark footprint 232x152 scaled to ~62 % of the tile.
    k = 0.62 * 256 / 232
    mark = (f'<g transform="translate({128 - 132 * k:.2f},{128 - 128 * k:.2f}) scale({k:.4f})">'
            f'{symbol("#FFFFFF")}</g>')
    (OUT / "cpsync-app-icon.svg").write_text(svg(256, 256,
        f'<rect width="256" height="256" rx="58" fill="{INK}"/>{mark}', "CpSync app icon"))
    (OUT / "cpsync-app-icon-ios.svg").write_text(svg(256, 256,           # iOS masks the corners itself
        f'<rect width="256" height="256" fill="{INK}"/>{mark}', "CpSync app icon (iOS, full bleed)"))

    # README banner 1500x500: lockup on ink + tagline
    tp, tw2 = wordmark_paths("Copy on iOS, paste on Windows or Linux.", size=44, tracking=0, weight=500)
    tag = ''.join(f'<path d="{q}"/>' for q in tp)
    lk = f'<g transform="translate({(1500 - tw * 1.25) / 2:.1f},70) scale(1.25)">{symbol("#FFFFFF")}<g transform="translate({248 + gap:.1f},0)">{wm_white}</g></g>'
    (OUT / "cpsync-banner.svg").write_text(svg(1500, 500,
        f'<rect width="1500" height="500" fill="{INK}"/>{lk}'
        f'<g fill="#9AA0A8" transform="translate({(1500 - tw2) / 2:.1f},428)">{tag}</g>', "CpSync banner"))
    print("wordmark width", round(width), "lockup width", round(tw))


if __name__ == "__main__":
    main()
