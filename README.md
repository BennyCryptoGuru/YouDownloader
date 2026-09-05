# YouDownloader

YouDownloader is a local desktop-style web app for previewing and downloading public YouTube videos and playlists. It combines a Python/FastAPI backend with a lightweight HTML/CSS/JavaScript frontend and can run either in your browser or inside a pywebview desktop window.

> Use this project only for content you own, content you are allowed to download, or content where downloading is permitted by the platform owner and applicable law.

## Features

- Paste a YouTube video, YouTube Shorts or playlist URL and load metadata before downloading.
- Show video title, channel, thumbnail, duration, views and playlist items.
- Choose output preset such as MP4 video, WebM video, MP3 audio, M4A audio or Opus audio.
- Save a default download folder in persistent settings.
- Download playlists into a subfolder named after the playlist.
- Resume interrupted playlist downloads without jumping back to old missing items.
- Retry network failures automatically and wait for the connection to return.
- Show download speed and current-item percentage when available.
- Keep download history in the queue until you remove it manually.
- Select target folders through the native Windows folder picker when running with pywebview.

## Tech stack

- Backend: Python 3.11+, FastAPI, Uvicorn, Pydantic
- Frontend: HTML, CSS and vanilla JavaScript
- Desktop shell: pywebview / WebView2 on Windows
- Downloader engine: yt-dlp
- Media processing: FFmpeg / FFprobe
- Database: SQLite through aiosqlite
- HTTP/network utilities: httpx
- Process management: psutil
- Tests and linting: pytest, pytest-asyncio, Ruff

## Requirements

Install these system-level tools before running the app:

- Python 3.11 or newer
- Git
- Node.js or Deno, recommended for reliable YouTube extraction with yt-dlp
- FFmpeg and FFprobe for MP3 conversion and MP4 merging

Python packages are listed in:

- `requirements.txt`
- `pyproject.toml`

## Install on Windows

Clone the repository:

```powershell
git clone https://github.com/BennyCryptoGuru/YouDownloader.git
cd YouDownloader
```

Run the installer:

```cmd
install.bat
```

The installer creates `.venv`, installs Python dependencies, prepares runtime folders, creates/updates a `YouDownloader` desktop shortcut pointing to `start.bat`, and checks optional system tools such as Node.js, FFmpeg/FFprobe and WebView2. If FFmpeg is not bundled in `resources/bin/`, the installer tries to install it with `winget`.

You can also install everything manually:

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install Python dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install FFmpeg:

```powershell
winget install Gyan.FFmpeg
```

Alternatively, place `ffmpeg.exe` and `ffprobe.exe` into:

```text
resources/bin/
```

The app checks bundled binaries first and then falls back to your system `PATH`.

## Run the app

Recommended on Windows:

```cmd
start.bat
```

`start.bat` automatically runs `install.bat` first when `.venv` is missing. By default it starts the pywebview desktop window. If the app is already running on `127.0.0.1:8765`, it opens the existing UI instead of starting a second copy.

Run only the local web server:

```cmd
start.bat -Server
```

Stop every YouDownloader session started from this project folder:

```cmd
stop.bat
```

Run as a local web server:

```powershell
python -m backend.main --server --port 8765
```

Then open:

```text
http://127.0.0.1:8765/
```

Run as a desktop window:

```powershell
python -m backend.main
```

If pywebview is not available, the app automatically falls back to server mode.

## Configuration

Runtime settings are stored locally and are intentionally not committed to Git:

```text
config/settings.json
data/app.db
cache/
logs/
```

An example settings file is provided at:

```text
config/settings.example.json
```

The default language is English. You can change the language, theme, default preset, quality and download directory from the Settings dialog.

## Development

Install development dependencies:

```powershell
pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest -q
```

Run linting:

```powershell
python -m ruff check .
```

Check frontend JavaScript syntax:

```powershell
node --check frontend/js/app.js
```

## Windows helper scripts

- `install.bat` — double-click installer wrapper for `scripts/install.ps1`.
- `start.bat` — double-click launcher wrapper for `scripts/start.ps1`.
- `stop.bat` — double-click stop wrapper for `scripts/stop.ps1`.
- `scripts/install.ps1` — creates/repairs `.venv`, installs requirements, creates/updates the desktop shortcut and checks Node.js, FFmpeg/FFprobe and WebView2.
- `scripts/start.ps1` — starts the desktop app or server mode and avoids opening duplicate instances when the server is already running.
- `scripts/stop.ps1` — stops YouDownloader backend/desktop processes and their child processes such as yt-dlp, FFmpeg or WebView2.

## Project structure

```text
backend/
  api/             FastAPI route handlers
  core/            app configuration, validation and errors
  domain/          Pydantic models and download presets
  repositories/    SQLite database layer
  services/        yt-dlp integration, metadata, downloads, events
frontend/
  assets/          SVG logo and favicon
  css/             application styles
  js/              frontend modules
resources/
  bin/             optional local FFmpeg/FFprobe binaries
scripts/           Windows install and start helpers
tests/             pytest test suite
```

## Notes about YouTube downloads

YouDownloader uses yt-dlp under the hood. Availability and supported formats may change when YouTube changes its site behavior. Keeping yt-dlp updated is recommended:

```powershell
pip install --upgrade yt-dlp
```

Some videos may be unavailable because they are private, region-restricted, age-restricted, deleted, members-only, DRM-protected, or because the requested format is not available.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
