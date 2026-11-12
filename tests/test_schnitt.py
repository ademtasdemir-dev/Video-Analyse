"""Tests für den Schnitt: Clips (auch Hochformat), Sprechpausen entfernen, ohne Musik, Lautstärke, Untertitel einbrennen."""
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

from videoanalyse import schnitt, server, werkzeug

ZEILEN = [{"start": 0.5, "ende": 2.0, "text": "Hallo zusammen.", "sprecher": "Sprecher 1", "woerter": 2},
          {"start": 2.2, "ende": 3.0, "text": "Kurze Pause davor.", "sprecher": "Sprecher 1", "woerter": 3},
          {"start": 6.0, "ende": 7.5, "text": "Nach langer Pause.", "sprecher": "Sprecher 2", "woerter": 3}]


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    """8 Sekunden Testbild 320x180 mit Ton (Sinus), 10 Bilder pro Sekunde."""
    p = tmp_path_factory.mktemp("video") / "quelle.mp4"
    werkzeug.lauf(["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=8",
                   "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-c:v", "libx264", "-preset", "veryfast",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    return p


def groesse(datei):
    out = werkzeug.lauf(["-i", str(datei)]).stderr.decode("utf-8", "replace")
    b, h = re.search(r", (\d{2,5})x(\d{2,5})", out).groups()
    return int(b), int(h)


def test_dateiname():
    assert schnitt.dateiname('Kapitel 1: "Start" / Ende?') == "Kapitel 1 Start Ende"
    assert schnitt.dateiname("   ...  ") == "clip" and len(schnitt.dateiname("x" * 200)) == 60


def test_sprechteile_fasst_kurze_pausen_zusammen():
    teile = schnitt.sprechteile(ZEILEN, 8.0, rand=0.1, pause=0.6)
    assert teile == [(0.4, 3.1), (5.9, 7.6)]
    assert schnitt.sprechteile([], 8.0) == []
    assert schnitt.sprechteile([{"start": 7.5, "ende": 9.0}], 8.0, rand=0.5) == [(7.0, 8.0)]  # nie über das Videoende


def test_clip_und_hochformat(video, tmp_path):
    c = schnitt.clip(video, 1, 3, tmp_path / "a.mp4")
    assert abs(werkzeug.dauer(c) - 2.0) < 0.25 and groesse(c) == (320, 180)
    h = schnitt.clip(video, 1, 3, tmp_path / "hoch.mp4", hochformat=True)
    assert groesse(h) == (1080, 1920)
    with pytest.raises(ValueError):
        schnitt.clip(video, 3, 3, tmp_path / "leer.mp4")


def test_clips_benennt_und_ueberschreibt_nicht(video, tmp_path):
    teile = [{"start": 0, "ende": 1, "titel": "Einstieg: Los"}, {"start": 1, "ende": 2, "titel": ""}]
    namen = [p.name for p in schnitt.clips(video, teile, tmp_path)]
    assert namen == ["01 Einstieg Los.mp4", "02 Clip.mp4"]
    assert schnitt.clips(video, teile[:1], tmp_path)[0].name == "01 Einstieg Los (2).mp4"
    with pytest.raises(ValueError):
        schnitt.clips(video, [], tmp_path)


def test_ohne_stille(video, tmp_path):
    r = schnitt.ohne_stille(video, ZEILEN, 8.0, tmp_path / "kurz.mp4", rand=0.1, pause=0.6)
    assert r["nachher"] == 4.4 and r["gespart"] == 3.6
    assert abs(werkzeug.dauer(r["datei"]) - 4.4) < 0.4
    assert not (tmp_path / "kurz.filter.txt").exists()
    with pytest.raises(ValueError):
        schnitt.ohne_stille(video, [], 8.0, tmp_path / "nix.mp4")


def test_ohne_musik_lautstaerke_untertitel(video, tmp_path):
    stimme = werkzeug.wav_speichern(tmp_path / "stimme.wav", np.zeros((2, 44100 * 8), np.float32), 44100)
    assert abs(werkzeug.dauer(schnitt.ohne_musik(video, stimme, tmp_path / "om.mp4")) - 8) < 0.3
    with pytest.raises(ValueError):
        schnitt.ohne_musik(video, tmp_path / "fehlt.wav", tmp_path / "x.mp4")
    assert abs(werkzeug.dauer(schnitt.lautstaerke(video, tmp_path / "laut.mp4")) - 8) < 0.3
    u = schnitt.untertitel(video, ZEILEN, tmp_path / "ut.mp4")
    assert abs(werkzeug.dauer(u) - 8) < 0.3 and not (tmp_path / "untertitel_einbrennen.srt").exists()
    with pytest.raises(ValueError):
        schnitt.untertitel(video, [], tmp_path / "leer.mp4")


def test_schnitt_ueber_schnittstelle(video, tmp_path, monkeypatch):
    daten = tmp_path / "daten"; arbeit = daten / "arbeit"; o = arbeit / "abc"; o.mkdir(parents=True)
    monkeypatch.setattr(server, "DATEN", daten); monkeypatch.setattr(server, "ARBEIT", arbeit)
    (o / "video.mp4").write_bytes(video.read_bytes())
    (o / "ergebnis.json").write_text(json.dumps({"video_datei": "video.mp4", "zeilen": ZEILEN}), encoding="utf-8")
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{h.server_address[1]}/api/schnitt"

    def post(daten):
        req = urllib.request.Request(url, json.dumps(daten).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        assert post({"ordner": "abc"}) == (200, {"dateien": [], "meldung": ""})
        c, r = post({"ordner": "abc", "art": "clips", "abschnitte": [{"start": "0:01", "ende": "0:02,5", "titel": "Mitte"}]})
        assert c == 200 and r["dateien"] == ["schnitt/01 Mitte.mp4"] and "1 Clip" in r["meldung"]
        c, r = post({"ordner": "abc", "art": "stille"})
        assert c == 200 and "schnitt/ohne Sprechpausen.mp4" in r["dateien"] and "gespart" in r["meldung"]
        c, r = post({"ordner": "abc", "art": "ohne_musik"})
        assert c == 400 and "trennen" in r["fehler"]
        c, r = post({"ordner": "abc", "art": "quatsch"})
        assert c == 400
        c, r = post({"ordner": "..", "art": "stille"})
        assert c == 403
    finally:
        h.shutdown()
