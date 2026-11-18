# Changelog

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
