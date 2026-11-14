# ✦ Herta Capture

Hotkey screenshots, text detection (OCR) and an image / point auto-clicker for Windows, with a purple glass UI inspired by The Herta (Honkai: Star Rail).

## Features
- **Capture** the whole screen, a region, or a single window with a hotkey (default `F8`)
- **Text detection** with RapidOCR or Tesseract, auto-copied to your clipboard
- **Embed** another program inside the app and click it like normal
- **Auto click sequence**: image steps and exact click points, each point with its own repeat count
- Loop, delay, skip-if-not-found, optional scroll-down
- **Discord webhook**: sends a loot screenshot when a round finishes
- Glass UI with your own background picture, position, zoom and transparency

## Install (easy)
1. Go to **Releases** and download `HertaCapture-Setup.exe`
2. Run it. Windows may show "unknown publisher" (the installer isn't code-signed): click **More info → Run anyway**
3. Start **Herta Capture** from the Start menu

## Run from source
```
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe hreg.py
```

## Build the installer yourself
1. Run `build.bat` (needs PyInstaller, see `requirements.txt`)
2. Open `installer.iss` in [Inno Setup](https://jrsoftware.org/isinfo.php) and press Compile
3. The installer appears in `installer\`

## Customize
| File (next to the app) | What it does |
|---|---|
| `default_bg.png` | Main background picture |
| `loading_bg.png` | Picture on the loading screen |
| `icon.ico` | Window / taskbar icon |
| `default_theme.json` | Default look (made with Settings → *Save current look as default*) |

## Notes
- Auto click uses your **real mouse**, so keep the target window visible.
- Hotkeys use the `keyboard` library, which some antivirus programs flag. It's a false positive; the source is right here.
- Your Discord webhook URL is stored in `settings.json`. **Never share or upload that file.**
- Tesseract is optional: install it from https://github.com/UB-Mannheim/tesseract/wiki if you want that engine.

## Credits
Background art belongs to its original artists. Honkai: Star Rail and The Herta belong to HoYoverse. This is an unofficial fan project.
