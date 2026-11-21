# Changelog

## 0.2 – the rule problems of the first review (branch `task/0011-format-0.2`, not tagged yet, for the leads' review)

### What changed for tool authors

1. **Everything says `"version": "0.2"`**, and until 1.0 a 0.2 tool reads no 0.1 file. All tools of one Toolbox
   folder move to 0.2 together: copy the new `tbf/` (Python) or `web/toolbox-folder.js` (web), and the tool writes
   its manifest at its next start. A native tool marks the folder as 0.2 by itself.
2. **Shorter names**: a file name at most 80 characters and 255 bytes, a tool id at most 60, a job id at most 32.
   Check your own ids and the names your tool gives its files (`nl.fresing.render`, `nl.fresing.house-planner` and
   the reference job ids fit).
3. **More names refused**: `COM0`, `COM¹`, `CONIN$`, `CLOCK$`, `con .txt` and others (3.3); a name must be NFC (the
   reference `send()` turns it into NFC); `ſ.txt` and `s.txt` count as one name.
4. **Own types may not use `head_matches`.** Neither House Planner nor Fresing Render has an own type today.
5. **Several copies**: a job is taken up only after its status is 5 minutes old, so **a copy that holds a job
   writes its status at least every 2 minutes** – also while it waits for its user ("Bake now"). Use
   `take_up()` / `takeUp()` for jobs from `unfinished()`, at start and about once a minute.
6. **Refusing a job**: call `refuse()` with what `take()` threw – a job its sender cancelled before it was taken now
   ends `cancelled`, not `failed`. A missing or short file is `bad-job` at once (before: waited for ever).
7. **When the user says no** (declines a bake): end the job `cancelled`, not `failed`.
8. **`write_status()` / `writeStatus()` never write over a final status** and return false then; a `failed` status
   always gets a code (`error` when none is given).
9. **House Planner, please check:** a `scene.json` inside a `.hpscene` now counts as a house scene only when it is
   at most 64 levels deep (3.4 holds for the JSON a rule reads). A real scene is far less deep, but say so if
   `house-scene-format` allows deeper.
10. **Fresing Render, please check:** a native tool that may run as several copies does not delete `alive.json` when
   it closes (6.4); and the jobs Fresing Render finishes may lose their files right away without the checker
   complaining (P30).
11. **A refused status write never stops a job (W3).** On Windows a program that reads `status.json` blocks the
   write for as long as it holds the file (up to half a second, measured by Fresing Render). `write_status()` /
   `writeStatus()` now return false for a refused `waiting` or `working` (write it at the next update, as you do
   anyway) and try a final status for 2 seconds before they throw – then write it again at your next look.
   `send_reply()` / `sendReply()` put the reply's id on that error (`.reply`, `.text`): write `done` with it, never
   send the result twice. The stand-in and the trial page show how. Before: the first refusal after 0.25 s threw,
   and the stand-in stopped in the middle of a bake.

### Each change and what an app has to do

The numbers are those of task 0011 (P1–P29 from the review in task 0001, P30–P32 from the neighbours). Where the
review offered a choice, the simpler rule was taken; that is said below.

- **P1 – jobs left behind (6.3, 7.1).** Before: at its start a tool took up every `waiting`/`working` job – also one
  another running copy held, and the final status it wrote could change again. Now only a status more than 5 minutes
  old is taken up, a holder writes its status every 2 minutes, `take_up()` lets only one of several copies take a job
  up (a lock file `.taking-up` made with an exclusive create, the status read once more, then written over; tested
  with 8 copies at once, 1500 times, and with the worst order of steps forced), and a final status is never written
  over. A status `text` is made one line by the reference code, so an error message cannot make it unreadable. *App:* write the status of a held job every 2 minutes; use
  `unfinished()` + `take_up()`/`takeUp()` at start and once a minute; check the return value of `write_status`.
- **P2 – own types without patterns (5.1).** Simpler of the review's two choices (the other: limits on counts).
  *App:* none today.
- **P3, P6 – lengths (3.1–3.3).** File name ≤ 80 characters and ≤ 255 bytes in UTF-8; tool id ≤ 60; job id ≤ 32;
  icon name as a file name. The path stays under 260 characters. *App:* check own ids and file names.
- **P4 – device names (3.3).** A rule of the format: the part before the first dot, without spaces at its end, in
  capitals, is none of `CON PRN AUX NUL COM0–9 COM¹–³ LPT0–9 LPT¹–³ CONIN$ CONOUT$ CLOCK$`. All 14 names of task 0010
  have a test in both languages. *App:* copy the code.
- **P5 – the same name (3.3).** Names must be NFC; two names are the same when they are equal "in capitals":
  characters below U+0590 whose capital is below U+0590 too are replaced by it. Not plain `upper()`: Python 3.11–3.13
  and Chrome differ for about 55 characters (capitals new in Unicode 16), this rule for none (tested for every
  character). NFC: Python and Chrome agree on every character Python knows; they differ only for 20 characters of
  four scripts new in Unicode 16 (Todhri, Tulu-Tigalari, Gurung Khema, Kirat Rai). *App:* copy the code; a sender
  writes NFC names.
- **P7 – JSON depth (3.4).** At most 64 levels. *App:* none, unless a tool's `options` nest deeper.
- **P8 – size (6.1, schema).** At most 2^53 − 1. *App:* none.
- **P9 – patterns (5.2).** No `[`, `--`, `&&`, `||`, `~~` inside a set. *App:* none.
- **P10–P12, P16 – text only.** `format` and `version` may stand anywhere among the keys (simpler than requiring the
  order); control characters are U+0000–U+001F and U+007F (others allowed, as the code did); one to three digits
  after the seconds; `starts_with` skips exactly 0x20, 0x09, 0x0D, 0x0A.
- **P13 – limits in the text (4, 6.1).** The schemas' limits are now listed. *App:* none.
- **P14, P15 – rules (5.2).** How deep `all`/`any`/`not` go, with an example; reading a zip written as seven steps,
  as the code does them; a zip rule names an ASCII file (simpler than describing CP437). *App:* none.
- **P17 – extensions no job can carry (5.3).** Text only: such a file cannot be sent until renamed (simpler than a
  new mapping).
- **P18 – sending (6.2).** A sender may make the receiver's `inbox/`; it need not look at `handover`. *App:* none.
- **P19 – codes (6.3).** A table says which fault gets which code; the code did this already.
- **P20 – a missing or short file (6.2, 6.3).** Now `bad-job` at once: `job.json` is written last, so such a file
  never comes. The sentence "MAY get up to a minute" is gone (simpler than a helper that waits). *App:* a reader
  that waited must now refuse (the reference `take()` does).
- **P21 – cancelled before taken (6.3, 7.3).** `take()` throws a problem with code `cancelled`; `refuse()` writes the
  status `cancelled`. *App:* use `refuse()` (or write `cancelled` for that code).
- **P22 – `alive.json` (6.4).** Only a tool that runs as one copy deletes it (simpler than a copy id). *App:* a tool
  that may run twice stops deleting it.
- **P23 – status fields (7.1).** `failed` has a `code` (the reference code adds `error`); `fraction` belongs to
  `working`. The checker warns otherwise.
- **P24 – a reply that cannot be sent (7.2).** Text says what the code did: `done`, a text, no `reply`.
- **P25 – cleaning up (7.4).** By `created` of `job.json` (and the final status's `updated`), else by the newest file;
  a folder without files is left. Not by the folder's date (a page cannot read it). `clean()` is now in the
  JavaScript too. *App:* use `clean()`.
- **P26 – when a manifest is written (2, 9).** Each time a tool connects to the folder. *App:* none (the trial page
  and the reference code did so).
- **P27 – unknown entries (11).** Folders in `tools/` or an inbox that are not ids, and a tool folder without
  `toolbox.json`, are WARNINGs (a reader ignores them).
- **P28 – `reply_to` (6.1, 6.3).** `take()` refuses a reply whose `reply_to.tool` is not `from` or that has a
  `return`, as the checker did. *App:* copy the code.
- **P29 – checker.** Warns about an icon that is no PNG or SVG and a `failed` without `code`. Key order is not
  checked (P10). The behaviour rules that cannot be seen in files stay unchecked; the reference code follows them.
- **P30 – a finished job without files (7.4).** The checker no longer calls the files of a job with a final status
  missing.
- **P31 – declined (6.3, 7.1).** A job the user declines ends `cancelled`; `failed` is for "could not".
- **P32 – Web Locks (6.3, 9).** They cover one origin; copies on other origins rely on "only what I can place" and
  write the status at once when they take a job.
- **W3 – a refused status write (2; lead review, 21 Nov 2026).** Fresing Render measured on Windows that a reader
  holding `status.json` blocks its replace for up to 0.5 s. Not final: `write_status()` / `writeStatus()` return
  false and the next update writes it. Final: tried for 2 s (about 4× the longest refusal), then the error; the
  caller writes it at its next look. `send_reply()` / `sendReply()` carry the sent reply's id on that error. In a
  browser the same refusal comes from another writer holding the file (tested in Chrome) and, on Windows, from a
  program that reads it. Also: the tests now run on Windows (GitHub's `windows-latest`) at every push.
- **Found by an independent review of this branch, and fixed:** a status `text` with a line break (an error message)
  made `status.json` unreadable, after which a final status could be written over; a key that is not UTF-8 in a job
  crashed Python's `refuse()` and left an empty `status.json`, and `check.py` crashed printing it; the first design
  of `take_up()` (moving `status.json` aside) could, in a very narrow timing, let two copies hold one job and on
  Windows leave a file behind; JavaScript's `claim()` failed on a folder named `status.json`; a `cancel.json` without
  a `job.json` was answered. Each has a test in both languages where both judge it.
- **Also fixed:** a test of the trial page (`tests/test_web.py`) failed once on GitHub by timing – it read the
  folder while the page was still removing a job, and while the stand-in tab wrote `alive.json`. It now waits for
  the page to finish, stops the stand-in first, and skips a browser's short-lived `.crswap` files.

## 0.1.1 – fixes from the first independent review (tag `v0.1.1`, 20 Nov 2026)

No rule of the format changed: `FORMAT.md`, the schemas and `types.json` are as in `v0.1`. One verdict of the checker
changed: text with an unpaired `\ud800`–`\udfff` escape is now refused (3.4 says UTF-8; before, it passed and then
broke the reply). Everything else the `v0.1` checker accepted it still accepts. Fixed in the checker and in the
reference code (a test for each that failed before; the review's report is task 0001 in `smholte/ToolBox`):

- **Crashes of the checker and of a Python tool**: JSON nested a few thousand deep (`RecursionError` in Python
  3.12+), a number with more than 4300 digits (`ValueError`), a count in a pattern Python cannot hold (`a{4294967295}`,
  `OverflowError`), a file name the system cannot hold (`OSError`, also aborted the whole check), the same in a
  house scene's `scene.json` (any tool that looked at the file crashed), and two copies writing `alive.json` at once.
- **Text that is not UTF-8** (`"\ud800"` escaped in JSON) is refused, as 3.4 says. Before, Python took it and then
  crashed writing the reply's title, and JavaScript read a file name with it as another file.
- **JavaScript and Python now agree** on: a range like `[\s-z]` in a pattern (refused), own types written with
  their keys in another order (the same type), a byte-order mark in a name inside a zip (kept), a zip64 field cut
  short at the end of the list (not a zip), a key written twice in a house scene's JSON or in a job (the last counts
  when reading; the checker still refuses it), a date that does not exist in a job or status (refused), a
  job field named `constructor` or `toString` (refused), a folder in place of a job's file (`bad-job`), a size no
  file can have (`bad-job`), a `job.json` another program holds open (try again – before: `failed` for good).
- **Python `send()`** refuses two files whose names differ only in capitals, and shortens a title to 120 characters
  (as JavaScript did). **`clean()`** deletes only job folders. **Junctions** are told on Python 3.11 too (which has no `os.path.isjunction`;
  Blender 5.2 itself runs Python 3.13).

What an app has to change: copy the new `tbf/` files or `web/toolbox-folder.js`. Nothing in the files it writes.

## 0.1 – tag `v0.1` (18 Nov 2026)

The first version, as changed by its review (FORMAT.md section 13). Compared with the draft the leads read:

- **Only a native tool makes the Toolbox folder.** A web tool refuses a folder without `toolbox-folder.json` (2, 9).
- **Only one copy takes a job:** an exclusive create of `status.json` for programs; one window at a time and "only
  what I can place" for pages (6.3). **Jobs left by an earlier run** are taken up at the next start (6.3).
- **A `working` job is believed for 5 minutes** even when `alive.json` is old (6.4, 7.1). `alive.json` is optional
  for a web tool.
- **Try again, never an error:** a rename or delete Windows refuses, a file found half written (2, 7.4).
- "No key twice" and "no byte-order mark" are rules for the writer; readers need not notice them (3.4).
- Links are refused and never followed when cleaning up, where the tool can tell (7.4, 10).
- `url` of a web tool is optional; `start.program` is what the user's shortcut starts (4).
- A page asks for the folder's permission only when its user acts (9).
- Reference code follows: `claim`, `unfinished`, `is_stalled` / `stalled`, `exclusively`. Licence: MIT.

What the draft held:

- The Toolbox folder: `Toolbox` in the user's home folder, one folder per tool, an inbox per tool.
- `toolbox.json`: a tool's manifest (id, name, kind, actions with the file types they accept and return).
- `types.json`: 15 built-in file types, with rules that recognise a file by its content (STEP against IFC, a house
  scene against any other zip).
- Jobs: `job.json` written last, `status.json` by the receiving tool, the result as a reply job in the sender's
  inbox, `cancel.json`, `alive.json`, cleaning up.
- What a web page needs to take part (Chrome and Edge on a PC; the folder is picked once).
- Checker (`check.py`), schemas, a made-up sample folder, tests on the samples and on broken copies.

Added the same day, still 0.1:

- `web/toolbox-folder.js` (a web tool's side) and `tbf/folder.py` (a native tool's side): reference code to copy.
- `trial/`: a page to try the folder on a real PC; `tools/standin.py`: the receiving side as a program.
- Tests in a real Chrome: JavaScript and Python name the same file types, refuse the same bad jobs, and read each
  other's jobs.
- Made stricter so both languages agree: reading a zip is written out step by step (5.2); patterns may not use a
  bare `.`, `{,n}` or a count after a count; a time's offset is at most `23:59`.
