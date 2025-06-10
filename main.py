"""
Script to generate a Lua file for Steam depot decryption and manifest setting.
Now requires manual download of get_appinfo.txt (VDF) for appinfo.
Ignores depots that are DLCs or language-specific when no config entry exists.
Creates an output folder "[appID] GameName" and writes logs directly into a logs folder.
Includes a 1-second artificial delay to display the manifest-copying spinner.
Deletes get_appinfo.txt after each run.
Supports auto-restart with banner always on top.
"""

import os
import sys
import re
import json
import shutil
import winreg
import time
import vdf
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# Initialize console and logging constants
console = Console()
LOG_DIR = "logs"
LOG_FILE_TEMPLATE = os.path.join(LOG_DIR, "steam_response_{appid}.log")
CONFIG_FILE = os.path.join(os.getcwd(), "luamaker_config.json")


def pause_on_error():
    console.print("[bold red]An error occurred. See message above.[/]")
    console.print("Press Enter to exit...")
    input()
    sys.exit(1)


def detect_steam_config_path():
    for key_path in [
        r"SOFTWARE\\Wow6432Node\\Valve\\Steam",
        r"SOFTWARE\\Valve\\Steam"
    ]:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            config_path = os.path.join(install_path, "config")
            if os.path.isdir(config_path):
                return config_path
        except Exception:
            pass
    possible = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Steam", "config"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Steam", "config"),
    ]
    for path in possible:
        if os.path.isdir(path):
            return path
    return None


def prompt_for_steam_path():
    detected = detect_steam_config_path()
    if detected:
        console.print(f"Detected Steam config folder at [green]{detected}[/]")
        while True:
            choice = console.input("Is this correct? (Y/N): ").strip().lower()
            if choice in ("y", "n"):
                break
        if choice == "y":
            return detected
    console.print(":warning: Could not detect Steam config folder automatically.")
    while True:
        user_input = console.input("Please enter the Steam config folder path: ").strip().strip('"')
        if os.path.basename(user_input).lower() != "config":
            candidate = os.path.join(user_input, "config")
        else:
            candidate = user_input
        if os.path.isdir(candidate):
            return candidate
        console.print(f"[red]Path not found:[/] {candidate}")


def load_config_vdf(config_path):
    try:
        with open(os.path.join(config_path, "config.vdf"), "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        console.print(f"[bold red]Failed to read config.vdf:[/] {e}")
        pause_on_error()


def fetch_app_info(appid):
    # Manual VDF fetch: user must download get_appinfo.txt containing raw VDF
    console.print(f"[yellow]Fetch disabled; download raw VDF from https://steamui.com/api/get_appinfo.php?appid={appid} and save as [bold]get_appinfo.txt[/] here.[/]")
    while not os.path.isfile("get_appinfo.txt"):
        console.input("Press Enter after placing get_appinfo.txt here...")
    try:
        raw = open("get_appinfo.txt", 'r', encoding='utf-8').read()
    except Exception as e:
        console.print(f"[bold red]Failed to read get_appinfo.txt:[/] {e}")
        pause_on_error()
    try:
        parsed = vdf.loads(raw)
    except Exception as e:
        console.print(f"[bold red]VDF parsing failed:[/] {e}")
        pause_on_error()
    return parsed.get('appinfo', parsed)


def extract_app_name(appinfo):
    name = appinfo.get('common', {}).get('name')
    if not name:
        console.print("[bold red]App name not found in VDF.[/]")
        pause_on_error()
    console.print(f"[green]Found App Name:[/] {name}")
    return name


def extract_depots(appinfo):
    depots = appinfo.get('depots')
    if not isinstance(depots, dict):
        console.print("[bold red]No depots section in VDF.[/]")
        pause_on_error()
    result = {}
    for did, info in depots.items():
        if not isinstance(info, dict):
            continue
        manifests = info.get('manifests')
        if not isinstance(manifests, dict):
            continue
        public = manifests.get('public')
        if not isinstance(public, dict):
            continue
        gid = public.get('gid')
        if not gid:
            continue
        result[did] = gid
    if not result:
        console.print("[bold red]No valid depots found.[/]")
        pause_on_error()
    return result


def find_decryption_key(cfg_text, did):
    match = re.search(rf'"{did}"\s*\{{(.*?)\}}', cfg_text, re.DOTALL)
    if not match:
        raise ValueError(f"Depot {did} not in config.vdf")
    block = match.group(1)
    km = re.search(r'"DecryptionKey"\s*"([^"]+)"', block)
    if not km:
        raise ValueError(f"DecryptionKey missing for {did}")
    return km.group(1)


def copy_manifest_files(depots, out_dir):
    src = r"C:\\Program Files\\Steam\\depotcache"
    if not os.path.isdir(src):
        console.print(f"[bold red]Depotcache not found[/]")
        pause_on_error()
    count = 0
    for did in depots:
        for fn in os.listdir(src):
            if fn.startswith(f"{did}_") and fn.endswith(".manifest"):
                try:
                    shutil.copy2(os.path.join(src, fn), os.path.join(out_dir, fn))
                    count += 1
                except:
                    pass
    return count


def write_lua_file(appid, depots, keys, out_dir):
    path = os.path.join(out_dir, f"{appid}.lua")
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"addappid({appid})\n")
            for d in depots:
                f.write(f"addappid({d},1,\"{keys[d]}\")\n")
            for d, g in depots.items():
                f.write(f"setManifestid({d},\"{g}\")\n")
        return True
    except Exception as e:
        console.print(f"[bold red]Lua write failed:[/] {e}")
        return False


def organize_outputs(appid, name):
    safe = re.sub(r'[\\/:*?"<>|]', '_', f"[{appid}] {name}")
    od = os.path.join(os.getcwd(), safe)
    os.makedirs(od, exist_ok=True)
    return od


def load_saved_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            p = json.load(open(CONFIG_FILE, 'r', encoding='utf-8'))
            path = p.get('steam_config_path')
            if path and os.path.isdir(path):
                console.print(f"Using saved path: [green]{path}[/]")
                return path
        except:
            pass
    return None


def save_config(path):
    try:
        json.dump({'steam_config_path': path}, open(CONFIG_FILE, 'w', encoding='utf-8'), indent=2)
    except Exception as e:
        console.print(f"[yellow]Config save failed:[/] {e}")


def main():
    os.system("title LUA Maker v1.0.0 (10/06/2025) by xpokerr")
    while True:
        # Banner
        console.clear()
        ascii_text = r"""
    ======================================================================

    ██╗░░░░░██╗░░░██╗░█████╗░  ███╗░░░███╗░█████╗░██╗░░██╗███████╗██████╗░
    ██║░░░░░██║░░░██║██╔══██╗  ████╗░████║██╔══██╗██║░██╔╝██╔════╝██╔══██╗
    ██║░░░░░██║░░░██║███████║  ██╔████╔██║███████║█████═╝░█████╗░░██████╔╝
    ██║░░░░░██║░░░██║██╔══██║  ██║╚██╔╝██║██╔══██║██╔═██╗░██╔══╝░░██╔══██╗
    ███████╗╚██████╔╝██║░░██║  ██║░╚═╝░██║██║░░██║██║░╚██╗███████╗██║░░██║
    ╚══════╝░╚═════╝░╚═╝░░╚═╝  ╚═╝░░░░░╚═╝╚═╝░░╚═╝╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝

                        LUA Maker by xpokerr
                    Version 1.0.0 (10/06/2025)

    ======================================================================"""
        console.print(ascii_text, style="bold blue")

        appid = console.input("Enter Steam App ID: ").strip()

        # Configure Steam path
        steam_cfg = load_saved_config() or prompt_for_steam_path()
        if not os.path.isfile(CONFIG_FILE):
            save_config(steam_cfg)

        cfg_text = load_config_vdf(steam_cfg)
        appinfo = fetch_app_info(appid)
        name = extract_app_name(appinfo)
        depots = extract_depots(appinfo)

        decryption_keys = {}
        for d in list(depots):
            try:
                decryption_keys[d] = find_decryption_key(cfg_text, d)
            except ValueError as ve:
                info = appinfo.get('depots', {}).get(d, {})
                if 'dlcappid' in info or info.get('config', {}).get('language'):
                    depots.pop(d)
                    continue
                console.print(f"[bold red]Error for depot {d}:[/] {ve}")
                pause_on_error()

        out_dir = organize_outputs(appid, name)

        # Copy manifests with spinner and delay
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
            progress.add_task(description="Copying manifest files...", total=None)
            time.sleep(1)
            copied = copy_manifest_files(depots, out_dir)

        console.print(f"[green]Copied {copied} manifest file(s) to {out_dir}[/]")

        # Write Lua file
        if write_lua_file(appid, depots, decryption_keys, out_dir):
            console.print(f"[green]Lua file written to: {os.path.join(out_dir, f'{appid}.lua')}[/]")
        else:
            console.print(f"[bold red]Failed to write Lua file in {out_dir}[/]")

        console.print(f"[bold green]All done! Outputs in {out_dir}[/]")

        # Delete the get_appinfo.txt
        if os.path.isfile("get_appinfo.txt"):
            try:
                os.remove("get_appinfo.txt")
                console.print("[blue]Removed temporary get_appinfo.txt[/]")
            except Exception as e:
                console.print(f"[yellow]Warning: could not remove get_appinfo.txt:[/] {e}")

        # Prompt for restart
        choice = console.input("Run again? (Y/N): ").strip().lower()
        if choice != 'y':
            console.print("Goodbye!")
            break


if __name__ == '__main__':
    main()
