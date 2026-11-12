"""Tests: Transkript bearbeiten, Sprecher umbenennen, Übersetzung, Highlights, DOCX/PDF, Thumbnail, Cartesia senden."""
import json
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image

from videoanalyse import bearbeiten, bericht, cartesia, gemini, server, sprecher


def ergebnis():
    zeilen = [{"start": 0.0, "ende": 4.0, "text": "Hallo und willkommen.", "sprecher": "Sprecher 1", "woerter": 3},
              {"start": 5.0, "ende": 9.0, "text": "Danke für die Einladung.", "sprecher": "Sprecher 2", "woerter": 4},
              {"start": 30.0, "ende": 36.0, "text": "Jetzt zum Tema Backup.", "sprecher": "Sprecher 1", "woerter": 4}]
    stat = sprecher.statistik(zeilen)
    stat[0]["rolle"] = "Moderator"
    kap = [{"nr": 1, "start": 0, "ende": 20, "titel": "Einstieg", "phase": "Einstieg", "inhalt": "", "visuell": "", "text": "", "woerter": 0,
            "wpm": 0, "sprecher": ["Sprecher 1", "Sprecher 2"], "bildart": "Folie", "szenen": 1},
           {"nr": 2, "start": 20, "ende": 40, "titel": "Backup", "phase": "Abschluss", "inhalt": "", "visuell": "", "text": "", "woerter": 0,
            "wpm": 0, "sprecher": ["Sprecher 1"], "bildart": "Folie", "szenen": 1}]
    return {"info": {"title": "Testvideo", "uploader": "Kanal", "webpage_url": "https://example.org/v", "tags": []},
            "kennzahlen": {"dauer": 40}, "analyse_art": "lokal (ohne KI)", "kapitel_quelle": "automatisch", "tempo": "normal",
            "zusammenfassung": {"kurz": "Kurzfassung.", "ausfuehrlich": "", "kernaussagen": ["Erstens.", "Zweitens."]},
            "schlagwoerter": ["Backup"], "zeilen": zeilen, "sprecher": stat, "kapitel": kap,
            "bild": {"bildarten": {"Folie": 40}, "szenen": []},
            "audio": {"Nur Stimme": "audio/stimme.wav", "Nur Sprecher 1": "audio/sprecher_1.wav", "Nur Sprecher 2": "audio/sprecher_2.wav"}}


def test_exporte_schreiben_mit_docx_und_pdf(tmp_path):
    e = ergebnis()
    ex = bericht.exporte_schreiben(e, tmp_path)
    for name in ("transkript.srt", "transkript.txt", "strukturplan.md", "transkript_sprecher_1.txt", "transkript.docx", "transkript.pdf", "ergebnis.json"):
        assert name in ex and (tmp_path / "export" / name).stat().st_size > 0, name
    with zipfile.ZipFile(tmp_path / "export" / "transkript.docx") as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "Testvideo" in xml and "Danke für die Einladung." in xml and "Einstieg" in xml
    assert (tmp_path / "export" / "transkript.pdf").read_bytes().startswith(b"%PDF")
    assert json.loads((tmp_path / "ergebnis.json").read_text(encoding="utf-8"))["exporte"]["transkript.pdf"] == "export/transkript.pdf"


def test_text_korrigieren_und_sprecher_umbenennen(tmp_path):
    e = ergebnis()
    bericht.exporte_schreiben(e, tmp_path)
    e = bearbeiten.anwenden(e, tmp_path, {"2": "  Jetzt zum   Thema Backup und RAID. "}, {"Sprecher 1": "Adem", "Sprecher 2": " Marcel "})
    assert e["_geaendert"] == {"zeilen": 1, "sprecher": 2}
    assert e["zeilen"][2]["text"] == "Jetzt zum Thema Backup und RAID." and e["zeilen"][2]["woerter"] == 6
    assert [s["sprecher"] for s in e["sprecher"]] == ["Adem", "Marcel"] and e["sprecher"][0]["rolle"] == "Moderator"
    assert e["kapitel"][0]["sprecher"] == ["Adem", "Marcel"] and "RAID" in e["kapitel"][1]["text"]
    assert "Nur Adem" in e["audio"] and "Nur Sprecher 1" not in e["audio"] and e["audio"]["Nur Stimme"] == "audio/stimme.wav"
    export = tmp_path / "export"
    assert (export / "transkript_adem.txt").is_file() and not (export / "transkript_sprecher_1.txt").exists()
    assert "[Adem] Hallo" in (export / "transkript.srt").read_text(encoding="utf-8")
    assert "Thema Backup" in (export / "strukturplan.md").read_text(encoding="utf-8")
    gespeichert = json.loads((tmp_path / "ergebnis.json").read_text(encoding="utf-8"))
    assert gespeichert["zeilen"][0]["sprecher"] == "Adem" and "_geaendert" not in gespeichert


def test_bearbeiten_fehler(tmp_path):
    e = ergebnis()
    with pytest.raises(ValueError):
        bearbeiten.anwenden(e, tmp_path, {"99": "gibt es nicht"})
    with pytest.raises(ValueError):
        bearbeiten.anwenden(e, tmp_path, None, {"Sprecher 1": "Sprecher 2"})
    e = bearbeiten.anwenden(e, tmp_path, {"0": "   "}, {"Unbekannt": "X", "Sprecher 1": "Sprecher 1"})
    assert e["_geaendert"] == {"zeilen": 0, "sprecher": 0} and e["zeilen"][0]["text"] == "Hallo und willkommen."


def test_uebersetzen_in_bloecken_und_speichern(tmp_path, monkeypatch):
    e = ergebnis()
    anfragen = []

    def falsch(schluessel, anfrage, modell, timeout):
        text = anfrage["contents"][0]["parts"][1]["text"]
        anfragen.append(text)
        return {"zeilen": [{"nr": int(z.split(":")[0]), "text": "EN " + z.split(": ", 1)[1]} for z in text.splitlines()]}

    monkeypatch.setattr(gemini, "_auswerten_einmal", falsch)
    texte = gemini.uebersetzen("k", e["zeilen"], "Englisch", block=2)
    assert len(anfragen) == 2 and texte[2] == "EN Jetzt zum Tema Backup."
    e = bearbeiten.uebersetzung_speichern(e, tmp_path, "en", texte)
    srt = (tmp_path / "export" / "uebersetzung_en.srt").read_text(encoding="utf-8")
    assert "EN Hallo und willkommen." in srt and "00:00:30,000" in srt and "[Sprecher" not in srt
    assert e["exporte"]["uebersetzung_en.txt"] == "export/uebersetzung_en.txt" and e["zeilen"][0]["text"] == "Hallo und willkommen."
    monkeypatch.setattr(gemini, "_auswerten_einmal", lambda *a: {"zeilen": [{"nr": 0, "text": "nur eine"}]})
    with pytest.raises(RuntimeError):
        gemini.uebersetzen("k", e["zeilen"], "Englisch")
    with pytest.raises(ValueError):
        bearbeiten.uebersetzung_speichern(e, tmp_path, "en", ["zu wenig"])


def test_highlights_werden_geprueft(monkeypatch):
    antwort = {"highlights": [{"start": 30, "ende": 99, "titel": "Backup", "grund": "klar"}, {"start": "x", "ende": 5},
                              {"start": 0, "ende": 1, "titel": "zu kurz"}, {"start": 5, "ende": 20, "titel": "Dank"}]}
    monkeypatch.setattr(gemini, "_auswerten_einmal", lambda *a: antwort)
    h = gemini.highlights("k", ergebnis()["zeilen"], 40.0)
    assert [(x["start"], x["ende"], x["titel"]) for x in h] == [(5.0, 20.0, "Dank"), (30.0, 40.0, "Backup")]


def test_thumbnail_quer_und_hoch(tmp_path):
    (tmp_path / "bilder").mkdir()
    Image.new("RGB", (640, 360), "red").save(tmp_path / "bilder" / "quer.jpg")
    Image.new("RGB", (360, 640), "blue").save(tmp_path / "bilder" / "hoch.png")
    for name in ("quer.jpg", "hoch.png"):
        assert bearbeiten.thumbnail(tmp_path / "bilder" / name, tmp_path) == "export/thumbnail.jpg"
        with Image.open(tmp_path / "export" / "thumbnail.jpg") as im:
            assert im.size == (1280, 720) and im.format == "JPEG"
    (tmp_path / "bilder" / "text.txt").write_text("x")
    with pytest.raises(ValueError):
        bearbeiten.thumbnail(tmp_path / "bilder" / "text.txt", tmp_path)


def test_cartesia_senden(monkeypatch):
    anfrage = cartesia.api_anfrage("Hallo.", "sonic-3", "abc-1")["json"]
    gesehen = {}

    class Antwort:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"RIFF" + b"\0" * 400

    def oeffnen(req, timeout=0):
        gesehen["kopf"] = dict(req.header_items()); gesehen["body"] = json.loads(req.data)
        return Antwort()

    monkeypatch.setattr(urllib.request, "urlopen", oeffnen)
    assert cartesia.senden("sk-test", anfrage).startswith(b"RIFF")
    assert gesehen["kopf"]["Authorization"] == "Bearer sk-test" and gesehen["body"]["transcript"] == "Hallo."
    with pytest.raises(RuntimeError, match="Stimmen-ID"):
        cartesia.senden("sk-test", cartesia.api_anfrage("Hallo.")["json"])
    with pytest.raises(RuntimeError, match="lesbar"):
        cartesia.senden("sk-test", "kein json")


@pytest.fixture
def srv(tmp_path, monkeypatch):
    daten = tmp_path / "daten"; arbeit = daten / "arbeit"; o = arbeit / "abc"; (o / "bilder").mkdir(parents=True)
    monkeypatch.setattr(server, "DATEN", daten); monkeypatch.setattr(server, "ARBEIT", arbeit)
    monkeypatch.setattr(server, "EINST", daten / "einstellungen.json")
    bericht.exporte_schreiben(ergebnis(), o)
    Image.new("RGB", (640, 360), "green").save(o / "bilder" / "bild_001.jpg")
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{h.server_address[1]}", o
    h.shutdown()


def post(url, daten):
    req = urllib.request.Request(url, json.dumps(daten).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_schnittstelle_transkript_thumbnail_und_schluessel(srv, monkeypatch):
    url, o = srv
    c, r = post(url + "/api/transkript", {"ordner": "abc", "texte": {"0": "Hallo zusammen."}, "namen": {"Sprecher 2": "Gast"}})
    assert c == 200 and r["zeilen"][0]["text"] == "Hallo zusammen." and {s["sprecher"] for s in r["sprecher"]} == {"Gast", "Sprecher 1"}
    c, r = post(url + "/api/transkript", {"ordner": "abc", "namen": {"Sprecher 1": "Gast"}})
    assert c == 400 and "denselben Namen" in r["fehler"]
    c, r = post(url + "/api/thumbnail", {"ordner": "abc", "bild": "bilder/bild_001.jpg"})
    assert c == 200 and (o / "export" / "thumbnail.jpg").is_file()
    assert json.loads((o / "ergebnis.json").read_text(encoding="utf-8"))["thumbnail"] == "export/thumbnail.jpg"
    c, r = post(url + "/api/thumbnail", {"ordner": "abc", "bild": "../../einstellungen.json"})
    assert c == 403
    c, r = post(url + "/api/uebersetzen", {"ordner": "abc", "sprache": "en"})
    assert c == 400 and "Gemini-Schlüssel" in r["fehler"]
    c, r = post(url + "/api/cartesia_senden", {"anfrage": "{}"})
    assert c == 400 and "Cartesia-Schlüssel" in r["fehler"]
    post(url + "/api/einstellungen", {"gemini_schluessel": "AQ.geheim1234", "cartesia_schluessel": "sk_car_GEHEIM9876"})
    with urllib.request.urlopen(url + "/api/einstellungen") as antwort:
        e = json.loads(antwort.read())
    assert e["cartesia_gesetzt"] and e["cartesia_schluessel"].endswith("9876") and "GEHEIM" not in json.dumps(e)
    c, r = post(url + "/api/uebersetzen", {"ordner": "abc", "sprache": "xx"})
    assert c == 400
    monkeypatch.setattr(gemini, "_auswerten_einmal",
                        lambda *a: {"zeilen": [{"nr": i, "text": f"line {i}"} for i in range(3)], "highlights": [{"start": 0, "ende": 20, "titel": "A"}]})
    c, r = post(url + "/api/uebersetzen", {"ordner": "abc", "sprache": "en"})
    assert c == 200 and r["uebersetzungen"]["en"][2] == "line 2" and (o / "export" / "uebersetzung_en.srt").is_file()
    c, r = post(url + "/api/highlights", {"ordner": "abc"})
    assert c == 200 and r["highlights"][0]["titel"] == "A"
