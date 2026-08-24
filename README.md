# Chronogram TG

[![CI](https://github.com/jagomf/chronogram-tg/actions/workflows/ci.yml/badge.svg)](https://github.com/jagomf/chronogram-tg/actions/workflows/ci.yml)

**Rescue your Telegram photos and videos with their original dates.**

Telegram doesn't save chat photos to your phone's gallery, and if you save
them manually today they show up in Google Photos dated *today* — not when
they were actually sent. Chronogram TG is a small desktop app that downloads
the photos (and optionally videos) of a Telegram chat and stamps each file
with the **original message date**, named exactly like the files Telegram
itself saves to the gallery (`IMG_20240815_143022_123.jpg`). Copy them to
the phone's Telegram gallery folders and Google Photos will back them up
and sort them in their true chronological place.

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
git clone https://github.com/jagomf/chronogram-tg.git
cd chronogram-tg
```

(No git? Use GitHub's **Code → Download ZIP** button, unzip it, and `cd`
into the unzipped folder instead.)

### 2. Create an isolated Python environment and install dependencies

This puts the app's dependencies in a `.venv` folder inside the project,
without touching the rest of your system.

macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> **The `.venv/bin/` prefix is not a typo.** It is what tells your computer
> to use the project's own Python instead of whichever one it would pick by
> default. Keep using it — the app is always run as
> `.venv/bin/python -m chronogram_tg` (macOS) or
> `.venv\Scripts\python -m chronogram_tg` (Windows), from the project
> folder. There is nothing to "activate" and nothing to remember between
> sessions. (If you already know about `source .venv/bin/activate`, it
> works too and lets you drop the prefix — but it must be repeated in every
> new terminal window, so the commands in this README don't rely on it.)

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

Open a terminal in the project folder and run — macOS:

```bash
.venv/bin/python -m chronogram_tg
```

Windows (PowerShell):

```powershell
.venv\Scripts\python -m chronogram_tg
```

That single line is the whole thing: it works in any freshly opened
terminal, with no previous step to remember. If it complains that it cannot
find the file, you are in the wrong folder — `cd` into the project folder
(the one containing `README.md`) and try again.

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

### Console commands

Useful for checking that your credentials work, or for diagnosing a problem
without the window in the way:

```bash
.venv/bin/python -m chronogram_tg chats            # log in and list your chats
.venv/bin/python -m chronogram_tg download --chat 123456 --dest ~/Downloads/rescue
.venv/bin/python -m chronogram_tg download --chat 123456 --dest ~/Downloads/rescue \
    --from 2023-01-01 --to 2023-12-31 --no-videos
```

The `download` command shows a progress counter, waits politely whenever
Telegram asks it to, and can be interrupted at any time with `Ctrl+C` —
running it again resumes where it left off, because files already in the
destination folder are recognised by name and skipped. To *start over*
instead, add `--clean`: it first deletes this download's own files from the
destination (other files in the folder are left alone) and then downloads
everything again. The very first download may ask you to
approve a *data export request* notification in the Telegram app; approve
it and run the command again.

### Getting the photos onto the phone

Connect the phone via USB (or use any file-transfer method) and copy the
downloaded **photos** into `Pictures/Telegram` and the **videos** into
`Movies/Telegram` on the phone. Those are the folders where Telegram itself
saves media when "Save to Gallery" is enabled, so the rescued history and
any newly arriving photos end up living together. Then make sure Google
Photos backs those folders up: **Google Photos → your profile picture →
Photos settings → Backup → Back up device folders → enable "Telegram"**.
Google Photos orders everything by the dates embedded in the files, so the
history lands in its true chronological place. (Any other backed-up folder,
`DCIM/Camera` included, works just as well — the dates travel inside the
files.) Alternatively, upload the folder at
[photos.google.com](https://photos.google.com).

### Filename patterns

By default files are named the way Telegram for Android names them when
saving to the gallery: `IMG_20240815_143022_123.jpg` for photos and
`VID_20240815_143022_123.mp4` for videos — except the date and time are the
message's, in UTC, with milliseconds used to avoid collisions. The settings
dialog offers other presets (Google Pixel camera style `PXL_...`, plain
date) and a free template with live preview.

## ⚠️ Security

- The `.session` file created after login grants **full access to your
  Telegram account**. Treat it like a password: never share it, never commit
  it, never upload it anywhere.
- The same applies to your `.env` file (`api_id`/`api_hash`).
- The repository's `.gitignore` already excludes both, plus the downloads
  folder. Keep it that way.

## License

[MIT](LICENSE).
