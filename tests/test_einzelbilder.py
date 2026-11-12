"""Tests der Bild-Option: Video in Einzelbilder zerlegen (Abstand 1 bis 10 Sekunden, auch 1,5)."""
import json
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image

from videoanalyse import analyse, einzelbilder, server, werkzeug

STILL = lambda *a, **k: None


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    """7 Sekunden Testbild, 320x180, 10 Bilder pro Sekunde, ohne Ton."""
    p = tmp_path_factory.mktemp("video") / "Mein Test.mp4"
    werkzeug.lauf(["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=7",
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


@pytest.mark.parametrize("wert, soll", [("1", 1.0), ("1,5", 1.5), (" 2.5 ", 2.5), (10, 10.0), (1.25, 1.25), ("3,333", 3.33)])
def test_abstand_gueltig(wert, soll):
    assert einzelbilder.abstand_lesen(wert) == soll


@pytest.mark.parametrize("wert", ["0,5", "0", "10,5", "11", "-2", "abc", "", None])
def test_abstand_ungueltig(wert):
    with pytest.raises(ValueError):
        einzelbilder.abstand_lesen(wert)


def test_zeitname():
    assert einzelbilder.zeitname(0) == "0-00-00" and einzelbilder.zeitname(1.5) == "0-00-01.5"
    assert einzelbilder.zeitname(90) == "0-01-30" and einzelbilder.zeitname(3725.25) == "1-02-05.25"
    assert einzelbilder.zeitname(3 * 1.1) == "0-00-03.3"


def test_zerlegen(video, tmp_path):
    e = einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, "1,5", log=STILL)
    assert e["abstand"] == 1.5 and e["anzahl"] == 5 and e["ordner"] == "einzelbilder"
    assert e["bilder"] == ["bild_00001_0-00-00.jpg", "bild_00002_0-00-01.5.jpg", "bild_00003_0-00-03.jpg",
                           "bild_00004_0-00-04.5.jpg", "bild_00005_0-00-06.jpg"]
    assert sorted(p.name for p in (tmp_path / "einzelbilder").iterdir()) == sorted(e["bilder"] + ["liste.json"])
    assert Image.open(tmp_path / "einzelbilder" / e["bilder"][0]).size == (320, 180)
    assert einzelbilder.vorhandene(tmp_path) == e
    neu = einzelbilder.zerlegen(video, werkzeug.dauer(video), tmp_path, 10, log=STILL)  # alte Zerlegung wird ersetzt
    assert neu["anzahl"] == 1 and len(list((tmp_path / "einzelbilder").glob("*.jpg"))) == 1
    (tmp_path / "einzelbilder" / neu["bilder"][0]).unlink()
    assert einzelbilder.vorhandene(tmp_path) is None and not (tmp_path / "einzelbilder_neu").exists()


def test_zerlegen_meldet_fehler(tmp_path):
    kaputt = tmp_path / "kaputt.mp4"; kaputt.write_bytes(b"kein Video")
    with pytest.raises(RuntimeError, match="Einzelbilder"):
        einzelbilder.zerlegen(kaputt, 5, tmp_path, 1, log=STILL)
    assert not (tmp_path / "einzelbilder").exists() and not (tmp_path / "einzelbilder_neu").exists()


def test_analyse_nur_bilder(video, tmp_path):
    """Lokale Datei, schneller Weg: kein Ton, kein Transkript, aber Standbilder und Einzelbilder."""
    fs = analyse.Fortschritt()
    e = analyse.analysieren(str(video), {"nur_bilder": True, "bild_abstand": "2"}, tmp_path / "arbeit", tmp_path / "cache", {}, fs)
    assert fs.fehler is None and fs.status["Einzelbilder"] == "fertig" and fs.status["Transkript erstellen"] == "übersprungen"
    assert all(v in ("fertig", "übersprungen") for v in fs.status.values()), fs.status
    assert e["analyse_art"] == "nur Bilder" and e["zeilen"] == [] and e["audio"] == {}
    assert e["einzelbilder"]["anzahl"] == 4 and e["einzelbilder"]["abstand"] == 2.0
    ordner = tmp_path / "arbeit" / e["ordner"]
    assert all((ordner / "einzelbilder" / b).is_file() for b in e["einzelbilder"]["bilder"])
    assert json.loads((ordner / "ergebnis.json").read_text(encoding="utf-8"))["einzelbilder"]["anzahl"] == 4
    # zweiter Lauf mit anderem Abstand ersetzt die alten Einzelbilder
    fs2 = analyse.Fortschritt()
    e2 = analyse.analysieren(str(video), {"nur_bilder": True, "bild_abstand": 5}, tmp_path / "arbeit", tmp_path / "cache", {}, fs2)
    assert e2["einzelbilder"]["anzahl"] == 2


def test_analyse_falscher_abstand_bricht_sofort_ab(video, tmp_path):
    fs = analyse.Fortschritt()
    with pytest.raises(ValueError):
        analyse.analysieren(str(video), {"einzelbilder": True, "bild_abstand": "20"}, tmp_path / "arbeit", tmp_path / "cache", {}, fs)
    assert "zwischen 1 und 10" in fs.fehler and fs.status["Video holen"] == "offen"


# ---------- Schnittstelle ----------
@pytest.fixture
def srv(video, tmp_path, monkeypatch):
    daten = tmp_path / "daten"; arbeit = daten / "arbeit"; ziel = tmp_path / "ziel"; ziel.mkdir()
    monkeypatch.setattr(server, "DATEN", daten); monkeypatch.setattr(server, "ARBEIT", arbeit)
    monkeypatch.setattr(server, "CACHE", daten / "modelle"); monkeypatch.setattr(server, "EINST", daten / "einstellungen.json")
    monkeypatch.setenv("VA_DIALOG_TEST", str(ziel))
    o = arbeit / "abc"; (o / "export").mkdir(parents=True)
    (o / "video.mp4").write_bytes(video.read_bytes())
    e = {"info": {"title": "Test"}, "kennzahlen": {"dauer": 7}, "analyse_art": "lokal", "video_datei": "video.mp4"}
    (o / "ergebnis.json").write_text(json.dumps(e), encoding="utf-8")
    (o / "export" / "ergebnis.json").write_text(json.dumps(e), encoding="utf-8")
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{h.server_address[1]}", ziel, o
    h.shutdown()


def post(url, daten):
    req = urllib.request.Request(url, json.dumps(daten).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_api_einzelbilder_und_speichern(srv):
    url, ziel, o = srv
    c, r = post(url + "/api/einzelbilder", {"ordner": "abc", "abstand": "1,5"})
    assert c == 200 and r["anzahl"] == 5 and r["abstand"] == 1.5
    for rel in ("ergebnis.json", "export/ergebnis.json"):
        assert json.loads((o / rel).read_text(encoding="utf-8"))["einzelbilder"]["bilder"] == r["bilder"]
    with urllib.request.urlopen(url + "/datei?ordner=abc&pfad=einzelbilder/" + r["bilder"][1]) as antwort:
        assert antwort.status == 200 and antwort.read()[:3] == b"\xff\xd8\xff"
    alle = ["einzelbilder/" + b for b in r["bilder"]]
    c, s = post(url + "/api/speichern", {"ordner": "abc", "dateien": alle, "unterordner": "Einzelbilder abc"})
    assert c == 200 and sorted(p.name for p in (ziel / "Einzelbilder abc").iterdir()) == sorted(r["bilder"])
    c, s = post(url + "/api/speichern", {"ordner": "abc", "dateien": alle, "unterordner": "../Einzelbilder abc"})
    assert (ziel / "Einzelbilder abc (2)").is_dir(), "vorhandener Ordner darf nicht überschrieben werden, kein Ausbruch nach oben"
    c, s = post(url + "/api/speichern", {"ordner": "abc", "dateien": alle, "zip": True, "praefix": "Einzelbilder abc"})
    with zipfile.ZipFile(ziel / "Einzelbilder abc.zip") as z:
        assert sorted(z.namelist()) == sorted(r["bilder"])


def test_api_einzelbilder_fehler(srv):
    url, _, o = srv
    for abstand in ("0,5", "11", "x", None):
        c, r = post(url + "/api/einzelbilder", {"ordner": "abc", "abstand": abstand})
        assert c == 400 and "1" in r["fehler"], r
    assert not (o / "einzelbilder").exists()
    c, r = post(url + "/api/einzelbilder", {"ordner": "gibtsnicht", "abstand": 2})
    assert c == 404
    c, r = post(url + "/api/einzelbilder", {"ordner": "..", "abstand": 2})
    assert c == 403
    c, r = post(url + "/api/analyse", {"eingabe": "C:/x.mp4", "optionen": {"einzelbilder": True, "bild_abstand": "99"}})
    assert c == 400 and "zwischen 1 und 10" in r["fehler"]
