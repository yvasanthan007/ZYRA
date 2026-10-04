"""
tools/make_icon.py — generate the ZYRA Windows application icon.

Renders the same mark as `desktop-ui/build-assets/icon.svg` with Pillow (no new
dependencies) and writes a multi-resolution `icon.ico` for electron-builder.

    .venv\\Scripts\\python.exe tools\\make_icon.py
"""

import os
from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]
BASE = 1024  # supersampled master, downscaled to every target size

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "desktop-ui", "build-assets", "icon.ico")

PLATE_TOP = (22, 22, 42)
PLATE_BOTTOM = (10, 10, 20)
MARK_TOP = (255, 217, 160)
MARK_MID = (255, 136, 3)
MARK_BOTTOM = (224, 96, 0)
ACCENT = (255, 136, 3)


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vertical_gradient(size, top, bottom, mask=None):
    """Vertical gradient image (optionally masked)."""
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        px[0, y] = _lerp(top, bottom, y / max(1, size - 1))
    grad = grad.resize((size, size), Image.NEAREST)
    if mask is not None:
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(grad, (0, 0), mask)
        return out
    return grad.convert("RGBA")


def _rounded_mask(size, inset, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, size - inset, size - inset], radius=radius, fill=255
    )
    return mask


def render(size=BASE) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Rounded plate with a vertical gradient.
    inset = round(s * 8 / 256)
    radius = round(s * 52 / 256)
    plate_mask = _rounded_mask(s, inset, radius)
    plate = _vertical_gradient(s, PLATE_TOP, PLATE_BOTTOM)
    img.alpha_composite(Image.composite(plate, Image.new("RGBA", (s, s)), plate_mask))

    # Accent border.
    border = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bw = max(1, round(s * 4 / 256))
    bd.rounded_rectangle(
        [inset, inset, s - inset, s - inset], radius=radius,
        outline=ACCENT + (140,), width=bw,
    )
    img.alpha_composite(border)

    # Neural-core ring (echoes the holographic dashboard).
    ring = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        [round(s * 42 / 256), round(s * 42 / 256),
         round(s * 214 / 256), round(s * 214 / 256)],
        outline=ACCENT + (56,), width=max(1, round(s * 3 / 256)),
    )
    img.alpha_composite(ring)

    # The "Z", drawn as a polygon and filled with the mark gradient.
    def P(x, y):
        return (round(s * x / 256), round(s * y / 256))

    z_poly = [
        P(78, 84), P(182, 84), P(182, 112), P(120, 176),
        P(182, 176), P(182, 204), P(76, 204), P(76, 176),
        P(138, 112), P(78, 112),
    ]
    z_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(z_mask).polygon(z_poly, fill=255)
    img.alpha_composite(_vertical_gradient(s, MARK_TOP, MARK_BOTTOM, z_mask))

    return img


def main():
    master = render(BASE)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    frames = [master.resize((n, n), Image.LANCZOS) for n in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])

    # A standalone PNG is handy for docs / the app menu.
    frames[-1].save(os.path.splitext(OUT)[0] + ".png", format="PNG")

    print(f"wrote {OUT}")
    print("sizes: " + ", ".join(f"{n}x{n}" for n in SIZES))


if __name__ == "__main__":
    main()
