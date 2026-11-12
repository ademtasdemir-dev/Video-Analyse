"""Erkennt, wie viele verschiedene Stimmen sprechen, und ordnet jede Zeile einer Stimme zu.

Verfahren: pro Zeile ein Stimm-Fingerabdruck (ECAPA-Modell von SpeechBrain, lokal), dann werden ähnliche
Fingerabdrücke zusammengefasst (hierarchisches Clustern mit Kosinus-Abstand). Kein Konto, kein Token nötig.
"""
from pathlib import Path

import numpy as np

from .transkript import verbinden

MIN_DAUER = 0.8  # kürzere Zeilen sind zu unsicher und bekommen die Stimme der Nachbarzeile


def clustern(emb: np.ndarray, schwelle: float = 0.55, anzahl: int | None = None) -> list[int]:
    """Average-Linkage-Clustering auf Kosinus-Abstand. Gibt pro Zeile eine Gruppennummer zurück.
    schwelle: maximaler mittlerer Abstand, bei dem zwei Gruppen noch als dieselbe Stimme gelten.
    anzahl: feste Sprecherzahl (überschreibt die Schwelle)."""
    n = len(emb)
    if n == 0:
        return []
    x = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
    d = 1 - x @ x.T
    gruppen = [[i] for i in range(n)]
    while len(gruppen) > 1:
        bester, paar = None, None
        for a in range(len(gruppen)):
            for b in range(a + 1, len(gruppen)):
                v = d[np.ix_(gruppen[a], gruppen[b])].mean()
                if bester is None or v < bester:
                    bester, paar = v, (a, b)
        if anzahl is not None:
            if len(gruppen) <= anzahl:
                break
        elif bester > schwelle:
            break
        a, b = paar
        gruppen[a] += gruppen[b]
        del gruppen[b]
    label = [0] * n
    for g, mitglieder in enumerate(sorted(gruppen, key=min)):
        for i in mitglieder:
            label[i] = g
    return label


def kleine_gruppen_aufloesen(label: list[int], emb: np.ndarray, dauern: list[float], min_sek: float = 4.0,
                             min_anteil: float = 0.03) -> list[int]:
    """Gruppen mit sehr wenig Redezeit (Räuspern, Lacher, Fehlzuordnung) gehören zur ähnlichsten großen Gruppe."""
    label = list(label)
    gesamt = sum(dauern) or 1
    while True:
        zeit = {}
        for l, d in zip(label, dauern):
            zeit[l] = zeit.get(l, 0) + d
        klein = [l for l, t in zeit.items() if t < max(min_sek, min_anteil * gesamt)]
        gross = [l for l in zeit if l not in klein]
        if not klein or not gross:
            break
        x = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
        mitte = {l: x[[i for i, k in enumerate(label) if k == l]].mean(0) for l in zeit}
        l = min(klein, key=lambda k: zeit[k])
        ziel = max(gross, key=lambda g: float(mitte[l] @ mitte[g]))
        label = [ziel if k == l else k for k in label]
    return label


class Stimmen:
    def __init__(self, cache: Path):
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy
        from .werkzeug import modell_ordner
        lokal = modell_ordner("ecapa")  # mitgeliefert: kein Download nötig
        self.m = EncoderClassifier.from_hparams(str(lokal) if lokal else "speechbrain/spkrec-ecapa-voxceleb", savedir=str(cache),
                                                run_opts={"device": "cpu"}, local_strategy=LocalStrategy.COPY,
                                                # sonst holt SpeechBrain die Gewichte trotz lokalem Ordner aus dem Internet
                                                overrides={"pretrained_path": str(lokal)} if lokal else {})

    def fingerabdruck(self, stueck: np.ndarray) -> np.ndarray:
        import torch
        with torch.no_grad():
            return self.m.encode_batch(torch.from_numpy(stueck.astype(np.float32))[None]).squeeze().numpy()


def zuordnen(zeilen: list[dict], audio16k: np.ndarray, cache: Path, anzahl: int | None = None,
             schwelle: float = 0.55, log=print) -> int:
    """Setzt zeile['sprecher'] = 'Sprecher N'. Gibt die Anzahl erkannter Stimmen zurück."""
    if not zeilen:
        return 0
    log("Lade Stimmerkennung …")
    st = Stimmen(cache)
    nutz, emb = [], []
    for i, z in enumerate(zeilen):
        if z["ende"] - z["start"] < MIN_DAUER:
            continue
        a, b = int(z["start"] * 16000), int(z["ende"] * 16000)
        emb.append(st.fingerabdruck(audio16k[a:b])); nutz.append(i)
        log(f"Stimmen {len(nutz) * 100 // len(zeilen)} %", prozent=len(nutz) / len(zeilen))
    if not nutz:
        for z in zeilen:
            z["sprecher"] = "Sprecher 1"
        return 1
    e = np.array(emb)
    label = clustern(e, schwelle=schwelle, anzahl=anzahl)
    if anzahl is None:
        label = kleine_gruppen_aufloesen(label, e, [zeilen[i]["ende"] - zeilen[i]["start"] for i in nutz])
    zu = dict(zip(nutz, label))
    for i, z in enumerate(zeilen):  # kurze Zeilen: nächstgelegene sichere Zeile
        if i not in zu:
            j = min(nutz, key=lambda k: abs(k - i))
            zu[i] = zu[j]
    # Zeilen, in denen die Stimme wechselt (ohne Pause), an der passenden Wortlücke teilen
    x = e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-9)
    mitte = {l: x[[k for k, m in enumerate(label) if m == l]].mean(0) for l in set(label)}
    if len(mitte) > 1:
        neu_z, neu_zu = [], {}
        for i, z in enumerate(zeilen):
            teile = _teilen(z, zu[i], audio16k, st, mitte) if z.get("_w") and z["ende"] - z["start"] >= 3 else [(z, zu[i])]
            for t, l in teile:
                neu_zu[len(neu_z)] = l; neu_z.append(t)
        zeilen[:] = neu_z
        zu = neu_zu
    reihenfolge = []
    for i in range(len(zeilen)):
        if zu[i] not in reihenfolge:
            reihenfolge.append(zu[i])
    for i, z in enumerate(zeilen):
        z["sprecher"] = f"Sprecher {reihenfolge.index(zu[i]) + 1}"
    return len(reihenfolge)


def _naechste(v, mitte):
    v = v / max(np.linalg.norm(v), 1e-9)
    return max(mitte, key=lambda l: float(v @ mitte[l]))


def _teilen(z, label, audio16k, st, mitte):
    w = z["_w"]
    if len(w) < 6:
        return [(z, label)]
    a, b = int(z["start"] * 16000), int(z["ende"] * 16000)
    n = b - a
    vorne = _naechste(st.fingerabdruck(audio16k[a:a + int(n * 0.4)]), mitte)
    hinten = _naechste(st.fingerabdruck(audio16k[b - int(n * 0.4):b]), mitte)
    if vorne == hinten:
        return [(z, label)]
    # Schnitt an der größten Wortlücke im mittleren Bereich
    kand = range(max(1, len(w) // 5), min(len(w) - 1, len(w) * 4 // 5) + 1)
    k = max(kand, key=lambda j: w[j]["s"] - w[j - 1]["e"])
    def zeile(ws):
        return {"start": ws[0]["s"], "ende": ws[-1]["e"], "text": verbinden(ws), "woerter": len(ws),
                "sprecher": z["sprecher"], "_w": ws}
    return [(zeile(w[:k]), vorne), (zeile(w[k:]), hinten)]


def statistik(zeilen: list[dict]) -> list[dict]:
    """Redeanteil pro Stimme."""
    summe = {}
    for z in zeilen:
        s = summe.setdefault(z["sprecher"], {"sprecher": z["sprecher"], "sekunden": 0.0, "woerter": 0, "zeilen": 0})
        s["sekunden"] += z["ende"] - z["start"]; s["woerter"] += z["woerter"]; s["zeilen"] += 1
    gesamt = sum(s["sekunden"] for s in summe.values()) or 1
    for s in summe.values():
        s["anteil"] = float(round(100 * s["sekunden"] / gesamt, 1)); s["sekunden"] = float(round(s["sekunden"], 1))
    return sorted(summe.values(), key=lambda s: s["sprecher"])
