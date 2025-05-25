"""
Script to generate a Lua file for Steam depot decryption and manifest setting.
Fetches VDF-formatted appinfo from Steam, parses both remote and local VDF data.
Ignores depots that are DLCs (contain 'dlcappid') or language-specific when no config entry exists.
Creates an output folder "[appID] GameName", saves Steam config location in a .config file,
and writes logs directly into a logs folder.
Includes a 1-second artificial delay to display the manifest-copying spinner.
"""

import os
import sys
import re
import json
import shutil
import winreg
import time
import requests
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
    """
    Attempt to detect the Steam config folder on Windows by checking common registry keys
    and default installation paths.
    Returns the full path to the Steam 'config' folder if found, otherwise None.
    """
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
        except OSError:
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
            choice = console.input("Is this correct? ([bold]Y[/]/[bold]N[/]): ").strip().lower()
            if choice in ("y", "n"):
                break
        if choice == "y":
            return detected
    else:
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
    config_file = os.path.join(config_path, "config.vdf")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        console.print(f"[bold red]Failed to read config.vdf:[/] {e}")
        pause_on_error()


def fetch_app_info(appid):
    os.makedirs(LOG_DIR, exist_ok=True)
    url = f"https://steamui.com/get_appinfo.php?appid={appid}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        raw = response.text
        log_path = LOG_FILE_TEMPLATE.format(appid=appid)
        try:
            with open(log_path, 'w', encoding='utf-8') as lf:
                lf.write(raw)
            console.print(f"[blue]Raw VDF response logged to {log_path}[/]")
        except Exception as log_err:
            console.print(f"[yellow]Warning: failed to write log file:[/] {log_err}")
        cleaned = raw.rstrip('\x00').strip()
        try:
            parsed = vdf.loads(cleaned)
        except Exception as vdf_err:
            snippet = cleaned[:500].replace('\n', ' ')
            console.print(f"[yellow]VDF parsing error:[/] {vdf_err}")
            console.print(f"[yellow]Response snippet (first 500 chars):[/] {snippet} ...")
            pause_on_error()
        return parsed.get('appinfo', parsed)
    except Exception as e:
        console.print(f"[bold red]HTTP request failed:[/] {e}")
        pause_on_error()


def extract_app_name(appinfo):
    name = appinfo.get('common', {}).get('name')
    if not name:
        console.print("[bold red]App name not found in response.[/]")
        pause_on_error()
    console.print(f"[green]Found App Name:[/] {name}")
    return name


def extract_depots(appinfo):
    depots = appinfo.get('depots')
    if not isinstance(depots, dict):
        console.print("[bold red]No depots section found or invalid format in response.[/]")
        pause_on_error()
    result = {}
    for depot_id, info in depots.items():
        if not isinstance(info, dict):
            continue
        manifests = info.get('manifests')
        if not isinstance(manifests, dict):
            continue
        public = manifests.get('public')
        if not isinstance(public, dict):
            continue
        gid = public.get('gid')
        if not isinstance(gid, str) or not gid:
            continue
        result[depot_id] = gid
    if not result:
        console.print("[bold red]No valid depots with manifests/public/gid found.[/]")
        pause_on_error()
    return result


def find_decryption_key(config_text, depot_id):
    pattern = rf'"{re.escape(depot_id)}"\s*\{{(.*?)\}}'
    match = re.search(pattern, config_text, re.DOTALL)
    if not match:
        raise ValueError(f"Depot {depot_id} block not found in config.vdf")
    block = match.group(1)
    key_match = re.search(r'"DecryptionKey"\s*"([^"]+)"', block)
    if not key_match:
        raise ValueError(f"DecryptionKey not found for depot {depot_id}")
    return key_match.group(1)


def copy_manifest_files(depots, out_dir):
    src = r"C:\\Program Files\\Steam\\depotcache"
    if not os.path.isdir(src):
        console.print(f"[bold red]Depotcache not found at {src}[/]")
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


def write_lua_file(appid, depots, decryption_keys, output_dir):
    file_name = f"{appid}.lua"
    out_path = os.path.join(output_dir, file_name)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f'addappid({appid})\n')
            for depot_id in depots:
                f.write(f'addappid({depot_id},1,"{decryption_keys[depot_id]}")\n')
            for depot_id, gid in depots.items():
                f.write(f'setManifestid({depot_id},"{gid}")\n')
        return True
    except Exception as e:
        console.print(f"[bold red]Failed to write Lua file:[/] {e}")
        return False


def organize_outputs(appid, name):
    safe_name = re.sub(r'[\\/:*?"<>|]', '', f"[{appid}] {name}")
    output_dir = os.path.join(os.getcwd(), safe_name)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def load_saved_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            data = json.load(open(CONFIG_FILE, 'r', encoding='utf-8'))
            path = data.get('steam_config_path')
            if path and os.path.isdir(path):
                console.print(f"Using saved Steam config path: [green]{path}[/]")
                return path
        except Exception:
            pass
    return None


def save_config(path):
    try:
        json.dump({'steam_config_path': path}, open(CONFIG_FILE, 'w', encoding='utf-8'), indent=2)
    except Exception as e:
        console.print(f"[yellow]Warning: failed to write config file:[/] {e}")


def main():
    os.system("title LUA Maker v1.0.0 (25/05/2025) by xpokerr")
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
                    Version 1.0.0 (25/05/2025)

    ======================================================================"""
        console.print(ascii_text, style="bold blue")

        appid = console.input("Enter Steam App ID: ").strip()

        # Load or prompt Steam config path
        steam_cfg = load_saved_config() or prompt_for_steam_path()
        if not os.path.isfile(CONFIG_FILE):
            save_config(steam_cfg)

        cfg_text = load_config_vdf(steam_cfg)

        appinfo = fetch_app_info(appid)
        name = extract_app_name(appinfo)
        depots = extract_depots(appinfo)

        decryption_keys = {}
        for did in list(depots):
            try:
                decryption_keys[did] = find_decryption_key(cfg_text, did)
            except ValueError as ve:
                info = appinfo.get('depots', {}).get(did, {})
                if 'dlcappid' in info or info.get('config', {}).get('language'):
                    depots.pop(did)
                    continue
                console.print(f"[bold red]Error for depot {did}:[/] {ve}")
                pause_on_error()

        out_dir = organize_outputs(appid, name)

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
            progress.add_task(description="Copying manifest files...", total=None)
            time.sleep(1)
            copied = copy_manifest_files(depots, out_dir)

        console.print(f"[green]Copied {copied} manifest file(s) to {out_dir}[/]")

        if write_lua_file(appid, depots, decryption_keys, out_dir):
            console.print(f"[green]Lua file written to: {os.path.join(out_dir, f'{appid}.lua')}[/]")
        else:
            console.print(f"[bold red]Failed to write Lua file in {out_dir}[/]")

        console.print(f"[bold green]All done! Outputs in {out_dir}[/]")

        # Prompt to restart or exit
        choice = console.input("Run again? (Y/N): ").strip().lower()
        if choice != 'y':
            console.print("Exiting. Goodbye!")
            break

if __name__ == '__main__':
    main()