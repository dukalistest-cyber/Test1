"""Procedurally draws a character-creator screen ("Make your person.").

Everything is generated in code: the blob background, the skin / hair /
clothing palettes, the cartoon figure and the option icons. Without
--seed the reference look is used; with --seed the background and the
figure's appearance are randomised from that seed.

    python3 character_creator.py
    python3 character_creator.py --seed 42 --out variant.png
"""
import argparse
import math
import os
import random
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE_W, BASE_H = 880, 480  # layout units of the reference screen
K = 4                      # supersampling factor for smooth edges
DEFAULT_SEED = 7

INK = (30, 36, 52)
WHITE = (255, 255, 255)
PURPLE = (122, 47, 181)
PANEL = (246, 214, 138)
PANEL_LIGHT = (250, 228, 168)
PANEL_DARK = (238, 198, 116)
CARD_YELLOW = (255, 255, 52)
SHOE = (240, 242, 246)
OVERALL = (255, 196, 46)
OVERALL_DARK = (236, 160, 28)

SKIN_TONES = [
    (246, 227, 211), (239, 205, 178), (221, 170, 135),
    (217, 176, 142), (201, 152, 116), (181, 132, 106),
]
HAIR_OPTIONS = [  # (colour, style)
    ((142, 42, 143), "bob"),
    ((46, 196, 166), "swoop"),
    ((61, 125, 216), "short"),
]
SHIRTS = [(226, 58, 58), (61, 125, 216), (92, 194, 74)]
BOTTOMS = [  # (length, colour)
    ("long", (47, 111, 208)),
    ("short", (76, 184, 76)),
    ("short", (255, 210, 58)),
]

DEFAULT_LOOK = {"skin": 1, "hair": 1, "shirt": 2, "bottom": 0}

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@lru_cache(maxsize=None)
def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


class Canvas:
    """Drawing helpers that take layout units and render at K times the size."""

    def __init__(self, w, h, bg):
        self.img = Image.new("RGBA", (w * K, h * K), bg)
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def _p(self, pts):
        return [(x * K, y * K) for x, y in pts]

    def poly(self, pts, fill, outline=None, width=1.5):
        self.d.polygon(self._p(pts), fill=fill, outline=outline,
                       width=round(width * K))

    def box(self, x0, y0, x1, y1, fill, outline=None, width=1.5, radius=0):
        self.d.rounded_rectangle([x0 * K, y0 * K, x1 * K, y1 * K],
                                 radius=radius * K, fill=fill,
                                 outline=outline, width=round(width * K))

    def ellipse(self, cx, cy, rx, ry, fill, outline=None, width=1.5):
        self.d.ellipse([(cx - rx) * K, (cy - ry) * K, (cx + rx) * K, (cy + ry) * K],
                       fill=fill, outline=outline, width=round(width * K))

    def pie(self, cx, cy, rx, ry, start, end, fill, outline=None, width=1.5):
        self.d.pieslice([(cx - rx) * K, (cy - ry) * K, (cx + rx) * K, (cy + ry) * K],
                        start, end, fill=fill, outline=outline,
                        width=round(width * K))

    def line(self, pts, fill, width):
        self.d.line(self._p(pts), fill=fill, width=round(width * K), joint="curve")

    def arc(self, cx, cy, rx, ry, start, end, fill, width):
        self.d.arc([(cx - rx) * K, (cy - ry) * K, (cx + rx) * K, (cy + ry) * K],
                   start, end, fill=fill, width=round(width * K))

    def text(self, x, y, s, size, fill):
        self.d.text((x * K, y * K), s, font=load_font(round(size * K)),
                    fill=fill, anchor="mm")

    def soft_blob(self, pts, color, blur):
        """Blurred filled shape. The layer keeps the blob colour at zero alpha
        so blurring does not pull dark fringes into the edge."""
        layer = Image.new("RGBA", self.img.size, color + (0,))
        ImageDraw.Draw(layer).polygon(self._p(pts), fill=color + (255,))
        self.img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur * K)))

    def clipped(self, rect, paint):
        """Run paint() on a transparent layer and keep only pixels inside rect."""
        target, draw = self.img, self.d
        self.img = Image.new("RGBA", target.size, (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        paint()
        mask = Image.new("L", target.size, 0)
        x0, y0, x1, y1 = rect
        ImageDraw.Draw(mask).rectangle([x0 * K, y0 * K, x1 * K - 1, y1 * K - 1], fill=255)
        self.img.putalpha(ImageChops.multiply(self.img.getchannel("A"), mask))
        target.alpha_composite(self.img)
        self.img, self.d = target, draw


def blob_outline(rng, cx, cy, r):
    """Organic blob: a circle wobbled by a few random sine waves."""
    phases = [rng.uniform(0, math.tau) for _ in range(3)]
    aspect = rng.uniform(0.7, 1.0)
    pts = []
    for i in range(96):
        t = math.tau * i / 96
        wobble = (1 + 0.10 * math.sin(2 * t + phases[0])
                  + 0.06 * math.sin(3 * t + phases[1])
                  + 0.04 * math.sin(5 * t + phases[2]))
        pts.append((cx + r * wobble * math.cos(t), cy + r * aspect * wobble * math.sin(t)))
    return pts


def draw_background(c, rng, rect):
    c.box(*rect, PANEL, radius=0)

    def blobs():
        x0, y0, x1, y1 = rect
        for _ in range(16):
            cx = rng.uniform(x0, x1)
            cy = rng.uniform(y0, y1)
            r = rng.uniform(35, 105)
            color = rng.choice([PANEL_LIGHT, PANEL_DARK, PANEL_LIGHT])
            c.soft_blob(blob_outline(rng, cx, cy, r), color, blur=8)

    c.clipped(rect, blobs)


def draw_capsule(c, p0, p1, w, fill):
    """Thick line with round ends and an ink outline."""
    for color, width in ((INK, w + 3), (fill, w)):
        c.line([p0, p1], color, width)
        for x, y in (p0, p1):
            c.ellipse(x, y, width / 2, width / 2, color)


def draw_hair_back(c, hx, hy, rx, ry, color, style):
    if style == "bob":
        c.box(hx - rx - 4, hy - ry - 4, hx + rx + 4, hy + ry * 0.5, color, INK, 1.5,
              radius=rx * 0.9)


def draw_hair_front(c, hx, hy, rx, ry, color, style):
    c.pie(hx, hy - 1, rx + 2, ry + 3, 180, 360, color, INK, 1.5)
    if style == "bob":
        c.poly([(hx - rx - 2, hy - 2), (hx - rx - 2, hy - ry * 0.7),
                (hx + rx + 2, hy - ry * 0.7), (hx + rx + 2, hy - 2),
                (hx + rx * 0.4, hy - ry * 0.35), (hx, hy - ry * 0.2),
                (hx - rx * 0.4, hy - ry * 0.35)], color, INK, 1.5)
    elif style == "swoop":
        c.poly([(hx - rx - 2, hy), (hx - rx * 0.9, hy - ry * 0.95),
                (hx + rx * 0.1, hy - ry * 1.25), (hx + rx + 3, hy - ry * 0.7),
                (hx + rx * 0.7, hy - ry * 0.4), (hx - rx * 0.3, hy - ry * 0.5),
                (hx - rx - 2, hy - ry * 0.05)], color, INK, 1.5)
    else:
        for pts in (
            [(hx - rx * 0.8, hy - ry * 0.7), (hx - rx * 0.5, hy - ry * 1.35),
             (hx - rx * 0.1, hy - ry * 0.85)],
            [(hx - rx * 0.1, hy - ry * 0.85), (hx + rx * 0.3, hy - ry * 1.45),
             (hx + rx * 0.6, hy - ry * 0.8)],
            [(hx + rx * 0.6, hy - ry * 0.8), (hx + rx * 0.95, hy - ry * 1.2),
             (hx + rx + 2, hy - ry * 0.4)],
        ):
            c.poly(pts, color, INK, 1.5)


def draw_head(c, hx, hy, rx, ry, skin, hair, style, face=True):
    draw_hair_back(c, hx, hy, rx, ry, hair, style)
    for side in (-1, 1):
        c.ellipse(hx + side * rx, hy + 2, 4, 5.5, skin, INK, 1.4)
    c.ellipse(hx, hy, rx, ry, skin, INK, 1.6)
    draw_hair_front(c, hx, hy, rx, ry, hair, style)
    if not face:
        return
    u = rx / 21
    for side in (-1, 1):
        ex = hx + side * rx * 0.42
        c.ellipse(ex, hy + ry * 0.08, 2.1 * u, 2.8 * u, INK)
        c.ellipse(ex + 0.6 * u, hy + ry * 0.02, 0.7 * u, 0.7 * u, WHITE)
        c.line([(hx + side * rx * 0.65, hy - ry * 0.4),
                (hx + side * rx * 0.2, hy - ry * 0.47)], INK, 1.4 * u)
        c.ellipse(hx + side * rx * 0.6, hy + ry * 0.42, 3.2 * u, 2 * u,
                  (240, 140, 130, 140))
    c.arc(hx, hy + ry * 0.35, rx * 0.38, ry * 0.22, 20, 160, INK, 1.6 * u)


def draw_figure(c, look, cx=443.0):
    skin = SKIN_TONES[look["skin"]]
    hair, hair_style = HAIR_OPTIONS[look["hair"]]
    shirt = SHIRTS[look["shirt"]]
    leg_kind, leg_color = BOTTOMS[look["bottom"]]
    hx, hy, rx, ry = cx, 184, 21, 23

    c.ellipse(cx, 354, 36, 5.5, (226, 196, 96))
    draw_hair_back(c, hx, hy, rx, ry, hair, hair_style)

    if leg_kind == "short":
        for x0, x1 in ((cx - 22, cx - 4), (cx + 3, cx + 24)):
            c.poly([(x0, 306), (x1, 306), (x1 - 1, 340), (x0 + 2, 340)], skin, INK, 1.5)
        leg_end = 318
    else:
        leg_end = 340
    c.poly([(cx - 23, 298), (cx - 3, 298), (cx - 5, leg_end), (cx - 23, leg_end)],
           leg_color, INK, 1.5)
    c.poly([(cx + 3, 298), (cx + 24, 298), (cx + 24, leg_end), (cx + 5, leg_end)],
           leg_color, INK, 1.5)

    c.box(cx - 30, 336, cx - 4, 354, SHOE, INK, 1.5, radius=8)
    c.box(cx + 4, 336, cx + 29, 354, SHOE, INK, 1.5, radius=8)

    c.box(cx - 6, 200, cx + 6, 216, skin, INK, 1.4, radius=3)
    c.poly([(cx - 22, 212), (cx + 22, 212), (cx + 27, 236), (cx + 22, 262),
            (cx - 22, 262), (cx - 27, 236)], shirt, INK, 1.5)

    c.poly([(cx - 23, 236), (cx + 23, 236), (cx + 24, 300), (cx - 24, 300)],
           OVERALL, INK, 1.5)
    for side in (-1, 1):
        c.poly([(cx + side * 15, 212), (cx + side * 10, 212),
                (cx + side * 8, 228), (cx + side * 13, 228)], OVERALL, INK, 1.2)
    c.box(cx - 13, 226, cx + 13, 256, OVERALL, INK, 1.4, radius=3)
    c.box(cx - 9, 246, cx + 9, 260, OVERALL_DARK, INK, 1.2, radius=2)

    draw_capsule(c, (cx - 22, 218), (cx - 31, 240), 9, shirt)
    draw_capsule(c, (cx - 31, 240), (cx - 34, 262), 8, skin)
    c.ellipse(cx - 34, 267, 5, 5, skin, INK, 1.4)

    draw_capsule(c, (cx + 22, 218), (cx + 30, 204), 9, shirt)
    draw_capsule(c, (cx + 30, 204), (cx + 38, 186), 8, skin)
    c.ellipse(cx + 39, 180, 6.5, 6.5, skin, INK, 1.4)

    draw_head(c, hx, hy, rx, ry, skin, hair, hair_style)


def option_card(c, cx, cy, selected, draw_inside):
    c.box(cx - 22, cy - 22, cx + 22, cy + 22, WHITE, INK, 1.6, radius=7)
    draw_inside(cx, cy)
    if selected:
        c.box(cx - 22.5, cy - 22.5, cx + 22.5, cy + 22.5, None, PURPLE, 3, radius=8)


def draw_hair_icon(c, cx, cy, index):
    color, style = HAIR_OPTIONS[index]
    draw_head(c, cx, cy + 3, 10, 11, SKIN_TONES[1], color, style, face=False)


def draw_shirt_icon(c, cx, cy, index):
    c.poly([(cx - 14, cy - 12), (cx - 6, cy - 14), (cx - 3, cy - 10), (cx + 3, cy - 10),
            (cx + 6, cy - 14), (cx + 14, cy - 12), (cx + 17, cy - 4), (cx + 12, cy - 1),
            (cx + 10, cy - 4), (cx + 10, cy + 12), (cx - 10, cy + 12), (cx - 10, cy - 4),
            (cx - 12, cy - 1), (cx - 17, cy - 4)], SHIRTS[index], INK, 1.3)


def draw_bottom_icon(c, cx, cy, index):
    kind, color = BOTTOMS[index]
    end = cy + 14 if kind == "long" else cy + 3
    c.box(cx - 12, cy - 14, cx + 12, cy - 9, color, INK, 1.3, radius=2)
    c.poly([(cx - 12, cy - 10), (cx - 1, cy - 10), (cx - 2, end), (cx - 10, end)],
           color, INK, 1.3)
    c.poly([(cx + 1, cy - 10), (cx + 12, cy - 10), (cx + 10, end), (cx + 2, end)],
           color, INK, 1.3)


def draw_option_grid(c, look):
    icons = [draw_hair_icon, draw_shirt_icon, draw_bottom_icon]
    selected = [look["hair"], look["shirt"], look["bottom"]]
    for row in range(3):
        for col in range(3):
            cx = 550 + 52.5 * col
            cy = 198 + 52.5 * row
            option_card(c, cx, cy, selected[row] == col,
                        lambda x, y, row=row, col=col: icons[row](c, x, y, col))


def draw_skin_grid(c, look):
    def paint():
        for index, color in enumerate(SKIN_TONES):
            cx = 242 + 48 * (index % 3)
            cy = 222 + 52 * (index // 3)
            c.box(cx - 22, cy - 22, cx + 22, cy + 22, WHITE, INK, 2, radius=8)
            c.box(cx - 18, cy - 18, cx + 18, cy + 18, color, None, 0, radius=6)
            if index == look["skin"]:
                c.box(cx - 22.5, cy - 22.5, cx + 22.5, cy + 22.5, None, PURPLE, 3, radius=8)
    c.clipped((222, 186, 358, 310), paint)


def draw_carousel_arrows(c):
    for x, direction in ((275, -1), (305, 1)):
        c.ellipse(x, 317, 9.5, 9.5, PURPLE)
        tip = x + direction * 3.5
        c.line([(x - direction * 4, 317), (tip, 317)], WHITE, 1.8)
        c.poly([(tip - direction * 3, 314), (tip, 317), (tip - direction * 3, 320)], WHITE)


def draw_ok_button(c):
    c.box(612, 384, 669, 414, PURPLE, radius=6)
    c.line([(624, 399), (632, 399)], WHITE, 2)
    c.poly([(630, 395), (635, 399), (630, 403)], WHITE)
    c.text(648, 399, "OK", 14, WHITE)


def draw_menu_button(c):
    c.box(14, 14, 46, 46, PURPLE, radius=9)
    for y in (23, 30, 37):
        c.box(22, y - 1.3, 38, y + 1.3, WHITE, radius=1.3)


def random_look(rng):
    return {
        "skin": rng.randrange(len(SKIN_TONES)),
        "hair": rng.randrange(len(HAIR_OPTIONS)),
        "shirt": rng.randrange(len(SHIRTS)),
        "bottom": rng.randrange(len(BOTTOMS)),
    }


def render(seed=None):
    rng = random.Random(DEFAULT_SEED if seed is None else seed)
    look = dict(DEFAULT_LOOK) if seed is None else random_look(rng)

    c = Canvas(BASE_W, BASE_H, WHITE)

    draw_background(c, rng, (208, 73, 684, 430))
    draw_menu_button(c)

    c.text(446, 118, "Make your person.", 16, INK)

    c.box(380, 138, 506, 362, CARD_YELLOW, INK, 2, radius=10)
    c.clipped((380, 138, 506, 362), lambda: draw_figure(c, look))

    draw_skin_grid(c, look)
    draw_carousel_arrows(c)
    draw_option_grid(c, look)
    draw_ok_button(c)

    image = c.img.resize((BASE_W * 2, BASE_H * 2), Image.LANCZOS)
    return image.convert("RGB")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=None,
                        help="randomise the background and the figure from this seed")
    parser.add_argument("--out", default=os.path.join(here, "character_creator.png"))
    args = parser.parse_args()

    render(args.seed).save(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
