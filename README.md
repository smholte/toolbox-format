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
| Reference code (names, file types, the checker) | [`tbf/`](tbf/) |
| What changed | [`CHANGELOG.md`](CHANGELOG.md) |

Everything here is **public and made up**.

## Use

```bash
python3 -m pip install -r requirements.txt
python3 check.py samples/Toolbox types.json
python3 check.py --type samples/files/*
python3 -m pytest -q tests
```

`check.py` prints `OK` or a list of errors (a reader must refuse it) and warnings (readable, look at it); the exit
code is 1 when there is an error.

## Versions

**0.1 is a draft**: not reviewed yet, no tag. Until 1.0 anything may change, and a tool reads only the version it
was written for. How the format is changed: [`CLAUDE.md`](CLAUDE.md).
