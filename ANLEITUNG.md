# Video-Analyse – Anleitung

Eigenständiges Programm im Dark Mode. Analysiert ein YouTube-Video (Link) oder eine eigene Videodatei:
Inhalt, Aufbau, Bilder, Transkript mit Zeitstempeln und Sprechern, Stimme/Musik getrennt, Strukturplan.
Dazu ein Baukasten, der aus jedem Text einen fertigen Cartesia-Sprechtext baut.

## Starten
1. Doppelklick auf **`start.bat`**.
2. Beim ersten Start richtet sich das Programm ein (einmalig einige Minuten, etwa 1 GB: Spracherkennung, Stimmentrennung, Sprechererkennung).
3. Das Programm öffnet sich in einem eigenen Fenster. Das schwarze Fenster dahinter offen lassen, es ist der Motor. Schließen beendet das Programm.

Voraussetzung: `uv` ist installiert (bei dir schon vorhanden). Sonst: `winget install astral-sh.uv`.

## Was die Reiter zeigen
| Reiter | Inhalt |
|---|---|
| Übersicht | Zusammenfassung, wichtigste Sätze, Schlagwörter, was zu sehen ist (Bildarten mit Anteil), wer spricht |
| Strukturplan | Kapitel mit Zeit, Phase, Inhalt, Bild/Darstellung, Sprechtempo. Klick springt im Video dorthin, Titel bearbeitbar, YouTube-Kapitelprüfung |
| Transkript | Jede Zeile mit Zeitstempel und Sprecher, Suche, Filter pro Sprecher. Export als .srt, .vtt, .txt, pro Sprecher |
| Bilder | Pro Szene ein Standbild mit Zeit und Bildart. Mit Gemini zusätzlich Beschreibung und Text im Bild. Dazu die Einzelbilder (siehe unten) |
| Audio | Original, nur Stimme, nur Musik/Hintergrund, jede Stimme einzeln. Je ein Klick für .wav oder .mp3 |
| Cartesia-Text | Text rein, fertiger Sprechtext raus (Regeln siehe unten), dazu der Befehl für die Cartesia-Schnittstelle |
| Export | Strukturplan (.md), Transkripte, Upload-Paket, alles als ZIP |
| Verlauf & Einstellungen | Frühere Analysen öffnen oder löschen, Gemini-Schlüssel, Modell |

**Jeder Download fragt nach dem Ordner.** Das Auswahlfenster kann hinter dem Programmfenster aufgehen.

## Einzelbilder (Bild-Option)
Zerlegt das Video in einzelne Bilder, ein Bild alle 1 bis 10 Sekunden (auch Kommawerte wie 1,5). Geht mit YouTube-Link und eigener Datei.
- **Bei der Analyse:** oben **Einzelbilder alle … s** anhaken und den Abstand eintragen.
- **Nur Bilder:** Haken bei **Nur Bilder (ohne Ton und Transkript)**. Dann gibt es in wenigen Sekunden nur Standbilder und Einzelbilder.
- **Nachträglich:** Reiter **Bilder** → Abstand eintragen → **Zerlegen**. Ein neuer Abstand ersetzt die alten Einzelbilder.
- Die Bilder haben die Auflösung des Videos (YouTube: höchstens 720p) und heißen z. B. `bild_00002_0-00-01.5.jpg` (Nummer und Zeit im Video).
- Speichern: **Alle in einen Ordner speichern** (legt einen Unterordner an) oder **Alle als ZIP speichern**.

## Gemini (optional, kostenlos)
Ohne Schlüssel läuft alles lokal auf deinem PC. Mit Schlüssel kommen dazu: ausführliche Zusammenfassung,
Kapitel mit Inhalt, Beschreibung jedes Standbilds, Text im Bild, Darstellung, Dramaturgie, Sprecherrollen.
- **Bei dir schon eingerichtet:** Schlüssel „Default Gemini Key“ aus dem Projekt *Automatischer YouTube-Upload*
  (AI Studio zeigt dort **Kostenlose Stufe**, also keine Kosten). Er steht nur lokal in `daten/einstellungen.json`.
- Prüfen: **Verlauf & Einstellungen → Schlüssel testen**.
- Anderer Schlüssel: https://aistudio.google.com/apikey → unter **Verlauf & Einstellungen** eintragen. Nimm einen Schlüssel
  aus einem Projekt mit „Kostenlose Stufe“. Schlüssel aus Projekten mit „Preisstufe 1“ kosten pro Aufruf Geld.
- Standardmodell: `gemini-3-flash-preview`. Ist es nicht verfügbar, nimmt das Programm automatisch `gemini-2.5-flash`.
- Bei **öffentlichen** YouTube-Videos schaut sich Gemini auf Wunsch das ganze Video an (kostenlos bis 8 Stunden Video pro Tag).
  Bei nicht gelisteten oder privaten Videos darf Gemini das nicht. Dann wertet es automatisch Transkript und Standbilder aus.
- Fehlt in der Antwort eine Bildbeschreibung, fragt das Programm für diese Bilder automatisch nach.

## Cartesia-Regeln (automatisch)
- Zahlen ausgeschrieben: 12 TB → zwölf Terabyte, 2,5 → zwei Komma fünf, 13:20 → dreizehn Minuten und zwanzig Sekunden
- IP-Netze: 192.168.10.0/27 → einhundertzweiundneunzig Punkt … slesh zwo siebn
- Aussprache: NAS → Naas, VLAN → Wii Lan, RAID → Rejd, CAD → Käht, Cat6A → Cat sechs A, DHCP-Server → DHCP Server
- Keine Bindestriche, keine Ausrufezeichen, jeder Satz endet mit Punkt, keine doppelten Pausen
- Pausen nach Satz, Absatz, Doppelpunkt und nach „ähm“ einstellbar, Füllwörter in vier Stufen
- Vorredner/Nachredner: „Ja, ähm, danke dir, Marcel.“ … „Weiter geht's mit meinem Kollegen Alexander.“
- Eigene Regeln pro Zeile, z. B. `USV = U S V`

Der Befehl für die Schnittstelle wird nur gebaut, das Programm schickt selbst nichts an Cartesia.

## Speicherplatz
Jede Analyse liegt in `daten/arbeit/<Video>`. Nach dem Speichern unter **Verlauf** löschen
(einzeln oder **Alle Analysen löschen**). Die einmal geladenen Modelle liegen in `daten/modelle`.

## Hinweise
- YouTube-Download nutzt yt-dlp. Meldet YouTube „Bot-Schutz“, unter Einstellungen „Browser-Anmeldung“ auf den Browser stellen, in dem du bei YouTube angemeldet bist.
- Sprechererkennung ist eine Schätzung. Bei bekannter Personenzahl oben „Sprecherzahl“ fest einstellen.
- Nur `127.0.0.1`: Das Programm ist von außen nicht erreichbar und nimmt nur Anfragen der eigenen Oberfläche an.

## Tests
```
uv run --python 3.12 pytest -q            # schnelle Tests
uv run --python 3.12 pytest -q -m langsam  # kompletter Durchlauf mit echten Modellen (VA_TESTSTIMME=<wav> setzen)
```


## Setup und portable Version bauen
```
uv run --python 3.12 python installer/bauen.py
```
Ergebnis in `build/` (nicht im Repo):
- `YVdctuAio_Setup_<Version>.exe`: Installation ohne Administratorrechte, mit Startmenü- und Desktop-Symbol und Deinstallation.
- `YVdctuAio-Portable.exe`: eine Datei ohne Installation. Entpackt sich beim ersten Start einmalig in den Ordner `YVdctuAio-Portable` daneben.

Beide enthalten Python, alle Pakete und die Modelle (Whisper „gut“, Stimmentrennung, Sprechererkennung) und brauchen weder uv noch Internet für eigene Videodateien.
In der installierten Version liegen Analysen und Einstellungen unter `%LOCALAPPDATA%\YVdctuAio\daten`, in der portablen im Ordner `daten` neben dem Programm.
Die Versionsnummer steht in `pyproject.toml` und in `videoanalyse/server.py` (`VERSION`). Gebraucht werden auf dem Bau-PC uv und Inno Setup 6.
