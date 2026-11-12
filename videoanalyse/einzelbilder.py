"""Bild-Option: das Video in einzelne Bilder zerlegen.

Entweder ein Bild alle 1 bis 10 Sekunden (auch 1,5) oder ein Bild pro Szenenwechsel. Wählbar sind außerdem
Zeitbereich (von/bis), Format (JPG oder PNG) und Bildbreite. Dazu ein Kontaktbogen (alle Bilder als Übersicht)."""
import json
import shutil
import subprocess
from pathlib import Path

from . import werkzeug, zeit

MIN_ABSTAND, MAX_ABSTAND = 1.0, 10.0
ORDNER, LISTE = "einzelbilder", "liste.json"
FORMATE = ("jpg", "png")
MODI = ("abstand", "szenen")


def abstand_lesen(wert) -> float:
    """'1,5' / '2' / 1.5 -> Sekunden. Erlaubt ist 1 bis 10."""
    try:
        a = round(float(str(wert).strip().replace(",", ".")), 2)
    except (TypeError, ValueError):
        raise ValueError(f"Abstand nicht lesbar: {wert!r}. Bitte eine Zahl von 1 bis 10 eingeben, z. B. 1,5.") from None
    if not MIN_ABSTAND <= a <= MAX_ABSTAND:
        raise ValueError("Der Abstand muss zwischen 1 und 10 Sekunden liegen (z. B. 1,5).")
    return a


def bereich_lesen(von, bis, dauer: float) -> tuple[float, float]:
    """von/bis als '1:30', '90' oder leer -> (Start, Ende) in Sekunden, begrenzt auf die Videolänge."""
    def lesen(wert, name):
        if wert is None or str(wert).strip() == "":
            return None
        try:
            return zeit.sekunden(str(wert))
        except ValueError:
            raise ValueError(f"„{name}“ nicht lesbar: {wert!r}. Bitte eine Zeit wie 1:30 oder 90 eingeben.") from None
    v = lesen(von, "von") or 0.0
    b = lesen(bis, "bis")
    b = dauer if b is None or b > dauer else b
    if v < 0 or v >= b:
        raise ValueError("Der Zeitbereich ist leer: „von“ muss vor „bis“ und innerhalb des Videos liegen.")
    return round(v, 2), round(b, 2)


def breite_lesen(wert) -> int | None:
    """Bildbreite in Pixeln (160 bis 7680) oder None für die Auflösung des Videos."""
    if wert is None or str(wert).strip().lower() in ("", "original", "0"):
        return None
    try:
        b = int(float(str(wert).strip()))
    except ValueError:
        raise ValueError(f"Bildbreite nicht lesbar: {wert!r}.") from None
    if not 160 <= b <= 7680:
        raise ValueError("Die Bildbreite muss zwischen 160 und 7680 Pixeln liegen.")
    return b - b % 2


def zeitname(t: float) -> str:
    """Sekunden -> 0-01-30 oder 0-00-01.5 (für Dateinamen, sortiert richtig)."""
    hundertstel = int(round(t * 100))
    ganz, rest = divmod(hundertstel, 100)
    h, r = divmod(ganz, 3600)
    m, s = divmod(r, 60)
    bruch = ("." + f"{rest:02d}".rstrip("0")) if rest else ""
    return f"{h}-{m:02d}-{s:02d}{bruch}"


def vorhandene(ordner: Path) -> dict | None:
    """Einzelbilder einer früheren Zerlegung (ordner = Arbeitsordner des Videos)."""
    try:
        e = json.loads((ordner / ORDNER / LISTE).read_text(encoding="utf-8"))
        return e if all((ordner / ORDNER / b).is_file() for b in e["bilder"]) else None
    except Exception:
        return None


def _komma(x) -> str:
    return str(x).rstrip("0").rstrip(".").replace(".", ",") if "." in str(x) else str(x)


def _nach_abstand(video: Path, neu: Path, a: float, v: float, b: float, endung: str, breite, log) -> list[float]:
    erwartet = max(1, int((b - v) / a) + 1)
    log(f"Zerlege das Video: ein Bild alle {_komma(a)} s (etwa {erwartet} Bilder) …")
    filter_ = f"select='gte(t,selected_n*{a})'" + (f",scale={breite}:-2" if breite else "")
    befehl = [werkzeug.ffmpeg(), "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1", "-y",
              "-ss", f"{v:.2f}", "-i", str(video), "-t", f"{b - v:.2f}", "-an", "-vf", filter_, "-fps_mode", "vfr"]
    befehl += (["-q:v", "2"] if endung == "jpg" else []) + [str(neu / f"roh_%06d.{endung}")]
    p = subprocess.Popen(befehl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    meldungen, zuletzt = [], -1
    for zeile in p.stdout:
        zeile = zeile.strip()
        if zeile.startswith("frame="):
            n = int(zeile[6:] or 0)
            if n != zuletzt and (n - zuletzt >= max(10, erwartet // 20) or n >= erwartet):
                zuletzt = n
                log(f"Einzelbilder {min(n, erwartet)}/{erwartet}", prozent=min(1.0, n / erwartet))
        elif zeile and "=" not in zeile[:20]:
            meldungen.append(zeile)
    p.wait()
    anzahl = len(list(neu.glob(f"roh_*.{endung}")))
    if p.returncode != 0 or not anzahl:
        raise RuntimeError("Einzelbilder konnten nicht erzeugt werden: " + (" ".join(meldungen)[-300:] or "keine Bilder erhalten"))
    return [round(v + i * a, 2) for i in range(anzahl)]


def _nach_szenen(video: Path, neu: Path, v: float, b: float, endung: str, breite, log) -> list[float]:
    from . import szenen
    log("Suche Szenenwechsel …")
    zeiten = [v] + [c for c in szenen.schnitte(video) if v + 0.5 < c < b - 0.1]
    log(f"Zerlege das Video: ein Bild pro Szenenwechsel ({len(zeiten)} Bilder) …")
    for i, t in enumerate(zeiten):
        args = ["-v", "error", "-y", "-ss", f"{min(t + 0.1, max(b - 0.05, 0)):.2f}", "-i", str(video), "-frames:v", "1"]
        args += (["-vf", f"scale={breite}:-2"] if breite else []) + (["-q:v", "2"] if endung == "jpg" else [])
        ziel = neu / f"roh_{i + 1:06d}.{endung}"
        if werkzeug.lauf(args + [str(ziel)]).returncode != 0 or not ziel.exists():
            raise RuntimeError(f"Einzelbild bei {t:.1f} s konnte nicht erzeugt werden.")
        log(f"Einzelbilder {i + 1}/{len(zeiten)}", prozent=(i + 1) / len(zeiten))
    return [round(t, 2) for t in zeiten]


def zerlegen(video: Path, dauer: float, ordner: Path, abstand=1, log=print, von=None, bis=None, bildformat="jpg",
             breite=None, modus="abstand") -> dict:
    """Schreibt die Einzelbilder nach <ordner>/einzelbilder. Eine alte Zerlegung wird ersetzt.
    modus 'abstand': das erste Bild ab von, von+abstand, von+2*abstand, … Sekunden. modus 'szenen': ein Bild pro Schnitt."""
    modus = (modus or "abstand").lower()
    endung = (bildformat or "jpg").lower().lstrip(".")
    if modus not in MODI:
        raise ValueError("Die Art muss „abstand“ oder „szenen“ sein.")
    if endung not in FORMATE:
        raise ValueError("Das Bildformat muss JPG oder PNG sein.")
    a = abstand_lesen(abstand) if modus == "abstand" else None
    v, b = bereich_lesen(von, bis, dauer)
    br = breite_lesen(breite)
    ziel, neu = ordner / ORDNER, ordner / (ORDNER + "_neu")
    shutil.rmtree(neu, ignore_errors=True)
    neu.mkdir(parents=True)
    try:
        zeiten = _nach_abstand(video, neu, a, v, b, endung, br, log) if modus == "abstand" else _nach_szenen(video, neu, v, b, endung, br, log)
    except Exception:
        shutil.rmtree(neu, ignore_errors=True)
        raise
    namen = []
    for i, bild in enumerate(sorted(neu.glob(f"roh_*.{endung}"))):
        name = f"bild_{i + 1:05d}_{zeitname(zeiten[i])}.{endung}"
        bild.rename(neu / name)
        namen.append(name)
    e = {"abstand": a, "anzahl": len(namen), "ordner": ORDNER, "bilder": namen, "zeiten": zeiten[:len(namen)], "modus": modus,
         "format": endung, "breite": br, "von": v, "bis": b, "ganz": v == 0 and b >= round(dauer, 2) - 0.01,
         "mb": round(sum((neu / n).stat().st_size for n in namen) / 1e6, 1)}
    (neu / LISTE).write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(ziel, ignore_errors=True)
    neu.rename(ziel)
    log(f"{e['anzahl']} Einzelbilder gespeichert ({_komma(e['mb'])} MB)")
    return e


def kontaktbogen(ordner: Path, spalten: int = 6, reihen: int = 8, kachel: int = 300) -> dict:
    """Alle Einzelbilder klein auf Übersichtsblättern (je spalten x reihen), mit der Zeit unter jedem Bild.
    Gibt die aktualisierte Bilderliste zurück; die Blätter stehen unter 'kontaktbogen'."""
    from PIL import Image, ImageDraw, ImageFont
    e = vorhandene(ordner)
    if not e or not e["bilder"]:
        raise ValueError("Es gibt noch keine Einzelbilder. Bitte zuerst das Video zerlegen.")
    ziel = ordner / ORDNER
    for alt in ziel.glob("kontaktbogen_*.jpg"):
        alt.unlink()
    zeiten = e.get("zeiten") or [i * (e.get("abstand") or 1) for i in range(len(e["bilder"]))]
    with Image.open(ziel / e["bilder"][0]) as erstes:
        hoehe = max(40, round(kachel * erstes.height / erstes.width))
    try:
        schrift = ImageFont.load_default(size=15)
    except TypeError:
        schrift = ImageFont.load_default()
    rand, text_h = 10, 24
    pro_blatt, blaetter = spalten * reihen, []
    for nr, ab in enumerate(range(0, len(e["bilder"]), pro_blatt), 1):
        teil = e["bilder"][ab:ab + pro_blatt]
        zeilen = -(-len(teil) // spalten)
        blatt = Image.new("RGB", (rand + spalten * (kachel + rand), rand + zeilen * (hoehe + text_h + rand)), (13, 17, 20))
        stift = ImageDraw.Draw(blatt)
        for i, name in enumerate(teil):
            x, y = rand + (i % spalten) * (kachel + rand), rand + (i // spalten) * (hoehe + text_h + rand)
            with Image.open(ziel / name) as bild:
                blatt.paste(bild.convert("RGB").resize((kachel, hoehe)), (x, y))
            stift.text((x + 2, y + hoehe + 4), zeitname(zeiten[ab + i]).replace("-", ":"), fill=(240, 179, 80), font=schrift)
        datei = f"kontaktbogen_{nr:02d}.jpg"
        blatt.save(ziel / datei, "JPEG", quality=88)
        blaetter.append(datei)
    e["kontaktbogen"] = blaetter
    (ziel / LISTE).write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    return e
