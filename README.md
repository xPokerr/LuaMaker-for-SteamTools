# LuaMaker for SteamTools
A command-line Python tool to automate creation of a Steam depot Lua file with depot decryption keys and manifest IDs.

Easily create lua and manifest for SteamTools from your installed Steam games!

---

## Features

* Fetches Steam app metadata (VDF format) via **SteamCMD**.
* Extracts depot IDs and public manifest GIDs.
* Reads local `config.vdf` for depot decryption keys.
* Skips DLC or language-only depots when no key is available.
* Copies available manifest files into a dedicated output folder.
* Displays DLC names when extracting manifest files (e.g. `Game - DLC`).
* Generates a Lua file (`<APPID>.lua`) containing:

  * `addappid(appID)`
  * `addappid(depotID,1,"decryptionKey")`
  * `setManifestid(depotID,"gid")`
* Persists Steam config path in `luamaker_config.json` on first run.
* Automatically restarts after completion if requested.

---
## Tool Screenshot

![image](https://github.com/user-attachments/assets/dd4f60f1-de5f-4adb-9179-47e31b502d15)

## Extracted Game
![image](https://github.com/user-attachments/assets/e30f722e-5f73-4ceb-b213-1c9f62329fd3)

---

## Usage (Standalone Executable)

If you are running the executable, follow these steps:

1. Copy the .exe to any folder where you want to run it (no Python required).
2. Launch by double-clicking the .exe
3. On first launch, confirm or enter your Steam `config` folder. This path is saved in `luamaker_config.json`.
4. When prompted enter the Steam App ID of the game you already have in your library and want to export.
5. The tool will automatically copy manifests to `[<APPID>] <GameName>` folder and generate `<APPID>.lua`.
6. Choose **Y** to restart and export other games or **N** to exit.

---


## Prerequisites (if running the python file)

* Windows 10 or newer
* Python 3.8+
* Installed Python packages:

  * `requests`
  * `vdf`
  * `rich`

---

## Installation

1. Clone or download this repository.
2. (Optional) Create and activate a Python virtual environment:

   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
3. Install dependencies:

   ```bash
   pip install requests vdf rich
   ```

---

## Configuration File

On first run, the script will detect your Steam `config` folder (via registry or common paths) and ask you to confirm or enter it manually. That path is saved in `luamaker_config.json` in the script directory. On subsequent runs, that saved path is used automatically.

If you ever need to change it, delete or edit `luamaker_config.json`.

---

## Usage

1. Run the script:

   ```bash
   python main.py
   ```
2. When prompted, enter the **Steam App ID** (numeric).
3. The tool will:

   * Fetch and log raw VDF response to `logs/steam_response_<APPID>.log`.
   * Extract and display the game name.
   * Copy any matching `.manifest` files (shows spinner).
   * Create an output folder named `[<APPID>] <GameName>`.
   * Generate `<APPID>.lua` inside that folder.
4. After completion, choose **Y** to run again or **N** to exit.

---

## Troubleshooting

* **Parsing errors**: Check the raw VDF response in `logs/steam_response_<APPID>.log` for malformed data.

---

## License

MIT © xPokerr

---

Generated on 2025-05-25
