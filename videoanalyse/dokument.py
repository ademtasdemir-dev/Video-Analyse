"""Transkript und Strukturplan als Word-Dokument (.docx) und als PDF."""
from pathlib import Path

from .zeit import hms

SCHRIFTEN = [("segoeui.ttf", "segoeuib.ttf"), ("arial.ttf", "arialbd.ttf"), ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")]
SCHRIFT_ORDNER = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")]


def _teile(e: dict) -> dict:
    """Die Inhalte beider Dokumente, einmal zusammengestellt."""
    i, k, z = e["info"], e["kennzahlen"], e.get("zusammenfassung", {})
    kopf = [("Kanal", i.get("uploader") or "–"), ("Link", i.get("webpage_url") or "–"), ("Länge", hms(k["dauer"])),
            ("Sprecher", ", ".join(s["sprecher"] for s in e["sprecher"]) or "–"), ("Analyse", e.get("analyse_art") or "–")]
    kapitel = [(f"{hms(c['start'])}–{hms(c['ende'])}", c.get("phase") or "", c.get("titel") or "",
                (c.get("inhalt") or c.get("text") or "")[:600]) for c in e.get("kapitel", [])]
    return {"titel": i.get("title") or "Video", "kopf": kopf, "kurz": z.get("kurz") or "", "lang": z.get("ausfuehrlich") or "",
            "kern": z.get("kernaussagen") or [], "kapitel": kapitel,
            "zeilen": [(hms(x["start"]), x["sprecher"], x["text"]) for x in e["zeilen"]]}


def als_docx(e: dict, ziel: Path) -> Path:
    from docx import Document
    from docx.shared import Pt, RGBColor
    t = _teile(e)
    d = Document()
    d.styles["Normal"].font.name = "Calibri"; d.styles["Normal"].font.size = Pt(11)
    d.add_heading(t["titel"], 0)
    for name, wert in t["kopf"]:
        p = d.add_paragraph(); p.add_run(name + ": ").bold = True; p.add_run(str(wert))
    if t["kurz"] or t["lang"] or t["kern"]:
        d.add_heading("Zusammenfassung", 1)
        for absatz in (t["kurz"], t["lang"]):
            if absatz:
                d.add_paragraph(absatz)
        for punkt in t["kern"]:
            d.add_paragraph(str(punkt), style="List Bullet")
    if t["kapitel"]:
        d.add_heading("Strukturplan", 1)
        tab = d.add_table(rows=1, cols=4); tab.style = "Light Grid Accent 1"
        for zelle, text in zip(tab.rows[0].cells, ("Zeit", "Phase", "Kapitel", "Inhalt")):
            zelle.text = text
        for reihe in t["kapitel"]:
            for zelle, text in zip(tab.add_row().cells, reihe):
                zelle.text = str(text)
    if t["zeilen"]:
        d.add_heading("Transkript", 1)
        for zeit, sprecher, text in t["zeilen"]:
            p = d.add_paragraph()
            r = p.add_run(f"[{zeit}] "); r.font.color.rgb = RGBColor(0x8A, 0x6A, 0x1F)
            p.add_run(sprecher + ": ").bold = True
            p.add_run(text)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(ziel))
    return ziel


def _schrift() -> tuple[Path, Path] | None:
    for ordner in SCHRIFT_ORDNER:
        for normal, fett in SCHRIFTEN:
            if (ordner / normal).is_file() and (ordner / fett).is_file():
                return ordner / normal, ordner / fett
    return None


def als_pdf(e: dict, ziel: Path) -> Path:
    import logging
    from fpdf import FPDF
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # sonst bei jedem PDF Warnungen zur Schrift im Protokoll
    t = _teile(e)
    pdf = FPDF(format="A4"); pdf.set_auto_page_break(True, margin=15); pdf.set_margins(18, 16, 18); pdf.add_page()
    schrift = _schrift()
    if schrift:
        pdf.add_font("Text", "", str(schrift[0])); pdf.add_font("Text", "B", str(schrift[1]))
        name, sauber = "Text", str
    else:  # ohne passende Schrift: Standardschrift, unbekannte Zeichen werden ersetzt
        name, sauber = "Helvetica", lambda s: str(s).replace("–", "-").encode("latin-1", "replace").decode("latin-1")

    def absatz(text, fett=False, gross=10.5, hoehe=5.4, nach=1.5):
        pdf.set_font(name, "B" if fett else "", gross)
        pdf.multi_cell(0, hoehe, sauber(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(nach)

    def ueberschrift(text):
        pdf.ln(3); absatz(text, fett=True, gross=14, hoehe=7, nach=2)

    absatz(t["titel"], fett=True, gross=18, hoehe=9, nach=3)
    for bezeichnung, wert in t["kopf"]:
        absatz(f"{bezeichnung}: {wert}", nach=0)
    if t["kurz"] or t["lang"] or t["kern"]:
        ueberschrift("Zusammenfassung")
        for text in (t["kurz"], t["lang"]):
            if text:
                absatz(text)
        for punkt in t["kern"]:
            absatz("• " + str(punkt), nach=0.5)
    if t["kapitel"]:
        ueberschrift("Strukturplan")
        for zeit, phase, titel, inhalt in t["kapitel"]:
            absatz(f"{zeit}  {titel}" + (f"  ({phase})" if phase else ""), fett=True, nach=0.3)
            if inhalt:
                absatz(inhalt)
    if t["zeilen"]:
        ueberschrift("Transkript")
        for zeit, sprecher, text in t["zeilen"]:
            absatz(f"[{zeit}] {sprecher}: {text}", nach=0.8)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))
    return ziel
