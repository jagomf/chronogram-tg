# PLAN.md — implementation plan for Chronogram TG

**Audience:** the implementing agent (Claude Opus 5).
**Read first:** [AGENTS.md](AGENTS.md) and [docs/DECISIONS.md](docs/DECISIONS.md).

**Progress:** tasks 1–8 implemented; task 8 (chat picker) awaits the
owner's live check. Task 2 confirmed live on 2026-08-23;
task 5 exercised live by the owner on a 161-item/6.5 GB test chat through
2026-08-24 (downloads, cancel, per-file and in-file resume, flood waits) —
the Google Photos date spot-check folds into task 12's acceptance. ffmpeg
is installed since 2026-08-24, so the video tests run for real. Milestone A
(console tool) is closed; CI is green on all platforms including the
downloader work. On 2026-08-24 the owner changed the destination and
default naming (decision D18: Telegram gallery folders and Telegram-style
names instead of `/DCIM/Camera` and Pixel names). Task 6's window shell and
task 7's login flow are verified by `scripts/smoke_gui.py` (GUI checks live
there, never in pytest — see AGENTS.md); task 7 was confirmed live by the
owner on 2026-08-25 (real phone→code login through the window, entry-size
and centring polish reviewed over screenshots). Update this line as part
of each task's commit.

## Ground rules (apply to every task)

1. **One task at a time, in order.** Complete a task, verify its
   done-criteria, commit (`Task N: <summary>`), then move on. Never
   implement several tasks in one sitting or one commit. If a task fails
   verification, fix it before continuing — the last commit must always be a
   known-good state.
2. **Closed decisions are closed.** Anything in `docs/DECISIONS.md` or in
   this plan's "Fixed behaviour" notes must not be changed without asking
   the user. If something proves impossible as specified, stop and ask.
3. **Security is non-negotiable.** Never commit `*.session`, `.env`,
   credentials or downloaded media. Never weaken `.gitignore`. Never log or
   echo credential values. Check `git status` before each commit.
4. **The user is not a Python developer.** Anything they must run by hand
   goes in the README as exact copy-paste commands for macOS *and* Windows.
   If a task changes how the app is installed or run, updating the README is
   part of that task.
5. **Live-Telegram verification is interactive.** You cannot log into
   Telegram yourself. When a done-criterion says *"user verifies"*, prepare
   the exact command, tell the user precisely what to run and what they
   should see, and wait for their confirmation before committing. All live
   tests use a **small throwaway chat** (user creates one, e.g. "Saved
   Messages" or a test group with ~10 photos/videos) — never the real
   family chat until the final acceptance task.
6. **Cross-platform always.** Use `pathlib`, no shell-outs except ffmpeg
   (invoked via `subprocess` with a list argv, never a shell string). Any
   platform-specific code needs an explicit reason.
7. **Unit tests** accompany pure logic (naming, metadata decisions, resume
   scanning). GUI and network code are verified manually. `pytest` must pass
   before every commit.

## Fixed behaviour (summary of the closed spec — do not deviate)

- Telethon + **takeout session** for bulk download; short pause between
  items; catch `FloodWaitError` and wait it out.
- All timestamps **UTC** (filenames, EXIF, `creation_time`, file mtime).
- Compressed photos: write EXIF `DateTimeOriginal` = message date (piexif).
- Image documents: keep existing `DateTimeOriginal`; write it only if absent.
- Videos: optional, require ffmpeg on PATH, write `creation_time` with
  `-c copy` (no re-encode).
- Output: **flat folder**, no subfolders.
- Filenames: template engine with tokens; default preset Telegram
  (`{kind}_{date}_{time}_{ms}` → `IMG_20240815_143022_123.jpg`, `VID_…` for
  videos — the exact format Telegram for Android writes when saving to the
  gallery; decision D18, changed 2026-08-24). Pixel (`PXL_…`) and plain-date
  presets remain selectable; millisecond counter resolves same-second
  collisions deterministically.
- Resume: skip files that already exist in the destination by name.
- UI: CustomTkinter, English strings, download in a worker thread,
  pause/resume/cancel, progress `n / total`, ffmpeg banner, chat-picker
  modal with search, date-range modal, settings modal (pattern + live
  preview + presets, logout with confirmation). All modals close on Esc —
  except the login window, where closing quits the app (owner-approved
  convention, 2026-08-26). Windows open centred on the screen.

## Proposed code layout

```
chronogram_tg/
├── __init__.py          # __version__
├── __main__.py          # entry point: python -m chronogram_tg
├── config.py            # .env loading, paths (session file, settings), settings persistence
├── naming.py            # filename pattern engine, presets, collision handling  [pure, tested]
├── metadata.py          # EXIF via piexif, mtime, ffmpeg detection & video dates [mostly pure, tested]
├── tg.py                # Telethon wrapper: connect, login steps, dialogs, takeout, media iteration
├── downloader.py        # orchestration: plan → download → stamp; resume; pause/cancel; progress callbacks
└── gui/
    ├── __init__.py
    ├── app.py           # main window + wiring
    ├── login.py         # login window (phone → code → 2FA)
    ├── chat_picker.py   # modal: chat list + search
    ├── date_range.py    # modal: date range selection
    └── settings.py      # modal: pattern editor + presets + preview, logout
tests/
    ├── test_naming.py
    ├── test_metadata.py
    └── test_downloader.py
```

Design rule: `naming.py`, `metadata.py`, `downloader.py` must not import
anything from `gui/` or Telethon types beyond what they strictly need —
`downloader.py` talks to the GUI only through callbacks (`on_progress`,
`on_state`), which is also what makes it testable and reusable from the CLI.

---

## Phase 1 — executable skeleton (console first)

The point of this phase is to validate credentials, login and download
mechanics with the user **before** any GUI exists.

### Task 1 — Package skeleton and config

- **Objective:** runnable empty package + credential loading.
- **Files:** `chronogram_tg/__init__.py`, `__main__.py`, `config.py`,
  `.env.example` (placeholder values, safe to commit), `tests/` dir.
- **Details:** `config.py` loads `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`
  from `.env` (python-dotenv). If missing, print a friendly English message
  pointing to the README section and exit — do not crash with a traceback.
  Define the session file location (`chronogram.session` in the project
  folder) and a JSON settings file path for persisted preferences (pattern
  template). `__main__.py` for now just parses `--version` and prints it.
- **Done when:** `python -m chronogram_tg --version` prints the version;
  running without `.env` prints the friendly message; `pytest` passes
  (trivial test that config parses a temp `.env`).
- **Depends on:** —

### Task 2 — Telegram login and chat listing (console)

- **Objective:** prove credentials, login flow and session persistence.
- **Files:** `chronogram_tg/tg.py`, `__main__.py`.
- **Details:** `tg.py` exposes an async-friendly wrapper (Telethon is
  asyncio; run it via `asyncio.run` in CLI, and later via a dedicated thread
  from the GUI). Implement: connect; `is_authorized()`; login steps as
  separate calls (`send_code(phone)`, `sign_in(code)`,
  `sign_in_2fa(password)`) so the GUI can drive them later; `list_dialogs()`
  returning `(id, display_name, kind)`. Add CLI subcommand
  `python -m chronogram_tg chats` that logs in interactively (console
  prompts) and prints the first ~50 dialogs.
- **Done when:** *user verifies:* running `chats` asks for phone/code
  (first time only), prints their chat list; a second run asks nothing
  (session persisted). `chronogram.session` exists locally and `git status`
  shows it ignored.
- **Depends on:** Task 1.

### Task 3 — Filename pattern engine

- **Objective:** deterministic naming with presets and collision handling.
- **Files:** `chronogram_tg/naming.py`, `tests/test_naming.py`.
- **Details:** tokens: `{date}` → `YYYYMMDD`, `{time}` → `HHMMSS`, `{ms}` →
  3-digit milliseconds, `{ext}` handled separately (always appended from the
  media's real extension); `{kind}` renders IMG or VID by media type, the
  way Telegram prefixes its gallery files. Presets: `Telegram` →
  `{kind}_{date}_{time}_{ms}` (default, D18); `Pixel` →
  `PXL_{date}_{time}{ms}`; `Plain date` → `{date}_{time}{ms}`. All times
  UTC. Collision rule: message dates have
  second precision; a `NameAllocator` class takes (datetime, ext) and yields
  names, bumping the millisecond field `000, 001, 002…` for items sharing
  the same second **in message order**, so the same input sequence always
  produces the same names (required for resume). Also validate templates
  (unknown token → error string for the GUI preview).
- **Done when:** `pytest` covers: each preset's exact output for a known
  datetime; three same-second items get `000/001/002`; determinism across
  two allocator runs; invalid template rejected.
- **Depends on:** Task 1 (repo layout only).

### Task 4 — Metadata stamping

- **Objective:** date-writing logic for photos, image documents and videos.
- **Files:** `chronogram_tg/metadata.py`, `tests/test_metadata.py`.
- **Details:**
  - `stamp_photo(path, dt_utc)` — write EXIF `DateTimeOriginal` (and
    `DateTimeDigitized`/`DateTime` for good measure) with piexif, format
    `YYYY:MM:DD HH:MM:SS`, preserving any other existing EXIF fields.
  - `stamp_image_document(path, dt_utc)` — read EXIF first; if
    `DateTimeOriginal` present, leave EXIF untouched (D3); else same as
    above. Handle non-JPEG documents piexif can't write (PNG, WebP):
    fall back to mtime only, and report which path was taken.
  - `detect_ffmpeg()` — `shutil.which("ffmpeg")`, cached at startup.
  - `stamp_video(path, dt_utc)` — ffmpeg `-i in -c copy -metadata
    creation_time=<ISO8601 UTC> out` to a temp file in the same directory,
    then atomic replace. Raise a clear error if ffmpeg exits non-zero.
  - `set_mtime(path, dt_utc)` — always applied last, to every file type.
- **Done when:** `pytest` passes using tiny generated fixtures (create a
  JPEG with Pillow-free minimal EXIF via piexif itself; skip video tests
  automatically when ffmpeg is absent, run them when present). Tests check:
  photo gets the date; document with existing `DateTimeOriginal` is
  untouched; document without it gets stamped; mtime set correctly (UTC).
- **Depends on:** Task 1.

### Task 5 — Console downloader with takeout, pacing and resume

- **Objective:** the complete download pipeline, driven from the CLI.
- **Files:** `chronogram_tg/downloader.py`, `tg.py` (extend), `__main__.py`.
- **Details:**
  - `tg.py`: `iter_media(chat_id, from_date, to_date, include_videos)`
    inside a **takeout session** (`client.takeout(...)`; handle the
    `TakeoutInitDelayError` by telling the user Telegram wants a delay —
    typically confirmed from the official app — and how to retry). Yield
    `(message_id, utc_datetime, media_kind, extension)` oldest-first.
    Media kinds: `photo` (`MessageMediaPhoto`), `image_document`
    (document with image mime), `video` (document with video mime,
    including video notes only if trivially supported — otherwise skip and
    count them as skipped).
  - `downloader.py`: two passes. **Pass 1 (plan):** iterate message
    metadata only, allocate all filenames with `NameAllocator` (guarantees
    deterministic names independent of which files already exist), compute
    total count. **Pass 2 (download):** for each planned item, if the
    target filename already exists → skip (resume, D11); else download to a
    `.part` temp name, stamp metadata, `set_mtime`, rename to final name,
    sleep a short pause (~1 s, constant in one place). Check
    pause/cancel flags between items. On `FloodWaitError`, report the wait
    via callback, sleep it out, continue. Progress/state via callbacks so
    the CLI prints and the GUI (later) updates widgets from the same hooks.
  - CLI: `python -m chronogram_tg download --chat <id> --dest <folder>
    [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--no-videos]` with a console
    progress line.
- **Done when:** *user verifies on the throwaway chat:* full run downloads
  everything with correct Telegram-style names; a photo checked with
  `exiftool` (or macOS Get Info / Google Photos web upload) shows the
  message date; cancelling mid-run (Ctrl+C) and rerunning skips existing
  files and completes; `--from/--to` limits correctly; with ffmpeg absent
  or `--no-videos`, videos are skipped and reported.
- **Depends on:** Tasks 2, 3, 4.

**Milestone A:** the tool is fully functional from the console. Ask the user
to confirm the end-to-end result in Google Photos (upload 2–3 test files via
photos.google.com and check their dates) before starting the GUI.

---

## Phase 2 — GUI (CustomTkinter)

CustomTkinter is pinned at **6.0.0** — check its current docs/changelog for
API differences from the widely-documented 5.x before writing widget code.
GUI pattern for Telethon: run one asyncio loop in a background thread for
all Telegram work; GUI thread communicates via
`asyncio.run_coroutine_threadsafe` and callbacks marshalled back with
`widget.after(...)`. Establish this in Task 6 and reuse it everywhere.

### Task 6 — App shell and async bridge

- **Objective:** main window skeleton + thread/asyncio plumbing.
- **Prerequisite (already satisfied on the owner's machine):** the
  interpreter must have Tk support. The project venv was rebuilt on
  2026-08-23 with Homebrew's Python 3.14.7 (`brew install python-tk@3.14`,
  which brings Tcl/Tk 9.0), and a smoke test confirmed CustomTkinter 6.0.0
  creates `CTk`, `CTkLabel`, `CTkButton` and `CTkProgressBar` widgets and
  detects the system appearance mode. If the venv is ever recreated, use
  `/opt/homebrew/opt/python@3.14/bin/python3.14` — pyenv's 3.14.6, the
  machine's default `python3`, has no `_tkinter`. Verify with
  `python -c "import tkinter"` before writing GUI code. Never fall back to
  macOS's `/usr/bin/python3`: its Tk 8.5 renders CustomTkinter badly.
- **Files:** `chronogram_tg/gui/__init__.py`, `gui/app.py`, `__main__.py`.
- **Details:** `python -m chronogram_tg` (no subcommand) now opens the main
  window: placeholder rows for chat selector, scope, destination, videos
  checkbox, progress area, Start/Pause/Cancel buttons (disabled), settings
  gear button. ffmpeg banner logic: on startup, if `detect_ffmpeg()` fails,
  show the non-modal banner "⚠ ffmpeg not found — videos are unavailable.
  See README." and disable+uncheck the videos checkbox; otherwise checkbox
  enabled and checked (D6/D7). Start the Telethon background loop thread.
- **Done when:** app opens on macOS without freezing, banner appears iff
  ffmpeg is hidden from PATH (verify by launching with a stripped PATH),
  closing the window cleanly stops the background loop. CLI subcommands
  from Phase 1 still work.
- **Depends on:** Task 5.

### Task 7 — Login window

- **Objective:** GUI login flow, shown only when the session is invalid.
- **Files:** `gui/login.py`, `gui/app.py`.
- **Details:** on startup, `is_authorized()`; if false, show login window
  (phone → code → optional 2FA password, with error feedback for wrong
  code/password) before the main window. Reuse the step methods from
  Task 2 — no Telethon calls directly in GUI code.
- **Done when:** *user verifies:* after logging out (delete session file
  manually for now), app shows login and completes it; next launch skips
  straight to the main window.
- **Depends on:** Task 6.

### Task 8 — Chat picker modal

- **Objective:** select the source chat.
- **Files:** `gui/chat_picker.py`, `gui/app.py`.
- **Details:** modal dialog listing dialogs (name + kind), text box filters
  as you type (case-insensitive substring). Selection closes the modal and
  shows the chat name in the main window. Load dialogs via the async
  bridge with a loading state.
- **Done when:** *user verifies:* search finds the throwaway chat, selection
  is reflected in the main window, Start remains disabled until chat +
  destination are set.
- **Depends on:** Task 7.

### Task 9 — Scope (date range) and destination

- **Objective:** remaining pre-download inputs.
- **Files:** `gui/date_range.py`, `gui/app.py`.
- **Details:** radio "Whole chat" / "Date range"; the latter opens a modal
  with from/to date entries (simple validated `YYYY-MM-DD` entries are
  fine; no calendar-widget dependency). Chosen range stays visible in the
  main window. Destination folder via `tkinter.filedialog.askdirectory`;
  the chosen folder persists in `settings.json` and is preselected on the
  next launch (owner request, 2026-08-26). The date-range modal closes on
  Esc like the chat picker.
- **Done when:** invalid dates rejected with inline message; chosen values
  visible in main window; Start button enables when chat + destination set;
  a relaunch shows the previous destination already selected.
- **Depends on:** Task 8.

### Task 10 — Download wiring: progress, pause/resume, cancel

- **Objective:** connect the GUI to `downloader.py`.
- **Files:** `gui/app.py`.
- **Details:** Start launches the download through the async bridge;
  progress callbacks update bar + `n / total` counter (e.g. `347 / 1,520`)
  via `after()`. Pause toggles to Resume; Cancel stops after the current
  item and re-enables the form. FloodWait shows a status line ("Telegram
  asked to wait 42 s — resuming automatically"). Errors on individual items
  are counted and listed at the end, not fatal. Inputs are disabled while
  running. The progress bar is hidden while no transfer runs — use the
  existing show/hide_progress_bar helpers: show on Start, keep during
  pause, hide on cancel and on completion (owner request, 2026-08-26).
- **Done when:** *user verifies on the throwaway chat:* full GUI run
  matches the Task 5 CLI results; pause/resume and cancel behave; UI stays
  responsive throughout; relaunching resumes.
- **Depends on:** Task 9.

### Task 11 — Settings modal: pattern editor and logout

- **Objective:** configuration UI.
- **Files:** `gui/settings.py`, `config.py` (persist template).
- **Details:** modal with: preset dropdown (Telegram / Pixel / Plain
  date), editable template field, **live preview** rendered with a fixed
  sample datetime, inline error for invalid templates (from Task 3's
  validator), Save/Cancel. Template persists in the settings JSON and is
  used by the downloader. Logout button → confirmation dialog ("Log out?
  You will need to enter the code again") → Telethon `log_out()` + session
  file removal → back to login window (D8).
- **Done when:** *user verifies:* changing preset changes downloaded names;
  invalid template can't be saved; logout returns to login and a fresh
  login works.
- **Depends on:** Task 10.

### Task 12 — Hardening pass and final acceptance

- **Objective:** close the loop on the real use case.
- **Files:** whatever the pass uncovers; `README.md`.
- **Details:** review error paths (no network at launch, revoked session →
  friendly re-login, destination not writable, disk full mid-run leaves
  only `.part` files never half-stamped finals). Re-read the README
  top-to-bottom and perform a clean-machine walkthrough of every command
  (fresh venv). Update anything stale.
- **Done when:** `pytest` green; *user performs final acceptance:* runs the
  real family chat download, spot-checks dates in Google Photos, copies
  the photos into `Pictures/Telegram` and the videos into `Movies/Telegram`
  on the Pixel, and enables Google Photos backup for those device folders.
  Their confirmation closes Phase 2.
- **Depends on:** Task 11.

---

## Phase 3 — optional (low priority, only if the user asks for it)

### Task 13 — (OPTIONAL) Packaged executables

- **Objective:** double-clickable `.app` (macOS) / `.exe` (Windows) via
  PyInstaller.
- **Details:** one-folder build, document build commands in README under an
  "Advanced" section. Known pain points: CustomTkinter data files need
  `--collect-all customtkinter`; ffmpeg stays external (still detected on
  PATH); unsigned binaries trigger Gatekeeper/SmartScreen warnings —
  document the right-click-open workaround rather than paying for signing.
- **Done when:** built app launches on the build machine and completes a
  small download. Cross-platform builds require building on each OS —
  document that; do not attempt cross-compilation.
- **Depends on:** Task 12. **Skip unless explicitly requested.**
