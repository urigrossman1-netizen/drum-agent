"""Draw the app icon (a drum and two sticks on the studio's mint-to-blue tile) into build/:
drum-agent.png (1024 px) and drum-agent.ico (16-256 px). Needs Pillow (build machine only)."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def icon() -> Image.Image:
    tile = Image.new("RGBA", (S, S))
    top, bottom = (46, 230, 166), (56, 112, 255)  # the studio's mint and blue
    px = tile.load()
    for y in range(S):
        for x in range(S):
            px[x, y] = (*lerp(top, bottom, (x + y) / (2 * S)), 255)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=230, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(tile, (0, 0), mask)

    d = ImageDraw.Draw(img)
    ink, shade = (11, 16, 32, 255), (11, 16, 32, 90)
    w = 34
    # sticks, crossed above the drum
    d.line((300, 230, 560, 520), fill=ink, width=w)
    d.line((724, 230, 464, 520), fill=ink, width=w)
    d.ellipse((276, 206, 324, 254), fill=ink)
    d.ellipse((700, 206, 748, 254), fill=ink)
    # the drum: shell, bottom rim, top head
    left, right, head_top, head_bottom, base = 232, 792, 470, 590, 800
    d.rectangle((left, (head_top + head_bottom) // 2, right, base), fill=(255, 255, 255, 235))
    d.ellipse((left, base - 60, right, base + 60), fill=(255, 255, 255, 235))
    for k in range(5):  # tension rods on the shell
        x = left + 70 + k * (right - left - 140) // 4
        d.line((x, (head_top + head_bottom) // 2 + 30, x, base + 20), fill=shade, width=16)
    d.ellipse((left, head_top, right, head_bottom), fill=(255, 255, 255, 255), outline=ink, width=w)
    return img


def main() -> None:
    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    img = icon()
    img.save(out / "drum-agent.png")
    img.save(out / "drum-agent.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print(f"icon written to {out}")


if __name__ == "__main__":
    main()
