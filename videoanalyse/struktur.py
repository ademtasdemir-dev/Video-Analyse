"""Strukturplan (Kapitel), Kennzahlen und eine Zusammenfassung ohne KI aus Transkript und Bildwechseln."""
import re
from collections import Counter

STOPP = set("""der die das den dem des ein eine einer eines einem einen und oder aber auch als am an auf aus bei bin bis
bist da dann dass daß dein deine dem den denn der des dich dir doch du durch er es euch euer für hab habe haben hat
hatte hier ich ihr im in ist ja je jetzt kann kein keine man mehr mein mich mir mit muss nach nicht noch nun nur ob
oder ohne schon sehr sich sie sind so über um und uns unser unter vom von vor wann war waren was weil wenn wer
werden wie wir wird wo zu zum zur also ähm äh halt mal eben einfach genau gut ganz okay ok sozusagen ne wirklich
dieser diese dieses diesem diesen hier heute dort sein seine soll sollte will wollen würde gibt geht gehen kommt
machen macht sagen viel viele etwas immer wieder alle alles dazu davon damit darum weiter erst mal sehen sieht
the and to of a is in that it you for this on with are be""".split())


def woerter(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]+", text)


def schlagwoerter(text: str, n: int = 12) -> list[str]:
    """Häufigste aussagekräftige Wörter (Großschreibung zählt doppelt, weil Nomen meist den Inhalt tragen)."""
    z = Counter()
    form = {}
    for w in woerter(text):
        k = w.lower()
        if k in STOPP or len(k) < 3 or k.isdigit():
            continue
        z[k] += 2 if w[0].isupper() else 1
        form.setdefault(k, w)
    return [form[k] for k, _ in z.most_common(n)]


def saetze(zeilen: list[dict]) -> list[dict]:
    """Zeilen zu Sätzen mit Startzeit."""
    out, puffer, start = [], "", None
    for z in zeilen:
        for teil in re.split(r"(?<=[.!?])\s+", z["text"]):
            if not teil:
                continue
            if start is None:
                start = z["start"]
            puffer = (puffer + " " + teil).strip()
            if re.search(r"[.!?]$", teil):
                out.append({"start": start, "text": puffer}); puffer, start = "", None
    if puffer:
        out.append({"start": start or 0, "text": puffer})
    return out


def zusammenfassung_lokal(zeilen: list[dict], anzahl: int = 5) -> list[str]:
    """Die aussagekräftigsten Sätze in Originalreihenfolge (Auszug, keine KI)."""
    ss = saetze(zeilen)
    if not ss:
        return []
    alle = " ".join(s["text"] for s in ss)
    gewicht = {w.lower(): 1 + i * 0 for i, w in enumerate(schlagwoerter(alle, 25))}
    def punkte(s):
        ws = [w.lower() for w in woerter(s["text"])]
        if len(ws) < 6:
            return 0
        return sum(gewicht.get(w, 0) for w in ws) / (len(ws) ** 0.5)
    beste = sorted(range(len(ss)), key=lambda i: -punkte(ss[i]))[:anzahl]
    return [ss[i]["text"] for i in sorted(beste)]


def _kandidaten(zeilen, szenen, dauer):
    k = {}
    for s in szenen:
        if s.get("schnitt"):
            k[round(s["start"], 1)] = k.get(round(s["start"], 1), 0) + 2
    for a, b in zip(zeilen, zeilen[1:]):
        luecke = b["start"] - a["ende"]
        if luecke > 1.2:
            t = round(b["start"] - min(0.3, luecke / 2), 1)
            # Schnitt in der Nähe? Dann zählt die Stelle als starker Kapitelwechsel
            nah = [x for x in k if abs(x - t) < 1.6]
            if nah:
                k[nah[0]] += 2 + luecke
            else:
                k[t] = k.get(t, 0) + luecke
    return {t: v for t, v in k.items() if 15 < t < dauer - 10}


def kapitel_bilden(zeilen: list[dict], szenen: list[dict], dauer: float, yt_kapitel: list[dict] | None = None,
                   ziel: int | None = None, mindestabstand: float = 20.0) -> list[dict]:
    if yt_kapitel and len(yt_kapitel) >= 2:
        starts = [float(c["start"]) for c in yt_kapitel]
        titel = [c["titel"] for c in yt_kapitel]
        quelle = "YouTube-Kapitel des Videos"
    else:
        ziel = ziel or max(3, min(12, round(dauer / 55)))
        kand = _kandidaten(zeilen, szenen, dauer)
        gewaehlt = []
        for t, v in sorted(kand.items(), key=lambda x: -x[1]):
            if all(abs(t - g) >= mindestabstand for g in gewaehlt):
                gewaehlt.append(t)
            if len(gewaehlt) >= ziel - 1:
                break
        starts = [0.0] + sorted(gewaehlt)
        titel = [None] * len(starts)
        quelle = "automatisch aus Sprechpausen und Bildwechseln"
    kap = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else dauer
        z = [x for x in zeilen if s - 0.5 <= x["start"] < e - 0.5]
        text = " ".join(x["text"] for x in z)
        sw = schlagwoerter(text, 5)
        if not titel[i]:
            ersterSatz = saetze(z)[0]["text"] if z else ""
            titel[i] = " · ".join(sw[:3]) if sw else (ersterSatz[:60] or f"Abschnitt {i + 1}")
        sz = [x for x in szenen if s - 0.5 <= x["start"] < e - 0.5] or [min(szenen, key=lambda x: abs(x["start"] - s))] if szenen else []
        arten = Counter(x["bildart"] for x in sz)
        minuten = max((e - s) / 60, 1e-6)
        wz = sum(x["woerter"] for x in z)
        kap.append({
            "nr": i + 1, "start": round(s, 2), "ende": round(e, 2), "titel": titel[i],
            "phase": "Einstieg" if i == 0 else ("Abschluss" if i == len(starts) - 1 else "Hauptteil"),
            "schlagwoerter": sw, "text": text, "woerter": wz, "wpm": round(wz / minuten),
            "sprecher": sorted({x["sprecher"] for x in z}),
            "szenen": len(sz), "bildart": arten.most_common(1)[0][0] if arten else "–",
            "bild": sz[0]["bild"] if sz else None, "inhalt": "", "visuell": "",
        })
    return kap, quelle


def kennzahlen(zeilen: list[dict], dauer: float, bild: dict) -> dict:
    sprechzeit = sum(z["ende"] - z["start"] for z in zeilen)
    wz = sum(z["woerter"] for z in zeilen)
    pausen = sum(1 for a, b in zip(zeilen, zeilen[1:]) if b["start"] - a["ende"] > 1.5)
    fuell = sum(len(re.findall(r"\b(ähm|äh|ehm|hm|öhm)\b", z["text"], re.I)) for z in zeilen)
    return {"dauer": round(dauer, 1), "woerter": wz, "wpm": round(wz / max(sprechzeit / 60, 1e-6)),
            "sprechanteil": round(100 * sprechzeit / max(dauer, 1e-6), 1), "lange_pausen": pausen, "fuellwoerter": fuell,
            "schnitte_pro_minute": bild.get("schnitte_pro_minute", 0),
            "einblendungen_pro_minute": bild.get("einblendungen_pro_minute", 0), "mittlere_szenenlaenge": bild.get("mittlere_szenenlaenge", 0)}


def tempo_text(k: dict) -> str:
    w = k["wpm"]
    t = "ruhig" if w < 120 else "normal" if w < 160 else "schnell"
    s = k["schnitte_pro_minute"]
    b = "wenige Bildwechsel" if s < 2 else "regelmäßige Bildwechsel" if s < 8 else "sehr schnelle Schnitte"
    e = k.get("einblendungen_pro_minute", 0)
    zus = f", dazu {e} kleinere Bildänderungen/Einblendungen pro Minute" if e else ""
    return f"Sprechtempo {t} ({w} Wörter/Min.), {b} ({s} pro Minute{zus}), Sprechanteil {k['sprechanteil']} %."
