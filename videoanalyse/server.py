"""Lokaler Server für die Oberfläche. Läuft nur auf diesem PC (127.0.0.1), nichts ist von außen erreichbar."""
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import analyse, bearbeiten, bericht, cartesia, einzelbilder, nightcut, quelle, schnitt, werkzeug, youtube, zeit

BASIS = Path(__file__).resolve().parent.parent
UI = BASIS / "ui"
DATEN = Path(os.environ.get("VA_DATEN", BASIS / "daten"))
ARBEIT, CACHE, EINST = DATEN / "arbeit", DATEN / "modelle", DATEN / "einstellungen.json"

JOB = {"fs": None, "thread": None, "ordner": None, "art": "analyse", "schritte": None, "meldung": None, "schlange": None}
EINZEL_SPERRE = threading.Lock()  # immer nur eine Zerlegung in Einzelbilder gleichzeitig
SCHNITT_SPERRE = threading.Lock()  # immer nur ein Schnitt-Auftrag gleichzeitig
GEHEIM = ("gemini", "cartesia")  # <name>_schluessel wird nur verdeckt an die Oberfläche gegeben
VERSION = "1.1.0"  # dieselbe Nummer steht in pyproject.toml und im Setup
FENSTER: dict[str, float] = {}  # offene Programmfenster: Kennung -> letztes Lebenszeichen


def einstellungen() -> dict:
    try:
        return json.loads(EINST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def einstellungen_speichern(neu: dict):
    alt = einstellungen()
    alt.update({k: v for k, v in neu.items() if v is not None})
    DATEN.mkdir(parents=True, exist_ok=True)
    EINST.write_text(json.dumps(alt, ensure_ascii=False, indent=1), encoding="utf-8")


def _dialog(art: str, titel: str) -> str | None:
    """Öffnet einen Windows-Dialog (Ordner wählen / Datei wählen). Für Tests: VA_DIALOG_TEST setzt die Antwort."""
    test = os.environ.get("VA_DIALOG_TEST")
    if test is not None:
        return test or None
    typen = "[('Zugangsdatei','*.json'),('Alle','*.*')]" if art == "json" else "[('Videos','*.mp4 *.mkv *.mov *.webm *.avi *.m4v'),('Alle','*.*')]"
    code = ("import tkinter as tk; from tkinter import filedialog as f; r=tk.Tk(); r.withdraw(); r.attributes('-topmost',1); "
            + ("p=f.askdirectory(title=%r, mustexist=True)" % titel if art == "ordner" else
               "p=f.askopenfilename(title=%r, filetypes=%s)" % (titel, typen))
            + "; print(p or '', end='')")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, creationflags=flags)
    return r.stdout.strip() or None


def _sicher(ordner: str, rel: str = "") -> Path:
    basis = (ARBEIT / ordner).resolve()
    p = (basis / rel).resolve()
    if ARBEIT.resolve() not in basis.parents or (p != basis and basis not in p.parents):
        raise PermissionError("Ungültiger Pfad")
    return p


def _frei(ziel: Path) -> Path:
    if not ziel.exists():
        return ziel
    for i in range(2, 1000):
        k = ziel.with_name(f"{ziel.stem} ({i}){ziel.suffix}")
        if not k.exists():
            return k
    return ziel


def ergebnis_laden(ordner: str) -> dict:
    return json.loads(_sicher(ordner, "ergebnis.json").read_text(encoding="utf-8"))


def verlauf() -> list[dict]:
    out = []
    for p in sorted(ARBEIT.glob("*/ergebnis.json"), key=lambda x: -x.stat().st_mtime) if ARBEIT.exists() else []:
        try:
            e = json.loads(p.read_text(encoding="utf-8"))
            groesse = sum(f.stat().st_size for f in p.parent.rglob("*") if f.is_file())
            out.append({"ordner": p.parent.name, "titel": e["info"].get("title"), "dauer": e["kennzahlen"]["dauer"],
                        "art": e.get("analyse_art"), "mb": round(groesse / 1e6, 1)})
        except Exception:
            continue
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, daten, code=200):
        b = json.dumps(daten, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _fehler(self, text, code=400):
        self._json({"fehler": text}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _datei(self, p: Path):
        if not p.is_file():
            return self._fehler("Datei nicht gefunden", 404)
        groesse = p.stat().st_size
        typ = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        bereich = self.headers.get("Range")
        start, ende = 0, groesse - 1
        if bereich and bereich.startswith("bytes="):
            a, _, b = bereich[6:].partition("-")
            start = int(a) if a else 0
            ende = int(b) if b else groesse - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{ende}/{groesse}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", typ + ("; charset=utf-8" if typ.startswith("text") else ""))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(ende - start + 1))
        self.end_headers()
        with open(p, "rb") as f:
            f.seek(start)
            rest = ende - start + 1
            while rest > 0:
                stueck = f.read(min(1 << 20, rest))
                if not stueck:
                    break
                try:
                    self.wfile.write(stueck)
                except (ConnectionResetError, BrokenPipeError):
                    return
                rest -= len(stueck)

    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self._eigene_seite():
            return self._fehler("Anfrage abgelehnt.", 403)
        try:
            if u.path in ("/", "/index.html"):
                return self._datei(UI / "index.html")
            if u.path in ("/icon.png", "/favicon.ico"):
                return self._datei(UI / ("icon.png" if u.path == "/icon.png" else "icon.ico"))
            if u.path == "/api/update":
                from . import update
                return self._json(update.pruefen(VERSION))
            if u.path == "/api/status":
                fs = JOB["fs"]
                return self._json({"laeuft": bool(JOB["thread"] and JOB["thread"].is_alive()), "ordner": JOB["ordner"],
                                   "fortschritt": fs.als_dict() if fs else None, "schritte": JOB.get("schritte") or analyse.SCHRITTE,
                                   "art": JOB.get("art") or "analyse", "schlange": JOB.get("schlange"), "meldung": JOB.get("meldung")})
            if u.path == "/api/ergebnis":
                return self._json(ergebnis_laden(q["ordner"]))
            if u.path == "/api/verlauf":
                return self._json(verlauf())
            if u.path == "/api/einstellungen":
                e = einstellungen()
                for name in GEHEIM:  # Schlüssel verlassen den Server nie im Klartext
                    k = e.get(name + "_schluessel", "")
                    e[name + "_schluessel"], e[name + "_gesetzt"] = ("•" * 8 + k[-4:]) if k else "", bool(k)
                return self._json(e)
            if u.path == "/datei":
                return self._datei(_sicher(q["ordner"], q["pfad"]))
            return self._fehler("Unbekannte Adresse", 404)
        except PermissionError as e:
            return self._fehler(str(e), 403)
        except (KeyError, FileNotFoundError) as e:
            return self._fehler(f"Nicht gefunden: {e}", 404)

    def _eigene_seite(self) -> bool:
        """Nur Anfragen von der eigenen Oberfläche annehmen (Schutz gegen fremde Webseiten im Browser)."""
        port = self.server.server_address[1]
        erlaubt = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in erlaubt:
            return False
        herkunft = self.headers.get("Origin")
        return herkunft is None or herkunft.split("://", 1)[-1] in erlaubt

    def do_POST(self):
        u = urlparse(self.path)
        if not self._eigene_seite():
            return self._fehler("Anfrage abgelehnt (nicht von der eigenen Oberfläche).", 403)
        try:
            d = self._body()
            if u.path == "/api/fenster":
                # Jedes offene Programmfenster meldet sich regelmäßig. Ist keins mehr da, beendet sich das Programm (siehe starten).
                if d.get("was") == "zu":
                    FENSTER.pop(str(d.get("id")), None)
                else:
                    FENSTER[str(d.get("id"))] = time.time()
                return self._json({"ok": True})
            if u.path == "/api/analyse":
                if JOB["thread"] and JOB["thread"].is_alive():
                    return self._fehler("Es läuft bereits eine Analyse.", 409)
                # Ein Eintrag ("eingabe") oder mehrere ("eingaben": Links, Dateien, Playlists) – sie laufen nacheinander.
                eingaben = [str(x).strip() for x in (d.get("eingaben") or [d.get("eingabe") or ""]) if str(x).strip()]
                if not eingaben:
                    return self._fehler("Bitte einen YouTube-Link oder eine Videodatei angeben.")
                o = d.get("optionen") or {}
                if (o.get("einzelbilder") or o.get("nur_bilder")) and (o.get("bild_modus") or "abstand") == "abstand":
                    einzelbilder.abstand_lesen(o.get("bild_abstand") or 1)  # falscher Abstand: sofort melden, nicht erst nach Minuten
                quelle.video_format(o.get("qualitaet"))
                fs = analyse.Fortschritt()
                schlange = {"gesamt": len(eingaben), "nr": 0, "fertig": [], "fehler": []}
                JOB.update(fs=fs, ordner=analyse.ordner_name(eingaben[0]), art="analyse", schritte=None, meldung=None, schlange=schlange)
                def lauf():
                    einst = einstellungen()
                    alle = []
                    for x in eingaben:  # Playlists in einzelne Videos auflösen
                        if zeit.ist_liste(x):
                            try:
                                fs.log("Lese die Playlist …")
                                alle += quelle.liste(x, einst.get("browser_cookies", ""))
                            except Exception as ex:
                                schlange["fehler"].append(f"{x}: {ex}")
                        else:
                            alle.append(x)
                    schlange["gesamt"] = len(alle)
                    if not alle:
                        fs.fehler = "; ".join(schlange["fehler"]) or "Nichts zu analysieren."
                        fs.log("✖ " + fs.fehler); fs.fertig = True
                        return
                    for i, x in enumerate(alle):
                        f = fs if i == 0 else analyse.Fortschritt()
                        schlange["nr"] = i + 1
                        JOB.update(fs=f, ordner=analyse.ordner_name(x))
                        try:
                            analyse.analysieren(x, o, ARBEIT, CACHE, einst, f)
                            schlange["fertig"].append(analyse.ordner_name(x))
                        except Exception as ex:
                            schlange["fehler"].append(f"{x}: {ex}")
                JOB["thread"] = threading.Thread(target=lauf, daemon=True); JOB["thread"].start()
                return self._json({"ok": True, "ordner": JOB["ordner"], "anzahl": len(eingaben)})
            if u.path == "/api/laden":
                # Nur herunterladen (Video als .mp4 oder Ton als .mp3), ohne Analyse. Fragt nach dem Zielordner.
                if JOB["thread"] and JOB["thread"].is_alive():
                    return self._fehler("Es läuft bereits eine Analyse oder ein Download.", 409)
                eingabe, art = (d.get("eingabe") or "").strip(), "audio" if d.get("art") == "audio" else "video"
                if not zeit.ist_youtube(eingabe):
                    return self._fehler("Bitte zuerst einen YouTube-Link einfügen.")
                quelle.video_format(d.get("qualitaet"))
                ziel = _dialog("ordner", "Wohin soll die Datei gespeichert werden?")
                if not ziel:
                    return self._json({"abgebrochen": True})
                fs = analyse.Fortschritt()
                schritt = "Ton herunterladen" if art == "audio" else "Video herunterladen"
                fs.status = {schritt: "offen"}
                JOB.update(fs=fs, ordner=None, art="laden", schritte=[schritt], meldung=None, schlange=None)
                def laden():
                    fs.start(schritt)
                    try:
                        p = quelle.direkt_laden(eingabe, Path(ziel), art, d.get("qualitaet"), log=fs.log,
                                                browser=einstellungen().get("browser_cookies", ""))
                        fs.status[schritt] = "fertig"
                        JOB["meldung"] = f"Gespeichert: {p}"
                        fs.log("✔ " + JOB["meldung"])
                    except Exception as ex:
                        fs.fehler = str(ex) or ex.__class__.__name__
                        fs.status[schritt] = "Fehler"
                        fs.log("✖ " + fs.fehler)
                    fs.fertig = True
                JOB["thread"] = threading.Thread(target=laden, daemon=True); JOB["thread"].start()
                return self._json({"ok": True})
            if u.path == "/api/youtube":
                # Zugang einrichten, anmelden, abmelden. "status" zeigt nur den Stand.
                was = d.get("was") or "status"
                if was == "zugang":
                    pfad = _dialog("json", "Zugangsdatei von Google wählen (client_secret.json)")
                    if not pfad:
                        return self._json({**youtube.status(DATEN), "abgebrochen": True})
                    return self._json(youtube.zugang_einrichten(Path(pfad), DATEN))
                try:
                    if was == "anmelden":
                        return self._json(youtube.anmelden(DATEN))
                except RuntimeError as ex:
                    return self._fehler(str(ex), 502)
                if was == "abmelden":
                    return self._json(youtube.abmelden(DATEN))
                return self._json(youtube.status(DATEN))
            if u.path == "/api/nightcut":
                # Startet eine vorhandene nightcut-Installation für eine Aufnahme. "stand" zeigt nur, ob nightcut da ist.
                ein = einstellungen()
                was = d.get("was") or "stand"
                if was == "ordner":
                    pfad = _dialog("ordner", "nightcut-Ordner wählen")
                    if pfad:
                        einstellungen_speichern({"nightcut_ordner": pfad}); ein = einstellungen()
                    return self._json(nightcut.stand(ein))
                if was == "aufnahme":
                    return self._json({"pfad": _dialog("datei", "Aufnahme für nightcut wählen")})
                if was != "start":
                    return self._json(nightcut.stand(ein))
                if JOB["thread"] and JOB["thread"].is_alive():
                    return self._fehler("Es läuft bereits etwas. Bitte warten, bis es fertig ist.", 409)
                o = nightcut.ordner(ein)
                if not nightcut.stand(ein)["vorhanden"]:
                    return self._fehler("nightcut wurde nicht gefunden. Bitte den nightcut-Ordner wählen.")
                aufnahme, profil = Path(str(d.get("aufnahme") or "").strip().strip('"')), str(d.get("profil") or "")
                schritte = nightcut.befehle(o, aufnahme, profil, bool(d.get("trennen")), d.get("modus") or "", bool(d.get("auffuellen")))
                fs = analyse.Fortschritt()
                namen = (["Stimmen vom Spielsound trennen"] if len(schritte) > 1 else []) + ["nightcut schneidet"]
                fs.status = {n: "offen" for n in namen}
                JOB.update(fs=fs, ordner=None, art="nightcut", schritte=namen, meldung=None, schlange=None)
                def lauf():
                    try:
                        for name, befehl in zip(namen, schritte):
                            fs.start(name)
                            nightcut.ausfuehren(o, [befehl], log=fs.log)
                        fs.status[namen[-1]] = "fertig"
                        ziel = nightcut.ergebnis_ordner(o, aufnahme, profil)
                        JOB["meldung"] = f"nightcut ist fertig: {ziel}"
                        fs.log("✔ " + JOB["meldung"])
                        if sys.platform == "win32" and ziel.is_dir():
                            os.startfile(ziel)  # noqa
                    except Exception as ex:
                        fs.fehler = str(ex) or ex.__class__.__name__
                        if fs.schritt:
                            fs.status[fs.schritt] = "Fehler"
                        fs.log("✖ " + fs.fehler)
                    fs.fertig = True
                JOB["thread"] = threading.Thread(target=lauf, daemon=True); JOB["thread"].start()
                return self._json({"ok": True})
            if u.path == "/api/youtube_upload":
                # Lädt das Video einer Analyse (oder ein geschnittenes Video daraus) wirklich auf YouTube hoch.
                if JOB["thread"] and JOB["thread"].is_alive():
                    return self._fehler("Es läuft bereits eine Analyse, ein Download oder ein Upload.", 409)
                e = ergebnis_laden(d["ordner"])
                video = _sicher(d["ordner"], d.get("datei") or e["video_datei"])
                if not video.is_file() or video.suffix.lower() not in (".mp4", ".mkv", ".webm", ".mov"):
                    return self._fehler("Diese Videodatei gibt es in der Analyse nicht.", 404)
                titel, sichtbar = " ".join(str(d.get("titel") or "").split()), d.get("sichtbarkeit") or "privat"
                if not titel:
                    return self._fehler("Bitte einen Titel eintragen.")
                if sichtbar not in youtube.SICHTBARKEIT:
                    return self._fehler("Sichtbarkeit muss privat, nicht gelistet oder öffentlich sein.")
                if not youtube.status(DATEN)["angemeldet"]:
                    return self._fehler("Bitte zuerst bei YouTube anmelden (Verlauf & Einstellungen).")
                bild = _sicher(d["ordner"], e["thumbnail"]) if d.get("thumbnail") and e.get("thumbnail") else None
                fs = analyse.Fortschritt()
                schritt = "Auf YouTube hochladen"
                fs.status = {schritt: "offen"}
                JOB.update(fs=fs, ordner=None, art="upload", schritte=[schritt], meldung=None, schlange=None)
                def hoch():
                    fs.start(schritt)
                    try:
                        r = youtube.hochladen(DATEN, video, titel, d.get("beschreibung") or "", str(d.get("tags") or "").split(","),
                                              sichtbar, bild, bool(d.get("fuer_kinder")), log=fs.log)
                        fs.status[schritt] = "fertig"
                        JOB["meldung"] = f"Hochgeladen ({sichtbar}): {r['url']}" + ("" if r["thumbnail"] or not bild else " · ohne Vorschaubild")
                        fs.log("✔ " + JOB["meldung"])
                    except Exception as ex:
                        fs.fehler = str(ex) or ex.__class__.__name__
                        fs.status[schritt] = "Fehler"
                        fs.log("✖ " + fs.fehler)
                    fs.fertig = True
                JOB["thread"] = threading.Thread(target=hoch, daemon=True); JOB["thread"].start()
                return self._json({"ok": True})
            if u.path == "/api/kontaktbogen":
                e = ergebnis_laden(d["ordner"])
                e["einzelbilder"] = einzelbilder.kontaktbogen(_sicher(d["ordner"]))
                for rel in ("ergebnis.json", "export/ergebnis.json"):
                    if _sicher(d["ordner"], rel).is_file():
                        _sicher(d["ordner"], rel).write_text(bericht.als_json(e), encoding="utf-8")
                return self._json(e["einzelbilder"])
            if u.path == "/api/einzelbilder":
                # Zerlegt das Video einer vorhandenen Analyse (YouTube oder eigene Datei) neu, ohne alles andere zu wiederholen.
                modus = (d.get("modus") or "abstand").lower()
                abstand = einzelbilder.abstand_lesen(d.get("abstand")) if modus == "abstand" else None
                if JOB["thread"] and JOB["thread"].is_alive() and JOB["ordner"] == d["ordner"]:
                    return self._fehler("Dieses Video wird gerade analysiert.", 409)
                e = ergebnis_laden(d["ordner"])
                video = _sicher(d["ordner"], e["video_datei"])
                if not video.is_file():
                    return self._fehler("Das Video dieser Analyse fehlt. Bitte neu analysieren.", 404)
                if not EINZEL_SPERRE.acquire(blocking=False):
                    return self._fehler("Es werden gerade schon Einzelbilder erzeugt.", 409)
                try:
                    e["einzelbilder"] = einzelbilder.zerlegen(video, werkzeug.dauer(video), _sicher(d["ordner"]), abstand,
                                                              log=lambda *a, **k: None, von=d.get("von"), bis=d.get("bis"),
                                                              bildformat=d.get("format") or "jpg", breite=d.get("breite"), modus=modus)
                finally:
                    EINZEL_SPERRE.release()
                for rel in ("ergebnis.json", "export/ergebnis.json"):
                    if _sicher(d["ordner"], rel).is_file():
                        _sicher(d["ordner"], rel).write_text(bericht.als_json(e), encoding="utf-8")
                return self._json(e["einzelbilder"])
            if u.path == "/api/schnitt":
                # Clips, Sprechpausen entfernen, ohne Musik, Lautstärke, Untertitel einbrennen. "liste" zeigt nur, was schon da ist.
                art = d.get("art") or "liste"
                if art == "liste":
                    return self._json({"dateien": schnitt.vorhandene(_sicher(d["ordner"])), "meldung": ""})
                e = ergebnis_laden(d["ordner"])
                video = _sicher(d["ordner"], e["video_datei"])
                if not video.is_file():
                    return self._fehler("Das Video dieser Analyse fehlt. Bitte neu analysieren.", 404)
                if not SCHNITT_SPERRE.acquire(blocking=False):
                    return self._fehler("Es läuft gerade schon ein Schnitt. Bitte kurz warten.", 409)
                try:
                    return self._json(schnitt.ausfuehren(art, video, e, _sicher(d["ordner"]), d))
                finally:
                    SCHNITT_SPERRE.release()
            if u.path == "/api/datei_waehlen":
                return self._json({"pfad": _dialog("datei", "Video auswählen")})
            if u.path == "/api/speichern":
                return self._speichern(d)
            if u.path == "/api/text_speichern":
                ziel = _dialog("ordner", "Wo soll die Datei gespeichert werden?")
                if not ziel:
                    return self._json({"abgebrochen": True})
                name = Path(d.get("name") or "text.txt").name
                p = _frei(Path(ziel) / name); p.write_text(d.get("inhalt", ""), encoding="utf-8")
                return self._json({"gespeichert": [str(p)]})
            if u.path == "/api/cartesia":
                o = d.get("optionen") or {}
                extra = {}
                for zeile in (o.get("aussprache") or "").splitlines():
                    if "=" in zeile:
                        a, b = zeile.split("=", 1)
                        if a.strip():
                            extra[a.strip()] = b.strip()
                r = cartesia.bauen(d.get("text", ""), int(o.get("satzpause", 400)), int(o.get("absatzpause", 700)),
                                   int(o.get("doppelpunktpause", 300)), o.get("fueller", "wenig"), extra,
                                   o.get("vorredner", ""), o.get("nachredner", ""), int(o.get("seed", 7)),
                                   int(o.get("aehm_pause", 200) or 0))
                r["api"] = cartesia.api_anfrage(r["text"], (o.get("modell") or "sonic-3").strip(), (o.get("stimme_id") or "").strip(),
                                                float(o.get("tempo") or 1.0))
                if o.get("modell") or o.get("stimme_id"):
                    einstellungen_speichern({"cartesia_modell": o.get("modell"), "cartesia_stimme": o.get("stimme_id")})
                return self._json(r)
            if u.path == "/api/einstellungen":
                neu = {k: d.get(k) for k in ("gemini_modell", "whisper_modell", "browser_cookies", "gemini_video")}
                for name in GEHEIM:
                    k = d.get(name + "_schluessel")
                    if k is not None and "•" not in k:
                        neu[name + "_schluessel"] = k.strip()
                einstellungen_speichern(neu)
                return self._json({"ok": True})
            if u.path == "/api/kapitel":
                e = ergebnis_laden(d["ordner"])
                e["kapitel"] = d["kapitel"]
                e["kapitel_hinweise"] = bericht.kapitel_pruefen(e["kapitel"])
                _sicher(d["ordner"], "ergebnis.json").write_text(bericht.als_json(e), encoding="utf-8")
                return self._json({"hinweise": e["kapitel_hinweise"],
                                   "beschreibung": bericht.youtube_beschreibung(e["zusammenfassung"].get("kurz", ""), e["kapitel"])})
            if u.path == "/api/transkript":
                # Text korrigieren und Sprecher umbenennen; alle Ausgaben werden danach neu geschrieben.
                e = bearbeiten.anwenden(ergebnis_laden(d["ordner"]), _sicher(d["ordner"]), d.get("texte"), d.get("namen"))
                return self._json(e)
            if u.path in ("/api/uebersetzen", "/api/highlights"):
                from . import gemini
                ein = einstellungen(); k = (ein.get("gemini_schluessel") or "").strip()
                if not k:
                    return self._fehler("Dafür wird ein Gemini-Schlüssel gebraucht (Verlauf & Einstellungen).")
                e = ergebnis_laden(d["ordner"])
                if not e.get("zeilen"):
                    return self._fehler("Diese Analyse hat kein Transkript.")
                modell = ein.get("gemini_modell") or gemini.STANDARD_MODELL
                try:
                    if u.path == "/api/uebersetzen":
                        sprache = (d.get("sprache") or "en").lower()
                        if sprache not in bearbeiten.SPRACHEN:
                            return self._fehler("Diese Sprache wird nicht angeboten.")
                        texte = gemini.uebersetzen(k, e["zeilen"], bearbeiten.SPRACHEN[sprache], modell)
                        return self._json(bearbeiten.uebersetzung_speichern(e, _sicher(d["ordner"]), sprache, texte))
                    e["highlights"] = gemini.highlights(k, e["zeilen"], e["kennzahlen"]["dauer"], int(d.get("anzahl") or 5), modell)
                except RuntimeError as ex:
                    return self._fehler(str(ex), 502)
                for rel in ("ergebnis.json", "export/ergebnis.json"):
                    _sicher(d["ordner"], rel).write_text(bericht.als_json(e), encoding="utf-8")
                return self._json({"highlights": e["highlights"]})
            if u.path == "/api/thumbnail":
                e = ergebnis_laden(d["ordner"])
                e["thumbnail"] = bearbeiten.thumbnail(_sicher(d["ordner"], d["bild"]), _sicher(d["ordner"]))
                for rel in ("ergebnis.json", "export/ergebnis.json"):
                    if _sicher(d["ordner"], rel).is_file():
                        _sicher(d["ordner"], rel).write_text(bericht.als_json(e), encoding="utf-8")
                return self._json({"thumbnail": e["thumbnail"]})
            if u.path == "/api/cartesia_senden":
                # Schickt die fertige Anfrage wirklich an Cartesia (kostet Guthaben) und speichert die WAV im gewählten Ordner.
                k = (einstellungen().get("cartesia_schluessel") or "").strip()
                if not k:
                    return self._fehler("Dafür wird ein Cartesia-Schlüssel gebraucht (Verlauf & Einstellungen).")
                try:
                    ton = cartesia.senden(k, d.get("anfrage") or "")
                except RuntimeError as ex:
                    return self._fehler(str(ex), 502)
                ziel = _dialog("ordner", "Wo soll die Sprachdatei gespeichert werden?")
                if not ziel:
                    return self._json({"abgebrochen": True})
                p = _frei(Path(ziel) / "cartesia_sprache.wav"); p.write_bytes(ton)
                return self._json({"gespeichert": [str(p)]})
            if u.path == "/api/ordner_oeffnen":
                p = _sicher(d["ordner"])
                if sys.platform == "win32":
                    os.startfile(p)  # noqa
                return self._json({"pfad": str(p)})
            if u.path == "/api/gemini_test":
                from . import gemini
                e = einstellungen(); k = (e.get("gemini_schluessel") or "").strip()
                if not k:
                    return self._fehler("Noch kein Gemini-Schlüssel gespeichert.")
                try:
                    return self._json(gemini.testen(k, e.get("gemini_modell") or gemini.STANDARD_MODELL))
                except Exception as ex:
                    return self._fehler(str(ex), 502)
            if u.path == "/api/alles_loeschen":
                if JOB["thread"] and JOB["thread"].is_alive():
                    return self._fehler("Es läuft gerade eine Analyse.", 409)
                anzahl = 0
                for p in list(ARBEIT.iterdir()) if ARBEIT.exists() else []:
                    if p.is_dir():
                        shutil.rmtree(p, ignore_errors=True); anzahl += 1
                return self._json({"geloescht": anzahl})
            if u.path == "/api/loeschen":
                if JOB["thread"] and JOB["thread"].is_alive() and JOB["ordner"] == d["ordner"]:
                    return self._fehler("Diese Analyse läuft gerade.", 409)
                p = _sicher(d["ordner"])
                shutil.rmtree(p, ignore_errors=True)
                return self._json({"geloescht": not p.exists()})
            return self._fehler("Unbekannte Adresse", 404)
        except PermissionError as e:
            return self._fehler(str(e), 403)
        except FileNotFoundError as e:
            return self._fehler(f"Nicht gefunden: {e}", 404)
        except ValueError as e:
            return self._fehler(str(e), 400)
        except Exception as e:
            return self._fehler(f"{e.__class__.__name__}: {e}", 500)

    def _speichern(self, d):
        """Fragt JEDES Mal nach dem Zielordner und kopiert die gewählten Dateien dorthin."""
        ordner, dateien, fmt = d["ordner"], d.get("dateien") or [], d.get("format", "original")
        quellen = [_sicher(ordner, x) for x in dateien]
        fehlend = [str(q) for q in quellen if not q.is_file()]
        if fehlend:
            return self._fehler("Fehlt: " + ", ".join(fehlend), 404)
        titel = d.get("titel") or "Download-Ordner wählen"
        ziel = _dialog("ordner", titel)
        if not ziel:
            return self._json({"abgebrochen": True})
        zielp = Path(ziel); zielp.mkdir(parents=True, exist_ok=True)
        praefix = (d.get("praefix") or "").strip()
        gespeichert = []
        if d.get("zip"):
            z = _frei(zielp / f"{praefix or ordner}.zip")
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                for q in quellen:
                    zf.write(q, q.name)
            return self._json({"gespeichert": [str(z)]})
        if d.get("unterordner"):  # viele Dateien (Einzelbilder) landen zusammen in einem eigenen Unterordner
            zielp = _frei(zielp / Path(str(d["unterordner"])).name); zielp.mkdir()
            for q in quellen:
                shutil.copy2(q, zielp / q.name)
            return self._json({"gespeichert": [f"{zielp} ({len(quellen)} Dateien)"]})
        for q in quellen:
            name = f"{praefix} – {q.name}" if praefix else q.name
            if fmt == "mp3" and q.suffix.lower() == ".wav":
                gespeichert.append(str(werkzeug.mp3_aus_wav(q, _frei(zielp / Path(name).with_suffix(".mp3")))))
            else:
                p = _frei(zielp / name); shutil.copy2(q, p); gespeichert.append(str(p))
        return self._json({"gespeichert": gespeichert})


def fenster_oeffnen(url: str):
    """Öffnet die Oberfläche als eigenes App-Fenster (Edge/Chrome im App-Modus), sonst im Standard-Browser."""
    if sys.platform == "win32":
        kandidaten = [Path(os.environ.get(v, "")) / rel for v in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")
                      for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe")]
        for exe in kandidaten:
            if exe.is_file():
                try:
                    subprocess.Popen([str(exe), f"--app={url}", "--window-size=1440,900"])
                    return
                except OSError:
                    continue
    webbrowser.open(url)


def soll_beenden(jetzt: float, gestartet: float, leer_seit: float | None, laeuft: bool, schonfrist: float = 8.0, ohne_fenster: float = 120.0) -> bool:
    """Installierte Version: beenden, wenn kein Programmfenster mehr offen ist. Eine laufende Analyse wird nie abgebrochen;
    die Schonfrist überbrückt das Neuladen der Seite. Kommt nie ein Fenster (Browser fehlt), ist nach zwei Minuten Schluss."""
    if laeuft or leer_seit is None:
        return False
    nie_ein_fenster = leer_seit <= gestartet
    return jetzt - leer_seit > (ohne_fenster if nie_ein_fenster else schonfrist)


def _waechter(srv, gestartet: float):
    leer_seit = gestartet
    while True:
        time.sleep(2)
        jetzt = time.time()
        for k in [k for k, t in FENSTER.items() if jetzt - t > 200]:  # Fenster ohne Lebenszeichen (Browser abgestürzt)
            FENSTER.pop(k, None)
        if FENSTER:
            leer_seit = None
        elif leer_seit is None:
            leer_seit = jetzt
        if soll_beenden(jetzt, gestartet, leer_seit, bool(JOB["thread"] and JOB["thread"].is_alive())):
            threading.Thread(target=srv.shutdown, daemon=True).start()
            return


def starten(port: int = 8765, browser: bool = True, beenden: bool = False, zustand: Path | None = None):
    """beenden: Programm endet von selbst, wenn das letzte Fenster zu ist (installierte und portable Version).
    zustand: Datei, in der die Adresse des laufenden Programms steht (für den zweiten Klick auf das Symbol)."""
    ARBEIT.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    for versuch in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", versuch), Handler)
            break
        except OSError:
            continue
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"YVdctuAio läuft: {url}" + ("" if beenden else "\nDieses Fenster offen lassen. Beenden mit Strg+C."), flush=True)
    if zustand:
        zustand.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    if beenden:
        threading.Thread(target=_waechter, args=(srv, time.time()), daemon=True).start()
    if browser:
        threading.Timer(0.8, lambda: fenster_oeffnen(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if zustand:
            zustand.unlink(missing_ok=True)
