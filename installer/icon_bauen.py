"""Baut das Programm-Icon: ui/icon.png (256 px, für das Fenster) und ui/icon.ico (alle Größen, für Exe und Setup).

Gleiche Formensprache wie das Logo oben im Programm: Kachel in Petrol, dunkles Abspiel-Dreieck. Dazu ab 48 px
eine Zeitleiste in Bernstein mit Schnittmarken. Aufruf:  uv run python installer/icon_bauen.py"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HELL, DUNKEL, TINTE, BERNSTEIN = (63, 184, 173), (29, 95, 89), (13, 17, 20), (240, 179, 80)
GROESSEN = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def kachel(n: int) -> Image.Image:
    """Ein Icon in n x n Pixeln (gezeichnet in vierfacher Größe, dann sauber verkleinert)."""
    f = 4
    s = n * f
    verlauf = Image.new("RGB", (s, s))
    px = verlauf.load()
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * s - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(HELL, DUNKEL))
    maske = Image.new("L", (s, s), 0)
    ImageDraw.Draw(maske).rounded_rectangle((0, 0, s - 1, s - 1), radius=round(s * 0.225), fill=255)
    bild = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bild.paste(verlauf, (0, 0), maske)
    z = ImageDraw.Draw(bild)
    leiste = n >= 48
    # Abspiel-Dreieck: ohne Zeitleiste mittig, mit Zeitleiste etwas höher
    mitte_y = s * (0.42 if leiste else 0.5)
    hoehe, breite = s * (0.40 if leiste else 0.50), s * (0.36 if leiste else 0.44)
    links = s * 0.5 - breite * 0.36
    z.polygon([(links, mitte_y - hoehe / 2), (links + breite, mitte_y), (links, mitte_y + hoehe / 2)], fill=TINTE)
    if leiste:
        a, b, oben, unten = s * 0.17, s * 0.83, s * 0.735, s * 0.815
        z.rounded_rectangle((a, oben, b, unten), radius=(unten - oben) / 2, fill=TINTE)
        innen = (unten - oben) * 0.22
        for start, ende in ((0.04, 0.33), (0.39, 0.60), (0.66, 0.96)):  # drei Clips mit Schnitten dazwischen
            z.rounded_rectangle((a + (b - a) * start, oben + innen, a + (b - a) * ende, unten - innen),
                                radius=(unten - oben) * 0.2, fill=BERNSTEIN)
    return bild.resize((n, n), Image.LANCZOS)


def bauen(ziel: Path) -> None:
    ziel.mkdir(parents=True, exist_ok=True)
    bilder = [kachel(n) for n in GROESSEN]
    bilder[-1].save(ziel / "icon.png")
    bilder[-1].save(ziel / "icon.ico", format="ICO", sizes=[(n, n) for n in GROESSEN], append_images=bilder[:-1])


if __name__ == "__main__":
    bauen(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "ui")
    print("Icon gebaut.")
