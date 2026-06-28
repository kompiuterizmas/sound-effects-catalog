from pathlib import Path
from mutagen import File
from tqdm import tqdm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
import webbrowser
import os
import threading
import time
import sys
import wave
import hashlib
import re
import subprocess
import shutil
import json
from flask import Flask, request, jsonify, send_file, send_from_directory, render_template
import tkinter as tk
from tkinter import filedialog, messagebox
from urllib.parse import quote
import configparser


SOURCE_FOLDER = None
CATALOG_ROWS = []


def get_app_folder():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


APP_FOLDER = get_app_folder()
CONFIG_FILE = APP_FOLDER / "config.ini"
CACHE_FILE = APP_FOLDER / "catalog_cache.json"

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

DELETED_FOLDER = APP_FOLDER / "deleted_files"
DELETED_FOLDER.mkdir(exist_ok=True)

CATALOG_CACHE_VERSION = 4
WAVEFORM_ASSET_VERSION = "wf10"
WAVEFORM_MAX_SECONDS = 10.0
WAVEFORM_POINT_COUNT = 400
WAVEFORM_VECTOR_SIZE = 64
LEADING_SILENCE_THRESHOLD = 0.01
WAVEFORM_BLOCK_SECONDS = 1.0
MIN_WAVEFORM_DISPLAY_PERCENT = 4.0


def get_empty_waveform_segment(sample_rate=0):
    return {
        "samples": np.array([], dtype=np.float32),
        "sample_rate": sample_rate,
        "display_duration": 0.0,
        "display_ratio": 0.0,
        "is_truncated": False,
        "envelope": [],
    }


def build_waveform_envelope(samples, point_count=WAVEFORM_POINT_COUNT):
    samples = np.asarray(samples, dtype=np.float32)

    if samples.size == 0:
        return []

    absolute_samples = np.abs(samples)
    edges = np.linspace(0, absolute_samples.size, point_count + 1, dtype=int)
    envelope = []

    for index in range(point_count):
        start = edges[index]
        end = edges[index + 1]

        if end <= start:
            envelope.append(0.0)
            continue

        peak = float(np.max(absolute_samples[start:end]))
        envelope.append(round(peak, 4))

    return envelope


def build_envelope_features(envelope, target_size=WAVEFORM_VECTOR_SIZE):
    envelope = np.asarray(envelope, dtype=np.float32)

    if envelope.size == 0:
        return []

    source_positions = np.linspace(0, 1, envelope.size)
    target_positions = np.linspace(0, 1, target_size)
    resized = np.interp(target_positions, source_positions, envelope)

    max_value = np.max(np.abs(resized))

    if max_value > 0:
        resized = resized / max_value

    return [round(float(value), 4) for value in resized]


def extract_waveform_segment(
    file_path,
    max_seconds=WAVEFORM_MAX_SECONDS,
    silence_threshold=LEADING_SILENCE_THRESHOLD
):
    try:
        with sf.SoundFile(str(file_path)) as audio_file:
            sample_rate = audio_file.samplerate
            max_samples = max(1, int(sample_rate * max_seconds))
            block_size = max(2048, int(sample_rate * WAVEFORM_BLOCK_SECONDS))

            collected_blocks = []
            collected_sample_count = 0
            found_signal = False
            is_truncated = False

            for block in audio_file.blocks(
                blocksize=block_size,
                dtype="float32",
                always_2d=True
            ):
                mono_block = np.mean(block, axis=1).astype(np.float32)

                if not found_signal:
                    active_indexes = np.where(np.abs(mono_block) > silence_threshold)[0]

                    if active_indexes.size == 0:
                        continue

                    mono_block = mono_block[active_indexes[0]:]
                    found_signal = True

                if mono_block.size == 0:
                    continue

                remaining_samples = max_samples - collected_sample_count

                if remaining_samples <= 0:
                    is_truncated = True
                    break

                if mono_block.size > remaining_samples:
                    collected_blocks.append(mono_block[:remaining_samples])
                    collected_sample_count += remaining_samples
                    is_truncated = True
                    break

                collected_blocks.append(mono_block)
                collected_sample_count += mono_block.size

            if not found_signal or not collected_blocks:
                return get_empty_waveform_segment(sample_rate)

            samples = np.concatenate(collected_blocks).astype(np.float32)
            max_value = np.max(np.abs(samples))

            if max_value > 0:
                samples = samples / max_value

            display_duration = samples.size / sample_rate
            display_ratio = min(1.0, display_duration / max_seconds) if max_seconds > 0 else 1.0
            envelope = build_waveform_envelope(samples, WAVEFORM_POINT_COUNT)

            return {
                "samples": samples,
                "sample_rate": sample_rate,
                "display_duration": round(display_duration, 3),
                "display_ratio": round(display_ratio, 4),
                "is_truncated": is_truncated,
                "envelope": envelope,
            }

    except Exception as error:
        print(f"Could not extract waveform segment: {Path(file_path).name} | {error}")
        return get_empty_waveform_segment()


def create_waveform_image(segment_data, output_path):
    try:
        envelope = np.asarray(segment_data.get("envelope", []), dtype=np.float32)

        if envelope.size == 0:
            envelope = np.zeros(10, dtype=np.float32)

        x_values = np.linspace(0, 1, envelope.size)

        plt.figure(figsize=(8, 1.2), dpi=150)
        plt.fill_between(x_values, envelope, -envelope, linewidth=0)
        plt.xlim(0, 1)
        plt.ylim(-1.05, 1.05)
        plt.axis("off")
        plt.tight_layout(pad=0)
        plt.savefig(output_path, bbox_inches="tight", pad_inches=0)
        plt.close()

        return output_path.exists()

    except Exception as error:
        print(f"Failed to create waveform image: {output_path.name} | {error}")
        return False


def get_audio_features_from_segment(segment_data):
    envelope = segment_data.get("envelope", [])

    return {
        "envelope": build_envelope_features(envelope, WAVEFORM_VECTOR_SIZE)
    }

def classify_duration(waveform_segment):
    active_duration = float(waveform_segment.get("display_duration", 0.0))

    if active_duration <= 0:
        return ""

    if active_duration < 1.0:
        return "very_short"

    if active_duration < 3.0:
        return "short"

    if active_duration < 5.0:
        return "medium"

    return "long"


def get_peak_position_class(envelope):
    if not envelope:
        return ""

    max_value = max(envelope)

    if max_value <= 0:
        return "flat"

    peak_index = envelope.index(max_value)
    peak_ratio = peak_index / max(1, len(envelope) - 1)

    if max_value < 0.18:
        return "flat"

    if peak_ratio < 0.25:
        return "early_peak"

    if peak_ratio < 0.70:
        return "middle_peak"

    return "late_peak"


def get_attack_score(envelope):
    if not envelope:
        return 0.0

    first_part = envelope[:max(3, len(envelope) // 10)]

    if not first_part:
        return 0.0

    total_max = max(envelope)

    if total_max <= 0:
        return 0.0

    return round(max(first_part) / total_max, 4)


def get_decay_score(envelope):
    if not envelope:
        return 0.0

    length = len(envelope)
    first_part = envelope[:max(3, length // 4)]
    last_part = envelope[length * 3 // 4:]

    if not first_part or not last_part:
        return 0.0

    first_avg = sum(first_part) / len(first_part)
    last_avg = sum(last_part) / len(last_part)

    if first_avg <= 0:
        return 0.0

    return round(max(0.0, first_avg - last_avg) / first_avg, 4)


def count_envelope_peaks(envelope):
    if len(envelope) < 5:
        return 0

    max_value = max(envelope)

    if max_value <= 0:
        return 0

    threshold = max_value * 0.55
    min_distance = max(3, len(envelope) // 16)

    peaks = []
    last_peak_index = -min_distance

    for index in range(2, len(envelope) - 2):
        current_value = envelope[index]

        is_peak = (
            current_value >= threshold
            and current_value >= envelope[index - 1]
            and current_value >= envelope[index - 2]
            and current_value > envelope[index + 1]
            and current_value > envelope[index + 2]
        )

        if not is_peak:
            continue

        if index - last_peak_index < min_distance:
            if peaks and current_value > envelope[peaks[-1]]:
                peaks[-1] = index
                last_peak_index = index
            continue

        peaks.append(index)
        last_peak_index = index

    return len(peaks)


def classify_start(envelope):
    attack_score = get_attack_score(envelope)

    if attack_score <= 0:
        return ""

    if attack_score >= 0.72:
        return "sharp"

    if attack_score <= 0.28:
        return "slow_build"

    return "soft"


def classify_shape(envelope):
    if not envelope:
        return ""

    length = len(envelope)
    first = envelope[:max(3, length // 4)]
    middle = envelope[length // 4:length * 3 // 4]
    last = envelope[length * 3 // 4:]

    first_avg = sum(first) / len(first)
    middle_avg = sum(middle) / len(middle) if middle else first_avg
    last_avg = sum(last) / len(last) if last else middle_avg

    peak_count = count_envelope_peaks(envelope)
    peak_position = get_peak_position_class(envelope)
    decay_score = get_decay_score(envelope)

    if peak_count >= 3:
        return "multiple_hits"

    if peak_count == 2:
        return "pulsing"

    if peak_position == "early_peak" and decay_score >= 0.45:
        return "hit_fade"

    if first_avg < middle_avg < last_avg:
        return "rising"

    if first_avg > middle_avg > last_avg:
        return "falling"

    avg_values = [first_avg, middle_avg, last_avg]
    if max(avg_values) - min(avg_values) <= 0.18:
        return "steady"

    if peak_position == "late_peak":
        return "rising"

    if peak_position == "early_peak":
        return "hit_fade"

    return "steady"


def classify_energy(envelope):
    if not envelope:
        return ""

    average_energy = sum(envelope) / len(envelope)
    peak_energy = max(envelope)

    combined_energy = average_energy * 0.7 + peak_energy * 0.3

    if combined_energy < 0.22:
        return "low"

    if combined_energy < 0.50:
        return "medium"

    return "high"


def classify_ending(envelope, is_truncated):
    if not envelope:
        return ""

    if is_truncated:
        return "abrupt_cut"

    length = len(envelope)
    last = envelope[length * 3 // 4:]

    if not last:
        return ""

    last_avg = sum(last) / len(last)
    last_value = envelope[-1]
    max_value = max(envelope)

    if max_value <= 0:
        return ""

    last_ratio = last_value / max_value
    last_avg_ratio = last_avg / max_value

    if last_ratio <= 0.10 and last_avg_ratio <= 0.22:
        return "fade_out"

    if last_avg_ratio >= 0.30:
        return "long_tail"

    return "short_tail"


def classify_audio_item(waveform_segment):
    envelope = waveform_segment.get("envelope", [])
    is_truncated = bool(waveform_segment.get("is_truncated", False))

    return {
        "duration_class": classify_duration(waveform_segment),
        "start_class": classify_start(envelope),
        "shape_class": classify_shape(envelope),
        "energy_class": classify_energy(envelope),
        "ending_class": classify_ending(envelope, is_truncated),
        "peak_position_class": get_peak_position_class(envelope),
        "peak_count": count_envelope_peaks(envelope),
        "attack_score": get_attack_score(envelope),
        "decay_score": get_decay_score(envelope),
    }

def format_duration(seconds):
    if seconds is None:
        return "unknown"

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


def is_path_inside_folder(file_path, folder_path):
    try:
        file_path = Path(file_path).absolute()
        folder_path = Path(folder_path).absolute()

        return file_path == folder_path or folder_path in file_path.parents

    except Exception:
        return False


def safe_file_stem(text):
    text = Path(text).stem
    text = re.sub(r'[<>:"/\\|?*]', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text[:80]


def stable_file_id(file_path):
    absolute_path = str(Path(file_path).absolute()).lower()
    return hashlib.sha1(absolute_path.encode("utf-8")).hexdigest()[:12]


def get_asset_name(file_path, extension):
    stem = safe_file_stem(file_path.name)
    file_id = stable_file_id(file_path)

    if extension == ".png":
        return f"{stem}_{file_id}_{WAVEFORM_ASSET_VERSION}{extension}"

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


def safe_rename_file(old_path_text, new_name):
    old_path = Path(old_path_text).absolute()

    if not old_path.exists():
        return False, "File does not exist."

    if not SOURCE_FOLDER:
        return False, "Source folder is not set."

    source_folder = Path(SOURCE_FOLDER).absolute()

    if not is_path_inside_folder(old_path, source_folder):
        return False, "Access denied."

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


def safe_delete_file(file_path_text):
    file_path = Path(file_path_text).absolute()

    if not file_path.exists():
        return False, "File does not exist.", ""

    if not file_path.is_file():
        return False, "Path is not a file.", ""

    if not SOURCE_FOLDER:
        return False, "Source folder is not set.", ""

    source_folder = Path(SOURCE_FOLDER).absolute()

    if not is_path_inside_folder(file_path, source_folder):
        return False, "Access denied.", ""

    deleted_name = f"{file_path.stem}_{stable_file_id(file_path)}{file_path.suffix}"
    deleted_path = DELETED_FOLDER / deleted_name
    counter = 1

    while deleted_path.exists():
        deleted_name = f"{file_path.stem}_{stable_file_id(file_path)}_{counter}{file_path.suffix}"
        deleted_path = DELETED_FOLDER / deleted_name
        counter += 1

    file_path.rename(deleted_path)
    rename_generated_assets(file_path, deleted_path)

    return True, "File moved to deleted files.", str(deleted_path.absolute())

def load_saved_source_folder():
    config = configparser.ConfigParser()

    if not CONFIG_FILE.exists():
        return None

    config.read(CONFIG_FILE, encoding="utf-8")
    saved_folder = config.get("Settings", "source_folder", fallback="").strip()

    return saved_folder or None


def save_source_folder(folder_path):
    config = configparser.ConfigParser()
    config["Settings"] = {
        "source_folder": folder_path
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
        config.write(config_file)


def load_catalog_cache():
    if not CACHE_FILE.exists():
        return {}

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except Exception as error:
        print(f"Could not load catalog cache: {error}")
        return {}


def save_catalog_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as cache_file:
            json.dump(cache, cache_file, ensure_ascii=False, separators=(",", ":"))
    except Exception as error:
        print(f"Could not save catalog cache: {error}")


def get_file_cache_key(file_path):
    return str(Path(file_path).absolute())


def get_file_signature(file_path):
    try:
        stat = Path(file_path).stat()

        return {
            "modified_time": stat.st_mtime,
            "size": stat.st_size,
            "cache_version": CATALOG_CACHE_VERSION,
        }

    except Exception:
        return {
            "modified_time": None,
            "size": None,
            "cache_version": CATALOG_CACHE_VERSION,
        }


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


def clean_unused_generated_files():
    source = Path(SOURCE_FOLDER)

    if not source.exists():
        return False, "Source folder does not exist."

    valid_asset_names = set()
    audio_files = [
        file for file in source.rglob("*")
        if file.is_file() and file.suffix.lower() in AUDIO_EXTENSIONS
    ]

    for file_path in audio_files:
        valid_asset_names.add(get_asset_name(file_path, ".png"))

        if file_path.suffix.lower() in PREVIEW_REQUIRED_AUDIO:
            valid_asset_names.add(get_asset_name(file_path, ".wav"))

    deleted_count = 0

    for folder in [WAVEFORM_FOLDER, PREVIEW_FOLDER]:
        for asset_path in folder.iterdir():
            if asset_path.is_file() and asset_path.name not in valid_asset_names:
                try:
                    asset_path.unlink()
                    deleted_count += 1
                except Exception as error:
                    print(f"Could not delete generated file: {asset_path} | {error}")

    return True, f"Deleted unused generated files: {deleted_count}"


def build_catalog_item(file_path, source, cached_item=None):
    relative_path = file_path.relative_to(source)
    file_extension = file_path.suffix.lower()
    file_signature = get_file_signature(file_path)

    waveform_name = get_asset_name(file_path, ".png")
    waveform_path = WAVEFORM_FOLDER / waveform_name

    preview_path = None
    audio_source_path = f"/audio?path={quote(str(file_path.absolute()))}"

    if file_extension in PREVIEW_REQUIRED_AUDIO:
        preview_name = get_asset_name(file_path, ".wav")
        preview_path = PREVIEW_FOLDER / preview_name

    cache_is_valid = (
        cached_item
        and cached_item.get("signature") == file_signature
        and waveform_path.exists()
    )

    if file_extension in PREVIEW_REQUIRED_AUDIO:
        cache_is_valid = cache_is_valid and preview_path and preview_path.exists()

    if cache_is_valid:
        item = cached_item["item"]
        item["full_path"] = str(file_path.absolute())
        item["path"] = audio_source_path
        item["waveform"] = f"/waveforms/{quote(waveform_path.name)}"

        if file_extension in PREVIEW_REQUIRED_AUDIO and preview_path and preview_path.exists():
            item["path"] = f"/preview/{quote(preview_path.name)}"

        return item, file_signature

    duration, file_type = get_audio_info(file_path)

    if file_extension in PREVIEW_REQUIRED_AUDIO and preview_path:
        if not preview_path.exists():
            create_wav_preview(file_path, preview_path)

        if preview_path.exists():
            audio_source_path = f"/preview/{quote(preview_path.name)}"

    waveform_source_path = preview_path if preview_path and preview_path.exists() else file_path
    waveform_segment = extract_waveform_segment(waveform_source_path)

    if not waveform_path.exists():
        create_waveform_image(waveform_segment, waveform_path)

    audio_features = get_audio_features_from_segment(waveform_segment)
    waveform_display_percent = round(
        max(MIN_WAVEFORM_DISPLAY_PERCENT, waveform_segment["display_ratio"] * 100),
        1
    )
    audio_classes = classify_audio_item(waveform_segment)

    item = {
        "name": file_path.name,
        "name_stem": file_path.stem,
        "extension": file_path.suffix.lower(),
        "duration": duration or 0,
        "duration_text": format_duration(duration),
        "type": file_type or "unknown",
        "folder": str(relative_path.parent),
        "full_path": str(file_path.absolute()),
        "path": audio_source_path,
        "waveform": f"/waveforms/{quote(waveform_path.name)}",
        "waveform_display_percent": waveform_display_percent,
        "waveform_is_truncated": bool(waveform_segment["is_truncated"]),
        "audio_features": audio_features,
        "duration_class": audio_classes["duration_class"],
        "start_class": audio_classes["start_class"],
        "shape_class": audio_classes["shape_class"],
        "energy_class": audio_classes["energy_class"],
        "ending_class": audio_classes["ending_class"],
        "peak_position_class": audio_classes["peak_position_class"],
        "peak_count": audio_classes["peak_count"],
        "attack_score": audio_classes["attack_score"],
        "decay_score": audio_classes["decay_score"],
    }

    return item, file_signature


def main():
    global CATALOG_ROWS

    source = Path(SOURCE_FOLDER)
    catalog_cache = load_catalog_cache()
    updated_cache = {}

    if not source.exists():
        print(f"Folder not found: {source}")
        CATALOG_ROWS = []
        return

    audio_files = [
        file for file in source.rglob("*")
        if file.is_file() and file.suffix.lower() in AUDIO_EXTENSIONS
    ]

    print(f"Audio files found: {len(audio_files)}")

    rows = []

    for file_path in tqdm(
        audio_files,
        desc="Scanning audio files",
        disable=getattr(sys, "frozen", False) or sys.stdout is None
    ):
        file_cache_key = get_file_cache_key(file_path)
        cached_item = catalog_cache.get(file_cache_key)
        item, file_signature = build_catalog_item(file_path, source, cached_item)

        rows.append(item)
        updated_cache[file_cache_key] = {
            "signature": file_signature,
            "item": item,
        }

    rows.sort(key=lambda item: (item["folder"], item["name"].lower()))
    CATALOG_ROWS = rows
    save_catalog_cache(updated_cache)

    print(f"Catalog ready. Files in catalog: {len(CATALOG_ROWS)}")


@app.route("/")
def index():
    return render_template(
        "index.html",
        rows=CATALOG_ROWS,
        file_count=len(CATALOG_ROWS)
    )

@app.route("/shutdown", methods=["POST"])
def shutdown_app():
    def stop_app():
        os._exit(0)

    threading.Timer(0.5, stop_app).start()

    return jsonify({
        "success": True,
        "message": "Application is shutting down."
    })

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
    data = request.get_json() or {}
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
            audio_path = f"/preview/{quote(preview_path.name)}"

    waveform_name = get_asset_name(new_path, ".png")
    waveform_path = WAVEFORM_FOLDER / waveform_name

    return jsonify({
        "success": True,
        "message": str(new_path.absolute()),
        "new_path": str(new_path.absolute()),
        "new_name": new_path.name,
        "new_stem": new_path.stem,
        "new_type": new_path.suffix.replace(".", "").upper(),
        "audio_path": audio_path,
        "waveform_path": f"/waveforms/{quote(waveform_path.name)}"
    })


@app.route("/open-folder", methods=["POST"])
def open_folder():
    data = request.get_json() or {}
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


@app.route("/delete-file", methods=["POST"])
def delete_file():
    data = request.get_json() or {}
    file_path = data.get("path", "")

    if not file_path:
        return jsonify({
            "success": False,
            "message": "Missing file path."
        })

    success, message, deleted_path = safe_delete_file(file_path)

    if success:
        main()

    return jsonify({
        "success": success,
        "message": message,
        "deleted_path": deleted_path
    })

@app.route("/clean-generated", methods=["POST"])
def clean_generated():
    if not SOURCE_FOLDER:
        return jsonify({
            "success": False,
            "message": "Source folder is not set."
        })

    success, message = clean_unused_generated_files()

    return jsonify({
        "success": success,
        "message": message
    })


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
