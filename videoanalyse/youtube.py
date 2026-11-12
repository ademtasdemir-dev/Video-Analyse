"""Video direkt auf YouTube hochladen (offizielle YouTube-Schnittstelle, Anmeldung mit dem eigenen Google-Konto).

Gebraucht wird einmalig eine eigene Zugangsdatei (client_secret.json, Typ „Desktop-App“) aus der Google Cloud Console.
Sie und die Anmeldung liegen nur lokal im Datenordner. Hochgeladen wird nur auf ausdrücklichen Klick."""
import json
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BEREICH = "https://www.googleapis.com/auth/youtube.upload"
ANMELDE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
BILD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?uploadType=media&videoId="
SICHTBARKEIT = {"privat": "private", "nicht gelistet": "unlisted", "öffentlich": "public"}
BLOCK = 8 * 1024 * 1024
ZUGANG, TOKEN = "youtube_zugang.json", "youtube_token.json"


def _zugang(daten: Path) -> dict:
    try:
        z = json.loads((daten / ZUGANG).read_text(encoding="utf-8"))
        return {"client_id": z["client_id"], "client_secret": z["client_secret"]}
    except Exception:
        raise RuntimeError("Der YouTube-Zugang ist noch nicht eingerichtet (Verlauf & Einstellungen).") from None


def status(daten: Path) -> dict:
    zugang = (daten / ZUGANG).is_file()
    return {"zugang": zugang, "angemeldet": zugang and (daten / TOKEN).is_file()}


def zugang_einrichten(quelle: Path, daten: Path) -> dict:
    """Übernimmt die Zugangsdatei aus der Google Cloud Console. Liegt daneben eine passende token.json
    (z. B. vom „Automatischen YouTube-Upload“), wird die Anmeldung gleich mit übernommen."""
    try:
        roh = json.loads(quelle.read_text(encoding="utf-8"))
        z = roh.get("installed") or roh.get("web") or roh
        zugang = {"client_id": z["client_id"], "client_secret": z["client_secret"]}
    except Exception:
        raise ValueError("Das ist keine Zugangsdatei von Google (client_secret.json).") from None
    daten.mkdir(parents=True, exist_ok=True)
    (daten / ZUGANG).write_text(json.dumps(zugang), encoding="utf-8")
    (daten / TOKEN).unlink(missing_ok=True)
    try:
        t = json.loads((quelle.parent / "token.json").read_text(encoding="utf-8"))
        if t.get("refresh_token") and t.get("client_id") == zugang["client_id"] and BEREICH in (t.get("scopes") or []):
            (daten / TOKEN).write_text(json.dumps({"refresh_token": t["refresh_token"]}), encoding="utf-8")
    except Exception:
        pass
    return status(daten)


def abmelden(daten: Path) -> dict:
    (daten / TOKEN).unlink(missing_ok=True)
    return status(daten)


def _formular(url: str, felder: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(felder).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            f = json.loads(e.read())
            text = f.get("error_description") or f.get("error") or str(e)
        except Exception:
            text = str(e)
        if "invalid_grant" in str(text) or "expired" in str(text).lower() or "revoked" in str(text).lower():
            raise RuntimeError("Die YouTube-Anmeldung ist abgelaufen. Bitte neu anmelden (Verlauf & Einstellungen).") from e
        raise RuntimeError(f"Google hat die Anmeldung abgelehnt: {text}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Google ist nicht erreichbar: {e.reason}") from e


def anmelden(daten: Path, oeffnen=webbrowser.open, warten: int = 240) -> dict:
    """Öffnet die Google-Anmeldung im Browser und wartet auf die Rückmeldung an diesen PC (127.0.0.1)."""
    zugang = _zugang(daten)
    pruef, erhalten = secrets.token_urlsafe(16), {}

    class Rueckruf(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}
            if q.get("state") == pruef and ("code" in q or "error" in q):
                erhalten.update(q)
            text = ("Anmeldung erledigt. Dieses Fenster kann geschlossen werden." if "code" in erhalten
                    else "Anmeldung abgebrochen. Dieses Fenster kann geschlossen werden.")
            seite = f"<!doctype html><meta charset=utf-8><title>YVdctuAio</title><body style='font:18px system-ui;background:#0d1114;color:#e4ebef;padding:40px'>{text}".encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(seite))); self.end_headers(); self.wfile.write(seite)

    srv = HTTPServer(("127.0.0.1", 0), Rueckruf)
    srv.timeout = 1
    ziel = f"http://127.0.0.1:{srv.server_address[1]}"
    oeffnen(ANMELDE_URL + "?" + urllib.parse.urlencode({
        "client_id": zugang["client_id"], "redirect_uri": ziel, "response_type": "code", "scope": BEREICH,
        "access_type": "offline", "prompt": "consent", "state": pruef}))
    try:
        for _ in range(warten):
            srv.handle_request()
            if erhalten:
                break
    finally:
        srv.server_close()
    if "code" not in erhalten:
        raise RuntimeError("Die Anmeldung wurde abgebrochen oder hat zu lange gedauert.")
    t = _formular(TOKEN_URL, {"code": erhalten["code"], "client_id": zugang["client_id"], "client_secret": zugang["client_secret"],
                              "redirect_uri": ziel, "grant_type": "authorization_code"})
    if not t.get("refresh_token"):
        raise RuntimeError("Google hat keine dauerhafte Anmeldung geliefert. Bitte noch einmal anmelden.")
    (daten / TOKEN).write_text(json.dumps({"refresh_token": t["refresh_token"]}), encoding="utf-8")
    return status(daten)


def zugriff(daten: Path) -> str:
    """Frischer Zugriffsschlüssel für die nächste Stunde."""
    zugang = _zugang(daten)
    try:
        dauerhaft = json.loads((daten / TOKEN).read_text(encoding="utf-8"))["refresh_token"]
    except Exception:
        raise RuntimeError("Bitte zuerst bei YouTube anmelden (Verlauf & Einstellungen).") from None
    return _formular(TOKEN_URL, {"client_id": zugang["client_id"], "client_secret": zugang["client_secret"],
                                 "refresh_token": dauerhaft, "grant_type": "refresh_token"})["access_token"]


def _fehlertext(e: urllib.error.HTTPError) -> str:
    try:
        f = json.loads(e.read())["error"]
        grund = (f.get("errors") or [{}])[0].get("reason", "")
        if grund in ("quotaExceeded", "uploadLimitExceeded"):
            return "Das Tageslimit für YouTube-Uploads ist erreicht. Morgen erneut versuchen."
        if grund == "youtubeSignupRequired":
            return "Dieses Google-Konto hat noch keinen YouTube-Kanal."
        return f"YouTube-Fehler {e.code}: {f.get('message') or grund}"
    except Exception:
        return f"YouTube-Fehler {e.code}"


def hochladen(daten: Path, video: Path, titel: str, beschreibung: str = "", tags: list[str] | None = None,
              sichtbarkeit: str = "privat", thumbnail: Path | None = None, fuer_kinder: bool = False, log=print) -> dict:
    """Lädt das Video in Blöcken hoch (bricht die Verbindung ab, geht nichts doppelt hoch) und setzt danach das Vorschaubild."""
    if not video.is_file():
        raise RuntimeError("Die Videodatei fehlt.")
    titel = " ".join(str(titel).split())[:100]
    if not titel:
        raise ValueError("Bitte einen Titel eintragen.")
    if sichtbarkeit not in SICHTBARKEIT:
        raise ValueError("Sichtbarkeit muss privat, nicht gelistet oder öffentlich sein.")
    schluessel = zugriff(daten)
    kopf = {"Authorization": f"Bearer {schluessel}"}
    groesse = video.stat().st_size
    angaben = {"snippet": {"title": titel, "description": str(beschreibung)[:4900], "tags": [t.strip() for t in (tags or []) if t.strip()][:30],
                           "categoryId": "22"},
               "status": {"privacyStatus": SICHTBARKEIT[sichtbarkeit], "selfDeclaredMadeForKids": bool(fuer_kinder)}}
    req = urllib.request.Request(UPLOAD_URL, data=json.dumps(angaben).encode(), method="POST",
                                 headers={**kopf, "Content-Type": "application/json; charset=UTF-8",
                                          "X-Upload-Content-Length": str(groesse), "X-Upload-Content-Type": "video/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            sitzung = r.headers["Location"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(_fehlertext(e)) from e
    antwort, gesendet = None, 0
    with open(video, "rb") as f:
        while gesendet < groesse:
            teil = f.read(BLOCK)
            teil_req = urllib.request.Request(sitzung, data=teil, method="PUT", headers={
                **kopf, "Content-Length": str(len(teil)), "Content-Range": f"bytes {gesendet}-{gesendet + len(teil) - 1}/{groesse}"})
            try:
                with urllib.request.urlopen(teil_req, timeout=600) as r:
                    antwort = json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                if e.code != 308:  # 308 heißt bei Google: Block angekommen, weiter mit dem nächsten
                    raise RuntimeError(_fehlertext(e)) from e
            gesendet += len(teil)
            log(f"Upload {gesendet * 100 // groesse} %", prozent=gesendet / groesse)
    if not antwort or not antwort.get("id"):
        raise RuntimeError("YouTube hat den Upload nicht bestätigt.")
    ergebnis = {"id": antwort["id"], "url": f"https://youtu.be/{antwort['id']}", "thumbnail": False}
    if thumbnail and thumbnail.is_file():
        bild = urllib.request.Request(BILD_URL + antwort["id"], data=thumbnail.read_bytes(), method="POST",
                                      headers={**kopf, "Content-Type": "image/jpeg"})
        try:
            with urllib.request.urlopen(bild, timeout=120):
                ergebnis["thumbnail"] = True
        except urllib.error.HTTPError as e:  # z. B. Kanal nicht für eigene Vorschaubilder freigeschaltet: Video ist trotzdem oben
            log("⚠ Vorschaubild nicht gesetzt: " + _fehlertext(e))
    return ergebnis
