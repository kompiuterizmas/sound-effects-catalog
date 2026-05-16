from pathlib import Path
from mutagen import File
from html import escape
from tqdm import tqdm
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
import webbrowser
import threading
import time
import sys
import wave
import hashlib
import re
import subprocess
import shutil
import json
import os
from flask import Flask, request, jsonify, send_file, send_from_directory
import tkinter as tk
from tkinter import filedialog, messagebox
from urllib.parse import quote
import configparser

# ENTER HERE YOUR SOUND FILES FOLDER
SOURCE_FOLDER = None

# ENTER ROUTE WHERE TO CREATE HTML FILE, OR LEAVE LIKE IS TO CREATE IN THE SAME FOLDER
def get_app_folder():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


APP_FOLDER = get_app_folder()
CONFIG_FILE = APP_FOLDER / "config.ini"
OUTPUT_HTML = APP_FOLDER / "sound_effects_catalog.html"
app = Flask(__name__)

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".aiff", ".aif", ".flac", ".ogg", ".m4a"
}

PREVIEW_REQUIRED_AUDIO = {
    ".aiff", ".aif", ".flac", ".ogg", ".m4a"
}

WAVEFORM_FOLDER = APP_FOLDER / "waveforms"
WAVEFORM_FOLDER.mkdir(exist_ok=True)
PREVIEW_FOLDER = APP_FOLDER / "previews"
PREVIEW_FOLDER.mkdir(exist_ok=True)


def create_waveform_image(file_path, output_path):
    try:
        # Skaitome audio failą per soundfile
        samples, sample_rate = sf.read(str(file_path), always_2d=True)

        if samples.size == 0:
            return False

        # Jei stereo / multi-channel – paverčiame į mono
        samples = samples.mean(axis=1)

        # Kad waveform PNG būtų lengvas ir greitai generuotųsi
        max_points = 1200
        if len(samples) > max_points:
            step = len(samples) // max_points
            samples = samples[::step]

        plt.figure(figsize=(6, 0.8))
        plt.plot(samples, linewidth=0.6)
        plt.axis("off")
        plt.tight_layout(pad=0)

        plt.savefig(output_path, dpi=100, bbox_inches="tight", pad_inches=0)
        plt.close()

        return True

    except Exception as error:
        print(f"Nepavyko sukurti waveform: {file_path.name} | {error}")
        return False

def get_waveform_vector(file_path):
    try:
        samples, sample_rate = sf.read(str(file_path), always_2d=True)

        if samples.size == 0:
            return []

        samples = samples.mean(axis=1)

        # Pašaliname tylą pradžioje ir pabaigoje
        samples_abs = np.abs(samples)
        silence_threshold = np.max(samples_abs) * 0.02

        active_indexes = np.where(samples_abs > silence_threshold)[0]

        if active_indexes.size > 0:
            samples = samples[active_indexes[0]:active_indexes[-1] + 1]

        samples_abs = np.abs(samples)

        max_value = np.max(samples_abs)
        if max_value > 0:
            samples_abs = samples_abs / max_value

        segments_count = 32
        segment_size = max(1, len(samples_abs) // segments_count)

        vector = []

        for index in range(segments_count):
            start = index * segment_size
            end = start + segment_size
            segment = samples_abs[start:end]

            if segment.size == 0:
                vector.append(0)
            else:
                vector.append(round(float(np.mean(segment)), 4))

        return vector

    except Exception:
        return []

def format_duration(seconds):
    if seconds is None:
        return "nežinoma"

    minutes = int(seconds // 60)
    secs = seconds % 60

    if minutes > 0:
        return f"{minutes}:{secs:04.1f}"
    return f"{secs:.1f} s"


def get_audio_info(file_path):
    try:
        audio = File(file_path)
        if audio is None or not hasattr(audio, "info"):
            return None, None

        duration = getattr(audio.info, "length", None)
        file_type = file_path.suffix.lower().replace(".", "").upper()

        return duration, file_type

    except Exception:
        return None, None

def safe_rename_file(old_path_text, new_name):
    old_path = Path(old_path_text)

    if not old_path.exists():
        return False, "File does not exist."

    new_name = new_name.strip()

    if not new_name:
        return False, "New file name cannot be empty."

    if any(char in new_name for char in r'<>:"/\|?*'):
        return False, "File name contains invalid characters."

    if not Path(new_name).suffix:
        new_name += old_path.suffix

    new_path = old_path.with_name(new_name)

    if new_path.exists():
        return False, "A file with this name already exists."

    old_path.rename(new_path)

    rename_generated_assets(old_path, new_path)

    return True, str(new_path.absolute())

def is_path_inside_folder(file_path, folder_path):
    try:
        file_path = Path(file_path).absolute()
        folder_path = Path(folder_path).absolute()

        return file_path == folder_path or folder_path in file_path.parents

    except Exception:
        return False

@app.route("/")
def index():
    return send_file(OUTPUT_HTML)

@app.route("/audio")
def audio_file():
    audio_path = request.args.get("path", "")

    if not audio_path:
        return "Missing audio path", 400

    if not SOURCE_FOLDER:
        return "Source folder is not set", 400

    file_path = Path(audio_path).absolute()
    source_folder = Path(SOURCE_FOLDER).absolute()

    if not is_path_inside_folder(file_path, source_folder):
        return "Access denied", 403

    if not file_path.exists() or not file_path.is_file():
        return "Audio file not found", 404

    if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
        return "Unsupported audio file", 400

    return send_file(file_path)

@app.route("/waveforms/<path:filename>")
def waveform_file(filename):
    return send_from_directory(WAVEFORM_FOLDER, filename)

@app.route("/preview/<path:filename>")
def preview_file(filename):
    return send_from_directory(PREVIEW_FOLDER, filename)

@app.route("/rename", methods=["POST"])
def rename_file():
    data = request.get_json()

    old_path = data.get("old_path", "")
    new_name = data.get("new_name", "")

    success, message = safe_rename_file(old_path, new_name)

    if not success:
        return jsonify({
            "success": False,
            "message": message
        })

    main()

    new_path = Path(message)
    file_extension = new_path.suffix.lower()

    audio_path = f"/audio?path={quote(str(new_path.absolute()))}"

    if file_extension in PREVIEW_REQUIRED_AUDIO:
        preview_name = get_asset_name(new_path, ".wav")
        preview_path = PREVIEW_FOLDER / preview_name

        if preview_path.exists():
            audio_path = f"/preview/{preview_path.name}"

    waveform_name = get_asset_name(new_path, ".png")
    waveform_path = WAVEFORM_FOLDER / waveform_name

    return jsonify({
        "success": True,
        "message": str(new_path.absolute()),
        "new_path": str(new_path.absolute()),
        "new_name": new_path.name,
        "audio_path": audio_path,
        "waveform_path": f"/waveforms/{waveform_path.name}"
    })

@app.route("/open-folder", methods=["POST"])
def open_folder():
    data = request.get_json()

    file_path_text = data.get("path", "")

    if not file_path_text:
        return jsonify({
            "success": False,
            "message": "Missing file path."
        })

    file_path = Path(file_path_text).absolute()

    if not file_path.exists():
        return jsonify({
            "success": False,
            "message": "File does not exist."
        })

    if not SOURCE_FOLDER:
        return jsonify({
            "success": False,
            "message": "Source folder is not set."
        })

    source_folder = Path(SOURCE_FOLDER).absolute()

    if not is_path_inside_folder(file_path, source_folder):
        return jsonify({
            "success": False,
            "message": "Access denied."
        })

    try:
        if sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(file_path)])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(file_path)])
        else:
            subprocess.run(["xdg-open", str(file_path.parent)])

        return jsonify({
            "success": True,
            "message": "Folder opened."
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "message": f"Could not open folder: {error}"
        })

def load_saved_source_folder():
    config = configparser.ConfigParser()

    if not CONFIG_FILE.exists():
        return None

    config.read(CONFIG_FILE, encoding="utf-8")

    saved_folder = config.get("Settings", "source_folder", fallback="").strip()

    if saved_folder:
        return saved_folder

    return None


def save_source_folder(folder_path):
    config = configparser.ConfigParser()
    config["Settings"] = {
        "source_folder": folder_path
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
        config.write(config_file)

def select_source_folder():
    saved_folder = load_saved_source_folder()
    selected_folder = {"path": saved_folder}

    window = tk.Tk()
    window.title("Sound Catalog Launcher")
    window.geometry("560x300")
    window.resizable(False, False)

    title_label = tk.Label(
        window,
        text="Sound Effects Catalog",
        font=("Arial", 18, "bold")
    )
    title_label.pack(pady=(20, 8))

    description_label = tk.Label(
        window,
        text="Select the folder that contains your sound effects.",
        font=("Arial", 11)
    )
    description_label.pack(pady=(0, 10))

    warning_label = tk.Label(
        window,
        text=(
            "Warning: after launch, the app will scan the selected folder.\n"
            "Depending on the number of audio files, this may take some time."
        ),
        font=("Arial", 10),
        fg="#8a4b00",
        justify="center"
    )
    warning_label.pack(pady=(0, 14))

    path_label = tk.Label(
        window,
        text=saved_folder if saved_folder else "No folder selected",
        font=("Arial", 10),
        wraplength=500,
        fg="#555"
    )
    path_label.pack(pady=(0, 12))

    def choose_folder():
        folder = filedialog.askdirectory(title="Select sound effects folder")

        if folder:
            selected_folder["path"] = folder
            path_label.config(text=folder)
            select_button.config(text="Change folder")

    def launch_app():
        if not selected_folder["path"]:
            messagebox.showwarning(
                "Folder required",
                "Please select a sound effects folder first."
            )
            return

        save_source_folder(selected_folder["path"])
        window.destroy()

    button_frame = tk.Frame(window)
    button_frame.pack(pady=10)

    select_button = tk.Button(
        button_frame,
        text="Change folder" if saved_folder else "Select folder",
        width=18,
        command=choose_folder
    )
    select_button.grid(row=0, column=0, padx=8)

    launch_button = tk.Button(
        button_frame,
        text="Launch",
        width=18,
        command=launch_app
    )
    launch_button.grid(row=0, column=1, padx=8)

    window.mainloop()

    return selected_folder["path"]

def get_ffmpeg_path():
    local_ffmpeg = APP_FOLDER / "ffmpeg.exe"

    if local_ffmpeg.exists():
        return str(local_ffmpeg)

    system_ffmpeg = shutil.which("ffmpeg")

    if system_ffmpeg:
        return system_ffmpeg

    return None


def create_preview_with_ffmpeg(file_path, output_path):
    ffmpeg_path = get_ffmpeg_path()

    if not ffmpeg_path:
        print(f"FFmpeg not found. Cannot create preview for: {file_path.name}")
        return False

    try:
        command = [
            ffmpeg_path,
            "-y",
            "-i", str(file_path),
            "-ac", "1",
            "-ar", "44100",
            "-sample_fmt", "s16",
            str(output_path)
        ]

        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        return output_path.exists()

    except Exception as error:
        print(f"Failed to create FFmpeg preview: {file_path.name} | {error}")
        return False

def create_wav_preview(file_path, output_path):
    try:
        samples, sample_rate = sf.read(str(file_path), always_2d=True)

        if samples.size == 0:
            return False

        samples = samples.mean(axis=1)

        max_value = np.max(np.abs(samples))
        if max_value > 0:
            samples = samples / max_value

        samples_int16 = (samples * 32767).astype(np.int16)

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(samples_int16.tobytes())

        return True

    except Exception:
        return create_preview_with_ffmpeg(file_path, output_path)

def safe_file_stem(text):
    text = Path(text).stem
    text = re.sub(r'[<>:"/\\|?*]', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text[:80]


def stable_file_id(file_path):
    resolved_path = str(file_path.resolve()).lower()
    return hashlib.sha1(resolved_path.encode("utf-8")).hexdigest()[:12]


def get_asset_name(file_path, extension):
    stem = safe_file_stem(file_path.name)
    file_id = stable_file_id(file_path)
    return f"{stem}_{file_id}{extension}"

def rename_generated_assets(old_file_path, new_file_path):
    asset_pairs = [
        (
            WAVEFORM_FOLDER / get_asset_name(old_file_path, ".png"),
            WAVEFORM_FOLDER / get_asset_name(new_file_path, ".png")
        ),
        (
            PREVIEW_FOLDER / get_asset_name(old_file_path, ".wav"),
            PREVIEW_FOLDER / get_asset_name(new_file_path, ".wav")
        )
    ]

    for old_asset_path, new_asset_path in asset_pairs:
        try:
            if old_asset_path.exists() and not new_asset_path.exists():
                old_asset_path.rename(new_asset_path)
        except Exception as error:
            print(f"Could not rename generated asset: {old_asset_path} | {error}")

def main():
    source = Path(SOURCE_FOLDER)

    if not source.exists():
        print(f"Aplankas nerastas: {source}")
        return

    audio_files = [
        file for file in source.rglob("*")
        if file.is_file() and file.suffix.lower() in AUDIO_EXTENSIONS
    ]

    print(f"Rasta garso failų: {len(audio_files)}")

    rows = []

    for file_path in tqdm(audio_files, desc="Kuriamas katalogas"):
        duration, file_type = get_audio_info(file_path)
        relative_path = file_path.relative_to(source)

        file_extension = file_path.suffix.lower()

        waveform_name = get_asset_name(file_path, ".png")
        waveform_path = WAVEFORM_FOLDER / waveform_name

        preview_path = None
        audio_source_path = f"/audio?path={quote(str(file_path.resolve()))}"

        if file_extension in PREVIEW_REQUIRED_AUDIO:
            preview_name = get_asset_name(file_path, ".wav")
            preview_path = PREVIEW_FOLDER / preview_name

            if not preview_path.exists():
                create_wav_preview(file_path, preview_path)

            if preview_path.exists():
                audio_source_path = f"/preview/{preview_path.name}"

        waveform_source_path = preview_path if preview_path and preview_path.exists() else file_path

        if not waveform_path.exists():
            create_waveform_image(waveform_source_path, waveform_path)

        rows.append({
            "name": file_path.name,
            "safe_name": escape(file_path.name),
            "duration": duration or 0,
            "duration_text": format_duration(duration),
            "type": file_type or "unknown",
            "folder": str(relative_path.parent),
            "full_path": str(file_path.resolve()),
            "path": audio_source_path,
            "waveform": f"/waveforms/{waveform_path.name}",
            "waveform_vector": json.dumps(get_waveform_vector(waveform_source_path))
        })

    rows.sort(key=lambda x: (x["folder"], x["name"].lower()))

    html_rows = ""

    for item in rows:
        html_rows += f"""
        <tr data-full-path="{escape(item["full_path"])}" data-waveform-vector="{escape(item["waveform_vector"])}">
            <td>
                <audio controls preload="none">
                    <source src="{item["path"]}">
                    Your browser does not support audio.
                </audio>
            </td>
            <td>{escape(item["name"])}</td>
            <td>
                <input class="rename-input" value="{item["safe_name"]}">
                <button onclick="renameFile(this)">Save</button>
            </td>
            <td data-sort="{item["duration"]}">{escape(item["duration_text"])}</td>
            <td>{escape(item["type"])}</td>
            <td><img src="{item["waveform"]}" class="waveform"></td>
            <td>
                <button onclick="findSimilar(this)">Find similar</button>
            </td>
            <td>
                <button onclick="openFolder(this)">Open folder</button>
            </td>
            <td class="path-cell">{escape(item["full_path"])}</td>
        </tr>
        """

    html = f"""

<!DOCTYPE html>
<html lang="lt">
<head>
    <meta charset="UTF-8">
    <title>Sound Catalog</title>
    <style>
        :root {{
            color-scheme: light dark;

            --bg-color: #f7f7f7;
            --panel-color: #ffffff;
            --text-color: #222222;
            --muted-text-color: #555555;
            --border-color: #dddddd;

            --table-header-bg: #222222;
            --table-header-text: #ffffff;
            --row-hover-bg: #f0f0f0;

            --input-bg: #ffffff;
            --input-text: #222222;
            --input-border: #cccccc;

            --waveform-bg: #fafafa;

            --success-bg: #e8f5e9;
            --success-text: #1b5e20;
            --error-bg: #ffebee;
            --error-text: #b71c1c;
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-color: #121212;
                --panel-color: #1e1e1e;
                --text-color: #eeeeee;
                --muted-text-color: #b0b0b0;
                --border-color: #333333;

                --table-header-bg: #2a2a2a;
                --table-header-text: #ffffff;
                --row-hover-bg: #2c2c2c;

                --input-bg: #1e1e1e;
                --input-text: #eeeeee;
                --input-border: #444444;

                --waveform-bg: #181818;

                --success-bg: #16351f;
                --success-text: #b8f5c6;
                --error-bg: #3a1717;
                --error-text: #ffb8b8;
            }}
        }}
        html, body {{
            height: 100%;
        }}
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0 24px 24px 24px;
            background: var(--bg-color);
            color: var(--text-color);

            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        h1 {{
            margin-bottom: 8px;
        }}
        .top-bar {{
            flex: 0 0 auto;
            background: var(--bg-color);
            padding: 24px 0 12px 0;
            border-bottom: 1px solid var(--border-color);
        }}

        .top-bar h1 {{
            margin-top: 0;
        }}
        .info {{
            margin-bottom: 20px;
            color: var(--muted-text-color);
        }}
        input {{
            width: 100%;
            padding: 12px;
            margin-bottom: 16px;
            font-size: 16px;
            box-sizing: border-box;
            background: var(--input-bg);
            color: var(--input-text);
            border: 1px solid var(--input-border);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--panel-color);
        }}
        th, td {{
            padding: 10px;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }}
        th {{
            background: var(--table-header-bg);
            color: var(--table-header-text);
            text-align: left;
            position: sticky;
            top: 0;
            z-index: 10;
            cursor: pointer;
            user-select: none;
        }}
        audio {{
            width: 100%;
            min-width: 280px;
            max-width: 420px;
        }}
        th:hover {{
            background: var(--row-hover-bg);
        }}
        button {{
            padding: 6px 10px;
            cursor: pointer;
            background: var(--panel-color);
            color: var(--text-color);
            border: 1px solid var(--border-color);
        }}
        .status-toast {{
            position: fixed;
            top: 18px;
            left: 50%;
            transform: translateX(-50%) translateY(-20px);
            z-index: 9999;

            display: none;
            min-width: 260px;
            max-width: 520px;
            padding: 12px 18px;

            border-radius: 8px;
            background: var(--success-bg);
            color: var(--success-text);

            font-size: 14px;
            font-weight: 600;
            text-align: center;

            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
            opacity: 0;
            transition: opacity 0.2s ease, transform 0.2s ease;
        }}

        .status-toast.visible {{
            display: block;
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }}

        .status-toast.error {{
            background: var(--error-bg);
            color: var(--error-text);
        }}

        .table-wrapper {{
            flex: 1 1 auto;
            overflow: auto;
            min-height: 0;
        }}
        .rename-input {{
            width: 220px;
            padding: 6px;
            font-size: 13px;
        }}
        .path-cell {{
            font-size: 12px;
            color: var(--muted-text-color);
            max-width: 520px;
            word-break: break-all;
        }}
        .waveform {{
            width: 260px;
            height: 45px;
            object-fit: contain;
            background: var(--waveform-bg);
        }}
        tr:hover {{
            background: var(--row-hover-bg);
        }}
        .similar-selected {{
            outline: 2px solid var(--success-text);
            outline-offset: -2px;
        }}
        .similar-match {{
            background: color-mix(in srgb, var(--success-bg) 45%, transparent);
        }}

        .similar-divider td {{
            padding: 12px;
            text-align: center;
            font-weight: 600;
            color: var(--muted-text-color);
            background: var(--bg-color);
            border-top: 2px solid var(--border-color);
            border-bottom: 2px solid var(--border-color);
        }}
    </style>
</head>
<body>
<div id="statusMessage" class="status-toast"></div>

<div class="top-bar">
    <h1>Sound catalog</h1>
    <div class="info">Files found: {len(rows)}</div>

    <input type="text" id="searchInput" placeholder="Search by name, folder, format...">
</div>
<div class="table-wrapper">
    <table id="audioTable">
        <thead>
            <tr>
                <th data-type="text">PLAY</th>
                <th data-type="text">File</th>
                <th data-type="text">Rename</th>
                <th data-type="number">Duration</th>
                <th data-type="text">Format</th>
                <th data-type="text">Waveform</th>
                <th data-type="text">Similar</th>
                <th data-type="text">Folder</th>
                <th data-type="text">Full path</th>
            </tr>
        </thead>
        <tbody>
            {html_rows}
        </tbody>
    </table>
</div>
<script>
    const searchInput = document.getElementById("searchInput");
    const table = document.getElementById("audioTable");
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const headers = table.querySelectorAll("th");
    const audioPlayers = Array.from(document.querySelectorAll("audio"));

    audioPlayers.forEach(audio => {{
        audio.addEventListener("play", () => {{
            audioPlayers.forEach(otherAudio => {{
                if (otherAudio !== audio) {{
                    otherAudio.pause();
                    otherAudio.currentTime = 0;
                }}
            }});
        }});
    }});
    let statusMessageTimeout = null;

    function showStatusMessage(message, isError = false) {{
        const statusMessage = document.getElementById("statusMessage");

        if (statusMessageTimeout) {{
            clearTimeout(statusMessageTimeout);
        }}

        statusMessage.textContent = message;
        statusMessage.classList.toggle("error", isError);
        statusMessage.style.display = "block";

        requestAnimationFrame(() => {{
            statusMessage.classList.add("visible");
        }});

        statusMessageTimeout = setTimeout(() => {{
            statusMessage.classList.remove("visible");

            setTimeout(() => {{
                statusMessage.style.display = "none";
            }}, 220);
        }}, 2500);
    }}

    function parseWaveformVector(row) {{
        try {{
            return JSON.parse(row.dataset.waveformVector || "[]");
        }} catch (error) {{
            return [];
        }}
    }}

    function calculateVectorDistance(vectorA, vectorB) {{
        if (!vectorA.length || !vectorB.length || vectorA.length !== vectorB.length) {{
            return Number.MAX_VALUE;
        }}

        let total = 0;

        for (let index = 0; index < vectorA.length; index++) {{
            const difference = vectorA[index] - vectorB[index];
            total += difference * difference;
        }}

        return Math.sqrt(total);
    }}

    function findSimilar(button) {{
        const selectedRow = button.closest("tr");
        const selectedVector = parseWaveformVector(selectedRow);
        const similarLimit = 10;

        if (!selectedVector.length) {{
            showStatusMessage("Waveform data is not available for this file.", true);
            return;
        }}

        const oldDivider = tbody.querySelector(".similar-divider");
        if (oldDivider) {{
            oldDivider.remove();
        }}

        rows.forEach(row => {{
            row.classList.remove("similar-selected");
            row.classList.remove("similar-match");
        }});

        const sortedRows = rows
            .map(row => {{
                const vector = parseWaveformVector(row);
                const distance = row === selectedRow
                    ? -1
                    : calculateVectorDistance(selectedVector, vector);

                return {{
                    row: row,
                    distance: distance
                }};
            }})
            .sort((a, b) => a.distance - b.distance);

        sortedRows.forEach((item, index) => {{
            tbody.appendChild(item.row);

            if (item.row === selectedRow) {{
                item.row.classList.add("similar-selected");
            }} else if (index <= similarLimit) {{
                item.row.classList.add("similar-match");
            }}

            if (index === similarLimit) {{
                const dividerRow = document.createElement("tr");
                dividerRow.className = "similar-divider";

                const dividerCell = document.createElement("td");
                dividerCell.colSpan = item.row.children.length;
                dividerCell.textContent = "End of closest matches";

                dividerRow.appendChild(dividerCell);
                tbody.appendChild(dividerRow);
            }}
        }});

        showStatusMessage("Closest similar files moved to the top.");
    }}

    async function openFolder(button) {{
        const row = button.closest("tr");
        const filePath = row.dataset.fullPath;

        if (!filePath) {{
            showStatusMessage("File path is missing.", true);
            return;
        }}

        const response = await fetch("/open-folder", {{
            method: "POST",
            headers: {{
                "Content-Type": "application/json"
            }},
            body: JSON.stringify({{
                path: filePath
            }})
        }});

        const result = await response.json();

        if (result.success) {{
            showStatusMessage("Folder opened.");
        }} else {{
            showStatusMessage(result.message, true);
        }}
    }}

    searchInput.addEventListener("keyup", function() {{
        const query = this.value.toLowerCase();

        rows.forEach(row => {{
            const text = row.innerText.toLowerCase();
            row.style.display = text.includes(query) ? "" : "none";
        }});
    }});

    headers.forEach((header, index) => {{
        header.addEventListener("click", () => {{
            const type = header.dataset.type;
            const currentDirection = header.dataset.direction || "asc";
            const newDirection = currentDirection === "asc" ? "desc" : "asc";

            headers.forEach(h => {{
                h.dataset.direction = "";
                h.textContent = h.textContent.replace(" ▲", "").replace(" ▼", "");
            }});

            header.dataset.direction = newDirection;
            header.textContent += newDirection === "asc" ? " ▲" : " ▼";

            const sortedRows = Array.from(tbody.querySelectorAll("tr")).sort((a, b) => {{
                const cellA = a.children[index];
                const cellB = b.children[index];

                let valueA;
                let valueB;

                if (type === "number") {{
                    valueA = parseFloat(cellA.dataset.sort || "0");
                    valueB = parseFloat(cellB.dataset.sort || "0");
                }} else {{
                    valueA = (cellA.dataset.sort || cellA.innerText).toLowerCase();
                    valueB = (cellB.dataset.sort || cellB.innerText).toLowerCase();
                }}

                if (valueA < valueB) return newDirection === "asc" ? -1 : 1;
                if (valueA > valueB) return newDirection === "asc" ? 1 : -1;
                return 0;
            }});

            sortedRows.forEach(row => tbody.appendChild(row));
        }});
    }});
    async function renameFile(button) {{
        const row = button.closest("tr");
        const input = row.querySelector(".rename-input");
        const oldPath = row.dataset.fullPath;
        const newName = input.value.trim();

        if (!newName) {{
            showStatusMessage("File name cannot be empty.", true);
            return;
        }}

        const response = await fetch("/rename", {{
            method: "POST",
            headers: {{
                "Content-Type": "application/json"
            }},
            body: JSON.stringify({{
                old_path: oldPath,
                new_name: newName
            }})
        }});

        const result = await response.json();

        if (result.success) {{
            const newPath = result.new_path;
            const newName = result.new_name;

            row.dataset.fullPath = newPath;

            row.children[1].textContent = newName;
            input.value = newName;

            const pathCell = row.querySelector(".path-cell");
            pathCell.textContent = newPath;

            const audio = row.querySelector("audio");
            const source = audio.querySelector("source");

            if (source.src.includes("/preview/")) {{
                source.src = result.audio_path;
            }} else {{
                source.src = "/audio?path=" + encodeURIComponent(newPath);
            }}

            audio.load();

            const waveform = row.querySelector(".waveform");
            if (waveform && result.waveform_path) {{
                waveform.src = result.waveform_path;
            }}

            showStatusMessage("File renamed successfully.");
        }} else {{
            showStatusMessage(result.message, true);
        }}
    }}
</script>

</body>
</html>
"""

    Path(OUTPUT_HTML).write_text(html, encoding="utf-8")

    print(f"Katalogas sukurtas: {Path(OUTPUT_HTML).resolve()}")


def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    selected_folder = select_source_folder()

    if selected_folder:
        SOURCE_FOLDER = selected_folder

        main()

        threading.Thread(target=open_browser, daemon=True).start()

        app.run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            use_reloader=False
        )