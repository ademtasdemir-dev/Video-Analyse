"""Kompletter Durchlauf mit echten Modellen auf einem erzeugten Video: zwei Stimmen + Hintergrundmusik + 3 Bildwechsel.
Start: uv run pytest -q -m langsam"""
import os
from pathlib import Path

import pytest

from videoanalyse import analyse, werkzeug

QUELLE = os.environ.get("VA_TESTSTIMME")  # WAV mit einer echten Stimme (mind. 60 s)


@pytest.mark.langsam
@pytest.mark.skipif(not QUELLE, reason="VA_TESTSTIMME nicht gesetzt")
def test_gesamt(tmp_path):
    f = werkzeug.lauf
    a = tmp_path / "a.wav"; b = tmp_path / "b.wav"
    f(["-v", "error", "-y", "-ss", "0", "-t", "20", "-i", QUELLE, "-ac", "1", "-ar", "44100", str(a)], check=True)
    f(["-v", "error", "-y", "-ss", "100", "-t", "20", "-i", QUELLE, "-ac", "1", "-af", "asetrate=44100*1.4,aresample=44100,atempo=0.714", "-ar", "44100", str(b)], check=True)
    video = tmp_path / "test.mp4"
    f(["-v", "error", "-y", "-i", str(a), "-i", str(b), "-f", "lavfi", "-i", "sine=f=220:d=40", "-f", "lavfi", "-i", "color=c=white:s=640x360:d=20",
       "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=20", "-filter_complex",
       "[0][1]concat=n=2:v=0:a=1[s];[2]volume=0.15[m];[s][m]amix=2:normalize=0[a];[3][4]concat=n=2:v=1:a=0[v]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)
    fs = analyse.Fortschritt()
    e = analyse.analysieren(str(video), {"trennen": True, "sprecher": True, "modell": "base", "gemini": False},
                            tmp_path / "arbeit", Path(os.environ.get("VA_CACHE", tmp_path / "cache")), {}, fs)
    assert fs.fehler is None and all(v in ("fertig", "übersprungen") for v in fs.status.values())
    assert len(e["sprecher"]) == 2, e["sprecher"]
    assert len(e["zeilen"]) > 3 and e["bild"]["schnitte"], e["bild"]["schnitte"]
    ordner = Path(e["ordner"]) if Path(e["ordner"]).is_absolute() else tmp_path / "arbeit" / e["ordner"]
    for p in list(e["audio"].values()) + list(e["exporte"].values()):
        assert (ordner / p).is_file() and (ordner / p).stat().st_size > 0, p
    assert "Sprecher 2" in (ordner / "export" / "transkript.srt").read_text(encoding="utf-8")
