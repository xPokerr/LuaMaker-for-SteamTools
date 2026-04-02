"""
Lua Maker v1.2.3
Automatically bootstraps SteamCMD, fetches appinfo, parses depot info,
extracts decryption keys, copies manifests, and generates a Lua file.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import winreg
import zipfile

try:
    import msvcrt
except ImportError:
    msvcrt = None

import requests
import vdf
from rich.console import Console
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

APP_VERSION = "1.2.3"
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(APP_DIR, "logs")
LOG_FILE_TEMPLATE = os.path.join(LOG_DIR, "steam_response_{appid}.log")
CONFIG_FILE = os.path.join(APP_DIR, "luamaker_config.json")
BANNER_BORDER = "=" * 70
ASCII_LOGO_LINES = [
    "██╗░░░░░██╗░░░██╗░█████╗░  ███╗░░░███╗░█████╗░██╗░░██╗███████╗██████╗░",
    "██║░░░░░██║░░░██║██╔══██╗  ████╗░████║██╔══██╗██║░██╔╝██╔════╝██╔══██╗",
    "██║░░░░░██║░░░██║███████║  ██╔████╔██║███████║█████═╝░█████╗░░██████╔╝",
    "██║░░░░░██║░░░██║██╔══██║  ██║╚██╔╝██║██╔══██║██╔═██╗░██╔══╝░░██╔══██╗",
    "███████╗╚██████╔╝██║░░██║  ██║░╚═╝░██║██║░░██║██║░╚██╗███████╗██║░░██║",
    "╚══════╝░╚═════╝░╚═╝░░╚═╝  ╚═╝░░░░░╚═╝╚═╝░░╚═╝╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝",
]
BANNER_SUBTITLE = [
    "LUA Maker by xpokerr",
    "-------------------------------------",
    "https://discord.gg/vKCMp9cbfG",
    "-------------------------------------",
    f"Version {APP_VERSION} (02/04/2026)",
]
BANNER_INDENT = ""
TITLE_BASE_COLOR = "bold bright_blue"
TITLE_WAVE_COLORS = ["bold cyan", "bold bright_cyan", "bold white", "bold bright_cyan", "bold cyan"]
SPINNER_FRAMES = ["[=     ]", "[==    ]", "[ ===  ]", "[  === ]", "[    ==]", "[     =]"]
ENABLE_LOOPING_BANNER_INPUT = True


def configure_console_output():
    if os.name != "nt":
        return

    try:
        os.system("chcp 65001 > nul")
    except OSError:
        pass

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


configure_console_output()
console = Console()


def pause_on_error():
    console.print("[bold red]An error occurred. See message above.[/]")
    console.print("Press Enter to exit...")
    input()
    sys.exit(1)


def normalize_user_input(value):
    return value.replace("\ufeff", "").replace("ï»¿", "").strip()


def safe_console_input(prompt):
    try:
        return normalize_user_input(console.input(prompt))
    except EOFError:
        console.print("\n[yellow]Input stream closed. Exiting...[/]")
        raise SystemExit(0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
        raise SystemExit(0)


def render_prompt_frame(frame_index, prompt, current_input, cursor_pos=None, cursor_visible=True):
    frame = render_banner_frame(frame_index)
    frame.append("\n")
    frame.append(prompt, style="bold white")
    cursor_pos = len(current_input) if cursor_pos is None else max(0, min(cursor_pos, len(current_input)))
    frame.append(current_input[:cursor_pos], style="bold bright_white")
    if cursor_visible:
        frame.append("|", style="dim white")
        frame.append(current_input[cursor_pos:], style="bold bright_white")
    else:
        frame.append(current_input[cursor_pos:], style="bold bright_white")
    return frame


def animated_console_input(prompt, frame_delay=0.08):
    if not ENABLE_LOOPING_BANNER_INPUT:
        console.clear()
        show_banner(animated=True)
        return safe_console_input(prompt)

    is_tty = getattr(sys.stdin, "isatty", lambda: False)()
    if os.name != "nt" or msvcrt is None or not is_tty:
        console.clear()
        show_banner(animated=True)
        return safe_console_input(prompt)

    console.clear()
    typed = []
    cursor_pos = 0
    frame_index = 0
    with Live(
        render_prompt_frame(0, prompt, "", cursor_pos=0, cursor_visible=True),
        console=console,
        refresh_per_second=20,
        transient=True,
    ) as live:
        while True:
            while msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ("\r", "\n"):
                    result = normalize_user_input("".join(typed))
                    console.print(
                        render_prompt_frame(
                            frame_index,
                            prompt,
                            result,
                            cursor_pos=len(result),
                            cursor_visible=False,
                        )
                    )
                    return result
                if char == "\003":
                    console.print("\n[yellow]Operation cancelled by user.[/]")
                    raise SystemExit(0)
                if char == "\b":
                    if cursor_pos > 0:
                        typed.pop(cursor_pos - 1)
                        cursor_pos -= 1
                    continue
                if char in ("\x00", "\xe0"):
                    special = msvcrt.getwch()
                    if special == "K":
                        cursor_pos = max(0, cursor_pos - 1)
                    elif special == "M":
                        cursor_pos = min(len(typed), cursor_pos + 1)
                    elif special == "G":
                        cursor_pos = 0
                    elif special == "O":
                        cursor_pos = len(typed)
                    elif special == "S":
                        if cursor_pos < len(typed):
                            typed.pop(cursor_pos)
                    continue
                if char == "\x1b":
                    typed.clear()
                    cursor_pos = 0
                    continue
                typed.insert(cursor_pos, char)
                cursor_pos += 1

            live.update(
                render_prompt_frame(
                    frame_index,
                    prompt,
                    "".join(typed),
                    cursor_pos=cursor_pos,
                    cursor_visible=True,
                )
            )
            frame_index += 1
            time.sleep(frame_delay)


def render_banner_frame(frame_index):
    logo_width = max(len(line) for line in ASCII_LOGO_LINES)
    phase_span = logo_width + 16
    phase = (frame_index * 2) % phase_span
    sheen_center = phase - 8
    border_center = round(phase * (len(BANNER_BORDER) - 1) / max(phase_span - 1, 1))

    def append_animated_border(target):
        target.append(BANNER_INDENT)
        for index, character in enumerate(BANNER_BORDER):
            distance = abs(index - border_center)
            if distance <= 1:
                style = "bold white"
            elif distance <= 4:
                style = "bold bright_cyan"
            else:
                style = "bold blue"
            target.append(character, style=style)

    frame = Text()
    append_animated_border(frame)
    frame.append("\n\n")

    for row_index, line in enumerate(ASCII_LOGO_LINES):
        line_text = Text()
        line_text.append(BANNER_INDENT)
        for char_index, character in enumerate(line):
            if character == " ":
                line_text.append(character)
                continue
            column_distance = abs(char_index - sheen_center)
            diagonal_offset = abs((char_index - row_index) - sheen_center)
            if column_distance <= 1:
                style = "bold white"
            elif column_distance <= 4 or diagonal_offset <= 2:
                style = "bold bright_cyan"
            else:
                style = "bold blue"
            line_text.append(character, style=style)
        frame.append_text(line_text)
        frame.append("\n")

    frame.append("\n")
    for subtitle_line in BANNER_SUBTITLE:
        subtitle_text = Text(BANNER_INDENT)
        subtitle_text.append(subtitle_line, style="bold bright_blue")
        frame.append_text(subtitle_text)
        frame.append("\n")

    frame.append("\n")
    append_animated_border(frame)
    return frame


def show_banner(animated=True, loop_frames=24, frame_delay=0.08):
    if not animated:
        console.print(render_banner_frame(0))
        return

    with Live(render_banner_frame(0), console=console, refresh_per_second=20, transient=True) as live:
        for frame_index in range(loop_frames):
            live.update(render_banner_frame(frame_index))
            time.sleep(frame_delay)

    console.print(render_banner_frame(loop_frames - 1))


def find_steamcmd_exe():
    bundled = os.path.join(APP_DIR, "steamcmd", "steamcmd.exe")
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("steamcmd.exe")


def ensure_steamcmd():
    """Ensure steamcmd.exe is present in steamcmd/; if missing, download and install."""
    steamcmd_dir = os.path.join(APP_DIR, "steamcmd")
    steamcmd_exe = os.path.join(steamcmd_dir, "steamcmd.exe")
    if os.path.isfile(steamcmd_exe):
        return steamcmd_exe

    console.print("[blue]SteamCMD not found. Downloading...[/]")
    zip_url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
    try:
        response = requests.get(zip_url, timeout=60, stream=True)
        response.raise_for_status()
        os.makedirs(steamcmd_dir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(steamcmd_dir)
        console.print("[blue]Updating SteamCMD...[/]")
        try:
            subprocess.run([steamcmd_exe, "+login", "anonymous", "+quit"], check=True)
        except subprocess.CalledProcessError as exc:
            console.print(
                f"[yellow]SteamCMD update returned exit code {exc.returncode}, continuing...[/]"
            )
        console.print("[green]SteamCMD ready at steamcmd/steamcmd.exe[/]")
        return steamcmd_exe
    except Exception as exc:
        console.print(f"[bold red]Failed to install SteamCMD:[/] {exc}")
        pause_on_error()


def detect_steam_paths():
    install_path = None
    for key_path in [r"SOFTWARE\\Wow6432Node\\Valve\\Steam", r"SOFTWARE\\Valve\\Steam"]:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            if os.path.isdir(install_path):
                break
        except OSError:
            continue

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
    if not os.path.isfile(CONFIG_FILE):
        return None

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except (OSError, json.JSONDecodeError):
        return None

    path = data.get("steam_config_path")
    if path and os.path.isdir(path):
        return path
    return None


def save_steam_config_path(path):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file_obj:
            json.dump({"steam_config_path": path}, file_obj, indent=2)
    except OSError:
        console.print("[yellow]Warning: could not save config file[/]")


def resolve_steam_paths():
    saved_config = load_or_prompt_steam_config()
    if saved_config:
        depotcache = os.path.join(os.path.dirname(saved_config), "depotcache")
        if os.path.isdir(depotcache):
            console.print(f"Using saved Steam config: [green]{saved_config}[/]")
            return saved_config, depotcache
        console.print(
            f"[yellow]Saved Steam config found but depotcache is missing at {depotcache}; auto-detecting again.[/]"
        )

    config, depotcache = detect_steam_paths()
    save_steam_config_path(config)
    return config, depotcache


def load_config_vdf(path):
    try:
        with open(os.path.join(path, "config.vdf"), "r", encoding="utf-8") as file_obj:
            return file_obj.read()
    except OSError as exc:
        console.print(f"[bold red]Failed reading config.vdf:[/] {exc}")
        pause_on_error()


def save_appinfo_log(appid, raw_text):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = LOG_FILE_TEMPLATE.format(appid=appid)
    with open(log_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(raw_text)
    console.print(f"[blue]Appinfo logged to {log_path}[/]")


def extract_vdf_blob(raw_text, appid):
    key_pattern = f'"{appid}"'
    key_index = raw_text.find(key_pattern)
    if key_index == -1:
        raise ValueError(f"No VDF section for appid {appid}")

    start = raw_text.find("{", key_index)
    if start == -1:
        raise ValueError("Missing opening brace in SteamCMD output")

    brace_count = 0
    end = None
    for index in range(start, len(raw_text)):
        if raw_text[index] == "{":
            brace_count += 1
        elif raw_text[index] == "}":
            brace_count -= 1
            if brace_count == 0:
                end = index
                break

    if end is None:
        raise ValueError("Unmatched braces in SteamCMD output")
    return raw_text[key_index : end + 1]


def parse_appinfo(raw_text, appid):
    parsed = vdf.loads(extract_vdf_blob(raw_text, appid))
    return parsed.get(str(appid), parsed)


def load_manual_appinfo(appid, manual_path="get_appinfo.txt"):
    console.print("[yellow]SteamCMD not available or failed; please save raw VDF to get_appinfo.txt[/]")
    console.print(f"[yellow]Download from https://steamui.com/api/get_appinfo.php?appid={appid}[/]")
    while not os.path.isfile(manual_path):
        console.input("Press Enter once get_appinfo.txt is here...")

    try:
        with open(manual_path, "r", encoding="utf-8") as file_obj:
            raw_text = file_obj.read()
        parsed = vdf.loads(raw_text)
        os.remove(manual_path)
        return parsed.get(str(appid), parsed)
    except Exception as exc:
        console.print(f"[bold red]Failed parsing get_appinfo.txt:[/] {exc}")
        pause_on_error()


def fetch_app_info(appid):
    steamcmd_exe = find_steamcmd_exe()
    if steamcmd_exe:
        try:
            console.print(f"[blue]Running SteamCMD at {steamcmd_exe} to fetch appinfo...[/]")
            proc = subprocess.run(
                [
                    steamcmd_exe,
                    "+login",
                    "anonymous",
                    "+app_info_update 1",
                    f"+app_info_print {appid}",
                    "+quit",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            raw_text = proc.stdout.decode("utf-8", errors="ignore").replace("\x00", "")
            save_appinfo_log(appid, raw_text)
            return parse_appinfo(raw_text, appid)
        except Exception as exc:
            console.print(f"[yellow]SteamCMD fetch error:[/] {exc}")

    return load_manual_appinfo(appid)


def extract_app_name(ai):
    name = ai.get("common", {}).get("name")
    if not name:
        console.print("[bold red]Game name missing[/]")
        time.sleep(2)
        return None
    console.print(f"[green]Found: {name}[/]")
    return name


def extract_depots(ai):
    depots = ai.get("depots")
    if not isinstance(depots, dict):
        console.print("[bold red]No depots section found[/]")
        pause_on_error()

    result = {}
    for depot_id, info in depots.items():
        if not isinstance(info, dict):
            continue
        public = info.get("manifests", {}).get("public")
        if not isinstance(public, dict):
            continue
        gid = public.get("gid")
        if isinstance(gid, str) and gid:
            result[depot_id] = gid

    if not result:
        console.print("[bold red]No valid depots found[/]")
        pause_on_error()
    return result


def extract_dlc_appids(ai):
    dlc_ids = []
    seen = set()

    def add_candidate(value):
        text = str(value).strip()
        if text.isdigit() and text not in seen:
            seen.add(text)
            dlc_ids.append(text)

    dlc_section = ai.get("dlc")
    if isinstance(dlc_section, dict):
        for key in dlc_section.keys():
            add_candidate(key)
    elif isinstance(dlc_section, list):
        for item in dlc_section:
            add_candidate(item)
    elif isinstance(dlc_section, str):
        for item in dlc_section.split(","):
            add_candidate(item)

    extended = ai.get("extended", {})
    if isinstance(extended, dict):
        listofdlc = extended.get("listofdlc", "")
        if isinstance(listofdlc, str):
            for item in listofdlc.split(","):
                add_candidate(item)

    return dlc_ids


def find_decryption_key(config_text, depot_id):
    match = re.search(rf'"{depot_id}"\s*\{{(.*?)\}}', config_text, re.DOTALL)
    if not match:
        raise ValueError(f"Depot {depot_id} missing in config")

    key_match = re.search(r'"DecryptionKey"\s*"([^"]+)"', match.group(1))
    if not key_match:
        raise ValueError(f"Key missing for {depot_id}")
    return key_match.group(1)


def copy_manifests(depots, depotcache, out_dir):
    copied = 0
    depot_ids = {str(depot_id) for depot_id in depots}

    for filename in os.listdir(depotcache):
        if not filename.endswith(".manifest"):
            continue
        depot_id = filename.split("_", 1)[0]
        if depot_id not in depot_ids:
            continue

        source = os.path.join(depotcache, filename)
        destination = os.path.join(out_dir, filename)
        try:
            shutil.copy2(source, destination)
            copied += 1
        except OSError as exc:
            console.print(f"[yellow]Failed to copy manifest {filename}: {exc}[/]")

    return copied


def write_lua(appid, depots, keys, out_dir, dlc_appids=None):
    file_path = os.path.join(out_dir, f"{appid}.lua")
    dlc_appids = dlc_appids or []
    with open(file_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(f"addappid({appid})\n")
        for dlc_appid in dlc_appids:
            file_obj.write(f"addappid({dlc_appid})\n")
        for depot_id in depots:
            file_obj.write(f'addappid({depot_id},1,"{keys[depot_id]}")\n')
        for depot_id, gid in depots.items():
            file_obj.write(f'setManifestid({depot_id},"{gid}")\n')
    return file_path


def sanitize(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def collect_decryption_keys(config_text, depots):
    usable_depots = {}
    keys = {}
    missing_depots = []

    for depot_id, gid in depots.items():
        try:
            keys[depot_id] = find_decryption_key(config_text, depot_id)
            usable_depots[depot_id] = gid
        except ValueError:
            missing_depots.append(depot_id)

    if missing_depots:
        console.print(
            "[yellow]No decryption key found for depot(s): "
            + ", ".join(sorted(missing_depots))
            + "[/]"
        )

    return usable_depots, keys


def copy_manifests_with_progress(depots, depotcache, out_dir):
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
        progress.add_task(description="Copying manifest files...", total=None)
        time.sleep(1)
        return copy_manifests(depots, depotcache, out_dir)


def run_plugin_flow(appid, plugin_file, depotcache, out_dir):
    console.print(f"[blue]Plugin file found at {plugin_file}; using plugin flow...[/]")
    shutil.copy2(plugin_file, os.path.join(out_dir, f"{appid}.lua"))

    with open(plugin_file, "r", encoding="utf-8") as file_obj:
        plugin_text = file_obj.read()
    plugin_depots = re.findall(r"addappid\(\s*(\d+)", plugin_text)

    copied = copy_manifests_with_progress(plugin_depots, depotcache, out_dir)
    if copied < 1:
        console.print("[bold red]No manifest files found for plugin depots[/]")
        pause_on_error()

    console.print(f"[green]Copied {copied} manifest(s) to {out_dir}[/]")
    console.print(f"[bold green]Done! Outputs in {out_dir}[/]")


def run_standard_flow(appid, config_text, app_info, depotcache, out_dir):
    depots = extract_depots(app_info)
    dlc_appids = extract_dlc_appids(app_info)
    keyed_depots, keys = collect_decryption_keys(config_text, depots)

    copied = copy_manifests_with_progress(depots, depotcache, out_dir)
    if copied < 1:
        console.print("[bold red]No manifest files found for any depots[/]")
        pause_on_error()
    console.print(f"[green]Copied {copied} manifest(s) to {out_dir}[/]")

    if keys:
        try:
            lua_path = write_lua(appid, keyed_depots, keys, out_dir, dlc_appids=dlc_appids)
            console.print(f"[green]Lua file at {lua_path}[/]")
            if dlc_appids:
                console.print(f"[green]Included DLC appid(s): {', '.join(dlc_appids)}[/]")
        except OSError as exc:
            console.print(f"[bold red]Lua write failed:[/] {exc}")
            pause_on_error()
    else:
        console.print("[yellow]No decryption keys found; skipping Lua file write[/]")

    console.print(f"[bold green]Done! Outputs in {out_dir}[/]")


def should_run_again():
    answer = safe_console_input("Process another App ID? (Y/n): ").lower()
    return answer in ("", "y", "yes")


def process_app(appid, output_root=None):
    ensure_steamcmd()
    steam_config_path, depotcache = resolve_steam_paths()
    config_text = load_config_vdf(steam_config_path)
    app_info = fetch_app_info(appid)
    name = extract_app_name(app_info)
    if not name:
        pause_on_error()

    output_root = output_root or os.getcwd()
    output_dir = os.path.join(output_root, sanitize(f"[{appid}] {name}"))
    os.makedirs(output_dir, exist_ok=True)

    plugin_dir = os.path.join(steam_config_path, "stplugin")
    plugin_file = os.path.join(plugin_dir, f"{appid}.lua")

    if os.path.isfile(plugin_file):
        run_plugin_flow(appid, plugin_file, depotcache, output_dir)
    else:
        run_standard_flow(appid, config_text, app_info, depotcache, output_dir)

    return output_dir


def main():
    os.system(f"title LUA Maker v{APP_VERSION}")

    while True:
        appid = animated_console_input("Enter Steam App ID (game must be already installed): ")
        process_app(appid)

        if not should_run_again():
            console.print("Goodbye!")
            break


if __name__ == "__main__":
    main()
