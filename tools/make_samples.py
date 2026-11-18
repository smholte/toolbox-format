#!/usr/bin/env python3
"""Make the sample files of this repository – all made up, the same bytes every time.

    python3 tools/make_samples.py            # write samples/
    python3 tools/make_samples.py --check    # exit 1 when samples/ is not what this script makes

samples/Toolbox   a Toolbox folder in the middle of one round trip (FORMAT.md section 8): House Planner sent a
                  house scene to Fresing Render (done, the bake came back as a reply job that House Planner has
                  not picked up yet) and a second scene that is being baked and was just asked to stop.
samples/files     one small file per file type the tests look at. They are only good enough to be recognised:
                  the .hpscene and .hpbake are NOT valid house-scene-format packages.
"""
from __future__ import annotations

import io
import json
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
V = "0.1"
RENDER, PLANNER = "nl.fresing.render", "nl.fresing.house-planner"
JOB1, JOB2, REPLY1 = "20261118-195100-9f3c2a", "20261118-203000-c81e55", "20261118-201500-4b7d10"


def js(doc) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3          # the same bytes on Windows and Linux
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def step(schema: str, name: str) -> bytes:
    return ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('made-up sample'),'2;1');\n"
            f"FILE_NAME('{name}','2026-11-18T00:00:00',(''),(''),'','','');\n"
            f"FILE_SCHEMA(('{schema}'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n").encode("ascii")


def glb() -> bytes:
    body = b'{"asset":{"version":"2.0"}}'
    body += b" " * (-len(body) % 4)
    return b"glTF" + struct.pack("<II", 2, 12 + 8 + len(body)) + struct.pack("<I", len(body)) + b"JSON" + body


def make() -> dict[str, bytes]:
    scene = zipped({"scene.json": js({"format": "house-scene", "version": "1.0", "note": "made-up, not a real package"})})
    scene2 = zipped({"scene.json": js({"format": "house-scene", "version": "1.0", "note": "made-up, second version"})})
    bake = zipped({"bake.json": js({"format": "house-bake", "version": "1.0", "note": "made-up, not a real package"})})
    f: dict[str, bytes] = {
        "files/sample-part.step": step("AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }", "sample-part.step"),
        "files/sample-building.ifc": step("IFC4", "sample-building.ifc"),
        "files/sample-house.hpscene": scene,
        "files/sample-house.hpbake": bake,
        "files/sample-model.glb": glb(),
        "files/sample-notes.csv": b"part,count\nbolt M12x40,8\n",
        "files/sample-archive.zip": zipped({"readme.txt": b"made-up\n"}),
        "files/sample.unknownkind": b"nothing knows this file\n",
    }
    t = "Toolbox/"
    f[t + "toolbox-folder.json"] = js({"format": "toolbox-folder", "version": V})
    f[t + f"tools/{RENDER}/toolbox.json"] = js({
        "format": "toolbox-tool", "version": V, "id": RENDER, "name": "Fresing Render", "app_version": "0.0.0-sample",
        "description": "Photo-realistic renders and animations of STEP assemblies; bakes light for House Planner.",
        "homepage": "https://smholte.github.io/CAD-render-animation/", "kind": "native",
        "start": {"program": "C:/Users/sample/AppData/Local/FresingRender/blender/blender.exe",
                  "args": ["--app-template", "fresing_render"]},
        "actions": [
            {"id": "import-step", "label": "Import STEP", "accepts": ["step"]},
            {"id": "bake-house", "label": "Bake house scene", "accepts": ["hpscene"], "returns": ["hpbake"]}],
        "handover": ["inbox"]})
    f[t + f"tools/{RENDER}/alive.json"] = js({"format": "toolbox-alive", "version": V,
                                               "seen": "2026-11-18T20:31:04+01:00", "app_version": "0.0.0-sample"})
    f[t + f"tools/{PLANNER}/toolbox.json"] = js({
        "format": "toolbox-tool", "version": V, "id": PLANNER, "name": "House Planner", "app_version": "0.0.0-sample",
        "description": "Plan a house in 2D and 3D.", "homepage": "https://smholte.github.io/house-planner/",
        "kind": "web", "url": "https://smholte.github.io/house-planner/",
        "actions": [
            {"id": "import-bake", "label": "Import baked light", "accepts": ["hpbake"]},
            {"id": "import-model", "label": "Add a model", "accepts": ["glb", "gltf", "ifc"]}],
        "sends": ["hpscene"], "handover": ["inbox"]})
    # job 1: done; its bake went back as a reply job
    j1 = t + f"tools/{RENDER}/inbox/{JOB1}/"
    f[j1 + "sample-house.hpscene"] = scene
    f[j1 + "job.json"] = js({
        "format": "toolbox-job", "version": V, "job": JOB1, "created": "2026-11-18T19:51:00+01:00",
        "from": PLANNER, "to": RENDER, "action": "bake-house", "return": "import-bake",
        "title": "Sample house – version 3",
        "files": [{"name": "sample-house.hpscene", "type": "hpscene", "size": len(scene)}]})
    f[j1 + "status.json"] = js({"format": "toolbox-status", "version": V, "job": JOB1, "state": "done",
                                "updated": "2026-11-18T20:15:00+01:00", "text": "Baked 8 moments", "reply": REPLY1})
    r1 = t + f"tools/{PLANNER}/inbox/{REPLY1}/"
    f[r1 + "sample-house.hpbake"] = bake
    f[r1 + "job.json"] = js({
        "format": "toolbox-job", "version": V, "job": REPLY1, "created": "2026-11-18T20:15:00+01:00",
        "from": RENDER, "to": PLANNER, "action": "import-bake", "reply_to": {"tool": RENDER, "job": JOB1},
        "title": "Sample house – version 3",
        "files": [{"name": "sample-house.hpbake", "type": "hpbake", "size": len(bake)}]})
    # job 2: being baked, and the sender just asked to stop
    j2 = t + f"tools/{RENDER}/inbox/{JOB2}/"
    f[j2 + "sample-house.hpscene"] = scene2
    f[j2 + "job.json"] = js({
        "format": "toolbox-job", "version": V, "job": JOB2, "created": "2026-11-18T20:30:00+01:00",
        "from": PLANNER, "to": RENDER, "action": "bake-house", "return": "import-bake",
        "title": "Sample house – version 4", "options": {},
        "files": [{"name": "sample-house.hpscene", "type": "hpscene", "size": len(scene2)}]})
    f[j2 + "status.json"] = js({"format": "toolbox-status", "version": V, "job": JOB2, "state": "working",
                                "updated": "2026-11-18T20:31:02+01:00", "fraction": 0.4,
                                "text": "Baking summer noon (3 of 8)"})
    f[j2 + "cancel.json"] = js({"format": "toolbox-cancel", "version": V, "job": JOB2,
                                "asked": "2026-11-18T20:31:03+01:00"})
    return f


def current() -> dict[str, bytes]:
    return {p.relative_to(OUT).as_posix(): p.read_bytes() for p in sorted(OUT.rglob("*")) if p.is_file()}


def main() -> int:
    want = make()
    if "--check" in sys.argv[1:]:
        have = current() if OUT.is_dir() else {}
        diff = sorted(k for k in set(want) | set(have) if want.get(k) != have.get(k))
        for k in diff:
            print(f"samples/{k}: " + ("missing" if k not in have else "not made by this script" if k not in want else "differs"))
        print("samples/ is up to date" if not diff else "run: python3 tools/make_samples.py")
        return 1 if diff else 0
    if OUT.is_dir():
        for p in sorted(OUT.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    for name, data in want.items():
        p = OUT / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    print(f"wrote {len(want)} files to samples/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
