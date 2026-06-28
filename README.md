# Sound Effects Catalog

Local web app for browsing, previewing, filtering, renaming, organizing, and comparing sound effect files.

The app scans a selected folder, creates waveform previews, classifies audio files by basic sound characteristics, and opens a local browser catalog.

## Main features

### Audio catalog

- Scans a selected folder recursively.
- Supports common audio formats:
  - WAV
  - MP3
  - AIFF / AIF
  - FLAC
  - OGG
  - M4A
- Shows every audio file as a card.
- Displays:
  - audio player;
  - file name;
  - file type;
  - duration;
  - waveform preview;
  - classification metadata;
  - action buttons.

### Waveform preview

- Generates waveform images automatically.
- Uses only the first 10 seconds of active audio.
- Ignores leading silence before waveform generation.
- Short sounds are displayed with proportionally shorter waveform width.
- Long sounds show an ellipsis marker to indicate that the audio continues after the displayed waveform.
- Generated waveform files are stored in the `waveforms/` folder.

### Audio classification

Each file is automatically classified by:

- Duration
  - Very short: under 1 second of active audio
  - Short: 1–3 seconds
  - Medium: 3–5 seconds
  - Long: over 5 seconds
- Start
  - Sharp start
  - Soft start
  - Slow build
- Shape
  - Hit and fade
  - Rising
  - Falling
  - Steady
  - Pulsing
  - Multiple hits
- Energy
  - Low
  - Medium
  - High
- Ending
  - Short tail
  - Long tail
  - Abrupt cut
  - Fade out
- Peak position
  - Early peak
  - Middle peak
  - Late peak
  - Flat

### Search and filters

- Text search by:
  - file name;
  - folder;
  - full path;
  - file type.
- Dropdown filters:
  - Duration
  - Start
  - Shape
  - Energy
  - Ending
- Reset filters button.
- Visible result count:
  - total file count;
  - currently shown file count.

### Similarity search

The app includes two waveform-based search modes.

#### Find similar

Finds sounds with a similar waveform shape.

The score uses:

- full waveform similarity;
- beginning similarity;
- duration class match;
- peak position match;
- shape class match.

Results show a similarity percentage.

#### Find same beginning

Finds files whose beginning is identical to the selected sound.
Useful for finding duplicates.


### Favorites

- Mark files as favorites.
- Favorites are stored locally in the browser using `localStorage`.
- Show only favorite files using the `Show favorites` button.

### File actions

Each audio card supports:

- Rename file
- Open folder
- Delete file

Delete does not permanently delete the file. It moves the file into the local `deleted_files/` folder.
Might be used to collect desired files into one folder while browsing catalog. after that take them all from `deleted_files/` folder.

### Generated files cleanup

The `Clean generated files` button removes unused generated waveform and preview files that no longer match existing source audio files.

### Loading indicator

The app displays a loading overlay while:

- the catalog interface is loading;
- similarity searches are running.

This prevents button clicks before JavaScript is ready.

## Project structure

Recommended structure:

```text
sound-effects-catalog/
├── sound_catalog_app.py
├── config.ini
├── catalog_cache.json
├── templates/
│   └── index.html
├── static/
│   ├── styles.css
│   └── app.js
├── waveforms/
├── previews/
└── deleted_files/
```

Generated folders and files should usually not be committed to GitHub:

```text
catalog_cache.json
config.ini
waveforms/
previews/
deleted_files/
```

## Requirements

Python packages used by the app:

```text
flask
mutagen
tqdm
matplotlib
numpy
soundfile
```

Optional but recommended:

```text
ffmpeg
```

FFmpeg is used as a fallback for preview generation when needed.

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install flask mutagen tqdm matplotlib numpy soundfile
```

## Running the app

Run:

```bash
python sound_catalog_app.py
```

The app opens a launcher window.

Choose the folder that contains your sound effects and click Launch.

The local web app opens at:

```text
http://127.0.0.1:5000
```

## First launch notes

The first scan can take some time if the folder contains many audio files.

The app will generate:

- waveform images;
- preview audio files for formats that need browser-compatible playback;
- a catalog cache.

Later launches should be faster because cache is used.

## Cache reset

Delete `catalog_cache.json` when:

- classification logic changes;
- waveform generation logic changes;
- audio metadata fields change;
- filters behave unexpectedly.

Also clear the `waveforms/` folder if waveform rendering logic changes.

## Browser refresh

If JavaScript or CSS was changed, hard-refresh the browser:

```text
Ctrl + F5
```

The HTML template can also use cache-busting for JavaScript:

```html
<script defer src="{{ url_for('static', filename='app.js') }}?v=7"></script>
```

Increase the version number after changing `app.js`.

## Exporting to Windows `.exe`

The app can be exported to a standalone Windows executable using PyInstaller.

Install PyInstaller:

```bash
pip install pyinstaller
```

If the `pyinstaller` command is not recognized, run it through Python:

```bash
python -m PyInstaller --onefile --windowed --name SoundEffectsCatalog --add-data "templates;templates" --add-data "static;static" --add-binary "ffmpeg.exe;." sound_catalog_app.py
```

The exported file will be created here:

```text
dist\SoundEffectsCatalog.exe
```

### Notes for `.exe` builds

The app is built with `--windowed`, so it runs without a terminal window.

Because of this, terminal progress bars such as `tqdm` must be disabled when the app is running as a packaged executable.

The app detects this using:

```python
getattr(sys, "frozen", False)
```

Generated runtime files and folders may appear next to the executable or inside the working folder:

```text
config.ini
catalog_cache.json
waveforms/
previews/
deleted_files/
```

These files are normal and should not be committed to GitHub.


## Notes

This app is intended for local use.

It is not designed as a public web service. It serves local files from the selected source folder and should be used only on a trusted local machine.

### Closing the app

When the app is exported as a Windows `.exe`, closing the browser tab does not automatically stop the local Flask server.

For this reason, the app includes an **Exit app** button next to the main title.

Use this button to properly close the application after finishing work.

The button sends a shutdown request to the local app and then stops the running `.exe` process.
