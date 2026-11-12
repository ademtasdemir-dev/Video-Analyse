"""Stimme und Musik trennen (Demucs, lokal) und Audio pro Sprecher ausschneiden."""
import os
from pathlib import Path

import numpy as np

from . import werkzeug

RATE = 44100


VIER = {"drums": "schlagzeug.wav", "bass": "bass.wav", "other": "instrumente.wav"}  # Demucs-Spur -> Datei
VIER_NAMEN = {"schlagzeug.wav": "Nur Schlagzeug", "bass.wav": "Nur Bass", "instrumente.wav": "Nur übrige Instrumente"}


def stimme_musik(video: Path, ziel: Path, cache: Path, log=print, vier: bool = False) -> dict:
    """Erzeugt stimme.wav (nur Gesprochenes) und musik.wav (alles andere: Musik, Geräusche)."""
    os.environ.setdefault("TORCH_HOME", str(cache))
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    log("Lade Trennmodell (einmalig ca. 80 MB) …")
    modell = get_model("htdemucs")
    modell.eval()
    mix = werkzeug.audio_laden(video, RATE, 2)
    t = torch.from_numpy(mix)
    ref = t.mean(0)
    mittel, streu = ref.mean(), ref.std() + 1e-8
    log("Trenne Stimme und Musik … (dauert etwa so lang wie das Video)", prozent=0.05)
    with torch.no_grad():
        quellen = apply_model(modell, ((t - mittel) / streu)[None], split=True, overlap=0.25, progress=False)[0]
    quellen = quellen * streu + mittel
    i = modell.sources.index("vocals")
    stimme = quellen[i].numpy()
    musik = (quellen.sum(0) - quellen[i]).numpy()
    ziel.mkdir(parents=True, exist_ok=True)
    werkzeug.wav_speichern(ziel / "stimme.wav", stimme, RATE)
    werkzeug.wav_speichern(ziel / "musik.wav", musik, RATE)
    if vier:  # das Modell trennt ohnehin in vier Spuren, hier werden die drei Instrumentenspuren zusätzlich gespeichert
        for quelle_name, datei in VIER.items():
            werkzeug.wav_speichern(ziel / datei, quellen[modell.sources.index(quelle_name)].numpy(), RATE)
    # Wie viel Musik ist überhaupt da? (Energie-Verhältnis)
    e_s, e_m = float((stimme ** 2).mean()), float((musik ** 2).mean())
    anteil = round(100 * e_m / max(e_s + e_m, 1e-12), 1)
    return {"stimme": str(ziel / "stimme.wav"), "musik": str(ziel / "musik.wav"), "musikanteil": anteil}


def vorhandene(ziel: Path) -> dict:
    s = werkzeug.audio_laden(ziel / "stimme.wav", 16000, 1); m = werkzeug.audio_laden(ziel / "musik.wav", 16000, 1)
    e_s, e_m = float((s ** 2).mean()), float((m ** 2).mean())
    return {"stimme": str(ziel / "stimme.wav"), "musik": str(ziel / "musik.wav"),
            "musikanteil": round(100 * e_m / max(e_s + e_m, 1e-12), 1)}


def original(video: Path, ziel: Path) -> Path:
    a = werkzeug.audio_laden(video, RATE, 2)
    return werkzeug.wav_speichern(ziel / "original.wav", a, RATE)


def pro_sprecher(quelle: Path, zeilen: list[dict], ziel: Path, rand: float = 0.15, stille: float = 0.35) -> dict:
    """Schneidet aus der (am besten getrennten) Stimmspur alle Stellen jedes Sprechers heraus und hängt sie aneinander."""
    a = werkzeug.audio_laden(quelle, RATE, 2)
    pause = np.zeros((2, int(stille * RATE)), np.float32)
    teile: dict[str, list] = {}
    for z in zeilen:
        s, e = max(0, int((z["start"] - rand) * RATE)), min(a.shape[1], int((z["ende"] + rand) * RATE))
        if e > s:
            teile.setdefault(z["sprecher"], []).extend([a[:, s:e], pause])
    dateien = {}
    for sp, stuecke in teile.items():
        name = sp.lower().replace(" ", "_") + ".wav"
        werkzeug.wav_speichern(ziel / name, np.concatenate(stuecke, axis=1), RATE)
        dateien[sp] = str(ziel / name)
    return dateien
