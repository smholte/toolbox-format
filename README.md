# Toolbox format

How tools on one PC find each other and hand files to each other – with no app in between.

- A tool describes itself in a small file, its **manifest** (`toolbox.json`): its name, what it can do, and which
  file types each action accepts.
- All manifests live in one folder, **`Toolbox` in the user's home folder**. Each tool has an **inbox** there.
- A file goes to another tool as a **job**: a folder in that tool's inbox with the file and a `job.json`. The result
  comes back the same way, as a job in the sender's inbox.
- A file's **type** is decided by its content, not its name, from one shared list (`types.json`).

First use: **House Planner** sends a house scene to **Fresing Render** and gets the baked light back with one button
and no Save or Open dialog. The files themselves (`.hpscene`, `.hpbake`) are described by
[`house-scene-format`](https://github.com/smholte/house-scene-format); this format only carries them.

This is step D of a larger plan: first the format (this repository), then a small background app that adds a
drop popup and routes, then a toolbox window. All three read the same folder.

| What | Where |
| --- | --- |
| The format, in plain words with examples | [`FORMAT.md`](FORMAT.md) |
| The built-in list of file types | [`types.json`](types.json) |
| JSON schemas of every file | [`schemas/`](schemas/) |
| A made-up Toolbox folder and small sample files | [`samples/`](samples/) – made by `tools/make_samples.py` |
| The checker | `python3 check.py <Toolbox folder / toolbox.json / job folder>` |
| Code a web tool can copy: connect the folder, send, read the inbox | [`web/toolbox-folder.js`](web/toolbox-folder.js) |
| Code a native tool can copy: the same in Python | [`tbf/folder.py`](tbf/folder.py) (with `names.py`, `detect.py`) |
| A trial page to try it on a real PC | [`trial/`](trial/) – see below |
| A stand-in program for the receiving side | `python3 tools/standin.py` |
| What changed | [`CHANGELOG.md`](CHANGELOG.md) |

Everything here is **public and made up**.

## Try it on your PC (no install)

The trial page checks, in your own Chrome or Edge, that a page can hand a file over through the Toolbox folder and
get a result back – and whether the browser still knows the folder the next day.

1. Open **https://smholte.github.io/toolbox-format/trial/** in Chrome or Edge.
2. Follow the four numbered boxes on the page. For box 2 the page opens a second tab that plays Fresing Render.
   The first time you make an empty folder `Toolbox` in your user folder and tell the page to set it up (later
   Fresing Render makes that folder).
3. Press **Copy the report** and keep the text.

The page works on made-up files only, and only inside the folder you pick. **Remove the trial tools from the
folder** on the page takes its two test tools out again.

## Use

```bash
python3 -m pip install -r requirements.txt
python3 check.py samples/Toolbox types.json
python3 check.py --type samples/files/*
python3 -m pytest -q tests          # the tests of the JavaScript need Chrome on the machine
```

`check.py` prints `OK` or a list of errors (a reader must refuse it) and warnings (readable, look at it); the exit
code is 1 when there is an error. Python 3.11 or newer.

## Versions

**0.1** was reviewed by the leads of House Planner and Fresing Render on 18 Nov 2026 and is tagged `v0.1`. Tools pin
a tag and test against its samples. Until 1.0 anything may change between versions, and a tool reads only the version
it was written for. How the format is changed: [`CLAUDE.md`](CLAUDE.md).

## Licence

MIT, © 2026 Fresing – see [`LICENSE`](LICENSE). Code from here may be copied into other tools, also into ones under
the GPL; keep the copyright line with it.
