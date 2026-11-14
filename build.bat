@echo off
REM Builds dist\HertaCapture\HertaCapture.exe  (then compile installer.iss with Inno Setup)
REM Files that don't exist are simply skipped.
set ADD=
if exist default_bg.png     set ADD=%ADD% --add-data "default_bg.png;."
if exist loading_bg.png     set ADD=%ADD% --add-data "loading_bg.png;."
if exist default_theme.json set ADD=%ADD% --add-data "default_theme.json;."
if exist icon.ico           set ADD=%ADD% --add-data "icon.ico;." --icon icon.ico

pyinstaller --noconfirm --windowed --name HertaCapture ^
  --collect-all customtkinter --collect-all rapidocr_onnxruntime ^
  --hidden-import cv2 %ADD% hreg.py
pause
