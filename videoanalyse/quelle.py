"""Video holen: YouTube-Link (yt-dlp) oder eigene Datei auf dem PC."""
import json
import shutil
from pathlib import Path

from . import werkzeug, zeit

FELDER = ("id", "title", "uploader", "channel", "duration", "description", "tags", "categories",
          "chapters", "upload_date", "view_count", "like_count", "thumbnail", "webpage_url", "language")


def _info_kurz(info: dict) -> dict:
    k = {f: info.get(f) for f in FELDER}
    k["chapters"] = [{"start": c.get("start_time", 0), "ende": c.get("end_time"), "titel": c.get("title", "")}
                     for c in (info.get("chapters") or [])]
    k["tags"] = k.get("tags") or []
    return k


def fehler_erklaeren(text: str) -> str:
    t = text.lower()
    if "sign in to confirm" in t or "not a bot" in t:
        return ("YouTube verlangt eine Anmeldung (Bot-Schutz). Unter Einstellungen „Browser-Anmeldung nutzen“ auf Firefox oder Edge "
                "stellen, dort bei YouTube angemeldet sein, und erneut versuchen.")
    if "private video" in t:
        return "Das Video ist privat. Nur nicht gelistete oder öffentliche Videos lassen sich analysieren."
    if "video unavailable" in t or "removed" in t:
        return "Das Video ist nicht verfügbar (gelöscht, gesperrt oder Link falsch)."
    if "age" in t and "confirm" in t:
        return "Das Video ist altersbeschränkt. Browser-Anmeldung in den Einstellungen nutzen."
    if "http error 403" in t:
        return "YouTube hat den Download abgelehnt (403). Später erneut versuchen oder Browser-Anmeldung nutzen."
    return text


QUALITAET = {"720": 720, "1080": 1080, "original": None}


def video_format(qualitaet) -> str:
    """yt-dlp-Formatwahl: höchstens 720p (Standard), höchstens 1080p oder das Original in bester Qualität."""
    q = str(qualitaet or "720").lower()
    if q not in QUALITAET:
        raise ValueError("Qualität muss 720, 1080 oder original sein.")
    h = QUALITAET[q]
    if h is None:
        return "bv*+ba/b"
    return f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/b[height<={h}][ext=mp4]/bv*[height<={h}]+ba/b"


def untertitel(url: str, ziel: Path, sprache: str = "", browser: str = "") -> tuple[Path, str] | None:
    """Holt vorhandene YouTube-Untertitel (auch automatisch erzeugte) als .vtt. Gibt (Datei, Sprache) zurück oder None."""
    import yt_dlp
    vid = zeit.video_id(url)
    if not vid:
        return None
    wunsch = [sprache] if sprache and sprache != "auto" else ["de", "en"]
    opts = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": wunsch,
            "subtitlesformat": "vtt", "outtmpl": str(ziel / "untertitel.%(ext)s"), "noplaylist": True,
            "quiet": True, "no_warnings": True, "noprogress": True}
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
    except Exception:
        return None
    for s in wunsch:
        p = ziel / f"untertitel.{s}.vtt"
        if p.is_file() and p.stat().st_size > 20:
            return p, s
    return None


def liste(url: str, browser: str = "", maximal: int = 200) -> list[str]:
    """Alle Video-Links einer YouTube-Playlist (höchstens `maximal`)."""
    import yt_dlp
    opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True, "playlistend": maximal}
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(fehler_erklaeren(str(e))) from None
    links = [f"https://www.youtube.com/watch?v={e['id']}" for e in (info.get("entries") or [])
             if e and zeit.video_id(str(e.get("id") or ""))]
    if not links:
        raise RuntimeError("In der Playlist wurden keine Videos gefunden.")
    return links


def direkt_laden(url: str, ziel: Path, art: str = "video", qualitaet="720", log=print, browser: str = "") -> Path:
    """Speichert nur das Video (.mp4) oder nur den Ton (.mp3) direkt in den Zielordner, ohne Analyse."""
    import yt_dlp
    vid = zeit.video_id(url)
    if not vid:
        raise ValueError("Das ist kein gültiger YouTube-Link.")
    ziel.mkdir(parents=True, exist_ok=True)

    def fortschritt(d):
        if d.get("status") == "downloading" and d.get("total_bytes"):
            log(f"Download {d['downloaded_bytes'] * 100 // d['total_bytes']} %", prozent=d["downloaded_bytes"] / d["total_bytes"])

    opts = {"outtmpl": str(ziel / "%(title).100B [%(id)s].%(ext)s"), "windowsfilenames": True, "noplaylist": True,
            "quiet": True, "no_warnings": True, "noprogress": True, "ffmpeg_location": werkzeug.ffmpeg(),
            "progress_hooks": [fortschritt]}
    if art == "audio":
        opts.update(format="ba/b", postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}])
    else:
        opts.update(format=video_format(qualitaet), merge_output_format="mp4")
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(fehler_erklaeren(str(e))) from None
    endung = (".mp3",) if art == "audio" else (".mp4", ".mkv", ".webm")
    treffer = sorted((p for p in ziel.glob(f"*[[]{vid}[]]*") if p.suffix.lower() in endung), key=lambda p: -p.stat().st_mtime)
    if not treffer:
        raise RuntimeError("Download fehlgeschlagen: keine Datei erhalten.")
    return treffer[0]


def von_youtube(url: str, ziel: Path, log=print, browser: str = "", qualitaet="720") -> dict:
    """Lädt das Video (Standard: höchstens 720p, reicht für die Analyse), Metadaten und Vorschaubild."""
    import yt_dlp
    vid = zeit.video_id(url)
    if not vid:
        raise ValueError("Das ist kein gültiger YouTube-Link.")
    ziel.mkdir(parents=True, exist_ok=True)

    def fortschritt(d):
        if d.get("status") == "downloading" and d.get("total_bytes"):
            log(f"Download {d['downloaded_bytes'] * 100 // d['total_bytes']} %", prozent=d["downloaded_bytes"] / d["total_bytes"])

    opts = {
        "format": video_format(qualitaet),
        "merge_output_format": "mp4",
        "outtmpl": str(ziel / "video.%(ext)s"),
        "noplaylist": True,
        "writethumbnail": True,
        "quiet": True, "no_warnings": True, "noprogress": True,
        "ffmpeg_location": werkzeug.ffmpeg(),
        "progress_hooks": [fortschritt],
    }
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(fehler_erklaeren(str(e))) from None
    video = next((p for p in ziel.glob("video.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm")), None)
    if not video:
        raise RuntimeError("Download fehlgeschlagen: keine Videodatei erhalten.")
    vorschau = next((p for p in ziel.glob("video.*") if p.suffix.lower() in (".jpg", ".webp", ".png")), None)
    k = _info_kurz(info)
    k.update({"video": str(video), "vorschaubild": str(vorschau) if vorschau else None, "quelle": "youtube"})
    (ziel / "info.json").write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")
    return k


def von_datei(pfad: str, ziel: Path) -> dict:
    p = Path(pfad.strip().strip('"'))
    if not p.is_file():
        raise FileNotFoundError(f"Datei nicht gefunden: {p}")
    ziel.mkdir(parents=True, exist_ok=True)
    kopie = ziel / ("video" + p.suffix.lower())
    shutil.copy2(p, kopie)
    k = {f: None for f in FELDER}
    k.update({"id": p.stem[:40], "title": p.stem, "duration": werkzeug.dauer(kopie), "tags": [], "chapters": [],
              "video": str(kopie), "vorschaubild": None, "quelle": "datei", "webpage_url": str(p)})
    (ziel / "info.json").write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")
    return k
