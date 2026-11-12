"""Generate the README artwork: a banner and one designed card per feature (SVG).

    python scripts/make_readme_art.py

Writes docs/art/banner.svg and docs/art/feature-*.svg in the app's palette
(graphite + amber). Pure vector, so it stays sharp on every screen.
"""

from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "art"

BG = "#0c0d10"
PANEL = "#14161a"
PANEL_HI = "#1b1e23"
LINE = "#262a31"
TEXT = "#e7e9ec"
MUTED = "#8a919c"
AMBER = "#ffb020"
RED = "#ff4d4f"
GREEN = "#3ddc97"
CYAN = "#4cc9f0"
VIOLET = "#b388ff"
FONT = "Segoe UI, -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif"
MONO = "Cascadia Mono, Consolas, SFMono-Regular, Menlo, monospace"

W, H = 560, 250


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------- icons
# Each icon is drawn in a 56x56 box at (0,0); the card places it.
def icon_tile(inner: str, tint: str = AMBER) -> str:
    return (f'<rect width="56" height="56" rx="14" fill="{tint}" fill-opacity="0.12" '
            f'stroke="{tint}" stroke-opacity="0.35"/>{inner}')


ICONS = {
    "deck": icon_tile(f'<circle cx="20" cy="28" r="8" fill="{RED}"/>'
                      f'<path d="M33 20 L44 28 L33 36 Z" fill="{GREEN}"/>', RED),
    "ghost": icon_tile(
        f'<path d="M16 42 V26 a12 12 0 0 1 24 0 V42 l-4 -4 l-4 4 l-4 -4 l-4 4 l-4 -4 Z" fill="{TEXT}"/>'
        f'<circle cx="24" cy="26" r="2.4" fill="{BG}"/><circle cx="32" cy="26" r="2.4" fill="{BG}"/>'),
    "target": icon_tile(
        f'<circle cx="28" cy="28" r="13" fill="none" stroke="{AMBER}" stroke-width="3"/>'
        f'<circle cx="28" cy="28" r="5" fill="{AMBER}"/>'
        f'<path d="M28 9 V16 M28 40 V47 M9 28 H16 M40 28 H47" stroke="{AMBER}" stroke-width="3" stroke-linecap="round"/>'),
    "repeat": icon_tile(
        f'<path d="M17 25 a11 11 0 0 1 19 -5 l3 -3 v9 h-9 l3 -3 a7 7 0 0 0 -12 3" fill="{AMBER}"/>'
        f'<path d="M39 31 a11 11 0 0 1 -19 5 l-3 3 v-9 h9 l-3 3 a7 7 0 0 0 12 -3" fill="{AMBER}"/>'),
    "keys": icon_tile(
        f'<rect x="10" y="17" width="16" height="14" rx="3" fill="none" stroke="{CYAN}" stroke-width="2.5"/>'
        f'<rect x="30" y="17" width="16" height="14" rx="3" fill="none" stroke="{CYAN}" stroke-width="2.5"/>'
        f'<rect x="14" y="35" width="28" height="8" rx="3" fill="{CYAN}"/>', CYAN),
    "steps": icon_tile(
        "".join(f'<rect x="14" y="{15 + i * 9}" width="5" height="5" rx="1.5" fill="{c}"/>'
                f'<rect x="23" y="{16 + i * 9}" width="{19 - i * 3}" height="3" rx="1.5" fill="{TEXT}" fill-opacity="0.8"/>'
                for i, c in enumerate([AMBER, CYAN, VIOLET, MUTED]))),
    "timer": icon_tile(
        f'<circle cx="28" cy="31" r="13" fill="none" stroke="{GREEN}" stroke-width="3"/>'
        f'<path d="M28 31 V23 M28 31 L34 35" stroke="{GREEN}" stroke-width="3" stroke-linecap="round"/>'
        f'<rect x="24" y="11" width="8" height="4" rx="2" fill="{GREEN}"/>', GREEN),
    "app": icon_tile(
        f'<rect x="11" y="15" width="34" height="24" rx="4" fill="none" stroke="{VIOLET}" stroke-width="2.5"/>'
        f'<path d="M22 44 H34" stroke="{VIOLET}" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="35" cy="27" r="5" fill="{VIOLET}"/><path d="M19 27 h9" stroke="{VIOLET}" stroke-width="2.5" stroke-linecap="round"/>',
        VIOLET),
}


# --------------------------------------------------------------- illustrations
# Drawn in a 200x150 box; the card places it on the right.
def chip(x, y, w, text, fg=MUTED, bg=PANEL_HI, mono=True, size=11, h=24):
    fam = MONO if mono else FONT
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{bg}" stroke="{LINE}"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle" font-family="{fam}" '
            f'font-size="{size}" font-weight="700" fill="{fg}">{esc(text)}</text>')


def tape(x0=0, y0=0, w=200, h=120, seed=3):
    import random

    rnd = random.Random(seed)
    out = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="10" fill="{PANEL_HI}" stroke="{LINE}"/>']
    lanes = [AMBER, CYAN, VIOLET, MUTED]
    lh = h / 4
    for i, c in enumerate(lanes):
        y = y0 + i * lh
        if i:
            out.append(f'<line x1="{x0}" y1="{y}" x2="{x0 + w}" y2="{y}" stroke="{LINE}"/>')
        for _ in range(9 if i < 3 else 16):
            x = x0 + 10 + rnd.random() * (w - 20)
            hh = lh * (0.22 if i == 3 else 0.34)
            out.append(f'<line x1="{x:.1f}" y1="{y + lh / 2 - hh:.1f}" x2="{x:.1f}" y2="{y + lh / 2 + hh:.1f}" '
                       f'stroke="{c}" stroke-width="2.4" stroke-linecap="round"/>')
    px = x0 + w * 0.62
    out.append(f'<rect x="{x0}" y="{y0}" width="{px - x0}" height="{h}" rx="10" fill="{AMBER}" fill-opacity="0.07"/>')
    out.append(f'<line x1="{px}" y1="{y0}" x2="{px}" y2="{y0 + h}" stroke="{AMBER}" stroke-width="2.5"/>')
    out.append(f'<path d="M{px - 6} {y0} L{px + 6} {y0} L{px} {y0 + 8} Z" fill="{AMBER}"/>')
    return "".join(out)


def window(x, y, w, h, title, active=False):
    stroke = AMBER if active else LINE
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PANEL_HI}" stroke="{stroke}" '
            f'stroke-width="{2 if active else 1}"/>'
            f'<rect x="{x}" y="{y}" width="{w}" height="18" rx="8" fill="{LINE}"/>'
            f'<rect x="{x}" y="{y + 10}" width="{w}" height="8" fill="{LINE}"/>'
            f'<text x="{x + 10}" y="{y + 13}" font-family="{FONT}" font-size="9" fill="{MUTED}">{esc(title)}</text>')


ILLUS = {
    "deck": tape(0, 15, 200, 120),
    "ghost": (window(0, 18, 120, 82, "Your work") + window(78, 52, 120, 82, "Target app", active=True)
              + f'<g transform="translate(118,82)">'
              + f'<path d="M0 30 V12 a12 12 0 0 1 24 0 V30 l-4 -4 l-4 4 l-4 -4 l-4 4 l-4 -4 Z" fill="{TEXT}" opacity="0.95"/>'
              + f'<circle cx="8" cy="12" r="2.3" fill="{BG}"/><circle cx="16" cy="12" r="2.3" fill="{BG}"/></g>'
              + f'<path d="M30 70 l10 16 l3 -7 l7 -2 Z" fill="{TEXT}" stroke="{BG}" stroke-width="1.5"/>'),
    "target": (chip(0, 10, 92, "ANY APP", AMBER) + f'<text x="102" y="27" font-family="{FONT}" font-size="11" fill="{MUTED}">All windows</text>'
               + f'<rect x="-4" y="44" width="208" height="30" rx="8" fill="{AMBER}" fill-opacity="0.1" stroke="{AMBER}" stroke-opacity="0.5"/>'
               + chip(0, 47, 92, "notepad.exe", AMBER) + f'<text x="102" y="64" font-family="{FONT}" font-size="11" font-weight="700" fill="{TEXT}">Notepad  ✓</text>'
               + chip(0, 84, 92, "chrome.exe") + f'<text x="102" y="101" font-family="{FONT}" font-size="11" fill="{MUTED}">Inbox - Chrome</text>'
               + chip(0, 118, 92, "EXCEL.EXE") + f'<text x="102" y="135" font-family="{FONT}" font-size="11" fill="{MUTED}">Report.xlsx</text>'),
    "repeat": (chip(0, 14, 96, "× 3 times", AMBER, size=13, h=34) + chip(104, 14, 96, "∞ forever", TEXT, size=13, h=34)
               + f'<rect x="0" y="62" width="200" height="74" rx="10" fill="{PANEL_HI}" stroke="{LINE}"/>'
               + f'<text x="14" y="82" font-family="{FONT}" font-size="10" font-weight="700" fill="{MUTED}">RUN FOR</text>'
               + f'<text x="14" y="116" font-family="{MONO}" font-size="30" font-weight="700" fill="{AMBER}">1:00</text>'
               + f'<text x="112" y="104" font-family="{MONO}" font-size="10" fill="{MUTED}">≈ 12 loops</text>'
               + f'<text x="112" y="120" font-family="{MONO}" font-size="10" fill="{MUTED}">≈ 480 steps</text>'),
    "keys": "".join(
        f'<circle cx="6" cy="{26 + i * 34}" r="4" fill="{c}"/>'
        f'<text x="18" y="{30 + i * 34}" font-family="{FONT}" font-size="11" fill="{TEXT}">{esc(label)}</text>'
        + chip(112, 13 + i * 34, 88, key, TEXT, h=26)
        for i, (c, label, key) in enumerate([(RED, "Record", "F9"), (GREEN, "Play", "F10"),
                                              (MUTED, "Stop all", "F12"), (AMBER, "Target app", "Ctrl+Alt+T")])),
    "steps": f'<rect x="0" y="8" width="200" height="134" rx="10" fill="{PANEL_HI}" stroke="{LINE}"/>' + "".join(
        f'<text x="12" y="{34 + i * 21}" font-family="{MONO}" font-size="10" fill="{MUTED}">{t}</text>'
        f'<text x="56" y="{34 + i * 21}" font-family="{FONT}" font-size="11" fill="{c}">{esc(a)}</text>'
        for i, (t, a, c) in enumerate([("0.10", "Left Down", AMBER), ("0.21", "Left Up", AMBER), ("0.64", "Key A", CYAN),
                                       ("0.81", "Scroll Down", VIOLET), ("1.02", "Mouse Move", MUTED),
                                       ("1.35", "Key Enter", CYAN)])),
    "timer": (f'<text x="0" y="56" font-family="{MONO}" font-size="40" font-weight="700" fill="{GREEN}">3</text>'
              f'<text x="40" y="56" font-family="{MONO}" font-size="28" font-weight="700" fill="{GREEN}" opacity="0.6">2</text>'
              f'<text x="72" y="56" font-family="{MONO}" font-size="20" font-weight="700" fill="{GREEN}" opacity="0.35">1</text>'
              f'<text x="100" y="56" font-family="{FONT}" font-size="12" fill="{MUTED}">then play</text>'
              f'<path d="M0 112 C 20 92, 30 132, 50 112 S 80 92, 100 112 S 130 132, 150 112 S 180 92, 200 112" fill="none" '
              f'stroke="{AMBER}" stroke-width="2.5"/>'
              f'<text x="0" y="146" font-family="{FONT}" font-size="11" fill="{MUTED}">humanized timing</text>'),
    "app": "".join(
        f'<rect x="0" y="{10 + i * 34}" width="36" height="20" rx="10" fill="{AMBER if on else LINE}"/>'
        f'<circle cx="{26 if on else 10}" cy="{20 + i * 34}" r="7" fill="{TEXT}"/>'
        f'<text x="48" y="{24 + i * 34}" font-family="{FONT}" font-size="12" fill="{TEXT}">{esc(t)}</text>'
        for i, (t, on) in enumerate([("Runs in the tray", True), ("Start with Windows", True),
                                      ("Always on top", False), ("Dark · Light · System", True)])),
}


FEATURES = [
    ("deck", "Record & play like a tape deck",
     ["Big REC, PLAY and STOP buttons and a", "live tape: every click, key and scroll", "shows up as you record."]),
    ("ghost", "Plays in the background",
     ["Replays inside the chosen app on its", "own. Your mouse and keyboard stay", "free for other work."]),
    ("target", "Point it at any app",
     ["Search open windows, pick by clicking,", "or press Ctrl + Alt + T inside the", "app you want."]),
    ("repeat", "Repeat — or run for a set time",
     ["3 times, forever, or for 1 min / 1 hour.", "Live estimate of loops and steps;", "alert when it's done."]),
    ("timer", "Countdown & human timing",
     ["A 3 or 5 s countdown to switch apps,", "and gentle random variation so it", "never looks robotic."]),
    ("keys", "Hotkeys that work anywhere",
     ["Record, play, stop and target even", "when Ghost is hidden. Press any key", "to change one; conflicts auto-fixed."]),
    ("steps", "See & edit every step",
     ["Colour-coded step list. Delete steps,", "trim mouse moves, save and open", "macros — never lose unsaved work."]),
    ("app", "Made for everyday use",
     ["Tray mode, start with Windows,", "always on top, light & dark themes.", "Every setting explained simply."]),
]


def card(key: str, title: str, lines: list[str]) -> str:
    body = "".join(
        f'<text x="28" y="{148 + i * 22}" font-family="{FONT}" font-size="14" fill="{MUTED}">{esc(t)}</text>'
        for i, t in enumerate(lines))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{PANEL_HI}"/><stop offset="1" stop-color="{PANEL}"/>
    </linearGradient>
  </defs>
  <rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="20" fill="url(#g)" stroke="{LINE}" stroke-width="1.5"/>
  <g transform="translate(28,28)">{ICONS[key]}</g>
  <text x="28" y="118" font-family="{FONT}" font-size="19" font-weight="700" fill="{TEXT}">{esc(title)}</text>
  {body}
  <g transform="translate(332,52)">{ILLUS[key]}</g>
</svg>
'''


def banner() -> str:
    logo_png = ROOT / "assets" / "icon_ui.png"
    logo = base64.b64encode(logo_png.read_bytes()).decode() if logo_png.exists() else ""
    bw, bh = 1200, 340
    img = (f'<image x="96" y="86" width="168" height="168" href="data:image/png;base64,{logo}"/>' if logo else "")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{bw}" height="{bh}" viewBox="0 0 {bw} {bh}">
  <defs>
    <radialGradient id="glow" cx="0.15" cy="0.5" r="0.45">
      <stop offset="0" stop-color="{AMBER}" stop-opacity="0.22"/><stop offset="1" stop-color="{AMBER}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#15171c"/><stop offset="1" stop-color="{BG}"/>
    </linearGradient>
  </defs>
  <rect width="{bw}" height="{bh}" rx="28" fill="url(#bg)"/>
  <rect width="{bw}" height="{bh}" rx="28" fill="url(#glow)"/>
  <rect x="1" y="1" width="{bw - 2}" height="{bh - 2}" rx="27" fill="none" stroke="{LINE}" stroke-width="2"/>
  {img}
  <text x="300" y="142" font-family="{FONT}" font-size="50" font-weight="800" fill="{TEXT}">Ghost<tspan>Macro</tspan><tspan fill="{AMBER}">Recorder</tspan></text>
  <text x="302" y="188" font-family="{FONT}" font-size="26" fill="{MUTED}">Record once. Run in the background.</text>
  <g transform="translate(302,218)">
    <circle cx="22" cy="22" r="22" fill="{RED}"/><circle cx="22" cy="22" r="7" fill="#fff"/>
    <circle cx="76" cy="22" r="22" fill="{GREEN}"/><path d="M70 12 L86 22 L70 32 Z" fill="#06261a"/>
    <circle cx="130" cy="22" r="22" fill="#2a2e35"/><rect x="122" y="14" width="16" height="16" rx="2" fill="{TEXT}"/>
    <text x="176" y="31" font-family="{MONO}" font-size="28" font-weight="700" fill="{AMBER}">00:21.051</text>
  </g>
  <g transform="translate(888,108) scale(1.25)">{tape(0, 0, 200, 115, seed=11)}</g>
</svg>
'''


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "banner.svg").write_text(banner(), encoding="utf-8")
    for key, title, lines in FEATURES:
        (OUT / f"feature-{key}.svg").write_text(card(key, title, lines), encoding="utf-8")
    print(f"Wrote banner + {len(FEATURES)} feature cards to {OUT}")


if __name__ == "__main__":
    main()
