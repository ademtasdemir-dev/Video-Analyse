"""Tests: Start der installierten Version, Selbstbeenden, Update-Hinweis, nightcut-Brücke."""
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from videoanalyse import nightcut, programm, server, update, werkzeug


def test_soll_beenden():
    f = server.soll_beenden
    assert not f(100, 0, None, False)            # ein Fenster ist offen
    assert not f(105, 0, 100, False)             # gerade erst geschlossen (Seite lädt vielleicht nur neu)
    assert f(109, 0, 100, False)                 # länger als die Schonfrist ohne Fenster
    assert not f(999, 0, 100, True)              # eine laufende Analyse wird nie abgebrochen
    assert not f(60, 0, 0, False) and f(121, 0, 0, False)  # nie ein Fenster gekommen: nach zwei Minuten Schluss


def test_fenster_melden_und_beenden(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATEN", tmp_path); monkeypatch.setattr(server, "ARBEIT", tmp_path / "arbeit")
    monkeypatch.setattr(server, "CACHE", tmp_path / "modelle"); monkeypatch.setattr(server, "FENSTER", {})
    monkeypatch.setitem(server.JOB, "thread", None)
    echte_frist = server.soll_beenden
    monkeypatch.setattr(server, "soll_beenden", lambda j, g, l, lf: echte_frist(j, g, l, lf, schonfrist=0.5))
    zustand = tmp_path / "laeuft.json"
    t = threading.Thread(target=server.starten, kwargs={"port": 8931, "browser": False, "beenden": True, "zustand": zustand}, daemon=True)
    t.start()
    for _ in range(50):
        if zustand.is_file():
            break
        time.sleep(0.1)
    url = json.loads(zustand.read_text())["url"]
    assert programm.laeuft_schon(zustand) == url

    def melden(was):
        req = urllib.request.Request(url + "api/fenster", json.dumps({"was": was, "id": "f1"}).encode(), {"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()

    melden("da")
    time.sleep(3)
    assert t.is_alive(), "mit offenem Fenster läuft das Programm weiter"
    melden("zu")
    t.join(timeout=8)
    assert not t.is_alive() and not zustand.exists(), "ohne Fenster beendet es sich und räumt die Zustandsdatei weg"
    assert programm.laeuft_schon(zustand) is None


def test_icon_wird_ausgeliefert(tmp_path, monkeypatch):
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{h.server_address[1]}/icon.png") as r:
            assert r.status == 200 and r.read().startswith(b"\x89PNG")
    finally:
        h.shutdown()


def test_update_hinweis(monkeypatch):
    assert update.nummer("v1.10.2") == (1, 10, 2) and update.nummer("1.2") < update.nummer("1.10")

    class Antwort:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"tag_name": "v1.3.0", "html_url": "https://example.org/r"}).encode()

    monkeypatch.setattr(update, "_ergebnis", None)
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=0: Antwort())
    assert update.pruefen("1.1.0") == {"neu": "1.3.0", "url": "https://example.org/r"}
    monkeypatch.setattr(update, "_ergebnis", None)
    assert update.pruefen("1.3.0") == {}

    def kaputt(req, timeout=0):
        raise OSError("kein Netz")

    monkeypatch.setattr(update, "_ergebnis", None)
    monkeypatch.setattr(update.urllib.request, "urlopen", kaputt)
    assert update.pruefen("1.0.0") == {}


def test_umgebung_und_mitgelieferte_modelle(tmp_path, monkeypatch):
    for name in ("VA_DATEN", "VA_MODELLE", "TORCH_HOME", "HF_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    assert programm.daten_ordner() == tmp_path / "lokal" / "YVdctuAio" / "daten"
    monkeypatch.setenv("VA_DATEN", str(tmp_path / "portabel"))
    assert programm.daten_ordner() == tmp_path / "portabel"
    monkeypatch.delenv("VA_DATEN")
    app = tmp_path / "prog" / "app"; app.mkdir(parents=True)
    (tmp_path / "prog" / "modelle" / "torch" / "hub" / "checkpoints").mkdir(parents=True)
    (tmp_path / "prog" / "modelle" / "whisper-small").mkdir(); (tmp_path / "prog" / "modelle" / "whisper-small" / "model.bin").write_bytes(b"x")
    (tmp_path / "prog" / "modelle" / "ecapa").mkdir()
    monkeypatch.setattr(programm, "BASIS", app)
    monkeypatch.setenv("PATH", "alt")
    daten = tmp_path / "daten"
    programm.umgebung(daten)
    import os
    assert os.environ["VA_DATEN"] == str(daten) and os.environ["TORCH_HOME"].endswith("torch") and "hf" in os.environ["HF_HOME"]
    assert os.environ["PATH"].endswith("alt") and "Scripts" in os.environ["PATH"]
    assert werkzeug.modell_ordner("whisper-small") == tmp_path / "prog" / "modelle" / "whisper-small"
    assert werkzeug.modell_ordner("ecapa") is None and werkzeug.modell_ordner("whisper-medium") is None  # leer oder nicht da: aus dem Netz


def test_nightcut_befehle(tmp_path):
    o = tmp_path / "nightcut"
    for teil in ("src/nightcut", "profiles", "config"):
        (o / teil).mkdir(parents=True)
    (o / "pyproject.toml").write_text("x"); (o / "profiles" / "warzone.yaml").write_text("x"); (o / "profiles" / "bf6.yaml").write_text("x")
    s = nightcut.stand({"nightcut_ordner": str(o)})
    assert s["vorhanden"] and s["profile"] == ["bf6", "warzone"] and not s["trennen"]
    assert not nightcut.stand({"nightcut_ordner": str(tmp_path / "fehlt")})["vorhanden"]
    aufnahme = tmp_path / "Runde 1.mkv"; aufnahme.write_bytes(b"x")
    b = nightcut.befehle(o, aufnahme, "warzone", False)
    assert b == [["uv", "run", "nightcut", "run", str(aufnahme), "--profile", "warzone", "--name", "Runde 1 warzone", "--no-fill"]]
    (o / "spuren_trennen.py").write_text("x"); (o / "config" / "local.yaml").write_text("x")
    b = nightcut.befehle(o, aufnahme, "bf6", True, "letsplay", True)
    assert b[0] == ["uv", "run", "python", "spuren_trennen.py", str(aufnahme)]
    assert b[1][4] == str(tmp_path / "getrennt" / "Runde 1.mkv") and b[1][-4:] == ["--config", "config/local.yaml", "--mode", "letsplay"] and "--fill" in b[1]
    assert nightcut.ergebnis_ordner(o, aufnahme, "bf6") == o / "output" / "Runde 1 bf6"
    for falsch in ((aufnahme, "gibtsnicht", ""), (tmp_path / "fehlt.mkv", "bf6", ""), (o / "pyproject.toml", "bf6", ""), (aufnahme, "bf6", "turbo")):
        with pytest.raises(ValueError):
            nightcut.befehle(o, falsch[0], falsch[1], False, falsch[2])


def test_nightcut_ausfuehren_liest_protokoll_und_meldet_abbruch(tmp_path):
    import sys
    zeilen = []
    nightcut.ausfuehren(tmp_path, [[sys.executable, "-c", "print('Schritt eins'); print('fertig')"]], log=zeilen.append)
    assert zeilen[1:] == ["Schritt eins", "fertig"]
    with pytest.raises(RuntimeError, match="kaputt"):
        nightcut.ausfuehren(tmp_path, [[sys.executable, "-c", "import sys; print('kaputt'); sys.exit(3)"]], log=zeilen.append)
    with pytest.raises(RuntimeError, match="uv wurde nicht gefunden"):
        nightcut.ausfuehren(tmp_path, [["gibt-es-nicht-xyz"]], log=zeilen.append)
