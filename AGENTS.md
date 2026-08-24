# AGENTS.md — contract for AI agents working on this repo

## What this project is

Chronogram TG is a small cross-platform (macOS + Windows) desktop app that
downloads the photos/videos of a Telegram chat and stamps each file with the
**original message date** (EXIF / MP4 `creation_time`, in UTC), named the
way Telegram itself names gallery files, so they sort chronologically once
moved to the phone's Telegram gallery folders (`Pictures/Telegram`,
`Movies/Telegram`) and backed up by Google Photos. Primary use is a one-off
rescue of a family photo history, operated by a non-Python user.

Read these before writing any code:

- **[PLAN.md](PLAN.md)** — the implementation plan. Work task by task, in
  order, exactly as specified there.
- **[docs/DECISIONS.md](docs/DECISIONS.md)** — closed design decisions with
  rationale. **You must not reverse, reopen or silently work around any of
  them.** If one seems wrong or impossible, stop and ask the user.

## Hard security rules (non-negotiable)

- **NEVER commit**: `*.session` files, `.env`, any `api_id`/`api_hash`
  value, or downloaded media. `.gitignore` already covers them — do not
  weaken it, and never use `git add -f` on ignored files.
- A Telethon `.session` file grants **full access to the Telegram account**.
  Treat it like a password. Never print its contents, copy it elsewhere, or
  include it in logs, tests or fixtures.
- Never hardcode credentials in source, tests or docs. Real credentials live
  only in the local `.env`.
- Before every commit, check `git status` for accidentally staged secrets.

## How to run and test

**Always invoke the project's own interpreter by its explicit path.** Never
call a bare `python`, `python3`, `pip` or `pytest`: shell state does not
persist between tool calls, so an activated virtualenv is not something you
can rely on, and the machine's default interpreter is not the one this
project runs on.

```bash
.venv/bin/python -m chronogram_tg      # run the app
.venv/bin/python -m pytest             # run the tests
.venv/bin/python -m ruff check .       # lint (must pass before committing)
.venv/bin/python -m ruff format .      # apply the house formatting
.venv/bin/pip install -r requirements-dev.txt   # runtime deps + pytest + ruff
```

`requirements.txt` holds only what the app needs to run — end users install
that one. Development tools are in `requirements-dev.txt`, which includes
it. CI (`.github/workflows/ci.yml`) runs the tests on Linux (Python 3.11 and
3.14), Windows (3.14) and macOS (3.14), runs `ruff check`, and fails if any
credential, session or downloaded file is ever tracked by git. Formatting is
not enforced by CI, so run `ruff format` yourself to keep diffs clean. Keep
the job count low — the repository is public, where GitHub-hosted runners
are free, but a private fork would be billed, and macOS minutes cost about
ten times Linux ones.

On Windows the equivalents live in `.venv\Scripts\` instead of `.venv/bin/`.

If `.venv` is missing, recreate it with a **Tk-capable** interpreter — the
GUI needs it and the machine's default `python3` (pyenv 3.14.6) has no
`_tkinter`:

```bash
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import tkinter"    # must print nothing
```

The README documents the generic, machine-independent version of this for
end users; keep both in sync when the run commands change.

Manual testing against Telegram requires the user's credentials and
interactive login — you cannot do it yourself. When a task needs live
verification, prepare it and ask the user to run the exact command; always
test against a **small throwaway chat** first, never the real family chat.

## Conventions

- **Language:** everything — code, comments, docs, UI strings — in English
  (decision D13). No i18n layer.
- **Dates:** all timestamps (filenames, EXIF, `creation_time`, mtime) in
  **UTC**, no timezone conversion (D15). Telegram already provides UTC.
- **Filenames:** deterministic, derived from the message date via the
  pattern engine; Telegram preset (`IMG_`/`VID_YYYYMMDD_HHMMSS_mmm.ext`,
  matching what Telegram for Android writes - decision D18) by default; the
  Pixel preset (`PXL_...`) remains selectable.
  Determinism is what makes resume-by-filename work — never add random
  components.
- **EXIF:** write `DateTimeOriginal` with piexif on compressed photos; on
  image documents, respect existing EXIF and only fill in when absent (D3).
- **Videos:** ffmpeg with `-c copy` only (never re-encode). ffmpeg is
  optional and detected on the system PATH at startup.
- **Anti-flood pacing:** use Telethon takeout sessions, keep short pauses
  between items, catch `FloodWaitError` and wait it out. Never remove or
  shorten this behaviour to "speed things up".
- **Threading:** downloads run in a worker thread; the UI thread never
  blocks. Pause/cancel flags are checked between items.
- **Commits:** one atomic commit per completed and verified PLAN.md task
  (`Task N: <summary>`). Never batch several tasks into one commit.
- **Dependencies:** pinned in `requirements.txt`. Do not add a dependency
  without a strong reason; if you must, pin it and record why in the commit.
- Keep the code plain and readable — the future maintainer may be a
  non-expert. No cleverness, no premature abstraction.
