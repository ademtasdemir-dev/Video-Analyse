"""Update-Hinweis: fragt GitHub höchstens einmal pro Programmstart, ob es eine neuere Version gibt. Es wird nichts installiert."""
import json
import re
import urllib.request

REPO = "ademtasdemir-dev/YVdctuAio"
_ergebnis: dict | None = None


def nummer(text: str) -> tuple[int, ...]:
    """'v1.2.0' -> (1, 2, 0)"""
    return tuple(int(x) for x in re.findall(r"\d+", str(text))[:3])


def pruefen(version: str, repo: str = REPO, timeout: float = 5.0) -> dict:
    """Gibt {"neu": "1.2.0", "url": "…"} zurück, wenn es ein neueres Release gibt, sonst {}.
    Ohne Internet oder solange das Repo privat ist, bleibt es still."""
    global _ergebnis
    if _ergebnis is None:
        _ergebnis = {}
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                         headers={"Accept": "application/vnd.github+json", "User-Agent": "YVdctuAio"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            if nummer(d.get("tag_name", "")) > nummer(version):
                _ergebnis = {"neu": ".".join(map(str, nummer(d["tag_name"]))), "url": d.get("html_url") or f"https://github.com/{repo}/releases"}
        except Exception:
            pass
    return _ergebnis
