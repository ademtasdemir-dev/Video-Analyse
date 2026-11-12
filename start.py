"""Startet die Video-Analyse und öffnet die Oberfläche im Browser."""
import ssl
import urllib.requests
import os

# SSL-Zertifikatsprüfung umgehen, um das "certificate has expired" Problem zu beheben
ssl._create_default_https_context = ssl._create_unverified_context

from videoanalyse.server import starten

if __name__ == "__main__":
    starten()
