# Design decisions

This file records every closed design decision for Chronogram TG and the
reasoning behind it. **These decisions are settled.** Do not reopen or
silently contradict any of them — in code, docs, or plans — without explicit
approval from the project owner. If a decision turns out to be technically
impossible, stop and ask; do not improvise an alternative.

---

## D1 — Desktop app, not an Android app

The tool exists to rescue one family photo history from one Telegram chat: a
one-off task operated by the project owner on their computer. An Android app
would add development, signing and permission overhead with no benefit for a
single run. Desktop Python is the smallest thing that works.

## D2 — Message date is the source of truth for photo dates

Telegram strips EXIF metadata from compressed photos (`MessageMediaPhoto`),
so the original capture date no longer exists anywhere. The send date of the
message is the best remaining approximation — and it is exactly the
chronology the user wants to see in Google Photos.

## D3 — Never overwrite surviving EXIF on image documents

Images sent "as a file" (image documents, not compressed photos) may keep
their original EXIF. When `DateTimeOriginal` already exists it is more
faithful than the message date, so it must be left untouched. Only when it is
absent do we write the message date.

## D4 — Local download + manual move to DCIM, not Google Photos API upload

Uploading via the Google Photos API is technically viable
(`photoslibrary.appendonly` still allows uploads after the 2025 API changes)
but requires setting up an OAuth project — disproportionate for a one-off
rescue. Google Photos orders items by their metadata, so manually moving the
files to `/DCIM/Camera` (or uploading via the web) yields the same
chronological result. API upload remains a possible future evolution.

## D5 — Native-camera-style filenames, Pixel preset by default

*Amended 2026-08-24 by D18: the default preset is now the Telegram style
and the destination is the phone's Telegram gallery folders. The Pixel
preset remains selectable; the rest of this decision (configurable
template, cosmetic purpose) stands.*

Google Photos ignores filenames, so this is purely cosmetic — but coherent
naming inside `DCIM/Camera` is an explicit wish of the user (whose target
device is a Pixel 6a). The pattern is configurable (template with tokens,
several presets) for users of other brands.

## D6 — Non-intrusive banner when ffmpeg is missing, not a blocking modal

The limitation only matters when the user thinks about videos. A banner in
the main window ("ffmpeg not found — videos unavailable, see README")
informs exactly where the limitation is felt, without adding friction at
startup or login.

## D7 — "Include videos" checkbox lives in the main window, not in settings

Whether to include videos is a per-download decision, not a stable
preference. It sits next to the other per-download choices (chat, range,
destination). Default: checked when ffmpeg is available, disabled (greyed
out) when it is not.

## D8 — Logout lives inside the settings modal, behind a confirmation dialog

Logging out forces a new phone-code login. Keeping it out of the main window
and adding a confirmation ("Log out? You will need to enter the code again")
minimises accidental logouts.

## D9 — CustomTkinter over plain Tkinter

Same simplicity and standard-library friendliness, but a modern look and
automatic light/dark mode following the OS.

## D10 — Telethon takeout sessions plus a prudent pace

Takeout sessions are Telegram's blessed mechanism for bulk exports and carry
lower flood limits. We still keep short pauses between downloads and handle
`FloodWaitError` explicitly (wait the requested time, then resume).

## D11 — Resume by detecting already-downloaded files

With large histories and a deliberately slow pace, interruptions are
expected. On relaunch, files already present in the destination (matched by
their deterministic names) are skipped and the download continues where it
left off.

*Extended 2026-08-24, after the owner lost a 1.2 GB video to a cancel:
resume now also works within a file. Partial `.part` downloads of documents
(videos, images sent as files) survive interruptions and continue from
their last 4 KiB-aligned byte instead of starting over. A partial that is
not strictly smaller than the expected size is not trusted and restarts;
one that ends at the wrong size is deleted and retried fresh on the next
run.*

## D12 — Name: "Chronogram TG"

"Chronogram" evokes dates — the essence of the project. The "TG" suffix
gives the slug uniqueness (`chronogram` is taken on PyPI), makes the domain
explicit, and avoids using the full "Telegram" brand, which Telegram's
guidelines discourage for unofficial apps.

## D13 — English everywhere (repo and UI)

Confirmed with the user on 2026-08-23. README, docs, code comments **and the
application UI** are all in English, maximising the public repo's reach. No
i18n layer — hardcoded English strings are fine.

## D14 — Flat output folder, no subfolders

Confirmed with the user on 2026-08-23. All downloaded files go directly into
the chosen destination folder. This makes the bulk move to `/DCIM/Camera`
trivial; Google Photos orders by metadata regardless of folder structure.

## D15 — All dates and times in UTC

Confirmed with the user on 2026-08-23. Telegram delivers message dates in
UTC and both the filename timestamp **and** the EXIF `DateTimeOriginal` /
video `creation_time` are written in UTC, with no timezone conversion. This
matches the Pixel's native `PXL_` filename convention and keeps the code
free of timezone logic. Accepted trade-off: EXIF times will differ from
local wall-clock time (e.g. by 1–2 h for Spain); day-level chronology in
Google Photos is unaffected for this use case.

## D16 — Run with Python; packaging is an optional final task

Confirmed with the user on 2026-08-23. The supported way to run the app is
Python + `requirements.txt`, with a README any non-Python user can follow
verbatim. A PyInstaller-based `.app`/`.exe` build exists in the plan only as
an explicitly optional, low-priority final task.

## D17 — Flat layout: the package lives at the repository root

Confirmed with the user on 2026-08-23. The importable package is
`chronogram_tg/` at the repository root, not `src/chronogram_tg/`. The
underscore spelling is forced by Python (hyphens are invalid in import
names), and the flat layout keeps `pip install -r requirements.txt` +
`python -m chronogram_tg` working with no packaging configuration — which is
what the README promises a non-Python user. The PyPA-recommended `src`
layout protects against importing the source tree instead of the installed
distribution, a problem that only arises when publishing to PyPI; we do not
(D16).

## D18 — Rescued files join the phone's Telegram gallery folders

Decided by the user on 2026-08-24, amending D5's default. While setting up
the rescue he also enabled Telegram's "Save to Gallery" on his mother's
phone, so *new* photos now land in the phone's Telegram gallery folders —
`Pictures/Telegram` for images, `Movies/Telegram` for videos — and Google
Photos will back those device folders up. The rescued history should live
where the new photos live, looking like them, rather than posing as camera
shots in `/DCIM/Camera`.

Consequences:

* The README's transfer instructions point at `Pictures/Telegram` and
  `Movies/Telegram`, plus enabling Google Photos backup for those device
  folders. (`DCIM/Camera` still works — Google Photos sorts by embedded
  dates — so it is mentioned as an alternative, not removed.)
* The default filename preset is now **Telegram**:
  `{kind}_{date}_{time}_{ms}`, where `{kind}` is `IMG` or `VID`. This is
  the exact format Telegram for Android writes when saving to the gallery
  (`IMG_yyyyMMdd_HHmmss_SSS.jpg` / `VID_…mp4`), verified in the app's
  source: `AndroidUtilities.generateFileName` and `MediaController.saveFile`
  in the DrKLO/Telegram repository. The Pixel preset remains selectable.
* Two deliberate differences from Telegram's own names, both invisible in
  practice: Telegram stamps the *save* moment in *local* time with random
  milliseconds, while Chronogram TG stamps the *message* date in *UTC*
  (D15) with a deterministic millisecond counter (D11 requires
  determinism). Collisions with files Telegram itself saves later are no
  concern: those carry arrival timestamps, not historical ones.
