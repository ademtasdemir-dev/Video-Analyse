"""Der komplette Ablauf: Video holen -> Ton -> Transkript -> Stimmen -> Bilder -> Struktur -> (Gemini) -> Ausgaben."""
import json
import re
import time
import traceback
from pathlib import Path

from . import bericht, einzelbilder, quelle, sprecher, struktur, szenen, transkript, trennen, werkzeug, zeit

SCHRITTE = ["Video holen", "Ton vorbereiten", "Stimme und Musik trennen", "Transkript erstellen", "Stimmen erkennen",
            "Audio pro Sprecher", "Bilder und Schnitte", "Einzelbilder", "Strukturplan", "KI-Auswertung (Gemini)", "Ausgaben speichern"]


class Fortschritt:
    def __init__(self):
        self.schritt, self.prozent, self.meldungen, self.fertig, self.fehler = "", 0.0, [], False, None
        self.status = {s: "offen" for s in SCHRITTE}

    def start(self, s):
        if self.schritt and self.status.get(self.schritt) == "läuft":
            self.status[self.schritt] = "fertig"
        self.schritt, self.prozent = s, 0.0
        self.status[s] = "läuft"
        self.log(f"▶ {s}")

    def ueberspringen(self, s, grund):
        self.status[s] = "übersprungen"
        self.log(f"– {s}: {grund}")

    def log(self, text, prozent=None):
        if prozent is not None:
            self.prozent = float(prozent)
            if self.meldungen and self.meldungen[-1][1].split(" ")[0] == text.split(" ")[0] and "%" in text:
                self.meldungen[-1] = (time.strftime("%H:%M:%S"), text)
                return
        self.meldungen.append((time.strftime("%H:%M:%S"), text))

    def als_dict(self):
        return {"schritt": self.schritt, "prozent": self.prozent, "status": self.status, "fertig": self.fertig,
                "fehler": self.fehler, "meldungen": self.meldungen[-80:]}


def ordner_name(text: str) -> str:
    vid = zeit.video_id(text) if zeit.ist_youtube(text) else None
    if vid:
        return vid
    return re.sub(r"[^\w\-]+", "_", Path(text.strip().strip('"')).stem)[:40] or "video"


def _gemini_einbauen(e: dict, g: dict, zeilen, szen, dauer):
    if g.get("zusammenfassung"):
        e["zusammenfassung"].update({k: v for k, v in g["zusammenfassung"].items() if v})
    bilder = {b.get("nr"): b for b in g.get("bilder", []) if isinstance(b, dict)}
    for s in szen:
        b = bilder.get(s["nr"])
        if b:
            s.update({"bildtyp": b.get("bildtyp", ""), "beschreibung": b.get("beschreibung", ""), "text_im_bild": b.get("text_im_bild", "")})
    if any(s.get("bildtyp") for s in szen) and isinstance(e.get("bild"), dict):
        arten = {}
        for s in szen:  # "Was ist zu sehen?" mit den Bildtypen von Gemini statt der groben Schätzung
            art = s.get("bildtyp") or s.get("bildart", "unbekannt")
            arten[art] = round(arten.get(art, 0) + s["ende"] - s["start"], 1)
        e["bild"]["bildarten"] = dict(sorted(arten.items(), key=lambda x: -x[1]))
    gk = [k for k in g.get("kapitel", []) if isinstance(k, dict) and "start" in k]
    if len(gk) >= 2:
        try:
            gk = sorted(gk, key=lambda k: float(k["start"]))
            gk[0]["start"] = 0
            neu = []
            for i, k in enumerate(gk):
                s = float(k["start"]); en = float(gk[i + 1]["start"]) if i + 1 < len(gk) else dauer
                z = [x for x in zeilen if s - 0.5 <= x["start"] < en - 0.5]
                sz = [x for x in szen if s - 0.5 <= x["start"] < en - 0.5]
                wz = sum(x["woerter"] for x in z)
                neu.append({"nr": i + 1, "start": round(s, 2), "ende": round(en, 2), "titel": k.get("titel", f"Kapitel {i + 1}"),
                            "phase": k.get("phase", "Hauptteil"), "inhalt": k.get("inhalt", ""), "visuell": k.get("visuell", ""),
                            "schlagwoerter": struktur.schlagwoerter(" ".join(x["text"] for x in z), 5),
                            "text": " ".join(x["text"] for x in z), "woerter": wz, "wpm": round(wz / max((en - s) / 60, 1e-6)),
                            "sprecher": sorted({x["sprecher"] for x in z}), "szenen": len(sz),
                            "bildart": sz[0].get("bildtyp") or sz[0]["bildart"] if sz else "–", "bild": sz[0]["bild"] if sz else None})
            e["kapitel"], e["kapitel_quelle"] = neu, "Gemini (aus Transkript und Bildern)"
        except (TypeError, ValueError):
            pass
    for schl in ("darstellung", "dramaturgie", "titel_vorschlaege", "verbesserungen"):
        if g.get(schl):
            e[schl] = g[schl]
    rollen = {r.get("sprecher"): r for r in g.get("sprecher_rollen", []) if isinstance(r, dict)}
    for s in e["sprecher"]:
        if s["sprecher"] in rollen:
            s["rolle"] = rollen[s["sprecher"]].get("rolle", ""); s["merkmale"] = rollen[s["sprecher"]].get("merkmale", "")


def analysieren(eingabe: str, opt: dict, arbeit: Path, cache: Path, einstellungen: dict, fs: Fortschritt) -> dict:
    t0 = time.time()
    try:
        nur_bilder = bool(opt.get("nur_bilder"))  # schneller Weg: nur Standbilder und Einzelbilder, kein Ton, kein Transkript
        bilder_an = bool(opt.get("einzelbilder") or nur_bilder)
        bild_modus = (opt.get("bild_modus") or "abstand").lower()
        abstand = einzelbilder.abstand_lesen(opt.get("bild_abstand") or 1) if bilder_an and bild_modus == "abstand" else None
        ordner = arbeit / ordner_name(eingabe)
        audio_dir, bilder_dir, export_dir = ordner / "audio", ordner / "bilder", ordner / "export"
        for d in (audio_dir, bilder_dir, export_dir):
            d.mkdir(parents=True, exist_ok=True)

        fs.start("Video holen")
        if zeit.ist_youtube(eingabe):
            info = quelle.von_youtube(eingabe, ordner, log=fs.log, browser=einstellungen.get("browser_cookies", ""),
                                      qualitaet=opt.get("qualitaet") or "720")
        else:
            info = quelle.von_datei(eingabe, ordner)
        fertige_untertitel = None
        if opt.get("untertitel") and not nur_bilder and info.get("quelle") == "youtube":
            fs.log("Suche YouTube-Untertitel …")
            fertige_untertitel = quelle.untertitel(eingabe, ordner, opt.get("sprache") or "", einstellungen.get("browser_cookies", ""))
            if not fertige_untertitel:
                fs.log("Keine YouTube-Untertitel gefunden. Die eigene Spracherkennung übernimmt.")
        video = Path(info["video"])
        dauer = werkzeug.dauer(video)
        info["duration"] = round(dauer, 2)
        fs.log(f"„{info.get('title')}“ · {zeit.hms(dauer)}")

        musikanteil, dateien, zeilen, sprache = None, {}, [], None
        if nur_bilder:
            for s in ("Ton vorbereiten", "Stimme und Musik trennen", "Transkript erstellen"):
                fs.ueberspringen(s, "nur Bilder gewählt")
        else:
            fs.start("Ton vorbereiten")
            audio16 = werkzeug.audio_laden(video, 16000, 1)
            trennen.original(video, audio_dir)
            dateien = {"Original (Video-Ton)": "audio/original.wav"}

        if nur_bilder:
            pass
        elif opt.get("trennen", True):
            fs.start("Stimme und Musik trennen")
            vier = bool(opt.get("vier_spuren"))
            da = (audio_dir / "stimme.wav").exists() and (audio_dir / "stimme.wav").stat().st_mtime > video.stat().st_mtime
            if da and (not vier or all((audio_dir / d).exists() for d in trennen.VIER_NAMEN)):
                fs.log("Getrennte Spuren von der letzten Analyse werden wiederverwendet.")
                st = trennen.vorhandene(audio_dir)
            else:
                st = trennen.stimme_musik(video, audio_dir, cache, log=fs.log, vier=vier)
            dateien["Nur Stimme"] = "audio/stimme.wav"; dateien["Nur Musik / Hintergrund"] = "audio/musik.wav"
            if vier:
                for datei, name in trennen.VIER_NAMEN.items():
                    dateien[name] = "audio/" + datei
            musikanteil = st["musikanteil"]
            fs.log(f"Hintergrund-/Musikanteil: {musikanteil} %")
            quelle_stimme = Path(st["stimme"])
            audio_transkript = werkzeug.audio_laden(quelle_stimme, 16000, 1)
        else:
            fs.ueberspringen("Stimme und Musik trennen", "abgeschaltet")
            quelle_stimme, audio_transkript = audio_dir / "original.wav", audio16

        transkript_quelle = None
        if not nur_bilder:
            fs.start("Transkript erstellen")
            if fertige_untertitel:
                zeilen = transkript.aus_untertitel(fertige_untertitel[0].read_text(encoding="utf-8", errors="replace"))
                sprache = fertige_untertitel[1]
            if zeilen:
                transkript_quelle = "YouTube-Untertitel"
                fs.log(f"YouTube-Untertitel übernommen: {len(zeilen)} Zeilen, Sprache: {sprache}")
            else:
                woerter, sprache = transkript.transkribieren(audio_transkript, opt.get("modell", "small"),
                                                             None if opt.get("sprache") in (None, "", "auto") else opt["sprache"], log=fs.log)
                zeilen = transkript.zeilen_bilden(woerter)
                transkript_quelle = "eigene Spracherkennung"
                fs.log(f"{len(woerter)} Wörter, {len(zeilen)} Zeilen, Sprache: {sprache}")

        kein_text = "nur Bilder gewählt" if nur_bilder else "kein Gesprochenes"
        if opt.get("sprecher", True) and zeilen:
            fs.start("Stimmen erkennen")
            n = sprecher.zuordnen(zeilen, audio_transkript, cache / "ecapa", anzahl=opt.get("sprecher_anzahl") or None, log=fs.log)
            fs.log(f"{n} verschiedene Stimme(n) erkannt")
        else:
            fs.ueberspringen("Stimmen erkennen", "abgeschaltet" if zeilen else kein_text)
        for z in zeilen:
            z.pop("_w", None)
        stat = sprecher.statistik(zeilen)

        if zeilen:
            fs.start("Audio pro Sprecher")
            for sp, p in trennen.pro_sprecher(quelle_stimme, zeilen, audio_dir).items():
                dateien[f"Nur {sp}"] = "audio/" + Path(p).name
        else:
            fs.ueberspringen("Audio pro Sprecher", kein_text)

        fs.start("Bilder und Schnitte")
        bild = szenen.analysieren(video, dauer, bilder_dir, log=fs.log)

        if bilder_an:
            fs.start("Einzelbilder")
            einzel = einzelbilder.zerlegen(video, dauer, ordner, abstand, log=fs.log, von=opt.get("bild_von"), bis=opt.get("bild_bis"),
                                           bildformat=opt.get("bild_format") or "jpg", breite=opt.get("bild_breite"), modus=bild_modus)
        else:
            einzel = einzelbilder.vorhandene(ordner)
            fs.ueberspringen("Einzelbilder", "von der letzten Zerlegung übernommen" if einzel else "abgeschaltet")

        fs.start("Strukturplan")
        kap, kq = struktur.kapitel_bilden(zeilen, bild["szenen"], dauer, info.get("chapters"))
        kz = struktur.kennzahlen(zeilen, dauer, bild)
        alle = " ".join(z["text"] for z in zeilen)
        lokal = struktur.zusammenfassung_lokal(zeilen)
        e = {"version": 1, "eingabe": eingabe, "ordner": ordner.name, "video_datei": video.name, "info": info, "sprache": sprache,
             "zeilen": zeilen, "sprecher": stat, "bild": bild, "kapitel": kap, "kapitel_quelle": kq, "kennzahlen": kz,
             "tempo": struktur.tempo_text(kz), "schlagwoerter": struktur.schlagwoerter(alle, 15), "musikanteil": musikanteil,
             "zusammenfassung": {"kurz": " ".join(lokal[:2]), "ausfuehrlich": "", "kernaussagen": lokal, "zielgruppe": "", "thema": ""},
             "analyse_art": "nur Bilder" if nur_bilder else "lokal (ohne KI)", "audio": dateien, "einzelbilder": einzel,
             "transkript_quelle": transkript_quelle}

        schluessel = (einstellungen.get("gemini_schluessel") or "").strip()
        if nur_bilder:
            fs.ueberspringen("KI-Auswertung (Gemini)", "nur Bilder gewählt")
        elif opt.get("gemini", True) and schluessel:
            fs.start("KI-Auswertung (Gemini)")
            from . import gemini
            try:
                fs.log("Sende Transkript und Standbilder an Gemini …")
                yt = (info.get("webpage_url") if info.get("quelle") == "youtube" and einstellungen.get("gemini_video", True) else None)
                if yt:
                    fs.log("Gemini schaut sich zusätzlich das ganze YouTube-Video an …")
                anfrage = gemini.anfrage_bauen(info, zeilen, bild["szenen"], kap, bilder_dir, youtube_url=yt)
                modell = einstellungen.get("gemini_modell") or gemini.STANDARD_MODELL
                try:
                    g = gemini.auswerten(schluessel, anfrage, modell, log=fs.log)
                except gemini.VideoNichtErlaubt:
                    fs.log("Gemini darf das Video selbst nicht abrufen (nur öffentliche YouTube-Videos). "
                           "Auswertung läuft mit Transkript und Standbildern weiter …")
                    g = gemini.auswerten(schluessel, gemini.ohne_video(anfrage), modell, log=fs.log)
                fehlen = gemini.fehlende_bilder(g, bild["szenen"])
                if fehlen:
                    fs.log(f"Beschreibe noch {len(fehlen)} Standbild(er) einzeln …")
                    for i in range(0, len(fehlen), 20):
                        try:
                            nach = gemini.auswerten(schluessel, gemini.bilder_anfrage(fehlen[i:i + 20], bilder_dir), modell, log=fs.log)
                            g.setdefault("bilder", []).extend(b for b in nach.get("bilder", []) if isinstance(b, dict))
                        except Exception as ex:
                            fs.log(f"⚠ Einzelbeschreibung nicht möglich: {ex}")
                _gemini_einbauen(e, g, zeilen, bild["szenen"], dauer)
                e["analyse_art"] = "lokal + Gemini"
                fs.log("Gemini-Auswertung übernommen")
            except Exception as ex:
                fs.log(f"⚠ Gemini nicht verfügbar: {ex}. Ergebnis bleibt lokal.")
                fs.status["KI-Auswertung (Gemini)"] = "Fehler"
        else:
            fs.ueberspringen("KI-Auswertung (Gemini)", "kein Gemini-Schlüssel eingetragen" if not schluessel else "abgeschaltet")

        fs.start("Ausgaben speichern")
        e["kapitel_hinweise"] = bericht.kapitel_pruefen(e["kapitel"])
        e["dauer_analyse"] = round(time.time() - t0)
        bericht.exporte_schreiben(e, ordner)
        fs.status["Ausgaben speichern"] = "fertig"
        fs.log(f"✔ Fertig in {e['dauer_analyse']} s")
        fs.fertig = True
        return e
    except Exception as ex:
        fs.fehler = str(ex) or ex.__class__.__name__
        if fs.schritt:
            fs.status[fs.schritt] = "Fehler"
        fs.log("✖ " + fs.fehler)
        letzte = traceback.format_exc().splitlines()[-1]
        if fs.fehler not in letzte:
            fs.log(letzte)
        fs.fertig = True
        raise
