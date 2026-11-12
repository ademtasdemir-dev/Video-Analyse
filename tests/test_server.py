"""Tests der Oberfläche/Schnittstelle: Ergebnis laden, Dateien ausliefern, Speichern mit Ordnerabfrage, Löschen, Sicherheit."""
import json
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

from videoanalyse import server, werkzeug


@pytest.fixture
def srv(tmp_path, monkeypatch):
    daten = tmp_path / "daten"; arbeit = daten / "arbeit"; ziel = tmp_path / "ziel"; ziel.mkdir()
    monkeypatch.setattr(server, "DATEN", daten); monkeypatch.setattr(server, "ARBEIT", arbeit)
    monkeypatch.setattr(server, "CACHE", daten / "modelle"); monkeypatch.setattr(server, "EINST", daten / "einstellungen.json")
    monkeypatch.setenv("VA_DIALOG_TEST", str(ziel))
    o = arbeit / "abc"
    (o / "audio").mkdir(parents=True); (o / "export").mkdir(); (o / "bilder").mkdir()
    werkzeug.wav_speichern(o / "audio" / "stimme.wav", np.zeros(4410, np.float32), 44100)
    (o / "export" / "transkript.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHallo\n", encoding="utf-8")
    (o / "bilder" / "bild_001.jpg").write_bytes(b"\xff\xd8\xff")
    e = {"info": {"title": "Test"}, "kennzahlen": {"dauer": 10}, "analyse_art": "lokal", "zusammenfassung": {"kurz": "Kurz"},
         "kapitel": [{"start": 0, "titel": "A"}, {"start": 20, "titel": "B"}]}
    (o / "ergebnis.json").write_text(json.dumps(e), encoding="utf-8")
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{h.server_address[1]}", ziel, o
    h.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def post(url, daten):
    req = urllib.request.Request(url, json.dumps(daten).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_oberflaeche_und_ergebnis(srv):
    url, _, _ = srv
    s, html = get(url + "/")
    assert s == 200 and b"YVdctuAio" in html and b"Cartesia" in html
    s, d = get(url + "/api/ergebnis?ordner=abc")
    assert json.loads(d)["info"]["title"] == "Test"
    s, v = get(url + "/api/verlauf")
    assert json.loads(v)[0]["ordner"] == "abc"


def test_datei_mit_bereich(srv):
    url, _, _ = srv
    req = urllib.request.Request(url + "/datei?ordner=abc&pfad=audio/stimme.wav", headers={"Range": "bytes=0-3"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206 and r.read() == b"RIFF"


def test_pfad_ausbruch_verboten(srv):
    url, _, _ = srv
    for pfad in ("../../einstellungen.json", "/etc/passwd"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(url + f"/datei?ordner=abc&pfad={pfad}")
        assert e.value.code in (403, 404)
    s, d = post(url + "/api/loeschen", {"ordner": ".."})
    assert s == 403


def test_speichern_einzeln_mp3_und_zip(srv):
    url, ziel, _ = srv
    s, d = post(url + "/api/speichern", {"ordner": "abc", "dateien": ["export/transkript.srt"]})
    assert s == 200 and (ziel / "transkript.srt").exists()
    s, d = post(url + "/api/speichern", {"ordner": "abc", "dateien": ["export/transkript.srt"]})
    assert (ziel / "transkript (2).srt").exists(), "vorhandene Datei darf nicht überschrieben werden"
    s, d = post(url + "/api/speichern", {"ordner": "abc", "dateien": ["audio/stimme.wav"], "format": "mp3"})
    assert s == 200 and (ziel / "stimme.mp3").stat().st_size > 0
    s, d = post(url + "/api/speichern", {"ordner": "abc", "dateien": ["audio/stimme.wav", "bilder/bild_001.jpg"], "zip": True, "praefix": "Paket"})
    with zipfile.ZipFile(ziel / "Paket.zip") as z:
        assert sorted(z.namelist()) == ["bild_001.jpg", "stimme.wav"]


def test_speichern_abgebrochen(srv, monkeypatch):
    url, _, _ = srv
    monkeypatch.setenv("VA_DIALOG_TEST", "")
    s, d = post(url + "/api/speichern", {"ordner": "abc", "dateien": ["export/transkript.srt"]})
    assert d == {"abgebrochen": True}


def test_text_speichern_und_cartesia(srv):
    url, ziel, _ = srv
    s, d = post(url + "/api/cartesia", {"text": "Das NAS hat 12 TB.", "optionen": {"fueller": "aus", "aussprache": "TB = Terabeit"}})
    assert "Naas" in d["text"] and "zwölf" in d["text"]
    s, d = post(url + "/api/text_speichern", {"name": "../cartesia.txt", "inhalt": d["text"]})
    assert (ziel / "cartesia.txt").read_text(encoding="utf-8").startswith("Das Naas")


def test_einstellungen_schluessel_verdeckt(srv):
    url, _, _ = srv
    post(url + "/api/einstellungen", {"gemini_schluessel": "AIzaGEHEIM1234", "gemini_modell": "gemini-2.5-flash"})
    s, d = get(url + "/api/einstellungen")
    d = json.loads(d)
    assert d["gemini_gesetzt"] and "GEHEIM" not in d["gemini_schluessel"] and d["gemini_schluessel"].endswith("1234")
    post(url + "/api/einstellungen", {"gemini_schluessel": d["gemini_schluessel"]})  # verdeckter Wert überschreibt nicht
    assert json.loads(server.EINST.read_text())["gemini_schluessel"] == "AIzaGEHEIM1234"


def test_kapitel_speichern(srv):
    url, _, o = srv
    s, d = post(url + "/api/kapitel", {"ordner": "abc", "kapitel": [{"start": 0, "titel": "Neu"}, {"start": 20, "titel": "B"}, {"start": 40, "titel": "C"}]})
    assert d["hinweise"] == [] and "0:00 Neu" in d["beschreibung"]
    assert json.loads((o / "ergebnis.json").read_text())["kapitel"][0]["titel"] == "Neu"


def test_analyse_fehler_ohne_eingabe_und_loeschen(srv):
    url, _, o = srv
    s, d = post(url + "/api/analyse", {"eingabe": ""})
    assert s == 400
    s, d = post(url + "/api/loeschen", {"ordner": "abc"})
    assert d["geloescht"] and not o.exists()


def test_fremde_webseite_wird_abgelehnt(srv):
    url, _, o = srv
    req = urllib.request.Request(url + "/api/loeschen", json.dumps({"ordner": "abc"}).encode(),
                                 {"Content-Type": "text/plain", "Origin": "https://boese-seite.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403 and o.exists()
    req = urllib.request.Request(url + "/api/verlauf", headers={"Host": "angreifer.example:80"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    req = urllib.request.Request(url + "/api/cartesia", json.dumps({"text": "Hallo."}).encode(), {"Origin": url})
    with urllib.request.urlopen(req) as r:
        assert r.status == 200


def test_cartesia_mit_api_befehl_merkt_stimme(srv):
    url, _, _ = srv
    c, r = post(url + "/api/cartesia", {"text": "Wir haben 20 Plätze.", "optionen": {"modell": "sonic-3", "stimme_id": "abc-1", "aehm_pause": 300}})
    assert c == 200 and "zwanzig" in r["text"] and json.loads(r["api"]["json"])["voice"]["id"] == "abc-1"
    _, e = get(url + "/api/einstellungen")
    e = json.loads(e)
    assert e["cartesia_stimme"] == "abc-1" and e["cartesia_modell"] == "sonic-3"


def test_alles_loeschen(srv):
    url, _, o = srv
    c, r = post(url + "/api/alles_loeschen", {})
    assert c == 200 and r["geloescht"] == 1 and not o.exists()


def test_gemini_test_ohne_und_mit_schluessel(srv, monkeypatch):
    url, _, _ = srv
    c, r = post(url + "/api/gemini_test", {})
    assert c == 400 and "Schlüssel" in r["fehler"]
    server.einstellungen_speichern({"gemini_schluessel": "AQ.test"})
    from videoanalyse import gemini
    monkeypatch.setattr(gemini, "_auswerten_einmal", lambda k, a, m, t: {"ok": True})
    c, r = post(url + "/api/gemini_test", {})
    assert c == 200 and r == {"ok": True, "modell": gemini.STANDARD_MODELL}
