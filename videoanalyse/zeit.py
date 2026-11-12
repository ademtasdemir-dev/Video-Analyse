"""Zeitstempel und YouTube-Links."""
import re

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id(text: str) -> str | None:
    """Liest die 11-stellige Video-ID aus allen üblichen YouTube-Links (watch, youtu.be, shorts, embed, live) oder der ID selbst."""
    if not text:
        return None
    t = text.strip()
    if _ID.match(t):
        return t
    for muster in (r"[?&]v=([A-Za-z0-9_-]{11})", r"youtu\.be/([A-Za-z0-9_-]{11})",
                   r"/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})"):
        m = re.search(muster, t)
        if m:
            return m.group(1)
    return None


def ist_youtube(text: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", text or "")) and video_id(text) is not None


def ist_liste(text: str) -> bool:
    """Reine YouTube-Playlist (ohne einzelnes Video im Link), z. B. youtube.com/playlist?list=…"""
    t = text or ""
    return bool(re.search(r"(youtube\.com|youtu\.be)", t)) and bool(re.search(r"[?&]list=[\w-]+", t)) and video_id(t) is None


def hms(sek: float) -> str:
    """Sekunden -> 0:00 / 1:02:03 (YouTube-Schreibweise)."""
    s = int(max(0, sek))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def sekunden(text: str) -> float:
    """'1:02:03', '2:05', '2:05.5', '00:01:02,500' -> Sekunden."""
    t = text.strip().replace(",", ".")
    teile = t.split(":")
    if not teile or any(p == "" for p in teile):
        raise ValueError(f"Kein Zeitstempel: {text!r}")
    wert = 0.0
    for p in teile:
        wert = wert * 60 + float(p)
    return wert


def srt_zeit(sek: float) -> str:
    sek = max(0.0, sek)
    ms = int(round(sek * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def vtt_zeit(sek: float) -> str:
    return srt_zeit(sek).replace(",", ".")
