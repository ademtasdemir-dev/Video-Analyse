"""Transkript nachträglich ändern: Text korrigieren, Sprecher umbenennen, übersetzen. Alle Ausgaben werden danach neu geschrieben."""
from pathlib import Path

from . import bericht, sprecher

SPRACHEN = {"en": "Englisch", "de": "Deutsch", "tr": "Türkisch", "fr": "Französisch", "es": "Spanisch", "it": "Italienisch",
            "pl": "Polnisch", "ru": "Russisch", "ar": "Arabisch", "uk": "Ukrainisch", "nl": "Niederländisch", "pt": "Portugiesisch"}


def _namen_pruefen(e: dict, namen: dict) -> dict:
    alt = [s["sprecher"] for s in e["sprecher"]]
    neu = {}
    for a, n in (namen or {}).items():
        n = " ".join(str(n).split())[:40]
        if a in alt and n and n != a:
            neu[a] = n
    ergebnis = [neu.get(a, a) for a in alt]
    if len(set(ergebnis)) != len(ergebnis):
        raise ValueError("Zwei Sprecher dürfen nicht denselben Namen haben.")
    return neu


def anwenden(e: dict, ordner: Path, texte: dict | None = None, namen: dict | None = None) -> dict:
    """texte: {Zeilennummer: neuer Text}, namen: {alter Sprechername: neuer Name}. Gibt das geänderte Ergebnis zurück."""
    zeilen = e["zeilen"]
    geaendert = 0
    for nr, text in (texte or {}).items():
        i = int(nr)
        text = " ".join(str(text).split())
        if not 0 <= i < len(zeilen):
            raise ValueError(f"Zeile {i + 1} gibt es nicht.")
        if text and text != zeilen[i]["text"]:
            zeilen[i]["text"], zeilen[i]["woerter"] = text, len(text.split())
            geaendert += 1
    neu = _namen_pruefen(e, namen or {})
    if neu:
        for z in zeilen:
            z["sprecher"] = neu.get(z["sprecher"], z["sprecher"])
        e["audio"] = {(f"Nur {neu[k[4:]]}" if k.startswith("Nur ") and k[4:] in neu else k): v for k, v in (e.get("audio") or {}).items()}
    if geaendert or neu:
        merkmale = {neu.get(s["sprecher"], s["sprecher"]): {k: s[k] for k in ("rolle", "merkmale") if s.get(k)} for s in e["sprecher"]}
        e["sprecher"] = sprecher.statistik(zeilen)
        for s in e["sprecher"]:
            s.update(merkmale.get(s["sprecher"], {}))
        for k in e.get("kapitel", []):
            z = [x for x in zeilen if k["start"] - 0.5 <= x["start"] < k["ende"] - 0.5]
            k["text"], k["woerter"] = " ".join(x["text"] for x in z), sum(x["woerter"] for x in z)
            k["wpm"] = round(k["woerter"] / max((k["ende"] - k["start"]) / 60, 1e-6))
            k["sprecher"] = sorted({x["sprecher"] for x in z})
        bericht.exporte_schreiben(e, ordner)
    e["_geaendert"] = {"zeilen": geaendert, "sprecher": len(neu)}
    return e


def uebersetzung_speichern(e: dict, ordner: Path, sprache: str, texte: list[str]) -> dict:
    """Legt die übersetzten Zeilen als Untertitel (.srt) und Text (.txt) ab."""
    if len(texte) != len(e["zeilen"]):
        raise ValueError("Die Übersetzung hat nicht gleich viele Zeilen wie das Transkript.")
    zeilen = [{**z, "text": " ".join(str(t).split())} for z, t in zip(e["zeilen"], texte)]
    export = ordner / "export"
    export.mkdir(parents=True, exist_ok=True)
    (export / f"uebersetzung_{sprache}.srt").write_text(bericht.srt(zeilen, sprecher=False), encoding="utf-8")
    (export / f"uebersetzung_{sprache}.txt").write_text(bericht.txt(zeilen), encoding="utf-8")
    e.setdefault("uebersetzungen", {})[sprache] = [z["text"] for z in zeilen]
    bericht.exporte_schreiben(e, ordner)
    return e


def thumbnail(bild: Path, ordner: Path) -> str:
    """Macht aus einem Standbild oder Einzelbild das Vorschaubild für YouTube: 1280x720 JPG in export/thumbnail.jpg.
    Querformat wird mittig zugeschnitten, Hochformat kommt vor seinen eigenen, weichgezeichneten Hintergrund."""
    from PIL import Image, ImageFilter, ImageOps
    if not bild.is_file() or bild.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        raise ValueError("Das ist kein Bild dieser Analyse.")
    with Image.open(bild) as roh:
        im = roh.convert("RGB")
    if im.width >= im.height:
        fertig = ImageOps.fit(im, (1280, 720), Image.LANCZOS)
    else:
        fertig = ImageOps.fit(im, (1280, 720), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28)).point(lambda v: int(v * 0.6))
        vorn = ImageOps.contain(im, (1280, 720), Image.LANCZOS)
        fertig.paste(vorn, ((1280 - vorn.width) // 2, 0))
    ziel = ordner / "export" / "thumbnail.jpg"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    fertig.save(ziel, "JPEG", quality=90)
    return "export/thumbnail.jpg"
