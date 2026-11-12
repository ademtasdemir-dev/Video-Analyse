"""Baut aus dem Projekt das Setup (YVdctuAio_Setup_<Version>.exe) und die portable Einzeldatei (YVdctuAio-Portable.exe).

Aufruf im Projektordner:   uv run python installer/bauen.py            (alles)
                           uv run python installer/bauen.py stufe      (nur den Programmordner build/stufe, zum Testen)
                           uv run python installer/bauen.py setup      (Setup aus vorhandener Stufe)
                           uv run python installer/bauen.py portabel   (portable Exe aus vorhandener Stufe)

Alles landet in build/ (nicht im Repo). Gebraucht werden auf dem Bau-PC: uv, Inno Setup 6 und die einmal geladenen
Modelle (eine vollständige Analyse muss schon einmal gelaufen sein). Die fertigen Dateien laufen ohne all das."""
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from importlib import metadata
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent
HIER = PROJEKT / "installer"
BUILD = PROJEKT / "build"
STUFE = BUILD / "stufe"
WERKZEUGE = BUILD / "werkzeuge"
VERSION = re.search(r'^version = "([\d.]+)"', (PROJEKT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
ISCC = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"), Path("C:/Program Files/Inno Setup 6/ISCC.exe")]
LAUFZEIT_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
HF = Path.home() / ".cache" / "huggingface" / "hub"
PYTHON_WEG = ("Doc", "include", "libs", "Scripts", "Tools", "NEWS.txt", "Lib/site-packages", "Lib/test", "Lib/idlelib",
              "Lib/ensurepip", "Lib/turtledemo", "Lib/venv", "Lib/lib2to3", "Lib/tkinter/test")


def sagen(text: str) -> None:
    print(text, flush=True)


def lauf(befehl: list, **kw) -> None:
    r = subprocess.run([str(x) for x in befehl], **kw)
    if r.returncode != 0:
        raise SystemExit(f"Abbruch: {' '.join(str(x) for x in befehl[:3])} … meldet Fehler {r.returncode}")


def kopieren(von: Path, nach: Path, ohne=()) -> None:
    """robocopy: schnell und kommt mit langen Pfaden zurecht. Rückgabewerte bis 7 bedeuten Erfolg."""
    befehl = ["robocopy", str(von), str(nach), "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/MT:16", "/R:1", "/W:1",
              "/XD", "__pycache__", *[str(von / o) for o in ohne if (von / o).is_dir()], "/XF", "*.pyc", *[str(von / o) for o in ohne if (von / o).is_file()]]
    if subprocess.run(befehl).returncode > 7:
        raise SystemExit(f"Abbruch: Kopieren von {von} fehlgeschlagen")


def groesse(ordner: Path) -> float:
    return sum(p.stat().st_size for p in ordner.rglob("*") if p.is_file()) / 1e6


def python_basis() -> Path:
    cfg = (PROJEKT / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8")
    return Path(re.search(r"^home = (.+)$", cfg, re.M).group(1).strip())


def stufe_python() -> None:
    sagen("1/6  Python und Pakete …")
    ziel = STUFE / "python"
    kopieren(python_basis(), ziel, ohne=PYTHON_WEG)
    # Eigene, saubere Umgebung ohne Testwerkzeuge, genau nach uv.lock. Die Entwicklungsumgebung .venv bleibt unberührt.
    umgebung = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(BUILD / "venv")}
    lauf(["uv", "sync", "--frozen", "--no-dev", "--python", "3.12", "--quiet"], cwd=PROJEKT, env=umgebung)
    pakete = BUILD / "venv" / "Lib" / "site-packages"
    kopieren(pakete, ziel / "Lib" / "site-packages", ohne=("torch/include", "_virtualenv.py", "_virtualenv.pth"))
    for lib in (ziel / "Lib" / "site-packages" / "torch" / "lib").glob("*.lib"):
        lib.unlink()  # nur zum Programmieren mit C++ nötig, zusammen rund 750 MB
    (ziel / "Scripts").mkdir(exist_ok=True)
    shutil.copy2(BUILD / "venv" / "Scripts" / "deno.exe", ziel / "Scripts" / "deno.exe")  # braucht yt-dlp für YouTube
    # Abgeschottet: Dieses Python sieht keine anderen Python-Installationen, Umgebungsvariablen oder Benutzerpakete.
    (ziel / "python312._pth").write_text("Lib\nDLLs\n..\\app\nimport site\n", encoding="ascii")
    lizenzen(pakete)


def lizenzen(pakete: Path) -> None:
    zeilen = ["YVdctuAio – Lizenzen", "",
              "YVdctuAio selbst: (c) LAG|ZERØ.", "",
              "Mitgeliefert werden diese fremden Programme und Bibliotheken. Jedes steht unter seiner eigenen Lizenz;",
              "die vollständigen Lizenztexte liegen im Programmordner unter python\\Lib\\site-packages\\<Paket>-<Version>.dist-info.", "",
              "Python 3.12 – PSF License (python\\LICENSE.txt)",
              "FFmpeg (in imageio-ffmpeg) – GPL v3. Quelltext: https://ffmpeg.org/download.html",
              "Deno (für yt-dlp) – MIT",
              "Modelle: Whisper small (OpenAI, MIT, umgewandelt von Systran), HTDemucs (Meta, MIT), ECAPA-TDNN VoxCeleb (SpeechBrain, Apache 2.0)",
              "nightcut wird nicht mitgeliefert, nur gestartet, wenn es auf dem PC installiert ist (Nilson89, MIT).", "",
              "Python-Pakete:"]
    for d in sorted(metadata.distributions(path=[str(pakete)]), key=lambda d: (d.metadata["Name"] or "").lower()):
        m = d.metadata
        lizenz = m.get("License-Expression") or next((c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")), "") \
            or (m.get("License") or "").strip().split("\n")[0][:80] or "siehe Paket"
        zeilen.append(f"  {m['Name']} {d.version} – {lizenz}")
    (STUFE / "LIZENZEN.txt").write_text("\r\n".join(zeilen) + "\r\n", encoding="utf-8-sig")


def stufe_programm() -> None:
    sagen("2/6  Programm und Icon …")
    lauf([sys.executable, HIER / "icon_bauen.py"])
    app = STUFE / "app"
    kopieren(PROJEKT / "videoanalyse", app / "videoanalyse")
    kopieren(PROJEKT / "ui", app / "ui")
    shutil.copy2(PROJEKT / "ANLEITUNG.md", STUFE / "ANLEITUNG.txt")
    exe_bauen(HIER / "starter.cs", STUFE / "YVdctuAio.exe", ["System.Windows.Forms.dll"])


def exe_bauen(quelle: Path, ziel: Path, verweise: list[str]) -> None:
    if not CSC.is_file():
        raise SystemExit(f"Abbruch: C#-Compiler nicht gefunden ({CSC})")
    text = quelle.read_text(encoding="utf-8").replace('"1.1.0.0"', f'"{VERSION}.0"').replace('VERSION = "1.1.0"', f'VERSION = "{VERSION}"')
    kopie = BUILD / quelle.name
    kopie.write_text(text, encoding="utf-8-sig")
    lauf([CSC, "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001", f"/win32icon:{PROJEKT / 'ui' / 'icon.ico'}",
          f"/out:{ziel}", *[f"/r:{v}" for v in verweise], kopie])


def stufe_modelle() -> None:
    sagen("3/6  Modelle …")
    ziel = STUFE / "modelle"

    def schnappschuss(name: str, pflicht: str) -> Path:
        for s in sorted((HF / name / "snapshots").glob("*"), key=lambda p: -p.stat().st_mtime):
            if (s / pflicht).is_file():
                return s
        raise SystemExit(f"Abbruch: Modell {name} fehlt. Bitte einmal eine vollständige Analyse laufen lassen und neu bauen.")

    kopieren(schnappschuss("models--Systran--faster-whisper-small", "model.bin"), ziel / "whisper-small")
    kopieren(schnappschuss("models--speechbrain--spkrec-ecapa-voxceleb", "embedding_model.ckpt"), ziel / "ecapa")
    # SpeechBrain sucht in einem lokalen Modellordner immer nach custom.py und bricht ab, wenn die Datei fehlt.
    (ziel / "ecapa" / "custom.py").write_text("# absichtlich leer: dieses Modell braucht keinen eigenen Code\n", encoding="utf-8")
    name = "955717e8-8726e21a.th"
    for quelle in (PROJEKT / "daten" / "modelle" / "hub" / "checkpoints" / name, Path.home() / ".cache" / "torch" / "hub" / "checkpoints" / name,
                   Path.home() / "Desktop" / "Video-Analyse" / "daten" / "modelle" / "hub" / "checkpoints" / name):
        if quelle.is_file():
            (ziel / "torch" / "hub" / "checkpoints").mkdir(parents=True, exist_ok=True)
            shutil.copy2(quelle, ziel / "torch" / "hub" / "checkpoints" / name)
            return
    raise SystemExit("Abbruch: Trennmodell (Demucs) fehlt. Bitte einmal eine Analyse mit „Stimme und Musik trennen“ laufen lassen.")


def stufe() -> None:
    if STUFE.exists():
        shutil.rmtree(STUFE)
    STUFE.mkdir(parents=True)
    stufe_python()
    stufe_programm()
    stufe_modelle()
    sagen(f"     Programmordner fertig: {groesse(STUFE):.0f} MB in {STUFE}")


def setup() -> Path:
    sagen("4/6  Microsoft-Laufzeit holen …")
    WERKZEUGE.mkdir(parents=True, exist_ok=True)
    laufzeit = WERKZEUGE / "vc_redist.x64.exe"
    if not laufzeit.is_file() or laufzeit.stat().st_size < 10_000_000:
        urllib.request.urlretrieve(LAUFZEIT_URL, laufzeit)
    iscc = next((p for p in ISCC if p.is_file()), None)
    if not iscc:
        raise SystemExit("Abbruch: Inno Setup 6 nicht gefunden (winget install JRSoftware.InnoSetup).")
    sagen("5/6  Setup packen (dauert einige Minuten) …")
    skript = BUILD / "YVdctuAio.iss"
    skript.write_text((HIER / "YVdctuAio.iss").read_text(encoding="utf-8"), encoding="utf-8-sig")  # Inno Setup braucht die Kennung am Dateianfang
    (STUFE / "portabel.txt").unlink(missing_ok=True)
    lauf([iscc, "/Qp", f"/DVersion={VERSION}", f"/DStufe={STUFE}", f"/DWerkzeuge={WERKZEUGE}", f"/DAusgabe={BUILD}", skript])
    fertig = BUILD / f"YVdctuAio_Setup_{VERSION}.exe"
    sagen(f"     Setup fertig: {fertig.stat().st_size / 1e6:.0f} MB  {fertig}")
    return fertig


def portabel() -> Path:
    sagen("6/6  Portable Einzeldatei packen (dauert einige Minuten) …")
    paket = BUILD / "portabel.zip"
    (STUFE / "portabel.txt").write_text("Portable Version: Alle Daten bleiben im Ordner daneben.\r\n", encoding="utf-8")
    try:
        with zipfile.ZipFile(paket, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for p in sorted(STUFE.rglob("*")):
                if p.is_file():
                    schon_gepackt = p.suffix.lower() in (".bin", ".ckpt", ".th", ".jpg", ".png", ".zip")
                    z.write(p, p.relative_to(STUFE).as_posix(), compress_type=zipfile.ZIP_STORED if schon_gepackt else zipfile.ZIP_DEFLATED)
    finally:
        (STUFE / "portabel.txt").unlink(missing_ok=True)
    kopf = BUILD / "portabel_kopf.exe"
    exe_bauen(HIER / "portabel.cs", kopf, ["System.Windows.Forms.dll", "System.Drawing.dll", "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll"])
    fertig = BUILD / "YVdctuAio-Portable.exe"
    with open(fertig, "wb") as aus:
        for teil in (kopf, paket):
            with open(teil, "rb") as ein:
                shutil.copyfileobj(ein, aus, 16 * 1024 * 1024)
        aus.write(struct.pack("<q", paket.stat().st_size))  # die letzten 8 Bytes: Länge des angehängten Pakets
    paket.unlink(); kopf.unlink()
    sagen(f"     Portable Exe fertig: {fertig.stat().st_size / 1e6:.0f} MB  {fertig}")
    return fertig


if __name__ == "__main__":
    was = sys.argv[1] if len(sys.argv) > 1 else "alles"
    if was not in ("alles", "stufe", "setup", "portabel"):
        raise SystemExit(__doc__)
    sagen(f"YVdctuAio {VERSION} bauen ({was})")
    if was in ("alles", "stufe"):
        stufe()
    if was in ("alles", "setup"):
        setup()
    if was in ("alles", "portabel"):
        portabel()
    sagen("Fertig.")
