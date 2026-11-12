"""Schnitt mit ffmpeg: Clips ausschneiden (auch Hochformat), Sprechpausen entfernen, Video ohne Musik,
Lautstärke normalisieren, Untertitel einbrennen. Alles landet in <Arbeitsordner>/schnitt."""
import re
from pathlib import Path

from . import bericht, werkzeug, zeit

ORDNER = "schnitt"
VIDEO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
TON = ["-c:a", "aac", "-b:a", "192k"]
ENDE = ["-movflags", "+faststart"]
HOCH = "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1"  # Mitte ausschneiden, 9:16 für Shorts
ARTEN = ("clips", "stille", "ohne_musik", "lautstaerke", "untertitel", "liste")


def dateiname(text, ersatz: str = "clip") -> str:
    """Titel -> Dateiname ohne verbotene Zeichen."""
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(text or "")).strip(" .")
    return re.sub(r"\s+", " ", t)[:60].strip(" .") or ersatz


def _frei(p: Path) -> Path:
    if not p.exists():
        return p
    for i in range(2, 1000):
        k = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not k.exists():
            return k
    return p


def _lauf(args: list[str], ziel: Path, **kw) -> Path:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    r = werkzeug.lauf(["-v", "error", "-y", *args, str(ziel)], **kw)
    if r.returncode != 0 or not ziel.is_file() or ziel.stat().st_size == 0:
        ziel.unlink(missing_ok=True)
        raise RuntimeError("Schnitt fehlgeschlagen: " + (r.stderr.decode("utf-8", "replace").strip()[-300:] or "keine Datei erhalten"))
    return ziel


def clip(video: Path, start: float, ende: float, ziel: Path, hochformat: bool = False) -> Path:
    """Schneidet start bis ende bildgenau aus (neu kodiert). hochformat: 1080x1920 aus der Bildmitte."""
    start, ende = float(start), float(ende)
    if ende - start < 0.2:
        raise ValueError("Der Clip ist zu kurz. Ende muss nach dem Start liegen.")
    vf = ["-vf", HOCH] if hochformat else []
    return _lauf(["-ss", f"{start:.3f}", "-i", str(video), "-t", f"{ende - start:.3f}", *vf, *VIDEO, *TON, *ENDE], ziel)


def clips(video: Path, abschnitte: list[dict], ziel: Path, hochformat: bool = False) -> list[Path]:
    """Jeder Abschnitt {start, ende, titel} wird eine eigene Datei."""
    if not abschnitte:
        raise ValueError("Kein Abschnitt gewählt.")
    out = []
    for i, a in enumerate(abschnitte, 1):
        name = f"{i:02d} {dateiname(a.get('titel'), 'Clip')}" + (" (Hochformat)" if hochformat else "") + ".mp4"
        out.append(clip(video, a["start"], a["ende"], _frei(ziel / name), hochformat))
    return out


def sprechteile(zeilen: list[dict], dauer: float, rand: float = 0.15, pause: float = 0.6) -> list[tuple[float, float]]:
    """Zeitabschnitte, in denen gesprochen wird. Pausen kürzer als `pause` bleiben drin, `rand` Sekunden Luft an jeder Seite."""
    teile: list[list[float]] = []
    for z in sorted(zeilen, key=lambda x: x["start"]):
        a, b = max(0.0, z["start"] - rand), min(dauer, z["ende"] + rand)
        if b <= a:
            continue
        if teile and a - teile[-1][1] < pause:
            teile[-1][1] = max(teile[-1][1], b)
        else:
            teile.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in teile]


def ohne_stille(video: Path, zeilen: list[dict], dauer: float, ziel: Path, rand: float = 0.15, pause: float = 0.6) -> dict:
    """Setzt das Video nur aus den gesprochenen Stellen neu zusammen."""
    teile = sprechteile(zeilen, dauer, rand, pause)
    if not teile:
        raise ValueError("Ohne Transkript lassen sich keine Sprechpausen finden.")
    ausdruck = "+".join(f"between(t,{a},{b})" for a, b in teile)
    skript = ziel.with_suffix(".filter.txt")
    skript.parent.mkdir(parents=True, exist_ok=True)
    skript.write_text(f"[0:v]select='{ausdruck}',setpts=N/FRAME_RATE/TB[v];[0:a]aselect='{ausdruck}',asetpts=N/SR/TB[a]", encoding="utf-8")
    try:
        # "-/filter_complex Datei": der Filter kommt aus einer Datei, weil er bei vielen Abschnitten zu lang für die Befehlszeile wird
        _lauf(["-i", str(video), "-/filter_complex", str(skript), "-map", "[v]", "-map", "[a]", *VIDEO, *TON, *ENDE], ziel)
    finally:
        skript.unlink(missing_ok=True)
    neu = sum(b - a for a, b in teile)
    return {"datei": ziel, "vorher": round(dauer, 1), "nachher": round(neu, 1), "gespart": round(dauer - neu, 1)}


def ohne_musik(video: Path, stimme: Path, ziel: Path) -> Path:
    """Das Bild bleibt, als Ton kommt nur die getrennte Stimme."""
    if not stimme.is_file():
        raise ValueError("Dafür muss die Analyse mit „Stimme und Musik trennen“ gelaufen sein.")
    return _lauf(["-i", str(video), "-i", str(stimme), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", *TON, "-shortest", *ENDE], ziel)


def lautstaerke(video: Path, ziel: Path, lufs: float = -14.0) -> Path:
    """Gleicht die Lautstärke an (Standard −14 LUFS wie bei YouTube). Das Bild wird nicht neu kodiert."""
    return _lauf(["-i", str(video), "-c:v", "copy", "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11", "-ar", "48000", *TON, *ENDE], ziel)


def bildgroesse(video: Path) -> tuple[int, int]:
    """Breite und Höhe des Videobilds (über ffmpeg, ohne ffprobe)."""
    out = werkzeug.lauf(["-i", str(video)]).stderr.decode("utf-8", "replace")
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", out)
    if not m:
        raise RuntimeError(f"Bildgröße nicht lesbar: {video}")
    return int(m.group(1)), int(m.group(2))


def untertitel(video: Path, zeilen: list[dict], ziel: Path, mit_sprecher: bool = False) -> Path:
    """Brennt das Transkript als Untertitel fest ins Bild."""
    if not zeilen:
        raise ValueError("Ohne Transkript gibt es keine Untertitel.")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    srt = ziel.parent / "untertitel_einbrennen.srt"  # ohne Pfad im Filter: ffmpeg läuft im selben Ordner
    srt.write_text(bericht.srt(zeilen, sprecher=mit_sprecher), encoding="utf-8")
    try:
        b, h = bildgroesse(video)
        gross = 18 if b >= h else max(8, round(18 * b / h * 1.1))  # Hochformat: kleinere Schrift, sonst füllt sie das halbe Bild
        stil = f"FontName=Segoe UI,FontSize={gross},Outline=1.5,Shadow=0,MarginV=24"
        return _lauf(["-i", str(video.resolve()), "-vf", f"subtitles={srt.name}:force_style='{stil}'", *VIDEO, "-c:a", "copy", *ENDE],
                     ziel.resolve(), cwd=str(ziel.parent))
    finally:
        srt.unlink(missing_ok=True)


def vorhandene(ordner: Path) -> list[str]:
    """Fertige Schnitt-Dateien einer Analyse, neueste zuerst (Pfade relativ zum Arbeitsordner)."""
    d = ordner / ORDNER
    if not d.is_dir():
        return []
    return [f"{ORDNER}/{p.name}" for p in sorted(d.glob("*.mp4"), key=lambda p: -p.stat().st_mtime)]


def ausfuehren(art: str, video: Path, e: dict, ordner: Path, d: dict) -> dict:
    """Ein Schnitt-Auftrag aus der Oberfläche. Gibt {"dateien": [...], "meldung": "..."} zurück."""
    if art not in ARTEN:
        raise ValueError("Unbekannter Schnitt-Auftrag.")
    ziel = ordner / ORDNER
    meldung = ""
    if art == "clips":
        teile = []
        for a in d.get("abschnitte") or []:
            teile.append({"start": zeit.sekunden(str(a["start"])), "ende": zeit.sekunden(str(a["ende"])), "titel": a.get("titel")})
        neu = clips(video, teile, ziel, bool(d.get("hochformat")))
        meldung = f"{len(neu)} Clip(s) erstellt."
    elif art == "stille":
        r = ohne_stille(video, e.get("zeilen") or [], werkzeug.dauer(video), _frei(ziel / "ohne Sprechpausen.mp4"))
        meldung = f"Sprechpausen entfernt: {zeit.hms(r['vorher'])} wird {zeit.hms(r['nachher'])} ({zeit.hms(r['gespart'])} gespart)."
    elif art == "ohne_musik":
        ohne_musik(video, ordner / "audio" / "stimme.wav", _frei(ziel / "ohne Musik.mp4"))
        meldung = "Video ohne Musik erstellt."
    elif art == "lautstaerke":
        lautstaerke(video, _frei(ziel / "Lautstärke angeglichen.mp4"))
        meldung = "Lautstärke angeglichen (−14 LUFS)."
    elif art == "untertitel":
        untertitel(video, e.get("zeilen") or [], _frei(ziel / "mit Untertiteln.mp4"), bool(d.get("mit_sprecher")))
        meldung = "Untertitel eingebrannt."
    return {"dateien": vorhandene(ordner), "meldung": meldung}
