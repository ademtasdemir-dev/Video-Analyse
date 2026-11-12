"""Brücke zu nightcut (von Nilson89, MIT-Lizenz): startet eine vorhandene nightcut-Installation auf diesem PC.

nightcut selbst steckt nicht in diesem Programm. Es braucht eine Grafikkarte, eine eigene PyTorch-Version und lokale
KI-Modelle und bleibt deshalb in seinem eigenen Ordner. Hier wird nur der Aufruf gebaut und das Protokoll mitgelesen."""
import os
import shutil
import subprocess
from pathlib import Path

STANDARD_ORDNER = Path.home() / "Desktop" / "nightcut"
ENDUNGEN = (".mkv", ".mp4", ".mov", ".webm")


def ordner(einstellungen: dict) -> Path:
    return Path(einstellungen.get("nightcut_ordner") or STANDARD_ORDNER)


def stand(einstellungen: dict) -> dict:
    """Ist nightcut da, und welche Spielprofile gibt es?"""
    o = ordner(einstellungen)
    da = (o / "pyproject.toml").is_file() and (o / "src" / "nightcut").is_dir()
    profile = sorted(p.stem for p in (o / "profiles").glob("*.yaml")) if da else []
    return {"ordner": str(o), "vorhanden": da, "uv": bool(shutil.which("uv")), "profile": profile,
            "trennen": da and (o / "spuren_trennen.py").is_file(), "eigene_einstellung": da and (o / "config" / "local.yaml").is_file()}


def befehle(o: Path, aufnahme: Path, profil: str, trennen: bool, modus: str = "", auffuellen: bool = False) -> list[list[str]]:
    """Die Aufrufe wie in „Warzone schneiden.bat“: erst (auf Wunsch) Stimmen trennen, dann nightcut."""
    if aufnahme.suffix.lower() not in ENDUNGEN or not aufnahme.is_file():
        raise ValueError("Bitte eine Aufnahme wählen (.mkv, .mp4, .mov oder .webm).")
    if not (o / "profiles" / f"{profil}.yaml").is_file():
        raise ValueError(f"Das Spielprofil „{profil}“ gibt es in nightcut nicht.")
    if modus not in ("", "highlights", "letsplay"):
        raise ValueError("Modus muss highlights oder letsplay sein.")
    schritte = []
    eingabe = aufnahme
    if trennen:
        if not (o / "spuren_trennen.py").is_file():
            raise ValueError("In diesem nightcut-Ordner fehlt spuren_trennen.py.")
        schritte.append(["uv", "run", "python", "spuren_trennen.py", str(aufnahme)])
        eingabe = aufnahme.parent / "getrennt" / aufnahme.name
    lauf = ["uv", "run", "nightcut", "run", str(eingabe), "--profile", profil, "--name", f"{aufnahme.stem} {profil}",
            "--fill" if auffuellen else "--no-fill"]
    if (o / "config" / "local.yaml").is_file():
        lauf += ["--config", "config/local.yaml"]
    if modus:
        lauf += ["--mode", modus]
    schritte.append(lauf)
    return schritte


def ausfuehren(o: Path, schritte: list[list[str]], log=print) -> None:
    """Führt die Aufrufe nacheinander im nightcut-Ordner aus und reicht jede Ausgabezeile ans Protokoll weiter."""
    umgebung = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT")}
    umgebung["PYTHONUTF8"] = "1"
    for befehl in schritte:
        log("▶ " + " ".join(befehl[:4]) + " …")
        try:
            p = subprocess.Popen(befehl, cwd=str(o), env=umgebung, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise RuntimeError("uv wurde nicht gefunden. nightcut braucht uv (winget install astral-sh.uv).") from None
        letzte = ""
        for zeile in p.stdout:
            zeile = zeile.rstrip()
            if zeile.strip():
                letzte = zeile.strip()
                log(letzte[:300])
        if p.wait() != 0:
            raise RuntimeError(f"nightcut hat abgebrochen: {letzte[:300] or 'ohne Meldung'}")


def ergebnis_ordner(o: Path, aufnahme: Path, profil: str) -> Path:
    return o / "output" / f"{aufnahme.stem} {profil}"
