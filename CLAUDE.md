# CLAUDE.md – toolbox format

How tools on one PC find each other and hand files to each other. Read `README.md`, then `FORMAT.md`.
First users: **House Planner** (`smholte/house-planner` public, `smholte/house-planner-dev` private) and
**Fresing Render** (`smholte/CAD-render-animation`). The files they exchange are described by
`smholte/house-scene-format`; this repository only describes how files travel.

## Rules

- **Draft until the owner says otherwise.** 0.1 was written on a branch for a first review; nothing is tagged.
  Once a version is tagged: changes only by a task, reviewed by the leads of the apps that use the format before
  they are merged and tagged, as in `house-scene-format`. Never move a tag.
- **Until 1.0** any minor version may change anything, and readers take only their own version (FORMAT.md 3.5).
  Say in `CHANGELOG.md` what an app has to change.
- **Every change** updates, in the same commit: `FORMAT.md`, the schemas, `types.json` when a type changes,
  `tools/make_samples.py` and the samples it writes (`python3 tools/make_samples.py`), `check.py` / `tbf/` and their
  tests (a new rule gets a broken-copy test), and `CHANGELOG.md`. `tbf/names.py` `VERSION` follows the format's.
- **Public and made up only.** No real house, machine, customer, path of a real PC or person. Samples come only from
  `tools/make_samples.py`. Workers here never attach `house-planner-dev`.
- Plain Python 3.11+ and PyPI (`requirements.txt`); no Blender, no Node in this repository's tests. The JavaScript
  (`web/toolbox-folder.js`, `trial/`) is one plain file without a build step and is tested in a real Chrome through
  Playwright for Python (`tests/test_web.py`), with the browser's private file system standing in for a picked folder.
- **Two copies must stay equal:** the type list (`types.json` and the `TYPES` block in `web/toolbox-folder.js`) and
  every rule both languages judge (names, times, patterns, rules, reading a zip, checking a job). A change to one
  side changes the other in the same commit; `tests/test_web.py` compares them case by case.
- The format must be writable by a web page (File System Access API), a Blender extension and a small program
  alike. A rule one of them cannot follow is a wrong rule.
- Owner: Sebastian – not a programmer. Plain language, short, results first, no code unless he asks.

## Tests

```bash
python3 tools/make_samples.py --check          # samples/ up to date
python3 check.py samples/Toolbox types.json    # samples valid
python3 -m pytest -q tests                     # the checker, the folder code, and the JavaScript in Chrome
```

GitHub runs the same at every push (`.github/workflows/check.yml`).

## Things learned

- Chrome refuses to give a web page `AppData` (Local and Roaming), `Program Files`, the home folder itself and
  `~/Library`; folders inside the home folder are fine. So the Toolbox folder is `C:\Users\<name>\Toolbox`, not
  `%LOCALAPPDATA%\Toolbox` (checked in Chromium's blocklist, 18 Nov 2026).
- A browser's `latin1` text decoder is really Windows-1252. Rules read the head of a file with every byte of 0x80
  and up as `?`, so JavaScript and Python see the same text.
- Python's `$` also matches before a final line break and JavaScript's does not; `(?…)` groups and `\b`-style escapes
  differ too. Patterns in rules are held to a small common part (FORMAT.md 5.2) and the checker refuses the rest.
- Python's `zipfile` and a hand-written reader disagree on damaged zips (which end record counts, bytes after the
  end, entry counts). Both sides now follow the same few written steps (FORMAT.md 5.2) instead of a library; several
  hundred damaged copies get the same answer in both.
- More places where the two languages differ, all now ruled out or pinned: a bare `.` (JavaScript's skips `\r`),
  `\s` on control characters (Python needs `re.ASCII`), `{,3}` (a count in Python, plain text in JavaScript), `a*+`
  (possessive in Python 3.11+, an error in JavaScript), and a time offset `+01:60` (Python reads it).
- Chrome's permission for a folder belongs to the site (`https://smholte.github.io`), not to one page under it.
- STEP and IFC files both start with `ISO-10303-21;` – only the `FILE_SCHEMA` line tells them apart.
- JSON-schema messages for "if this then not that" are unreadable; such rules are checked in `tbf/check.py` with a
  plain sentence instead.
- From `house-scene-format`: all the author's tests can pass while an independent reviewer still finds crashes. Give
  the checker to someone who did not write it before the first tag.
