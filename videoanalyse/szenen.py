"""Bildanalyse: Schnitte/Folienwechsel finden, pro Szene ein Standbild, Bildart grob einschätzen."""
import re
from pathlib import Path

import numpy as np
from PIL import Image

from . import werkzeug


def schnitte(video: Path, schwelle: float = 0.12) -> list[float]:
    """Zeitpunkte, an denen sich das Bild deutlich ändert (Schnitt, Folienwechsel, Szenenwechsel)."""
    r = werkzeug.lauf(["-i", str(video), "-an", "-vf", f"scale=320:-2,select='gt(scene,{schwelle})',showinfo", "-f", "null", "-"])
    log = r.stderr.decode("utf-8", "replace")
    return sorted({round(float(t), 2) for t in re.findall(r"pts_time:([\d.]+)", log)})


def szenen_bilden(cuts: list[float], dauer: float, min_laenge: float = 1.5, max_laenge: float = 30.0, max_anzahl: int = 80) -> list[dict]:
    """Aus Schnittzeiten werden Szenen. Sehr kurze werden angehängt, sehr lange in Abschnitte geteilt (für Standbilder)."""
    grenzen = [0.0]
    for c in cuts:
        if c - grenzen[-1] >= min_laenge and dauer - c >= min_laenge * 0.5:
            grenzen.append(c)
    grenzen.append(dauer)
    szenen = []
    for a, b in zip(grenzen, grenzen[1:]):
        teile = max(1, int(np.ceil((b - a) / max_laenge)))
        for k in range(teile):
            s = a + (b - a) * k / teile
            e = a + (b - a) * (k + 1) / teile
            szenen.append({"start": round(s, 2), "ende": round(e, 2), "schnitt": k == 0 and a > 0})
    while len(szenen) > max_anzahl:  # kürzeste Szene mit Nachbar zusammenlegen
        i = min(range(len(szenen)), key=lambda j: szenen[j]["ende"] - szenen[j]["start"])
        j = i - 1 if i > 0 else i + 1
        a, b = sorted((i, j))
        szenen[a] = {"start": szenen[a]["start"], "ende": szenen[b]["ende"], "schnitt": szenen[a]["schnitt"]}
        del szenen[b]
    return szenen


def standbild(video: Path, t: float, ziel: Path, breite: int = 960) -> Path:
    r = werkzeug.lauf(["-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                       "-vf", f"scale={breite}:-2", "-q:v", "3", str(ziel)])
    if r.returncode != 0 or not ziel.exists():
        raise RuntimeError(f"Standbild bei {t:.1f} s fehlgeschlagen")
    return ziel


def merkmale(bild: Path) -> dict:
    im = Image.open(bild).convert("RGB").resize((240, 135))
    a = np.asarray(im).astype(np.float32) / 255
    hell = a.mean(2)
    mx, mn = a.max(2), a.min(2)
    saett = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    gx = np.abs(np.diff(hell, axis=1)).mean(); gy = np.abs(np.diff(hell, axis=0)).mean()
    kanten = float(gx + gy)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    haut = (r > 0.37) & (g > 0.16) & (b > 0.08) & (r > g) & (r > b) & ((r - g) > 0.06) & (mx - mn > 0.06) & (saett < 0.68)
    q = (a * 7).astype(int)
    farben = len(np.unique(q[..., 0] * 64 + q[..., 1] * 8 + q[..., 2]))
    # Anteil der häufigsten (Hintergrund-)Farbe
    werte, anz = np.unique(q[..., 0] * 64 + q[..., 1] * 8 + q[..., 2], return_counts=True)
    hintergrund = float(anz.max() / anz.sum())
    flach = saett < 0.15
    hell_flaeche = float(((hell > 0.8) & flach).mean())   # weiße/helle Fläche (Folienhintergrund)
    dunkel_flaeche = float(((hell < 0.2) & flach).mean())  # dunkle Fläche (Code, dunkle Folien)
    return {"hell_flaeche": round(hell_flaeche, 3), "dunkel_flaeche": round(dunkel_flaeche, 3), "helligkeit": round(float(hell.mean()), 3), "saettigung": round(float(saett.mean()), 3),
            "kanten": round(kanten, 4), "haut": round(float(haut.mean()), 3), "farben": int(farben),
            "hintergrund": round(hintergrund, 3)}


def bildart(m: dict) -> str:
    """Grobe, automatische Einschätzung ohne KI. Mit Gemini gibt es echte Bildbeschreibungen."""
    if m["helligkeit"] < 0.08:
        return "Schwarzbild / Übergang"
    if (m["hintergrund"] > 0.45 or m.get("hell_flaeche", 0) > 0.55) and m["helligkeit"] > 0.6 and m["kanten"] > 0.01:
        return "Folie / Präsentation (heller Hintergrund mit Text)"
    if (m["hintergrund"] > 0.45 or m.get("dunkel_flaeche", 0) > 0.55) and m["helligkeit"] < 0.35 and m["kanten"] > 0.01:
        return "Bildschirm / Text auf dunklem Hintergrund"
    if m["haut"] > 0.08 and m["hintergrund"] < 0.35:
        return "Person im Bild (Kamera)"
    if m["saettigung"] > 0.45 and m["hintergrund"] > 0.25:
        return "Grafik / Animation"
    return "Realbild / Szene"


def analysieren(video: Path, dauer: float, ziel: Path, log=print) -> dict:
    ziel.mkdir(parents=True, exist_ok=True)
    log("Suche Schnitte und Folienwechsel …")
    cuts = schnitte(video)
    fein = [t for t in schnitte(video, 0.05) if all(abs(t - c) > 0.5 for c in cuts)]
    sz = szenen_bilden(cuts, dauer)
    for i, s in enumerate(sz):
        t = min(s["start"] + min(1.0, (s["ende"] - s["start"]) / 2), max(0, dauer - 0.1))
        p = standbild(video, t, ziel / f"bild_{i + 1:03d}.jpg")
        m = merkmale(p)
        s.update({"nr": i + 1, "bild": p.name, "bild_zeit": round(t, 2), "merkmale": m, "bildart": bildart(m)})
        log(f"Standbilder {i + 1}/{len(sz)}", prozent=(i + 1) / len(sz))
    minuten = max(dauer / 60, 1e-6)
    arten = {}
    for s in sz:
        arten[s["bildart"]] = round(arten.get(s["bildart"], 0) + s["ende"] - s["start"], 1)
    return {"schnitte": cuts, "einblendungen": fein, "szenen": sz, "einblendungen_pro_minute": round(len(fein) / minuten, 1), "schnitte_pro_minute": round(len(cuts) / minuten, 1),
            "mittlere_szenenlaenge": round(dauer / max(1, len(cuts) + 1), 1),
            "bildarten": dict(sorted(arten.items(), key=lambda x: -x[1]))}
