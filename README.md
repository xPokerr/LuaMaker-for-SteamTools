# LuaMaker for SteamTools

LuaMaker is a Windows command-line tool that generates SteamTools-ready Lua files and copies matching depot manifests from games already installed through Steam.

It automatically fetches app metadata with SteamCMD, extracts usable depot keys from your local Steam config, includes DLC app IDs when available, and exports everything into a clean output folder.

---

## Features

* Automatically bootstraps `steamcmd.exe` if it is missing.
* Detects your local Steam `config` and `depotcache` folders.
* Saves the detected Steam config path to `luamaker_config.json`.
* Fetches and logs app info to `logs/steam_response_<APPID>.log`.
* Extracts public depot manifest IDs from Steam app info.
* Reads depot decryption keys from your local `config.vdf`.
* Includes DLC app IDs when Steam exposes them in `extended.listofdlc`.
* Copies matching `.manifest` files into `[APPID] Game Name`.
* Generates a SteamTools Lua file with:
  * `addappid(appID)`
  * `addappid(dlcAppID)`
  * `addappid(depotID,1,"decryptionKey")`
  * `setManifestid(depotID,"gid")`
* Provides an animated terminal banner and a repeat prompt with default `Yes`.

---

## Requirements

* Windows 10 or newer
* Steam installed
* The target game already installed in Steam
* Python 3.10+ if running from source

Python dependencies:

```bash
pip install requests vdf rich
```

---

## Repository Layout

* `main.py`: thin entrypoint used by PyInstaller
* `luamaker_app.py`: main application logic
* `1.2.3.py`: compatibility wrapper for the current script version
* `main.spec`: PyInstaller spec file
* `build.bat`: helper to build a versioned executable
* `test_main_module.py`: automated tests for core logic

---

## Running from Source

```bash
python main.py
```

What happens:

1. LuaMaker shows the animated header in the terminal.
2. You enter a Steam App ID.
3. The tool fetches app info via SteamCMD.
4. It resolves available depots, keys, DLC app IDs, and manifest files.
5. It creates an output folder named `[APPID] Game Name`.
6. It writes `<APPID>.lua` inside that folder.
7. It asks `Process another App ID? (Y/n):` and pressing Enter continues by default.

---

## Standalone Executable

If you use the built `.exe`:

1. Place the executable in any folder you want.
2. Launch it normally.
3. On first run, LuaMaker auto-detects your Steam config path and stores it in `luamaker_config.json`.
4. Enter the Steam App ID you want to export.
5. The tool exports manifests and Lua files into a dedicated output folder beside the executable.

---

## Building the EXE

PyInstaller:

```bash
pyinstaller --clean --noconfirm .\main.spec
```

Or with the helper script:

```bat
build.bat
```

The executable is generated in `dist/`.

---

## Testing

Run the automated tests:

```bash
python -m unittest .\test_main_module.py -v
```

Recommended local verification before release:

```bash
python -m py_compile .\luamaker_app.py .\main.py .\1.2.3.py .\test_main_module.py
pyinstaller --clean --noconfirm .\main.spec
```

---

## Troubleshooting

* If Steam app info parsing fails, inspect `logs/steam_response_<APPID>.log`.
* If some depots are skipped, it usually means Steam did not expose a usable local decryption key for those depots.
* If you need to re-detect Steam paths, delete `luamaker_config.json` and launch again.

---

## License

MIT (c) xPokerr
