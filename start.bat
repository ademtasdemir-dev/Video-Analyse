@echo off
cd /d "%~dp0"
title Video-Analyse
set PYTHONUTF8=1
where uv >nul 2>nul
if errorlevel 1 (
  echo uv wurde nicht gefunden. Bitte installieren: winget install astral-sh.uv
  pause
  exit /b 1
)
echo Erster Start: Programme werden eingerichtet (einmalig einige Minuten) ...
uv run --python 3.12 start.py
if errorlevel 1 pause
