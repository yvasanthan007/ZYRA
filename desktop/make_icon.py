"""One-time generator for desktop/icon.ico (run: python desktop/make_icon.py)."""
from PIL import Image, ImageDraw


def main():
    base = 256
    img = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded dark plate
    d.rounded_rectangle([8, 8, base - 8, base - 8], radius=48,
                        fill=(8, 10, 24, 255), outline=(64, 220, 255, 255), width=6)

    # Cyan "Z" glyph — ZYRA signature
    pts = [(64, 64), (192, 64), (64, 176), (192, 176)]
    d.line([pts[0], pts[1]], fill=(64, 220, 255, 255), width=22)
    d.line([pts[1], pts[2]], fill=(64, 220, 255, 255), width=22)
    d.line([pts[2], pts[3]], fill=(64, 220, 255, 255), width=22)

    # Accent dot (AI "eye")
    d.ellipse([200, 40, 226, 66], fill=(140, 120, 255, 255))

    img.save(
        "desktop/icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("desktop/icon.ico written")


if __name__ == "__main__":
    main()
