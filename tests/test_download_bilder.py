"""Tests für Download-Optionen (Qualität, nur Video/Ton, Untertitel, Playlist, Warteschlange) und die erweiterten Einzelbilder."""
import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from videoanalyse import analyse, einzelbilder, quelle, server, transkript, werkzeug, zeit

STILL = lambda *a, **k: None


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    """8 Sekunden: 4 s Testbild, dann 4 s rote Fläche (ein klarer Schnitt bei 4 s), 320x180, 10 Bilder pro Sekunde."""
    p = tmp_path_factory.mktemp("video") / "schnitt.mp4"
    werkzeug.lauf(["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=4",
                   "-f", "lavfi", "-i", "color=c=red:size=320x180:rate=10:duration=4",
                   "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264", "-preset", "veryfast",
                   "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


def test_video_format():
    assert "height<=720" in quelle.video_format(None) and "height<=720" in quelle.video_format("720")
    assert "height<=1080" in quelle.video_format("1080") and quelle.video_format("Original") == "bv*+ba/b"
    with pytest.raises(ValueError):
        quelle.video_format("4k")


def test_ist_liste():
    assert zeit.ist_liste("https://www.youtube.com/playlist?list=PLabcDEF123_-x")
    assert not zeit.ist_liste("https://www.youtube.com/watch?v=bK6JBW4hPoU&list=PLabcDEF123")  # einzelnes Video
    assert not zeit.ist_liste("https://youtu.be/bK6JBW4hPoU") and not zeit.ist_liste(r"C:\Videos\list=1.mp4")


def test_untertitel_automatisch_ohne_wiederholung():
    vtt = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
hallo<00:00:00.500><c> und</c><00:00:01.000><c> willkommen</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
hallo und willkommen
 

00:00:02.010 --> 00:00:04.000 align:start position:0%
hallo und willkommen
heute<00:00:02.500><c> geht</c><00:00:03.000><c> es</c><00:00:03.500><c> los</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
heute geht es los
 
"""
    # YouTube schreibt zusätzlich Zeilen, die nur ein Leerzeichen enthalten. Die dürfen keinen Block trennen.
    vtt = vtt.replace("0%\n\nhallo<", "0%\n \nhallo<").replace("0%\nhallo und willkommen\n\n", "0%\nhallo und willkommen\n \n\n")
    assert "\n \n" in vtt
    z = transkript.aus_untertitel(vtt)
    assert [x["text"] for x in z] == ["hallo und willkommen", "heute geht es los"]
    assert z[0]["start"] == 0 and z[0]["ende"] == 2.0 and z[1]["start"] == 2.01 and z[1]["woerter"] == 4


def test_bereich_und_breite():
    assert einzelbilder.bereich_lesen("", None, 60) == (0.0, 60) and einzelbilder.bereich_lesen("0:10", "1:00", 30) == (10.0, 30)
    assert einzelbilder.bereich_lesen("1,5", "20", 60) == (1.5, 20.0)
    for von, bis in (("50", "20"), ("70", ""), ("abc", "")):
        with pytest.raises(ValueError):
            einzelbilder.bereich_lesen(von, bis, 60)
    assert einzelbilder.breite_lesen("") is None and einzelbilder.breite_lesen("original") is None and einzelbilder.breite_lesen("641") == 640
    for wert in ("50", "99999", "breit"):
        with pytest.raises(ValueError):
            einzelbilder.breite_lesen(wert)


def test_zerlegen_bereich_png_breite(video, tmp_path):
    e = einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, 2, log=STILL, von="2", bis="7", bildformat="PNG", breite="160")
    assert e["bilder"] == ["bild_00001_0-00-02.png", "bild_00002_0-00-04.png", "bild_00003_0-00-06.png"]
    assert e["zeiten"] == [2.0, 4.0, 6.0] and e["format"] == "png" and e["breite"] == 160 and e["ganz"] is False
    with Image.open(tmp_path / "einzelbilder" / e["bilder"][0]) as b:
        assert b.size == (160, 90) and b.format == "PNG"
    with Image.open(tmp_path / "einzelbilder" / e["bilder"][1]) as b:  # ab 4 s ist das Bild rot
        r, g, bl = b.convert("RGB").getpixel((80, 45))
        assert r > 200 and g < 60 and bl < 60
    ganz = einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, 4, log=STILL)
    assert ganz["ganz"] is True and ganz["format"] == "jpg" and ganz["anzahl"] == 2
    with pytest.raises(ValueError):
        einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, 1, log=STILL, bildformat="gif")


def test_zerlegen_pro_szene(video, tmp_path):
    e = einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, None, log=STILL, modus="szenen")
    assert e["modus"] == "szenen" and e["abstand"] is None and e["anzahl"] == 2
    assert e["zeiten"][0] == 0 and abs(e["zeiten"][1] - 4.0) < 0.3
    with Image.open(tmp_path / "einzelbilder" / e["bilder"][1]) as b:
        assert b.convert("RGB").getpixel((160, 90))[0] > 200


def test_kontaktbogen(video, tmp_path):
    with pytest.raises(ValueError):
        einzelbilder.kontaktbogen(tmp_path)
    e = einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, 1, log=STILL)
    k = einzelbilder.kontaktbogen(tmp_path, spalten=3, reihen=2, kachel=100)
    assert k["kontaktbogen"] == ["kontaktbogen_01.jpg", "kontaktbogen_02.jpg"] and e["anzahl"] == 8
    with Image.open(tmp_path / "einzelbilder" / "kontaktbogen_01.jpg") as blatt:
        assert blatt.size == (10 + 3 * 110, 10 + 2 * (56 + 24 + 10))
    assert einzelbilder.vorhandene(tmp_path)["kontaktbogen"] == k["kontaktbogen"]


@pytest.fixture
def srv(tmp_path, monkeypatch, video):
    daten = tmp_path / "daten"; arbeit = daten / "arbeit"; ziel = tmp_path / "ziel"; ziel.mkdir()
    monkeypatch.setattr(server, "DATEN", daten); monkeypatch.setattr(server, "ARBEIT", arbeit)
    monkeypatch.setattr(server, "CACHE", daten / "modelle"); monkeypatch.setattr(server, "EINST", daten / "einstellungen.json")
    monkeypatch.setenv("VA_DIALOG_TEST", str(ziel))
    o = arbeit / "abc"; o.mkdir(parents=True)
    shutil.copy2(video, o / "video.mp4")
    (o / "ergebnis.json").write_text(json.dumps({"video_datei": "video.mp4", "info": {"title": "T"}, "kennzahlen": {"dauer": 8}}), encoding="utf-8")
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{h.server_address[1]}", ziel, o
    if server.JOB["thread"]:
        server.JOB["thread"].join(10)
    h.shutdown()


def post(url, daten):
    req = urllib.request.Request(url, json.dumps(daten).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def status(url, bis_fertig=True):
    for _ in range(100):
        with urllib.request.urlopen(url + "/api/status") as r:
            s = json.loads(r.read())
        if not bis_fertig or not s["laeuft"]:
            return s
        time.sleep(0.05)
    raise AssertionError("Auftrag wurde nicht fertig")


def test_einzelbilder_und_kontaktbogen_ueber_schnittstelle(srv):
    url, _, o = srv
    c, r = post(url + "/api/einzelbilder", {"ordner": "abc", "modus": "szenen", "format": "png", "breite": "160"})
    assert c == 200 and r["anzahl"] == 2 and r["format"] == "png" and r["breite"] == 160
    c, r = post(url + "/api/einzelbilder", {"ordner": "abc", "abstand": "2", "von": "0:02", "bis": "0:06"})
    assert c == 200 and r["zeiten"] == [2.0, 4.0] and r["ganz"] is False
    c, r = post(url + "/api/einzelbilder", {"ordner": "abc", "abstand": "2", "von": "0:07", "bis": "0:03"})
    assert c == 400 and "Zeitbereich" in r["fehler"]
    c, r = post(url + "/api/kontaktbogen", {"ordner": "abc"})
    assert c == 200 and r["kontaktbogen"] == ["kontaktbogen_01.jpg"] and (o / "einzelbilder" / "kontaktbogen_01.jpg").is_file()
    assert json.loads((o / "ergebnis.json").read_text(encoding="utf-8"))["einzelbilder"]["kontaktbogen"] == r["kontaktbogen"]


def test_warteschlange_mit_playlist(srv, monkeypatch):
    url, _, _ = srv
    gelaufen = []
    def falsch(eingabe, opt, arbeit, cache, einst, fs):
        gelaufen.append((eingabe, opt.get("qualitaet")))
        if "kaputt" in eingabe:
            fs.fehler = "geht nicht"; fs.fertig = True
            raise RuntimeError("geht nicht")
        fs.fertig = True
    monkeypatch.setattr(analyse, "analysieren", falsch)
    monkeypatch.setattr(quelle, "liste", lambda u, b="": ["https://www.youtube.com/watch?v=AAAAAAAAAAA", "https://www.youtube.com/watch?v=BBBBBBBBBBB"])
    c, r = post(url + "/api/analyse", {"eingaben": ["https://www.youtube.com/playlist?list=PL123", r"C:\x\kaputt.mp4", r"C:\x\gut.mp4"],
                                       "optionen": {"qualitaet": "1080"}})
    assert c == 200 and r["anzahl"] == 3
    s = status(url)
    assert [g[0] for g in gelaufen] == ["https://www.youtube.com/watch?v=AAAAAAAAAAA", "https://www.youtube.com/watch?v=BBBBBBBBBBB",
                                        r"C:\x\kaputt.mp4", r"C:\x\gut.mp4"]
    assert all(g[1] == "1080" for g in gelaufen)
    assert s["schlange"]["gesamt"] == 4 and s["schlange"]["fertig"] == ["AAAAAAAAAAA", "BBBBBBBBBBB", "gut"]
    assert len(s["schlange"]["fehler"]) == 1 and "geht nicht" in s["schlange"]["fehler"][0] and s["ordner"] == "gut"
    c, r = post(url + "/api/analyse", {"eingabe": "x.mp4", "optionen": {"qualitaet": "8k"}})
    assert c == 400 and "Qualität" in r["fehler"]


def test_nur_laden(srv, monkeypatch):
    url, ziel, _ = srv
    aufrufe = []
    def falsch(u, z, art, qualitaet, log, browser):
        aufrufe.append((art, qualitaet, Path(z)))
        log("Download 50 %", prozent=0.5)
        return Path(z) / ("ton.mp3" if art == "audio" else "film.mp4")
    monkeypatch.setattr(quelle, "direkt_laden", falsch)
    c, r = post(url + "/api/laden", {"eingabe": "kein link", "art": "video"})
    assert c == 400
    c, r = post(url + "/api/laden", {"eingabe": "https://youtu.be/bK6JBW4hPoU", "art": "audio", "qualitaet": "1080"})
    assert c == 200 and r == {"ok": True}
    s = status(url)
    assert s["art"] == "laden" and s["schritte"] == ["Ton herunterladen"] and s["fortschritt"]["fertig"] and not s["fortschritt"]["fehler"]
    assert s["meldung"].endswith("ton.mp3") and aufrufe == [("audio", "1080", ziel)]
    monkeypatch.setenv("VA_DIALOG_TEST", "")
    c, r = post(url + "/api/laden", {"eingabe": "https://youtu.be/bK6JBW4hPoU", "art": "video"})
    assert r == {"abgebrochen": True} and len(aufrufe) == 1
    def kaputt(*a, **k):
        raise RuntimeError("YouTube sagt nein")
    monkeypatch.setattr(quelle, "direkt_laden", kaputt); monkeypatch.setenv("VA_DIALOG_TEST", str(ziel))
    post(url + "/api/laden", {"eingabe": "https://youtu.be/bK6JBW4hPoU", "art": "video"})
    s = status(url)
    assert s["fortschritt"]["fehler"] == "YouTube sagt nein" and s["schritte"] == ["Video herunterladen"]


def test_untertitel_von_hand_geschrieben(tmp_path):
    vtt = tmp_path / "u.de.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nErster Satz.\n\n00:00:02.000 --> 00:00:04.000\nZweiter Satz.\n", encoding="utf-8")
    z = transkript.aus_untertitel(vtt.read_text(encoding="utf-8"))
    assert [x["text"] for x in z] == ["Erster Satz.", "Zweiter Satz."] and z[1]["ende"] == 4.0
