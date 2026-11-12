"""Tests der Video-Analyse. Start: uv run pytest -q   (langsamer Gesamttest: uv run pytest -q -m langsam)"""
import json
import numpy as np
import pytest

from videoanalyse import bericht, cartesia, gemini, sprecher, struktur, szenen, transkript, zeit
from videoanalyse.analyse import _gemini_einbauen, ordner_name


# ---------- Links und Zeit ----------
@pytest.mark.parametrize("link", ["https://www.youtube.com/watch?v=bK6JBW4hPoU", "https://youtu.be/bK6JBW4hPoU?si=abc",
                                  "https://youtube.com/shorts/bK6JBW4hPoU", "https://www.youtube.com/embed/bK6JBW4hPoU",
                                  "https://m.youtube.com/watch?feature=share&v=bK6JBW4hPoU&t=10", "bK6JBW4hPoU"])
def test_video_id(link):
    assert zeit.video_id(link) == "bK6JBW4hPoU"


def test_kein_youtube():
    assert zeit.video_id("https://example.com/video") is None and not zeit.ist_youtube("C:/Videos/test.mp4")


def test_zeit_formate():
    assert zeit.hms(0) == "0:00" and zeit.hms(75.9) == "1:15" and zeit.hms(3725) == "1:02:05"
    assert zeit.sekunden("1:02:05") == 3725 and zeit.sekunden("00:01:02,500") == 62.5
    assert zeit.srt_zeit(62.5) == "00:01:02,500" and zeit.vtt_zeit(3600) == "01:00:00.000"


def test_ordner_name():
    assert ordner_name("https://youtu.be/bK6JBW4hPoU") == "bK6JBW4hPoU"
    assert ordner_name('"C:/Videos/Mein Video (1).mp4"') == "Mein_Video_1_"


# ---------- Cartesia ----------
def test_cartesia_regeln():
    r = cartesia.bauen("Das NAS hat 6 × 12 TB im RAID 6. Die CAD-Rechner bekommen 64 GB! Netz: 192.168.10.0/27 im VLAN 10.\n\nDer DHCP-Server ist da.",
                       fueller="aus")
    t = r["text"]
    for soll in ("Naas", "sechs mal zwölf Terabyte", "Rejd sechs", "Käht Rechner", "vierundsechzig Gigabyte",
                 "einhundertzweiundneunzig Punkt einhundertachtundsechzig Punkt zehn Punkt null slesh zwo siebn", "Wii Lan zehn", "DHCP Server"):
        assert soll in t, soll
    assert "!" not in t and "-" not in t.replace("<break", "") and not any(c.isdigit() for c in t.replace('time="', "").split('ms"')[-1])
    assert '<break time="700ms"/>' in t and '<break time="300ms"/>' in t


def test_cartesia_ein_gigabit_und_komma():
    t = cartesia.bauen("Jeder Platz kriegt 1 Gbit/s. Bei 2,5 Gbit/s dauert es 5:20.", fueller="aus")["text"]
    assert "ein Gigabit pro Sekunde" in t and "zwei Komma fünf Gigabit" in t and "fünf Minuten und zwanzig Sekunden" in t


def test_cartesia_keine_doppelten_pausen():
    t = cartesia.pausen_zusammenfassen('Hallo. <break time="100ms"/> <break time="700ms"/>, <break time="200ms"/>Weiter.')
    assert t.count("<break") == 1 and '700ms' in t


def test_cartesia_rahmen_und_fueller():
    r = cartesia.bauen("Satz eins ist hier. Satz zwei ist hier. Satz drei ist hier. Satz vier ist hier. Satz fünf ist hier.",
                       fueller="viel", vorredner="Marcel", nachredner="Alexander", seed=1)
    assert r["text"].startswith('Ja, ähm, <break time="200ms"/>danke dir, Marcel.') and r["text"].endswith("mit meinem Kollegen Alexander.")
    assert ", ähm," in r["text"] and r["sekunden"] > 0


def test_cartesia_aehm_pause_und_rahmen():
    r = cartesia.bauen("Erster Satz. Zweiter Satz mit 20 Plätzen. Dritter Satz.", fueller="viel", vorredner="Marcel",
                       nachredner="Alexander", aehm_pause=400, seed=3)["text"]
    assert r.startswith('Ja, ähm, <break time="400ms"/>danke dir, Marcel.')
    assert "zwanzig" in r and "400 Millisekunden" not in r and "vierhundert" not in r
    assert r.rstrip().endswith("geht's mit meinem Kollegen Alexander.")
    ohne = cartesia.bauen("Satz eins. Satz zwei.", fueller="aus", vorredner="Marcel")["text"]
    assert "ähm" not in ohne and ohne.startswith("Ja, danke dir, Marcel.")


def test_cartesia_api_anfrage():
    a = cartesia.api_anfrage('Hallo. <break time="400ms"/>Welt.', "sonic-3", "abc-123", 1.1)
    body = json.loads(a["json"])
    assert body["model_id"] == "sonic-3" and body["voice"]["id"] == "abc-123" and body["language"] == "de"
    assert body["generation_config"]["speed"] == 1.1 and "<break" in body["transcript"]
    neu = json.loads(cartesia.api_anfrage("x", "sonic-3.6")["json"])
    assert neu["locale"] == "de-DE" and "language" not in neu and "generation_config" not in neu
    assert "Cartesia-Version: 2026-03-01" in a["befehl"] and "@cartesia_anfrage.json" in a["befehl"]


def test_cartesia_eigene_aussprache():
    assert "U S V" in cartesia.bauen("Die USV hält.", fueller="aus", extra_aussprache={"USV": "U S V"})["text"]


# ---------- Transkript ----------
def test_zeilen_und_verbinden():
    w = [{"w": "Hallo", "s": 0, "e": 0.4}, {"w": "zusammen.", "s": 0.5, "e": 1.0}, {"w": "Netz", "s": 3.5, "e": 3.8},
         {"w": "192", "s": 3.9, "e": 4.2}, {"w": ".168", "s": 4.2, "e": 4.6}, {"w": ".1", "s": 4.6, "e": 4.8}]
    z = transkript.zeilen_bilden(w)
    assert len(z) == 2 and z[0]["text"] == "Hallo zusammen." and z[1]["text"] == "Netz 192.168.1" and z[1]["start"] == 3.5


def test_untertitel_einlesen():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<c>Hallo</c> Welt\n\n00:00:03.000 --> 00:00:05.500\nZweite Zeile\n"
    z = transkript.aus_untertitel(vtt)
    assert [x["text"] for x in z] == ["Hallo Welt", "Zweite Zeile"] and z[1]["ende"] == 5.5


# ---------- Sprecher ----------
def _emb(n, richtung, rng):
    return np.array([richtung + rng.normal(0, 0.15, len(richtung)) for _ in range(n)])


def test_clustern_findet_zwei_stimmen():
    rng = np.random.default_rng(0)
    a, b = np.eye(16)[0] * 3, np.eye(16)[1] * 3
    e = np.vstack([_emb(5, a, rng), _emb(4, b, rng), _emb(3, a, rng)])
    l = sprecher.clustern(e)
    assert l[:5] == [l[0]] * 5 and l[5:9] == [l[5]] * 4 and l[9:] == [l[0]] * 3 and l[0] != l[5]


def test_clustern_feste_anzahl_und_eine_stimme():
    rng = np.random.default_rng(1)
    e = _emb(6, np.eye(8)[2] * 3, rng)
    assert len(set(sprecher.clustern(e))) == 1
    assert len(set(sprecher.clustern(e, anzahl=2))) == 2


def test_kleine_gruppen_werden_aufgeloest():
    e = np.array([[1, 0], [1, 0.05], [0.9, 0.1], [0, 1]], float)
    assert sprecher.kleine_gruppen_aufloesen([0, 0, 0, 1], e, [10, 10, 10, 0.9]) == [0, 0, 0, 0]
    assert sprecher.kleine_gruppen_aufloesen([0, 0, 1, 1], e, [10, 10, 10, 10]) == [0, 0, 1, 1]


def test_statistik():
    z = [{"sprecher": "Sprecher 1", "start": 0, "ende": 3, "woerter": 6}, {"sprecher": "Sprecher 2", "start": 3, "ende": 4, "woerter": 2}]
    s = sprecher.statistik(z)
    assert s[0]["anteil"] == 75.0 and s[1]["woerter"] == 2
    json.dumps(s)


# ---------- Bilder ----------
def test_szenen_bilden():
    sz = szenen.szenen_bilden([0.5, 10.0, 10.8, 50.0], 100.0, max_laenge=30)
    starts = [s["start"] for s in sz]
    assert starts[0] == 0 and 10.0 in starts and 10.8 not in starts and 50.0 in starts
    assert all(s["ende"] - s["start"] <= 30.01 for s in sz)
    assert len(szenen.szenen_bilden([float(i) * 2 for i in range(1, 200)], 400, max_anzahl=20)) == 20


def test_bildart():
    folie = {"hintergrund": 0.7, "helligkeit": 0.85, "kanten": 0.03, "haut": 0, "saettigung": 0.05, "farben": 20}
    assert szenen.bildart(folie).startswith("Folie")
    assert szenen.bildart({**folie, "helligkeit": 0.03, "kanten": 0.001, "hintergrund": 0.2}).startswith("Schwarzbild")


def test_folie_mit_lupe_ist_folie_und_foto_nicht(tmp_path):
    from PIL import Image, ImageDraw
    import numpy as np
    im = Image.new("RGB", (640, 360), (246, 247, 245)); d = ImageDraw.Draw(im)
    for y in range(30, 330, 18):
        d.text((30, y), "VLAN 10 Arbeitsplaetze 192.168.10.0/27 Gateway " * 2, fill=(40, 40, 40))
    d.rounded_rectangle((20, 150, 620, 230), 12, fill=(252, 252, 252), outline=(20, 20, 20), width=3)  # Lupe
    d.text((40, 180), "VLAN 20 Server/NAS 192.168.20.0/28", fill="black")
    im.save(tmp_path / "lupe.png")
    assert szenen.bildart(szenen.merkmale(tmp_path / "lupe.png")).startswith("Folie")
    rng = np.random.default_rng(1)
    foto = (rng.random((360, 640, 3)) * 120 + np.linspace(40, 120, 640)[None, :, None]).clip(0, 255).astype("uint8")
    Image.fromarray(foto).save(tmp_path / "foto.png")
    assert not szenen.bildart(szenen.merkmale(tmp_path / "foto.png")).startswith("Folie")


def test_merkmale_und_standbild(tmp_path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 360), "white"); d = ImageDraw.Draw(im)
    for y in range(40, 300, 30):
        d.text((40, y), "Netzwerk und Backup im Architekturbüro " * 2, fill="black")
    im.save(tmp_path / "f.png")
    assert szenen.bildart(szenen.merkmale(tmp_path / "f.png")).startswith("Folie")


# ---------- Struktur ----------
def _zeilen():
    out, t = [], 0.0
    for abschnitt in range(4):
        for k in range(6):
            out.append({"start": t, "ende": t + 4, "text": f"Thema{abschnitt} Netzwerk Satz {k}.", "woerter": 4, "sprecher": "Sprecher 1"})
            t += 4.5
        t += 3  # lange Pause zwischen Abschnitten
    return out


def test_kapitel_automatisch():
    z = _zeilen(); dauer = z[-1]["ende"] + 2
    sz = [{"start": 0, "ende": dauer, "bildart": "Folie", "bild": "bild_001.jpg", "schnitt": False}]
    kap, quelle = struktur.kapitel_bilden(z, sz, dauer, ziel=4)
    assert quelle.startswith("automatisch") and kap[0]["start"] == 0 and len(kap) == 4
    assert kap[0]["phase"] == "Einstieg" and kap[-1]["phase"] == "Abschluss"
    assert bericht.kapitel_pruefen(kap) == []


def test_kapitel_aus_youtube():
    z = _zeilen(); dauer = z[-1]["ende"]
    yt = [{"start": 0, "titel": "Intro"}, {"start": 30, "titel": "Teil 2"}, {"start": 60, "titel": "Ende"}]
    kap, quelle = struktur.kapitel_bilden(z, [], dauer, yt)
    assert quelle.startswith("YouTube") and [k["titel"] for k in kap] == ["Intro", "Teil 2", "Ende"]


def test_kapitel_pruefen_und_beschreibung():
    assert "mindestens 3" in " ".join(bericht.kapitel_pruefen([{"start": 0, "titel": "a"}, {"start": 30, "titel": "b"}]))
    assert "0:00" in " ".join(bericht.kapitel_pruefen([{"start": 5, "titel": "a"}, {"start": 30, "titel": "b"}, {"start": 60, "titel": "c"}]))
    b = bericht.youtube_beschreibung("Intro-Text", [{"start": 0, "titel": "Start"}, {"start": 65, "titel": "Mitte"}])
    assert b == "Intro-Text\n\nKapitel:\n0:00 Start\n1:05 Mitte"


def test_zusammenfassung_und_schlagwoerter():
    z = [{"start": i, "ende": i + 1, "text": t, "woerter": len(t.split()), "sprecher": "Sprecher 1"} for i, t in enumerate([
        "Das Backup liegt auf dem zweiten NAS im Keller.", "Heute ist schönes Wetter draußen.",
        "Ein RAID ist kein Backup, deshalb brauchen wir das Backup NAS.", "Ok."])]
    sw = struktur.schlagwoerter(" ".join(x["text"] for x in z))
    assert "Backup" in sw[:2] and "NAS" in sw[:3]
    assert any("RAID" in s for s in struktur.zusammenfassung_lokal(z, 2))


def test_kennzahlen():
    k = struktur.kennzahlen(_zeilen(), 120, {"schnitte_pro_minute": 1.5})
    assert k["woerter"] == 96 and k["lange_pausen"] == 3 and 0 < k["sprechanteil"] <= 100
    assert "Wörter/Min." in struktur.tempo_text(k)


# ---------- Ausgaben ----------
def test_srt_vtt_txt():
    z = [{"start": 0, "ende": 2.5, "text": "Hallo", "sprecher": "Sprecher 1"}, {"start": 3, "ende": 3, "text": "Ja", "sprecher": "Sprecher 2"}]
    s = bericht.srt(z)
    assert "1\n00:00:00,000 --> 00:00:02,500\n[Sprecher 1] Hallo" in s and "00:00:03,000 --> 00:00:05,000" in s
    assert bericht.vtt(z).startswith("WEBVTT") and "<v Sprecher 2>Ja" in bericht.vtt(z)
    assert bericht.txt(z).splitlines()[0] == "[0:00 – 0:02] Sprecher 1: Hallo"
    assert bericht.nur_sprecher(z, "Sprecher 2") == "[0:03] Ja"


# ---------- Gemini (Netz simuliert) ----------
GEMINI_ANTWORT = {
    "zusammenfassung": {"kurz": "Es geht um Netzwerk und Backup.", "kernaussagen": ["RAID ist kein Backup"]},
    "kapitel": [{"start": 0, "titel": "Netzwerk", "phase": "Einstieg", "inhalt": "Switch", "visuell": "Folie"},
                {"start": "40", "titel": "Backup", "phase": "Hauptteil", "inhalt": "NAS", "visuell": "Tabelle"},
                {"start": 80, "titel": "Ende", "phase": "Abschluss"}],
    "bilder": [{"nr": 1, "bildtyp": "Folie", "beschreibung": "Titelfolie", "text_im_bild": "Netzwerk"}],
    "darstellung": {"stil": "Folien"}, "sprecher_rollen": [{"sprecher": "Sprecher 1", "rolle": "Vortragender"}],
    "titel_vorschlaege": ["Netzwerk einfach erklärt"],
}


def test_gemini_antwort_lesen():
    roh = {"candidates": [{"content": {"parts": [{"text": "```json\n" + json.dumps(GEMINI_ANTWORT) + "\n```"}]}}]}
    assert gemini.antwort_lesen(roh)["kapitel"][1]["titel"] == "Backup"
    with pytest.raises(RuntimeError):
        gemini.antwort_lesen({"promptFeedback": {"blockReason": "SAFETY"}})


def test_gemini_anfrage_und_aufruf(tmp_path, monkeypatch):
    from PIL import Image
    Image.new("RGB", (960, 540), "white").save(tmp_path / "bild_001.jpg")
    sz = [{"nr": 1, "start": 0, "ende": 100, "bild": "bild_001.jpg", "bild_zeit": 1.0, "bildart": "Folie"}]
    z = [{"start": 0, "ende": 2, "text": "Hallo", "sprecher": "Sprecher 1", "woerter": 1}]
    a = gemini.anfrage_bauen({"title": "T"}, z, sz, [{"start": 0, "titel": "x"}], tmp_path)
    teile = a["contents"][0]["parts"]
    assert any("inline_data" in t for t in teile) and "[0:00] Sprecher 1: Hallo" in json.dumps(teile, ensure_ascii=False)
    gesendet = {}
    class Antwort:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(GEMINI_ANTWORT)}]}}]}).encode()
    def urlopen(req, timeout=0):
        gesendet["key"] = req.headers.get("X-goog-api-key"); gesendet["url"] = req.full_url
        return Antwort()
    monkeypatch.setattr(gemini.urllib.request, "urlopen", urlopen)
    g = gemini.auswerten("TESTKEY", a)
    assert gesendet["key"] == "TESTKEY" and gemini.STANDARD_MODELL in gesendet["url"] and g["titel_vorschlaege"]


def test_gemini_ersatzmodell_bei_404(monkeypatch):
    import io, urllib.error
    urls = []
    class Antwort:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(GEMINI_ANTWORT)}]}}]}).encode()
    def urlopen(req, timeout=0):
        urls.append(req.full_url)
        if len(urls) == 1:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error":{"message":"models/x is not found"}}'))
        return Antwort()
    monkeypatch.setattr(gemini.urllib.request, "urlopen", urlopen)
    meldungen = []
    g = gemini.auswerten("K", {"contents": []}, "gemini-gibts-nicht", log=meldungen.append)
    assert "gemini-gibts-nicht" in urls[0] and "gemini-2.5-flash" in urls[1] and g["kapitel"] and meldungen


def test_gemini_mit_youtube_video(tmp_path):
    from PIL import Image
    for i in range(1, 31):
        Image.new("RGB", (64, 36), "white").save(tmp_path / f"bild_{i:03d}.jpg")
    sz = [{"nr": i, "start": i, "ende": i + 1, "bild": f"bild_{i:03d}.jpg", "bild_zeit": i, "bildart": "Folie"} for i in range(1, 31)]
    a = gemini.anfrage_bauen({"title": "T"}, [], sz, [], tmp_path, youtube_url="https://www.youtube.com/watch?v=bK6JBW4hPoU")
    teile = a["contents"][0]["parts"]
    assert teile[2] == {"file_data": {"file_uri": "https://www.youtube.com/watch?v=bK6JBW4hPoU"}}
    assert sum("inline_data" in t for t in teile) <= 12
    ohne = gemini.anfrage_bauen({"title": "T"}, [], sz, [], tmp_path)["contents"][0]["parts"]
    assert not any("file_data" in t for t in ohne) and sum("inline_data" in t for t in ohne) == 30


def test_gemini_einbauen():
    z = [{"start": float(t), "ende": t + 3.0, "text": "Wort " * 5, "woerter": 5, "sprecher": "Sprecher 1"} for t in range(0, 100, 5)]
    sz = [{"nr": 1, "start": 0, "ende": 100, "bild": "bild_001.jpg", "bildart": "Folie"}]
    e = {"zusammenfassung": {"kurz": "lokal"}, "sprecher": [{"sprecher": "Sprecher 1"}], "kapitel": []}
    _gemini_einbauen(e, GEMINI_ANTWORT, z, sz, 100.0)
    assert e["zusammenfassung"]["kurz"].startswith("Es geht") and len(e["kapitel"]) == 3
    assert e["kapitel"][1]["start"] == 40 and e["kapitel"][1]["ende"] == 80 and e["kapitel"][2]["ende"] == 100
    assert sz[0]["beschreibung"] == "Titelfolie" and e["sprecher"][0]["rolle"] == "Vortragender"
    e2 = {**e, "bild": {"bildarten": {"Folie": 100}}}
    _gemini_einbauen(e2, GEMINI_ANTWORT, z, sz, 100.0)
    assert list(e2["bild"]["bildarten"]) == [sz[0]["bildtyp"]]
    assert bericht.kapitel_pruefen(e["kapitel"]) == []


def test_youtube_fehler_verstaendlich():
    from videoanalyse.quelle import fehler_erklaeren
    assert "Bot-Schutz" in fehler_erklaeren("ERROR: Sign in to confirm you’re not a bot")
    assert "privat" in fehler_erklaeren("ERROR: Private video. Sign in")
    assert fehler_erklaeren("irgendwas") == "irgendwas"


def test_cartesia_transkript_fehler_werden_sauber():
    b = lambda t: cartesia.bauen(t, fueller="aus")["text"]
    assert b("Verkabelt wird mit CAT 6a.") == "Verkabelt wird mit Cat sechs A."
    assert "." not in b("Netz 192.168.10.0.2.7")[:-1] and "Punkt zwei Punkt sieben" in b("Netz 192.168.10.0.2.7")
    assert b("die beiden NAS -Geräte") == "die beiden Naas Geräte."
    assert b("ums Backup,.") == "ums Backup."
    assert b("Das kostet 1.000 Euro.") == "Das kostet eintausend Euro."


def test_gemini_ohne_video_bei_403(tmp_path, monkeypatch):
    import io, urllib.error
    from PIL import Image
    Image.new("RGB", (64, 36), "white").save(tmp_path / "bild_001.jpg")
    sz = [{"nr": 1, "start": 0, "ende": 10, "bild": "bild_001.jpg", "bild_zeit": 1, "bildart": "Folie"}]
    a = gemini.anfrage_bauen({"title": "T"}, [], sz, [], tmp_path, youtube_url="https://www.youtube.com/watch?v=bK6JBW4hPoU")
    def urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(b'{"error":{"message":"The caller does not have permission"}}'))
    monkeypatch.setattr(gemini.urllib.request, "urlopen", urlopen)
    with pytest.raises(gemini.VideoNichtErlaubt):
        gemini.auswerten("K", a)
    ohne = gemini.ohne_video(a)
    teile = ohne["contents"][0]["parts"]
    assert not any("file_data" in t for t in teile) and any("inline_data" in t for t in teile)
    assert not any(t.get("text", "").startswith("Das komplette Video") for t in teile)
    with pytest.raises(RuntimeError, match="403"):   # ohne Video: normaler Fehler, keine Schleife
        gemini.auswerten("K", ohne)


def test_gemini_fehlende_bilder_nachfragen(tmp_path):
    from PIL import Image
    for i in (1, 2, 3):
        Image.new("RGB", (64, 36), "white").save(tmp_path / f"bild_{i:03d}.jpg")
    sz = [{"nr": i, "start": i, "ende": i + 1, "bild": f"bild_{i:03d}.jpg", "bild_zeit": i, "bildart": "Folie"} for i in (1, 2, 3)]
    g = {"bilder": [{"nr": 1, "beschreibung": "Titelfolie"}, {"nr": 2, "beschreibung": ""}]}
    fehlen = gemini.fehlende_bilder(g, sz)
    assert [s["nr"] for s in fehlen] == [2, 3]
    teile = gemini.bilder_anfrage(fehlen, tmp_path)["contents"][0]["parts"]
    assert sum("inline_data" in t for t in teile) == 2 and "Bild 2" in teile[1]["text"]
