"""Generate Ghost Macro Recorder icon assets from the master logo artwork.

Inputs:
    assets/logo_source.png  - full square brand artwork (ghost + wordmark)

Outputs:
    assets/logo.png  - full artwork with transparent rounded corners (README, about)
    assets/icon.png  - ghost-only square icon, 512px (UI header, tray)
    assets/app.ico   - multi-size Windows icon (exe, taskbar, installer)
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

TILE_COLOR = (16, 17, 20)  # app dark panel graphite
# Region of the source artwork that holds only the ghost (no wordmark), in
# source pixels for the 1254px master.
GHOST_BOX = (190, 150, 1080, 880)
# Tighter crop used for taskbar-size icons (<= 48px): just the ghost body,
# so it fills the tile instead of shrinking to a smudge.
GHOST_BOX_SMALL = (300, 175, 960, 835)
SMALL_SIZES = (16, 20, 24, 32, 40, 48)
LARGE_SIZES = (64, 96, 128, 256)


AMBER_HUE = 39 / 360  # app accent #ffb020


def recolor_to_app_palette(src: Image.Image) -> Image.Image:
    """Re-tint the neon-purple master art into the app's graphite + amber palette.

    Purple hues are rotated to amber. How much colour a pixel keeps depends on
    its brightness: the dark purple tile becomes near-neutral graphite, the
    bright glow/orbit ring becomes amber, the near-white ghost stays white.
    Non-purple pixels (the red record dot, pure black corners) are untouched.
    """
    out = []
    rgb = src.convert("RGB")
    pixels = rgb.get_flattened_data() if hasattr(rgb, "get_flattened_data") else rgb.getdata()
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if 0.55 <= h <= 0.9 and s > 0.04:
            if v < 0.2:
                s_factor, v_factor = 0.12, 0.62  # tile background -> graphite
            elif s < 0.25:
                s_factor, v_factor = 0.18, 1.0  # ghost body -> warm white
            else:
                ramp = min(1.0, (v - 0.2) / 0.35)
                s_factor, v_factor = 0.15 + 0.95 * ramp, 0.8 + 0.25 * ramp  # glow -> amber
            h = AMBER_HUE
            s = min(1.0, s * s_factor)
            v = min(1.0, v * v_factor)
            r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
            out.append((int(r2 * 255), int(g2 * 255), int(b2 * 255)))
        else:
            out.append((r, g, b))
    img = Image.new("RGB", src.size)
    img.putdata(out)
    return img


def _rounded_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    scale = 4
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, size * scale - 1, size * scale - 1), radius=int(size * scale * radius_ratio), fill=255
    )
    return big.resize((size, size), Image.LANCZOS)


def _full_logo(src: Image.Image) -> Image.Image:
    """Source art has black corners outside its rounded tile — make them transparent."""
    w, h = src.size
    inset = int(w * 0.017)
    tile = src.crop((inset, inset, w - inset, h - inset)).convert("RGBA")
    tile.putalpha(_rounded_mask(tile.width, 0.2))
    return tile


def _ghost_icon(src: Image.Image, size: int = 1024) -> Image.Image:
    sx = src.width / 1254
    box = tuple(int(v * sx) for v in GHOST_BOX)
    ghost = src.crop(box).convert("RGBA")

    canvas = Image.new("RGBA", (size, size), TILE_COLOR + (255,))
    # Soft purple glow behind the ghost so the tile isn't flat
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (size * 0.12, size * 0.1, size * 0.88, size * 0.86), fill=(255, 176, 32, 70)
    )
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(size * 0.09)))

    # Scale ghost to fill ~92% of tile width and feather its edges into the tile
    target_w = int(size * 0.94)
    target_h = int(ghost.height * target_w / ghost.width)
    ghost = ghost.resize((target_w, target_h), Image.LANCZOS)
    feather = Image.new("L", ghost.size, 0)
    pad = int(target_w * 0.05)
    ImageDraw.Draw(feather).rounded_rectangle(
        (pad, pad, ghost.width - pad, ghost.height - pad), radius=pad * 3, fill=255
    )
    feather = feather.filter(ImageFilter.GaussianBlur(pad * 0.8))
    ghost.putalpha(feather)
    canvas.alpha_composite(ghost, ((size - target_w) // 2, (size - target_h) // 2 + int(size * 0.02)))

    canvas.putalpha(_rounded_mask(size))
    return canvas


def _small_master(src: Image.Image, size: int = 1024) -> Image.Image:
    """High-contrast, glow-free ghost crop that stays crisp when tiny."""
    sx = src.width / 1254
    box = tuple(int(v * sx) for v in GHOST_BOX_SMALL)
    ghost = src.crop(box).convert("RGB")
    ghost = ImageEnhance.Contrast(ghost).enhance(1.3)
    ghost = ghost.resize((int(size * 0.98), int(size * 0.98)), Image.LANCZOS).convert("RGBA")
    canvas = Image.new("RGBA", (size, size), TILE_COLOR + (255,))
    canvas.alpha_composite(ghost, ((size - ghost.width) // 2, (size - ghost.height) // 2))
    return canvas


def _render_size(master: Image.Image, px: int, sharpen: bool) -> Image.Image:
    """Downscale in two steps, sharpen at the target size, then round the corners."""
    img = master.resize((px * 4, px * 4), Image.LANCZOS).resize((px, px), Image.LANCZOS)
    if sharpen:
        rgb = img.convert("RGB").filter(ImageFilter.UnsharpMask(radius=0.8, percent=140, threshold=0))
        img = rgb.convert("RGBA")
    img.putalpha(_rounded_mask(px, 0.2))
    return img


def generate_icons(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    src = recolor_to_app_palette(Image.open(output_dir / "logo_source.png"))

    _full_logo(src).resize((640, 640), Image.LANCZOS).save(output_dir / "logo.png", optimize=True)

    icon = _ghost_icon(src)
    png_path = output_dir / "icon.png"
    icon.resize((512, 512), Image.LANCZOS).save(png_path, optimize=True)

    small = _small_master(src)
    frames = [_render_size(small, px, sharpen=True) for px in SMALL_SIZES]
    frames += [_render_size(icon, px, sharpen=px <= 96) for px in LARGE_SIZES]
    small_png = output_dir / "icon_small.png"
    _render_size(small, 64, sharpen=True).save(small_png, optimize=True)

    ico_path = output_dir / "app.ico"
    frames[-1].save(
        ico_path,
        format="ICO",
        sizes=[f.size for f in frames],
        append_images=frames[:-1],
    )
    # Legacy name kept for anything still referencing it
    icon.resize((256, 256), Image.LANCZOS).save(output_dir / "app.png", optimize=True)
    return ico_path, png_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    ico, png = generate_icons(root / "assets")
    print(f"Generated {ico} and {png}")
