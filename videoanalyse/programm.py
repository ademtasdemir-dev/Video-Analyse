"""Start der installierten und der portablen Version (YVdctuAio.exe ruft: python -m videoanalyse.programm).

Unterschiede zum Entwicklerstart (start.bat): kein schwarzes Fenster, die Daten liegen im Benutzerordner statt im
Programmordner, mitgelieferte Modelle werden benutzt, ein zweiter Klick aufs Symbol öffnet nur ein weiteres Fenster,
und das Programm beendet sich selbst, wenn das letzte Fenster zu ist."""
import json
import os
import sys
import urllib.request
from pathlib import Path

NAME = "YVdctuAio"
BASIS = Path(__file__).resolve().parent.parent  # Ordner "app" neben YVdctuAio.exe


def daten_ordner() -> Path:
    """VA_DATEN (setzt die portable Exe) oder %LOCALAPPDATA%\\YVdctuAio\\daten."""
    if os.environ.get("VA_DATEN"):
        return Path(os.environ["VA_DATEN"])
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / NAME / "daten"


def umgebung(daten: Path) -> None:
    """Alles, was sonst „uv run“ erledigt: Datenordner, Modelle, Pfad zu den mitgelieferten Programmen."""
    daten.mkdir(parents=True, exist_ok=True)
    os.environ["VA_DATEN"] = str(daten)
    os.environ.setdefault("PYTHONUTF8", "1")
    modelle = BASIS.parent / "modelle"
    if modelle.is_dir():
        os.environ.setdefault("VA_MODELLE", str(modelle))
        if (modelle / "torch" / "hub" / "checkpoints").is_dir():
            os.environ.setdefault("TORCH_HOME", str(modelle / "torch"))  # Trennmodell (Demucs) ist mitgeliefert
    os.environ.setdefault("HF_HOME", str(daten / "modelle" / "hf"))  # nachgeladene Modelle bleiben im Datenordner
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    skripte = Path(sys.executable).parent / "Scripts"  # dort liegt deno.exe, das yt-dlp für YouTube braucht
    os.environ["PATH"] = str(skripte) + os.pathsep + os.environ.get("PATH", "")


def protokoll(daten: Path) -> None:
    """Ohne Konsole gibt es kein Ausgabefenster: Meldungen und Fehler landen in daten/protokoll.log."""
    datei = daten / "protokoll.log"
    try:
        if datei.is_file() and datei.stat().st_size > 2_000_000:
            datei.replace(datei.with_suffix(".alt.log"))
        ziel = open(datei, "a", encoding="utf-8", buffering=1)
    except OSError:
        ziel = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stderr = ziel


def laeuft_schon(zustand: Path) -> str | None:
    """Adresse eines schon laufenden Programms, sonst None."""
    try:
        url = json.loads(zustand.read_text(encoding="utf-8"))["url"]
        with urllib.request.urlopen(url + "api/status", timeout=3) as r:
            return url if "schritte" in json.loads(r.read()) else None
    except Exception:
        return None


def _mutex():
    """Benannter Windows-Mutex: Setup und Deinstallation erkennen daran, dass das Programm läuft."""
    if sys.platform != "win32":
        return None
    import ctypes
    return ctypes.windll.kernel32.CreateMutexW(None, False, NAME + "_laeuft")


def haupt() -> int:
    daten = daten_ordner()
    umgebung(daten)
    protokoll(daten)
    from . import server  # erst jetzt: server liest VA_DATEN beim Laden
    zustand = daten / "laeuft.json"
    url = laeuft_schon(zustand)
    if url:
        server.fenster_oeffnen(url)
        return 0
    halten = _mutex()  # noqa: F841 (muss bis zum Programmende leben)
    import time
    print(f"--- {NAME} {server.VERSION} gestartet {time.strftime('%d.%m.%Y %H:%M:%S')} ---", flush=True)
    server.starten(browser=not os.environ.get("VA_OHNE_FENSTER"), beenden=True, zustand=zustand)  # VA_OHNE_FENSTER: nur für Tests
    print("--- beendet ---", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(haupt())
