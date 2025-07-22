"""
Lua Maker v1.1.1
Automatically bootstraps SteamCMD, fetches appinfo, parses depot info,
extracts decryption keys, copies manifests, and generates a Lua file.
"""

import os
import sys
import re
import json
import shutil
import winreg
import time
import zipfile
import io
import subprocess
import requests
import vdf
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# Console and file constants
console = Console()
LOG_DIR = "logs"
LOG_FILE_TEMPLATE = os.path.join(LOG_DIR, "steam_response_{appid}.log")
# Config file in application directory
CONFIG_FILE = os.path.join(
    getattr(sys, 'frozen', False) and os.path.dirname(sys.executable) or os.getcwd(),
    "luamaker_config.json"
)


def pause_on_error():
    console.print("[bold red]An error occurred. See message above.[/]")
    console.print("Press Enter to exit...")
    input()
    sys.exit(1)


def ensure_steamcmd():
    """
    Ensure steamcmd.exe is present in steamcmd/; if missing, download and install.
    """
    # Determine application directory (works for script and frozen exe)
    if getattr(sys, 'frozen', False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.path.dirname(__file__)
    steamcmd_dir = os.path.join(script_dir, 'steamcmd')
    steamcmd_exe = os.path.join(steamcmd_dir, 'steamcmd.exe')
    if not os.path.isfile(steamcmd_exe):
        console.print("[blue]SteamCMD not found. Downloading...[/]")
        zip_url = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip'
        try:
            r = requests.get(zip_url, timeout=60, stream=True)
            r.raise_for_status()
            os.makedirs(steamcmd_dir, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                z.extractall(steamcmd_dir)
            console.print("[blue]Updating SteamCMD...[/]")
            # Run updater without failing on non-zero exit
            try:
                subprocess.run([steamcmd_exe, '+login', 'anonymous', '+quit'], check=True)
            except subprocess.CalledProcessError as cpe:
                console.print(f"[yellow]SteamCMD update returned exit code {cpe.returncode}, continuing...[/]")
            console.print("[green]SteamCMD ready at steamcmd/steamcmd.exe[/]")
        except Exception as e:
            console.print(f"[bold red]Failed to install SteamCMD:[/] {e}")
            pause_on_error()


def detect_steam_paths():
    # Try registry
    install_path = None
    for key_path in [r"SOFTWARE\\Wow6432Node\\Valve\\Steam", r"SOFTWARE\\Valve\\Steam"]:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            if os.path.isdir(install_path):
                break
        except Exception:
            continue
    # Fallback default folders
    if not install_path:
        for pf in ["PROGRAMFILES", "PROGRAMFILES(X86)"]:
            path = os.path.join(os.environ.get(pf, ""), "Steam")
            if os.path.isdir(path):
                install_path = path
                break
    if not install_path:
        console.print("[bold red]Cannot locate Steam installation.[/]")
        pause_on_error()
    config = os.path.join(install_path, "config")
    depotcache = os.path.join(install_path, "depotcache")
    if not os.path.isdir(config):
        console.print(f"[bold red]Missing config folder at {config}[/]")
        pause_on_error()
    if not os.path.isdir(depotcache):
        console.print(f"[bold red]Missing depotcache folder at {depotcache}[/]")
        pause_on_error()
    return config, depotcache


def load_or_prompt_steam_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            data = json.load(open(CONFIG_FILE, 'r', encoding='utf-8'))
            path = data.get('steam_config_path')
            if path and os.path.isdir(path):
                console.print(f"Using saved Steam config: [green]{path}[/]")
                return path
        except Exception:
            pass
    config, _ = detect_steam_paths()
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'steam_config_path': config}, f, indent=2)
    except Exception:
        console.print("[yellow]Warning: could not save config file[/]")
    return config


def load_config_vdf(path):
    try:
        return open(os.path.join(path, "config.vdf"), 'r', encoding='utf-8').read()
    except Exception as e:
        console.print(f"[bold red]Failed reading config.vdf:[/] {e}")
        pause_on_error()


def fetch_app_info(appid):
    os.makedirs(LOG_DIR, exist_ok=True)
    # Determine application directory (script or frozen exe)
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(__file__)
    # Look for steamcmd.exe in steamcmd subfolder
    steamcmd_exe = os.path.join(base_dir, 'steamcmd', 'steamcmd.exe')
    if not os.path.isfile(steamcmd_exe):
        # Fallback to PATH
        steamcmd_exe = shutil.which('steamcmd.exe')

    # If we located steamcmd, use it for appinfo
    if steamcmd_exe:
        try:
            console.print(f"[blue]Running SteamCMD at {steamcmd_exe} to fetch appinfo...[/]")
            proc = subprocess.run([
                steamcmd_exe,
                '+login', 'anonymous',
                '+app_info_update 1',
                f'+app_info_print {appid}',
                '+quit'
            ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60
            )
            # Decode as UTF-8, ignoring any invalid bytes, then strip nulls
            raw = proc.stdout.decode('utf-8', errors='ignore').replace('\x00', '')

            # Log raw output
            log_path = LOG_FILE_TEMPLATE.format(appid=appid)
            with open(log_path, 'w', encoding='utf-8') as lf:
                lf.write(raw)
            console.print(f"[blue]Appinfo logged to {log_path}[/]")

            # Extract VDF block under the appid key
            key_pattern = f'"{appid}"'
            key_index = raw.find(key_pattern)
            if key_index == -1:
                raise ValueError(f"No VDF section for appid {appid}")
            start = raw.find('{', key_index)
            brace_count = 0
            end = None
            for i in range(start, len(raw)):
                if raw[i] == '{': brace_count += 1
                elif raw[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i
                        break
            if end is None:
                raise ValueError("Unmatched braces in SteamCMD output")
            vdf_blob = raw[key_index:end+1]
            parsed = vdf.loads(vdf_blob)
            return parsed.get(str(appid), parsed)
        except Exception as e:
            console.print(f"[yellow]SteamCMD fetch error:[/] {e}")

    # Fallback to manual VDF file
    console.print(f"[yellow]SteamCMD not available or failed; please save raw VDF to get_appinfo.txt[/]")
    console.print(f"[yellow]Download from https://steamui.com/api/get_appinfo.php?appid={appid}[/]")
    while not os.path.isfile("get_appinfo.txt"):
        console.input("Press Enter once get_appinfo.txt is here...")
    try:
        raw = open("get_appinfo.txt", 'r', encoding='utf-8').read()
        parsed = vdf.loads(raw)
        os.remove("get_appinfo.txt")
        return parsed.get(str(appid), parsed)
    except Exception as e:
        console.print(f"[bold red]Failed parsing get_appinfo.txt:[/] {e}")
        pause_on_error()
    script_dir = os.path.dirname(__file__)
    steamcmd_exe = os.path.join(script_dir, 'steamcmd', 'steamcmd.exe')
    if not os.path.isfile(steamcmd_exe):
        steamcmd_exe = shutil.which('steamcmd.exe')

    if steamcmd_exe:
        try:
            console.print(f"[blue]Running SteamCMD at {steamcmd_exe} to fetch appinfo...[/]")
            proc = subprocess.run([
                steamcmd_exe,
                '+login', 'anonymous',
                '+app_info_update 1',
                f'+app_info_print {appid}',
                '+quit'
            ], capture_output=True, text=True, timeout=60)
            raw = proc.stdout.replace('\x00', '')
            log_path = LOG_FILE_TEMPLATE.format(appid=appid)
            with open(log_path, 'w', encoding='utf-8') as lf:
                lf.write(raw)
            console.print(f"[blue]Appinfo logged to {log_path}[/]")
            # Extract appid block
            key_pattern = f'"{appid}"'
            key_index = raw.find(key_pattern)
            if key_index == -1:
                raise ValueError(f"No VDF section for appid {appid}")
            start = raw.find('{', key_index)
            brace_count = 0
            end = None
            for i in range(start, len(raw)):
                if raw[i] == '{': brace_count += 1
                elif raw[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i
                        break
            if end is None:
                raise ValueError("Unmatched braces in SteamCMD output")
            vdf_blob = raw[key_index:end+1]
            parsed = vdf.loads(vdf_blob)
            return parsed.get(str(appid), parsed)
        except Exception as e:
            console.print(f"[yellow]SteamCMD fetch error:[/] {e}")

    # Fallback manual VDF
    console.print(f"[yellow]SteamCMD not available; please save raw VDF to get_appinfo.txt[/]")
    console.print(f"[yellow]Download from https://steamui.com/get_appinfo.php?appid={appid}[/]")
    while not os.path.isfile("get_appinfo.txt"):
        console.input("Press Enter once get_appinfo.txt is here...")
    try:
        raw = open("get_appinfo.txt", 'r', encoding='utf-8').read()
        parsed = vdf.loads(raw)
        os.remove("get_appinfo.txt")
        return parsed.get(str(appid), parsed)
    except Exception as e:
        console.print(f"[bold red]Failed parsing get_appinfo.txt:[/] {e}")
        pause_on_error()


def extract_app_name(ai):
    name = ai.get('common', {}).get('name')
    if not name:
        console.print("[bold red]Game name missing[/]")
        time.sleep(2)
        return None
    console.print(f"[green]Found: {name}[/]")
    return name


def extract_depots(ai):
    depots = ai.get('depots')
    if not isinstance(depots, dict):
        console.print("[bold red]No depots section found[/]")
        pause_on_error()
    result = {}
    for did, info in depots.items():
        if not isinstance(info, dict): continue
        public = info.get('manifests', {}).get('public')
        if not isinstance(public, dict): continue
        gid = public.get('gid')
        if isinstance(gid, str) and gid:
            result[did] = gid
    if not result:
        console.print("[bold red]No valid depots found[/]")
        pause_on_error()
    return result


def find_decryption_key(cfg, did):
    m = re.search(rf'"{did}"\s*\{{(.*?)\}}', cfg, re.DOTALL)
    if not m: raise ValueError(f"Depot {did} missing in config")
    km = re.search(r'"DecryptionKey"\s*"([^"]+)"', m.group(1))
    if not km: raise ValueError(f"Key missing for {did}")
    return km.group(1)


def copy_manifests(depots, depotcache, out_dir):
    count = 0
    for did in depots:
        for fn in os.listdir(depotcache):
            if fn.startswith(f"{did}_") and fn.endswith('.manifest'):
                try:
                    shutil.copy2(os.path.join(depotcache, fn), os.path.join(out_dir, fn))
                    count += 1
                except:
                    pass
    return count


def write_lua(appid, depots, keys, out_dir):
    fpath = os.path.join(out_dir, f"{appid}.lua")
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(f"addappid({appid})\n")
            for d in depots:
                f.write(f"addappid({d},1,\"{keys[d]}\")\n")
            for d, g in depots.items(): f.write(f"setManifestid({d},\"{g}\")\n")
        return True
    except:
        return False


def sanitize(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)


def main():
    ensure_steamcmd()
    os.system("title LUA Maker v1.1.1")
    scfg, depotcache = detect_steam_paths()

    while True:
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
                ------------------------------------- 
                    https://discord.gg/FSjGzKH4Bq
                -------------------------------------
                    Version 1.1.1 (23/07/2025)

    ======================================================================"""
        console.print(ascii_text, style="bold blue")
        
        appid = console.input("Enter Steam App ID (game must be already installed): ").strip()
        cfg_text = load_config_vdf(scfg)
        ai = fetch_app_info(appid)
        name = extract_app_name(ai)
        depots = extract_depots(ai)
        keys = {}
        for d in list(depots):
            try:
                keys[d] = find_decryption_key(cfg_text, d)
            except ValueError:
                depots.pop(d)
        out_dir = os.path.join(os.getcwd(), sanitize(f"[{appid}] {name}"))
        os.makedirs(out_dir, exist_ok=True)
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as p:
            p.add_task(description="Copying manifest files...", total=None)
            time.sleep(1)
            copied = copy_manifests(depots, depotcache, out_dir)
        console.print(f"[green]Copied {copied} manifests to {out_dir}[/]")
        if write_lua(appid, depots, keys, out_dir):
            console.print(f"[green]Lua file at {os.path.join(out_dir, f'{appid}.lua')}[/]")
        else:
            console.print("[bold red]Lua write failed[/]")
        console.print(f"[bold green]Done! Outputs in {out_dir}[/]")
        if console.input("Run again? (Y/N): ").strip().lower() != 'y':
            console.print("Goodbye!")
            break

if __name__ == '__main__':
    main()
