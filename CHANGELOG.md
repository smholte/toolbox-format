# Changelog

## 0.1 – draft (18 Nov 2026)

First version, for review. Not tagged.

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
