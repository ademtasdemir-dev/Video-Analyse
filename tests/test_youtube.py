"""Tests für den YouTube-Upload. Google wird nachgestellt: Es geht nichts ins Internet."""
import io
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from videoanalyse import server, youtube


class Antwort:
    def __init__(self, daten=b"{}", kopf=None):
        self.daten, self.headers = daten, kopf or {}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.daten


def zugang(tmp_path, mit_token=True, client="abc.apps"):
    q = tmp_path / "quelle"; q.mkdir(exist_ok=True)
    (q / "client_secret.json").write_text(json.dumps({"installed": {"client_id": client, "client_secret": "geheim"}}))
    if mit_token:
        (q / "token.json").write_text(json.dumps({"refresh_token": "dauer-1", "client_id": "abc.apps", "scopes": [youtube.BEREICH]}))
    return q / "client_secret.json"


def test_zugang_einrichten_uebernimmt_passende_anmeldung(tmp_path):
    daten = tmp_path / "daten"
    assert youtube.status(daten) == {"zugang": False, "angemeldet": False}
    assert youtube.zugang_einrichten(zugang(tmp_path), daten) == {"zugang": True, "angemeldet": True}
    assert json.loads((daten / youtube.TOKEN).read_text()) == {"refresh_token": "dauer-1"}
    assert youtube.zugang_einrichten(zugang(tmp_path, client="anderer.apps"), daten) == {"zugang": True, "angemeldet": False}  # Token passt nicht
    assert youtube.abmelden(daten)["angemeldet"] is False
    (tmp_path / "falsch.json").write_text("{}")
    with pytest.raises(ValueError):
        youtube.zugang_einrichten(tmp_path / "falsch.json", daten)
    with pytest.raises(RuntimeError, match="eingerichtet"):
        youtube.zugriff(tmp_path / "leer")


def test_anmelden_ueber_rueckruf(tmp_path, monkeypatch):
    daten = tmp_path / "daten"
    youtube.zugang_einrichten(zugang(tmp_path, mit_token=False), daten)
    echt = urllib.request.urlopen

    def browser(url):  # spielt den Browser: Google leitet mit code und state zurück an 127.0.0.1
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        assert q["scope"] == youtube.BEREICH and q["access_type"] == "offline" and q["redirect_uri"].startswith("http://127.0.0.1:")
        threading.Thread(target=lambda: echt(q["redirect_uri"] + "/?" + urllib.parse.urlencode({"code": "c-1", "state": q["state"]})).read(),
                         daemon=True).start()

    def google(req, timeout=0):
        felder = dict(urllib.parse.parse_qsl(req.data.decode()))
        assert felder["code"] == "c-1" and felder["grant_type"] == "authorization_code"
        return Antwort(json.dumps({"access_token": "kurz", "refresh_token": "dauer-neu"}).encode())

    monkeypatch.setattr(youtube.urllib.request, "urlopen", google)
    assert youtube.anmelden(daten, oeffnen=browser, warten=10) == {"zugang": True, "angemeldet": True}
    assert json.loads((daten / youtube.TOKEN).read_text())["refresh_token"] == "dauer-neu"
    with pytest.raises(RuntimeError, match="abgebrochen"):
        youtube.anmelden(daten, oeffnen=lambda url: None, warten=1)


def test_hochladen_in_bloecken_mit_vorschaubild(tmp_path, monkeypatch):
    daten = tmp_path / "daten"
    youtube.zugang_einrichten(zugang(tmp_path), daten)
    video = tmp_path / "v.mp4"; video.write_bytes(b"x" * 25)
    bild = tmp_path / "t.jpg"; bild.write_bytes(b"\xff\xd8bild")
    monkeypatch.setattr(youtube, "BLOCK", 10)
    gesehen, fortschritt = [], []

    def google(req, timeout=0):
        url, kopf = req.full_url, dict(req.header_items())
        if url == youtube.TOKEN_URL:
            assert dict(urllib.parse.parse_qsl(req.data.decode()))["refresh_token"] == "dauer-1"
            return Antwort(b'{"access_token": "kurz-1"}')
        assert kopf["Authorization"] == "Bearer kurz-1"
        if url == youtube.UPLOAD_URL:
            gesehen.append(("start", json.loads(req.data), kopf["X-upload-content-length"]))
            return Antwort(kopf={"Location": "https://upload.example/sitzung"})
        if url == "https://upload.example/sitzung":
            gesehen.append(("teil", kopf["Content-range"], len(req.data)))
            if kopf["Content-range"].startswith("bytes 20-"):
                return Antwort(b'{"id": "VIDEO123abc"}')
            raise urllib.error.HTTPError(url, 308, "Resume Incomplete", {}, io.BytesIO(b""))
        gesehen.append(("bild", url, req.data))
        return Antwort()

    monkeypatch.setattr(youtube.urllib.request, "urlopen", google)
    r = youtube.hochladen(daten, video, "  Mein   Titel ", "Text", ["a", " b ", ""], "nicht gelistet", bild,
                          log=lambda t, prozent=None: fortschritt.append(prozent))
    assert r == {"id": "VIDEO123abc", "url": "https://youtu.be/VIDEO123abc", "thumbnail": True}
    start = gesehen[0]
    assert start[1]["snippet"]["title"] == "Mein Titel" and start[1]["snippet"]["tags"] == ["a", "b"] and start[2] == "25"
    assert start[1]["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}
    assert [g[1] for g in gesehen if g[0] == "teil"] == ["bytes 0-9/25", "bytes 10-19/25", "bytes 20-24/25"]
    assert gesehen[-1] == ("bild", youtube.BILD_URL + "VIDEO123abc", b"\xff\xd8bild") and fortschritt[-1] == 1.0
    with pytest.raises(ValueError):
        youtube.hochladen(daten, video, "Titel", sichtbarkeit="geheim")
    with pytest.raises(ValueError):
        youtube.hochladen(daten, video, "   ")


def test_fehler_von_google_werden_erklaert(tmp_path, monkeypatch):
    daten = tmp_path / "daten"
    youtube.zugang_einrichten(zugang(tmp_path), daten)
    video = tmp_path / "v.mp4"; video.write_bytes(b"x")

    def abgelaufen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error": "invalid_grant"}'))

    monkeypatch.setattr(youtube.urllib.request, "urlopen", abgelaufen)
    with pytest.raises(RuntimeError, match="abgelaufen"):
        youtube.hochladen(daten, video, "Titel")

    def limit(req, timeout=0):
        if req.full_url == youtube.TOKEN_URL:
            return Antwort(b'{"access_token": "k"}')
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"error": {"message": "x", "errors": [{"reason": "quotaExceeded"}]}}'))

    monkeypatch.setattr(youtube.urllib.request, "urlopen", limit)
    with pytest.raises(RuntimeError, match="Tageslimit"):
        youtube.hochladen(daten, video, "Titel")


def test_schnittstelle(tmp_path, monkeypatch):
    daten = tmp_path / "daten"; arbeit = daten / "arbeit"; o = arbeit / "abc"; o.mkdir(parents=True)
    monkeypatch.setattr(server, "DATEN", daten); monkeypatch.setattr(server, "ARBEIT", arbeit)
    monkeypatch.setitem(server.JOB, "thread", None)
    (o / "video.mp4").write_bytes(b"video"); (o / "ergebnis.json").write_text(json.dumps({"video_datei": "video.mp4"}))
    h = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{h.server_address[1]}"
    echt = urllib.request.urlopen

    def post(pfad, d):
        req = urllib.request.Request(url + pfad, json.dumps(d).encode(), {"Content-Type": "application/json"})
        try:
            with echt(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        assert post("/api/youtube", {}) == (200, {"zugang": False, "angemeldet": False})
        c, r = post("/api/youtube_upload", {"ordner": "abc", "titel": "T"})
        assert c == 400 and "anmelden" in r["fehler"]
        monkeypatch.setenv("VA_DIALOG_TEST", str(zugang(tmp_path)))
        assert post("/api/youtube", {"was": "zugang"}) == (200, {"zugang": True, "angemeldet": True})
        assert post("/api/youtube_upload", {"ordner": "abc", "titel": ""})[0] == 400
        assert post("/api/youtube_upload", {"ordner": "abc", "titel": "T", "sichtbarkeit": "alle"})[0] == 400
        assert post("/api/youtube_upload", {"ordner": "abc", "titel": "T", "datei": "ergebnis.json"})[0] == 404
        assert post("/api/youtube_upload", {"ordner": "abc", "titel": "T", "datei": "../../x.mp4"})[0] == 403
        aufruf = {}
        monkeypatch.setattr(youtube, "hochladen", lambda *a, **k: aufruf.update(a=a) or {"id": "x", "url": "https://youtu.be/x", "thumbnail": False})
        assert post("/api/youtube_upload", {"ordner": "abc", "titel": "Mein Video", "tags": "a, b", "sichtbarkeit": "privat"}) == (200, {"ok": True})
        for _ in range(50):
            with echt(url + "/api/status") as antwort:
                s = json.loads(antwort.read())
            if not s["laeuft"] and s["fortschritt"]["fertig"]:
                break
            time.sleep(0.05)
        assert s["art"] == "upload" and s["meldung"] == "Hochgeladen (privat): https://youtu.be/x"
        assert aufruf["a"][2] == "Mein Video" and aufruf["a"][4] == ["a", " b"] and aufruf["a"][5] == "privat"
        assert post("/api/youtube", {"was": "abmelden"}) == (200, {"zugang": True, "angemeldet": False})
    finally:
        h.shutdown()
