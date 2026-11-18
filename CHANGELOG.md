# Changelog

## 0.1.1 – fixes from the first independent review (branch `task/0001-independent-review`, not tagged yet)

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
  (as JavaScript did). **`clean()`** deletes only job folders. **Junctions** are told on Python 3.11 too (Blender).

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
