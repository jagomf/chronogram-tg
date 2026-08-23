# Chronogram TG

**Rescue your Telegram photos and videos with their original dates.**

Telegram doesn't save chat photos to your phone's gallery, and if you save
them manually today they show up in Google Photos dated *today* — not when
they were actually sent. Chronogram TG is a small desktop app that downloads
the photos (and optionally videos) of a Telegram chat and stamps each file
with the **original message date**, using camera-style filenames
(`PXL_20240815_143022123.jpg`). Copy the resulting files to your phone's
`/DCIM/Camera` folder and Google Photos will back them up and sort them in
their true chronological place.

> **Project status:** the repository scaffolding and implementation plan are
> ready; the application itself is being built following [PLAN.md](PLAN.md).

## How it works

1. You log into Telegram with your own account (official MTProto API via
   [Telethon](https://github.com/LonamiWebs/Telethon)) — first run only.
2. You pick a chat, a date range (or the whole chat) and a destination
   folder.
3. The app downloads every photo (and video, if enabled) at a gentle pace,
   writing the message's date into the file:
   - **Photos:** EXIF `DateTimeOriginal` (UTC) + file modification time.
   - **Images sent as files:** original EXIF is respected if present.
   - **Videos:** MP4 `creation_time` via ffmpeg (lossless, no re-encoding).
4. If the download is interrupted, just run it again — already-downloaded
   files are detected and skipped.

## Requirements

- **Python 3.11 or newer.** On macOS and Windows, install it from
  [python.org/downloads](https://www.python.org/downloads/) — the python.org
  installer includes Tk, the toolkit the app's window needs. (Pythons from
  pyenv or Homebrew often omit it; you can check yours with
  `python3 -c "import tkinter"`, which should print nothing at all. On a
  Homebrew Python, `brew install python-tk@3.14` adds it.)
- **ffmpeg** — *only if you want videos*. Photos work without it.
- A **Telegram API key** (`api_id` + `api_hash`) — free, takes 2 minutes,
  instructions below.

## Installation

Open a terminal (**Terminal** app on macOS, **PowerShell** on Windows) and
paste these commands one by one.

### 1. Get the code

```bash
git clone https://github.com/YOUR_USERNAME/chronogram-tg.git
cd chronogram-tg
```

(No git? Use GitHub's **Code → Download ZIP** button, unzip it, and `cd`
into the unzipped folder instead.)

### 2. Create an isolated Python environment and install dependencies

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. (Optional) Install ffmpeg for video support

macOS (with [Homebrew](https://brew.sh)):

```bash
brew install ffmpeg
```

Windows (PowerShell):

```powershell
winget install --id Gyan.FFmpeg
```

Then close and reopen the terminal. Verify with `ffmpeg -version`. If ffmpeg
is missing the app still works — the "Include videos" option is simply
disabled.

### 4. Get your Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in with your
   phone number.
2. Click **API development tools**.
3. Fill the form (App title: `Chronogram TG`, Short name: `chronogram`,
   platform: Desktop — the rest can stay empty).
4. Copy the **api_id** (a number) and **api_hash** (a long hex string).
5. In the project folder, create a file named `.env` with this content:

```
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

## Usage

With the environment activated (step 2), run:

```bash
python -m chronogram_tg
```

- **First run:** enter your phone number, the code Telegram sends you, and
  your 2FA password if you have one. The session is remembered — you won't
  be asked again.
- Pick the **chat**, the **scope** (whole chat or a date range), the
  **destination folder**, and whether to **include videos**.
- Press **Start**. You can **pause/resume** or **cancel** at any time; the
  progress bar shows `downloaded / total`.
- Large chats are downloaded deliberately slowly to respect Telegram's
  limits. If Telegram asks the app to wait (flood control), it waits and
  continues automatically. Interrupted? Run again — it resumes.

### Getting the photos onto the phone

Connect the phone via USB (or use any file-transfer method) and copy **all**
downloaded files into `/DCIM/Camera` on the phone. Google Photos will back
them up and order them by their embedded dates. Alternatively, upload the
folder at [photos.google.com](https://photos.google.com).

### Filename patterns

By default files are named like a Google Pixel camera:
`PXL_20240815_143022123.jpg` (date and time in UTC, milliseconds used to
avoid collisions). The settings dialog offers other presets (`IMG_...`,
plain date) and a free template with live preview.

## ⚠️ Security

- The `.session` file created after login grants **full access to your
  Telegram account**. Treat it like a password: never share it, never commit
  it, never upload it anywhere.
- The same applies to your `.env` file (`api_id`/`api_hash`).
- The repository's `.gitignore` already excludes both, plus the downloads
  folder. Keep it that way.

## License

[MIT](LICENSE).
