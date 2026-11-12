"""ffmpeg finden und aufrufen, Audio laden/speichern."""
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np


@lru_cache(maxsize=1)
def ffmpeg() -> str:
    """Eigenes ffmpeg aus imageio-ffmpeg (läuft überall), sonst das System-ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pfad = shutil.which("ffmpeg")
        if not pfad:
            raise RuntimeError("ffmpeg wurde nicht gefunden.")
        return pfad


def lauf(args: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run([ffmpeg(), "-hide_banner", *args], creationflags=flags, **kw)


def dauer(datei: str | Path) -> float:
    """Länge in Sekunden (über ffmpeg, ohne ffprobe)."""
    import re
    out = lauf(["-i", str(datei)]).stderr.decode("utf-8", "replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        raise RuntimeError(f"Länge nicht lesbar: {datei}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def audio_laden(datei: str | Path, rate: int = 16000, kanaele: int = 1) -> np.ndarray:
    """Beliebige Audio-/Videodatei -> float32-Array (Kanäle x Samples bei kanaele>1)."""
    r = lauf(["-v", "error", "-i", str(datei), "-f", "f32le", "-ac", str(kanaele), "-ar", str(rate), "-"])
    if r.returncode != 0:
        raise RuntimeError("Audio konnte nicht gelesen werden: " + r.stderr.decode("utf-8", "replace")[-300:])
    a = np.frombuffer(r.stdout, np.float32)
    return a if kanaele == 1 else a.reshape(-1, kanaele).T.copy()


def wav_speichern(datei: str | Path, daten: np.ndarray, rate: int) -> Path:
    """float-Array (Samples) oder (Kanäle x Samples) als 16-bit-WAV speichern."""
    d = np.asarray(daten, dtype=np.float32)
    if d.ndim == 1:
        d = d[None, :]
    pcm = (np.clip(d.T, -1, 1) * 32767).astype("<i2")
    p = Path(datei)
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(d.shape[0]); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return p


def mp3_aus_wav(wav: Path, mp3: Path) -> Path:
    r = lauf(["-v", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "2", str(mp3)])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
    return mp3


def modell_ordner(name: str) -> Path | None:
    """Mitgeliefertes Modell (installierte und portable Version): Ordner unter VA_MODELLE, sonst None.
    Dann lädt das Programm das Modell wie bisher einmalig aus dem Internet."""
    import os
    basis = os.environ.get("VA_MODELLE")
    p = Path(basis) / name if basis else None
    return p if p and p.is_dir() and any(p.iterdir()) else None
