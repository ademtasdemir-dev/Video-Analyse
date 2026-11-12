"""Text -> fertiger Sprechtext für Cartesia (Sonic) mit allen Regeln aus dem Projekt.

Regeln (abgestimmt mit Adem):
- Zahlen immer ausschreiben (12 TB -> zwölf Terabyte, 2,5 -> zwei Komma fünf, IP-Adressen mit "Punkt")
- Aussprache: NAS -> Naas, VLAN -> Wii Lan, RAID -> Rejd, CAD -> Käht, "DHCP-Server" -> "DHCP Server"
- keine Bindestriche (Bindestriche lassen die Stimme die Sprache wechseln)
- keine Ausrufezeichen (klingt sonst wie Anfeuern), jeder Satz endet mit Punkt
- Pausen mit <break time="…ms"/>, keine doppelt hintereinander
- optional natürliche Füllwörter (", ähm,") in einstellbarer Menge
"""
import json
import random
import re

from num2words import num2words

AUSSPRACHE = {
    "NAS": "Naas", "NASe": "Naas Geräte", "VLANs": "Wii Lans", "VLAN": "Wii Lan",
    "WLAN": "We Lan", "RAID": "Rejd", "CAD": "Käht", "SSD": "S S D", "USB": "U S B", "PC": "P C", "IT": "I T",
    "VPN": "V P N", "MFA": "M F A", "z. B.": "zum Beispiel", "z.B.": "zum Beispiel", "ca.": "circa", "bzw.": "beziehungsweise",
    "usw.": "und so weiter", "d. h.": "das heißt", "&": "und", "%": " Prozent", "Nr.": "Nummer",
}
EINHEITEN = [  # (Muster nach einer Zahl, Wort)
    (r"Gbit/s|Gbps|GBit/s", "Gigabit pro Sekunde"), (r"Mbit/s|Mbps", "Megabit pro Sekunde"), (r"Gbit|GBit", "Gigabit"),
    (r"TB", "Terabyte"), (r"GB", "Gigabyte"), (r"MB", "Megabyte"), (r"KB|kB", "Kilobyte"), (r"GHz", "Gigahertz"),
    (r"km/h", "Kilometer pro Stunde"), (r"km", "Kilometer"), (r"kg", "Kilogramm"), (r"m²", "Quadratmeter"),
    (r"€|EUR", "Euro"), (r"\$", "Dollar"), (r"h\b", "Stunden"), (r"min\b|Min\.", "Minuten"), (r"s\b|Sek\.", "Sekunden"),
]
ZIFFER_GESPROCHEN = ["null", "eins", "zwo", "drei", "vier", "fünf", "sechs", "siebn", "acht", "neun"]
FUELLER = {"aus": 0.0, "wenig": 0.12, "mittel": 0.25, "viel": 0.45}


def zahl(n: str) -> str:
    n = n.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", n) else n
    if "," in n:
        a, b = n.split(",", 1)
        return f"{num2words(int(a), lang='de')} Komma " + " ".join(num2words(int(c), lang="de") for c in b)
    return num2words(int(n), lang="de")


def zahlen_ausschreiben(t: str) -> str:
    # IP-Adressen und Netze: 192.168.10.0/27
    def ip(m):
        teile = " Punkt ".join(num2words(int(x), lang="de") for x in m.group(1).split("."))
        if m.group(2):
            teile += " slesh " + " ".join(ZIFFER_GESPROCHEN[int(c)] for c in m.group(2))
        return teile
    t = re.sub(r"\b(\d{1,3}(?:\.\d{1,3}){3,})(?:\s*/\s*(\d{1,2}))?\b", ip, t)
    # übrige Punkte zwischen Ziffern (keine Tausender wie 1.000) gesprochen als "Punkt"
    t = re.sub(r"(?<=\d)\.(?=\d(?!\d\d(?:\D|$)))", " Punkt ", t)
    # Cat 6A, Cat6
    t = re.sub(r"\bCat\s?(\d+)([A-Za-z]?)\b", lambda m: f"Cat {num2words(int(m.group(1)), lang='de')}" + (f" {m.group(2).upper()}" if m.group(2) else ""),
               t, flags=re.IGNORECASE)
    # 4 × 16 / 4x16
    t = re.sub(r"(\d)\s*[×x]\s*(\d)", r"\1 mal \2", t)
    # Uhrzeit/Dauer 13:20
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: f"{num2words(int(m.group(1)), lang='de')} Minuten und {num2words(int(m.group(2)), lang='de')} Sekunden", t)
    # Zahl + Einheit
    for muster, wort in EINHEITEN:
        t = re.sub(r"(\d+(?:,\d+)?)\s?(?:" + muster + ")", lambda m, w=wort: f"{m.group(1)} {w}", t)
    t = re.sub(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?", lambda m: zahl(m.group(0)), t)
    t = re.sub(r"\beins (?=[A-ZÄÖÜ])", "ein ", t)  # "ein Gigabit", nicht "eins Gigabit"
    return t


def aussprache(t: str, extra: dict | None = None) -> str:
    regeln = {**AUSSPRACHE, **(extra or {})}
    for alt in sorted(regeln, key=len, reverse=True):
        neu = regeln[alt]
        if re.fullmatch(r"[\w\-]+", alt):
            t = re.sub(rf"(?<!\w){re.escape(alt)}(?!\w)", neu, t)
        else:
            t = t.replace(alt, neu)
    return t


def pausen_zusammenfassen(t: str) -> str:
    """Mehrere <break/> direkt hintereinander -> eine Pause mit der längsten Dauer."""
    def ms(x):
        return int(float(x[:-2])) if x.endswith("ms") else int(float(x[:-1]) * 1000)
    muster = re.compile(r'(?:\s*[,.]?\s*<break time="([\d.]+m?s)"\s*/>\s*){2,}')
    def ersetzen(m):
        werte = re.findall(r'<break time="([\d.]+m?s)"', m.group(0))
        return f' <break time="{max(ms(w) for w in werte)}ms"/> '
    return muster.sub(ersetzen, t)


def bauen(text: str, satzpause: int = 400, absatzpause: int = 700, doppelpunktpause: int = 300,
          fueller: str = "wenig", extra_aussprache: dict | None = None, vorredner: str = "", nachredner: str = "",
          seed: int = 7, aehm_pause: int = 200) -> dict:
    rnd = random.Random(seed)
    absaetze = [a.strip() for a in re.split(r"\n\s*\n", text.strip()) if a.strip()]
    p_fuell = FUELLER.get(fueller, 0.0)
    aehm = ", ähm, " + (f'<break time="{int(aehm_pause)}ms"/>' if aehm_pause else "")
    MARKE = "\uE000"  # Platzhalter, damit Zahlenregeln die Pause nicht verändern
    if vorredner:
        absaetze.insert(0, f"Ja{MARKE if p_fuell else ', '}danke dir, {vorredner}.")
    if nachredner:
        absaetze.append(f"Gut{MARKE if p_fuell else ', '}das war's von mir. Weiter geht's mit meinem Kollegen {nachredner}.")
    fertig = []
    for a in absaetze:
        a = " ".join(a.split())
        a = re.sub(r"\s[-–—]\s", ", ", a)               # Gedankenstrich -> Komma
        a = re.sub(r"(\d)\s?[-–]\s?(\d)", r"\1 bis \2", a)  # 1-2 -> 1 bis 2
        a = re.sub(r"(?<=[A-Za-zÄÖÜäöüß])-(?=[A-Za-zÄÖÜäöüß0-9])", " ", a)  # keine Bindestriche
        a = re.sub(r"(?<=\w)\s+-(?=\w)", " ", a)                        # "NAS -Geräte" -> "NAS Geräte"
        a = aussprache(a, extra_aussprache)
        a = zahlen_ausschreiben(a)
        a = a.replace("!", ".").replace("?.", "?")
        a = re.sub(r"\.{2,}", ".", a)
        a = re.sub(r"[,;]\s*\.", ".", a)                                   # "Backup,." -> "Backup."
        if not re.search(r"[.?]$", a):
            a += "."
        saetze = re.split(r"(?<=[.?])\s+", a)
        teile = []
        for i, s in enumerate(saetze):
            if not s:
                continue
            if i > 0 and rnd.random() < p_fuell:
                s = aehm + (s[0].lower() + s[1:] if not s.startswith(("Ich", "Sie", "Ihr")) else s)
            s = re.sub(r":\s+", f': <break time="{doppelpunktpause}ms"/>', s) if doppelpunktpause else s
            teile.append(s)
        fertig.append(f' <break time="{satzpause}ms"/>'.join(teile))
    ergebnis = f' <break time="{absatzpause}ms"/>\n'.join(fertig)
    ergebnis = ergebnis.replace(MARKE, aehm)
    ergebnis = pausen_zusammenfassen(ergebnis)
    ergebnis = re.sub(r"[ \t]{2,}", " ", ergebnis).strip()
    pausen_ms = sum(int(x) for x in re.findall(r'<break time="(\d+)ms"', ergebnis))
    woerter = len(re.sub(r"<[^>]+>", " ", ergebnis).split())
    sekunden = woerter / 150 * 60 + pausen_ms / 1000
    return {"text": ergebnis, "woerter": woerter, "pausen": ergebnis.count("<break"), "sekunden": round(sekunden),
            "zeichen": len(ergebnis)}


def api_anfrage(text: str, modell: str = "sonic-3", stimme_id: str = "", tempo: float = 1.0) -> dict:
    """Fertige Anfrage für die Cartesia-Schnittstelle (TTS Bytes) plus Befehl für die Windows-Eingabeaufforderung.
    Es wird nichts gesendet: Claude/das Programm ruft Cartesia nicht selbst auf (keine Kosten)."""
    body = {"model_id": modell or "sonic-3", "transcript": text,
            "voice": {"mode": "id", "id": stimme_id or "DEINE-STIMMEN-ID"},
            "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}}
    if re.match(r"sonic-3\.(\d+)", body["model_id"]) and float(body["model_id"][6:] or 0) >= 3.6:
        body["locale"] = "de-DE"        # ab Sonic 3.6: locale statt language
    else:
        body["language"] = "de"
        if tempo and abs(float(tempo) - 1.0) > 1e-6:
            body["generation_config"] = {"speed": float(tempo)}
    befehl = ('curl.exe -X POST https://api.cartesia.ai/tts/bytes ^\n'
              '  -H "Authorization: Bearer %CARTESIA_API_KEY%" ^\n'
              '  -H "Cartesia-Version: 2026-03-01" ^\n'
              '  -H "Content-Type: application/json" ^\n'
              '  -d "@cartesia_anfrage.json" --output sprache.wav')
    return {"json": json.dumps(body, ensure_ascii=False, indent=2), "befehl": befehl}


def senden(schluessel: str, anfrage_json: str, timeout: int = 300) -> bytes:
    """Schickt die fertige Anfrage an Cartesia und gibt die WAV-Daten zurück. Das verbraucht Cartesia-Guthaben,
    deshalb passiert es nur auf ausdrücklichen Klick."""
    import urllib.error
    import urllib.request
    try:
        body = json.loads(anfrage_json)
    except (TypeError, ValueError):
        raise RuntimeError("Die Cartesia-Anfrage ist nicht lesbar. Bitte den Text neu bauen.") from None
    if not (body.get("transcript") or "").strip():
        raise RuntimeError("Es gibt keinen Text zum Senden.")
    if (body.get("voice") or {}).get("id") in ("", None, "DEINE-STIMMEN-ID"):
        raise RuntimeError("Bitte zuerst die Stimmen-ID aus Cartesia eintragen.")
    req = urllib.request.Request("https://api.cartesia.ai/tts/bytes", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {schluessel}", "Cartesia-Version": "2026-03-01",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ton = r.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise RuntimeError("Cartesia-Schlüssel ungültig. Bitte in den Einstellungen prüfen.") from e
        if e.code == 402:
            raise RuntimeError("Cartesia-Guthaben aufgebraucht.") from e
        raise RuntimeError(f"Cartesia-Fehler {e.code}: {text}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cartesia nicht erreichbar: {e.reason}") from e
    if len(ton) < 100:
        raise RuntimeError("Cartesia hat keine Sprachdatei geliefert.")
    return ton
