"""Optionale KI-Auswertung mit Google Gemini (kostenloser API-Schlüssel aus Google AI Studio).

Bekommt: Metadaten, Transkript mit Zeitstempeln und Sprechern, Szenenliste und Standbilder.
Liefert: ausführliche Zusammenfassung, Kapitel mit Inhalt und Bildbeschreibung, Beschreibung jedes Standbilds,
Analyse von Darstellung und Dramaturgie.
"""
import base64
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .zeit import hms

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modell}:generateContent"
MAX_BILDER = 30
STANDARD_MODELL = "gemini-3-flash-preview"
ERSATZ_MODELLE = ["gemini-2.5-flash"]  # falls das gewählte Modell (noch/nicht mehr) nicht verfügbar ist

AUFGABE = """Du analysierst ein Video vollständig und sehr genau, auf Deutsch. Du bekommst Metadaten, das Transkript
mit Zeitstempeln und Sprechern, eine Szenenliste und Standbilder (je Bild steht Nummer und Zeit davor).
Beschreibe nur, was wirklich im Material steckt. Erfinde nichts. Wenn etwas unklar ist, sag das.
Antworte ausschließlich mit JSON in genau diesem Aufbau:
{
 "zusammenfassung": {"kurz": "2-3 Sätze", "ausfuehrlich": "mehrere Absätze, was im Video passiert und gesagt wird",
                      "kernaussagen": ["..."], "zielgruppe": "...", "thema": "..."},
 "kapitel": [{"start": Sekunden als Zahl, "titel": "kurzer Kapiteltitel", "phase": "Einstieg|Hauptteil|Abschluss|Hook|Übergang|Call-to-Action",
              "inhalt": "was in dem Abschnitt gesagt/gezeigt wird", "visuell": "welche Bilder/Folien/Einblendungen zu sehen sind"}],
 "bilder": [{"nr": Bildnummer, "bildtyp": "z.B. Folie, Diagramm, Person vor Kamera, Bildschirmaufnahme, B-Roll, Animation, Text-Einblendung",
             "beschreibung": "was genau zu sehen ist", "text_im_bild": "lesbarer Text im Bild, sonst leer"}],
 "darstellung": {"stil": "...", "grafiken_und_einblendungen": "...", "kamera_und_licht": "...", "sprecher_und_vortrag": "...",
                 "tempo_und_schnitt": "...", "ton_und_musik": "..."},
 "dramaturgie": {"einstieg": "...", "aufbau": "...", "spannung_und_wiederholung": "...", "abschluss": "..."},
 "sprecher_rollen": [{"sprecher": "Sprecher 1", "rolle": "z.B. Moderator, Gast, Erzähler", "merkmale": "..."}],
 "titel_vorschlaege": ["..."],
 "verbesserungen": ["konkrete Hinweise, was man am Video besser machen könnte"]
}
Kapitel: nutze die vorgeschlagenen Kapitelgrenzen als Hilfe, verbessere sie, wenn der Inhalt es nahelegt. Erstes Kapitel bei 0.
"bilder": für JEDES mitgeschickte Bild genau einen Eintrag mit seiner Nummer, keins auslassen."""

BILDER_AUFGABE = """Beschreibe jedes der folgenden Standbilder aus einem Video, auf Deutsch, nur was wirklich zu sehen ist.
Antworte ausschließlich mit JSON: {"bilder": [{"nr": Bildnummer, "bildtyp": "z.B. Folie, Diagramm, Person vor Kamera,
Bildschirmaufnahme, B-Roll, Animation, Text-Einblendung", "beschreibung": "was genau zu sehen ist",
"text_im_bild": "lesbarer Text im Bild, sonst leer"}]}. Für jedes Bild genau ein Eintrag."""


def bilder_anfrage(szenen: list[dict], bilder_ordner: Path) -> dict:
    """Zweite, kleine Anfrage nur für Standbilder, die in der ersten Antwort fehlten."""
    teile = [{"text": BILDER_AUFGABE}]
    for s in szenen:
        teile.append({"text": f"Bild {s['nr']} ({hms(s['bild_zeit'])}):"})
        teile.append(_bild_teil(bilder_ordner / s["bild"]))
    return {"contents": [{"role": "user", "parts": teile}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}


def fehlende_bilder(g: dict, szenen: list[dict]) -> list[dict]:
    da = {b.get("nr") for b in g.get("bilder", []) if isinstance(b, dict) and (b.get("beschreibung") or "").strip()}
    return [s for s in szenen if s["nr"] not in da]


def _bild_teil(pfad: Path) -> dict:
    im = Image.open(pfad).convert("RGB")
    im.thumbnail((640, 640))
    b = io.BytesIO(); im.save(b, "JPEG", quality=80)
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}


def anfrage_bauen(info: dict, zeilen: list[dict], szenen: list[dict], kapitel: list[dict], bilder_ordner: Path,
                  youtube_url: str | None = None) -> dict:
    """youtube_url: wenn gesetzt, schaut sich Gemini zusätzlich das ganze Video an (Bewegung, Schnitte, Einblendungen).
    Zählt beim kostenlosen Schlüssel zum Tageskontingent (8 Stunden YouTube-Video pro Tag)."""
    meta = {k: info.get(k) for k in ("title", "uploader", "duration", "description", "tags", "upload_date")}
    transkript = "\n".join(f"[{hms(z['start'])}] {z['sprecher']}: {z['text']}" for z in zeilen)
    szen = "\n".join(f"Bild {s['nr']} bei {hms(s['bild_zeit'])} (Szene {hms(s['start'])}–{hms(s['ende'])}), Schätzung: {s['bildart']}" for s in szenen)
    vorschlag = "\n".join(f"{hms(k['start'])} {k['titel']}" for k in kapitel)
    teile = [{"text": AUFGABE},
             {"text": "METADATEN:\n" + json.dumps(meta, ensure_ascii=False)},
             {"text": "TRANSKRIPT:\n" + (transkript or "(kein gesprochener Text erkannt)")},
             {"text": "SZENEN:\n" + szen},
             {"text": "VORGESCHLAGENE KAPITEL:\n" + vorschlag}]
    if youtube_url:
        teile.insert(1, {"file_data": {"file_uri": youtube_url}})
        teile.insert(1, {"text": "Das komplette Video ist beigefügt. Beschreibe Bilder, Einblendungen und Schnitte anhand des Videos."})
    max_b = 12 if youtube_url else MAX_BILDER
    schritt = max(1, -(-len(szenen) // max_b))
    for s in szenen[::schritt][:max_b]:
        teile.append({"text": f"Bild {s['nr']} ({hms(s['bild_zeit'])}):"})
        teile.append(_bild_teil(bilder_ordner / s["bild"]))
    return {"contents": [{"role": "user", "parts": teile}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}}


def testen(schluessel: str, modell: str = STANDARD_MODELL) -> dict:
    """Kurzer Probeaufruf: prüft Schlüssel und Modell. Gibt das Modell zurück, das geantwortet hat."""
    benutzt = {}
    anfrage = {"contents": [{"role": "user", "parts": [{"text": 'Antworte nur mit diesem JSON: {"ok": true}'}]}],
               "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    antwort = auswerten(schluessel, anfrage, modell, timeout=60, gewaehlt=benutzt)
    return {"ok": bool(antwort.get("ok")), "modell": benutzt.get("modell")}


def auswerten(schluessel: str, anfrage: dict, modell: str = STANDARD_MODELL, timeout: int = 600, log=None,
              gewaehlt: dict | None = None) -> dict:
    """Probiert das gewählte Modell, bei „Modell nicht gefunden“ automatisch die Ersatzmodelle."""
    kandidaten = [modell or STANDARD_MODELL] + [m for m in ERSATZ_MODELLE if m != modell]
    for i, m in enumerate(kandidaten):
        try:
            ergebnis = _auswerten_einmal(schluessel, anfrage, m, timeout)
            if gewaehlt is not None:
                gewaehlt["modell"] = m
            return ergebnis
        except ModellFehlt:
            if i + 1 == len(kandidaten):
                raise RuntimeError(f"Kein Gemini-Modell verfügbar ({', '.join(kandidaten)}).") from None
            if log:
                log(f"Modell {m} nicht verfügbar, nehme {kandidaten[i + 1]} …")


class ModellFehlt(Exception):
    pass


class VideoNichtErlaubt(Exception):
    """Gemini darf das YouTube-Video nicht abrufen (z. B. nicht gelistet oder privat; nur öffentliche Videos gehen)."""


def ohne_video(anfrage: dict) -> dict:
    """Dieselbe Anfrage ohne den YouTube-Video-Teil (nur Transkript und Standbilder)."""
    neu = json.loads(json.dumps(anfrage))
    for c in neu.get("contents", []):
        c["parts"] = [t for t in c.get("parts", []) if "file_data" not in t
                      and not t.get("text", "").startswith("Das komplette Video ist beigefügt")]
    return neu


def _auswerten_einmal(schluessel: str, anfrage: dict, modell: str, timeout: int) -> dict:
    req = urllib.request.Request(URL.format(modell=modell), data=json.dumps(anfrage).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": schluessel})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            antwort = json.loads(r.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(text)["error"]["message"]
        except Exception:
            msg = text[:300]
        if e.code in (400, 403) and "API key" in msg:
            raise RuntimeError("Gemini-Schlüssel ungültig. Bitte in den Einstellungen prüfen.") from e
        if e.code == 404 or (e.code == 400 and "model" in msg.lower() and "not" in msg.lower() and "found" in msg.lower()):
            raise ModellFehlt(msg) from e
        if e.code == 403 and any("file_data" in t for c in anfrage.get("contents", []) for t in c.get("parts", [])):
            raise VideoNichtErlaubt(msg) from e
        if e.code == 429:
            raise RuntimeError("Gemini-Tageslimit erreicht (kostenloser Schlüssel). Später erneut versuchen.") from e
        raise RuntimeError(f"Gemini-Fehler {e.code}: {msg}") from e
    return antwort_lesen(antwort)


def antwort_lesen(antwort: dict) -> dict:
    try:
        text = antwort["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError("Gemini hat keine Antwort geliefert: " + json.dumps(antwort)[:300]) from e
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def _text_anfrage(aufgabe: str, inhalt: str, temperatur: float = 0.2) -> dict:
    return {"contents": [{"role": "user", "parts": [{"text": aufgabe}, {"text": inhalt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperatur}}


def uebersetzen(schluessel: str, zeilen: list[dict], sprache: str, modell: str = STANDARD_MODELL, block: int = 120, log=None) -> list[str]:
    """Übersetzt jede Transkriptzeile einzeln (Zeitstempel bleiben gleich). sprache: Name der Zielsprache, z. B. 'Englisch'."""
    aufgabe = (f"Übersetze jede der folgenden Zeilen eines Video-Transkripts ins {sprache}. Natürlich und sinngemäß, Fachbegriffe "
               "bleiben erhalten. Jede Zeile bleibt eine Zeile, nichts zusammenfassen, nichts weglassen. "
               'Antworte ausschließlich mit JSON: {"zeilen": [{"nr": Nummer, "text": "Übersetzung"}]} mit genau einem Eintrag je Nummer.')
    fertig: list[str] = []
    for a in range(0, len(zeilen), block):
        teil = zeilen[a:a + block]
        inhalt = "\n".join(f"{a + i}: {z['text']}" for i, z in enumerate(teil))
        antwort = auswerten(schluessel, _text_anfrage(aufgabe, inhalt), modell, log=log)
        texte = {int(x["nr"]): str(x.get("text") or "") for x in antwort.get("zeilen", []) if isinstance(x, dict) and "nr" in x}
        fehlen = [a + i for i in range(len(teil)) if not texte.get(a + i, "").strip()]
        if fehlen:
            raise RuntimeError(f"Gemini hat {len(fehlen)} Zeile(n) nicht übersetzt. Bitte noch einmal versuchen.")
        fertig += [texte[a + i] for i in range(len(teil))]
        if log:
            log(f"Übersetzung {len(fertig)}/{len(zeilen)}")
    return fertig


def highlights(schluessel: str, zeilen: list[dict], dauer: float, anzahl: int = 5, modell: str = STANDARD_MODELL) -> list[dict]:
    """Die besten Stellen des Videos als Vorschläge für kurze Clips (je 15 bis 60 Sekunden)."""
    aufgabe = (f"Du bekommst das Transkript eines Videos mit Zeitstempeln in Sekunden. Suche die {anzahl} stärksten Stellen für kurze Clips "
               "(Shorts): eine klare Aussage, ein Aha-Moment, etwas Witziges oder Überraschendes. Jede Stelle 15 bis 60 Sekunden, "
               "beginnt und endet an einer Satzgrenze, Stellen überschneiden sich nicht. Erfinde nichts. "
               'Antworte ausschließlich mit JSON: {"highlights": [{"start": Sekunden, "ende": Sekunden, "titel": "kurzer Titel", '
               '"grund": "warum die Stelle stark ist"}]}')
    inhalt = "\n".join(f"[{z['start']:.1f}–{z['ende']:.1f}] {z['sprecher']}: {z['text']}" for z in zeilen)
    antwort = auswerten(schluessel, _text_anfrage(aufgabe, inhalt, 0.4), modell)
    out = []
    for h in antwort.get("highlights", []):
        try:
            s, e = max(0.0, float(h["start"])), min(float(dauer), float(h["ende"]))
        except (KeyError, TypeError, ValueError):
            continue
        if e - s >= 3:
            out.append({"start": round(s, 2), "ende": round(e, 2), "titel": str(h.get("titel") or "Highlight")[:80],
                        "grund": str(h.get("grund") or "")[:300]})
    return sorted(out, key=lambda x: x["start"])
