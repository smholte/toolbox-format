#!/usr/bin/env python3
"""A stand-in for a native tool: it takes house scenes from its inbox, "bakes" for a few seconds and sends a
made-up bake back. For trying a real sender (a web page, another program) against a real folder without Blender.

    python3 tools/standin.py                       # watches ~/Toolbox as nl.fresing.trial.receiver
    python3 tools/standin.py --folder /tmp/Toolbox --seconds 3 --once

The trial page (trial/index.html, "House Planner side") sends to this id, so the page and this script together
are a browser-to-program round trip. Stop it with Ctrl+C. Everything it writes is made up.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tbf import folder as F  # noqa: E402
from tools.make_samples import js, zipped  # noqa: E402


def manifest(tool_id: str) -> dict:
    return {"format": "toolbox-tool", "version": F.VERSION, "id": tool_id, "name": "Trial: stand-in for Fresing Render",
            "app_version": "0.1", "kind": "native", "description": "Test program of the toolbox format. Safe to delete.",
            "actions": [{"id": "bake-house", "label": "Bake house scene", "accepts": ["hpscene"], "returns": ["hpbake"]}],
            "handover": ["inbox"]}


LOOK = 2              # seconds between two looks at the inbox


def write_final(root: Path, me: str, job: str, state: str, say, **more):
    """A final status Windows refuses now (another program reads status.json) is written again at the next looks
    (section 2). write_status itself already tried for 2 seconds."""
    for _ in range(30):
        try:
            F.write_status(root, me, job, state, **more)
            return
        except PermissionError as e:
            say(f"status {state} of {job} cannot be written right now ({e.strerror or e}); trying again")
            time.sleep(LOOK)
    say(f"status {state} of {job} could not be written; it will be taken up as left behind")


def bake(root: Path, me: dict, folder: Path, seconds: float, say) -> str:
    """do one job; returns its final state"""
    try:
        job, files = F.take(root, me, folder)
    except FileNotFoundError:
        return "not-complete"
    except F.JobProblem as p:
        if F.refuse(root, me["id"], folder.name, p):
            say(f"refused {folder.name}: {p.state} {p.code} {p.text}")
        return p.state
    if not F.claim(root, me["id"], job["job"], "working", fraction=0.0, text="Starting to bake"):
        return "taken"                              # another copy of this stand-in was first
    name, kind, path = files[0]
    say(f"took {job['job']} from {job['from']}: {name}, {path.stat().st_size} bytes, checked as {kind}")
    steps = max(1, round(seconds))
    for s in range(steps + 1):
        if F.wants_cancel(root, me["id"], job["job"]):
            write_final(root, me["id"], job["job"], "cancelled", say, text="Stopped because the sender asked")
            say(f"cancelled {job['job']}")
            return "cancelled"
        # a refused "working" is not written now (False) and written at the next moment: the bake goes on
        F.write_status(root, me["id"], job["job"], "working", fraction=s / steps,
                       text=f"Baking moment {min(8, 1 + 8 * s // steps)} of 8")
        if s < steps:
            time.sleep(seconds / steps)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / (Path(name).stem + ".hpbake")
        out.write_bytes(zipped({"bake.json": js({"format": "house-bake", "version": "1.0",
                                                 "note": f"made-up by the stand-in, answer to job {job['job']}"})}))
        try:
            reply = F.send_reply(root, me, job, [out], text="Baked 8 moments")
        except PermissionError as e:              # the reply went out; only the status "done" waits
            reply = e.reply
            say(f"status done of {job['job']} cannot be written right now ({e.strerror or e}); trying again")
            write_final(root, me["id"], job["job"], "done", say, text=e.text, reply=reply)
    say(f"done {job['job']}; bake sent back as {reply}")
    return "done"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--folder", type=Path, help="the Toolbox folder (default: TOOLBOX_HOME or ~/Toolbox)")
    ap.add_argument("--as", dest="me", default="nl.fresing.trial.receiver", help="the tool id to play")
    ap.add_argument("--seconds", type=float, default=8, help="how long a bake takes")
    ap.add_argument("--once", action="store_true", help="stop after the first job")
    a = ap.parse_args(argv)
    root = a.folder or F.toolbox_home()
    me = manifest(a.me)
    F.ensure_folder(root)
    F.write_manifest(root, me)

    def say(text):
        print(time.strftime("%H:%M:%S"), text, flush=True)

    say(f"watching {root / 'tools' / a.me / 'inbox'}  (Ctrl+C stops)")
    last_alive = last_left = 0.0
    try:
        while True:
            if time.time() - last_left > 60:          # at the start and once a minute: jobs nobody holds (6.3)
                for folder, status in F.unfinished(root, a.me):
                    if F.take_up(root, a.me, folder.name, "failed", code="error",
                                 text="The stand-in was closed while it worked on this"):
                        say(f"ended {folder.name}, left {status['state']} by an earlier run")
                last_left = time.time()
            if time.time() - last_alive > 8:
                try:
                    F.write_alive(root, a.me, "0.1")
                    last_alive = time.time()
                except PermissionError:               # another program reads alive.json: at the next look (2)
                    pass
            for folder in F.pending(root, a.me):
                if bake(root, me, folder, a.seconds, say) != "not-complete" and a.once:
                    return 0
            F.clean(root, a.me)
            time.sleep(LOOK)
    except KeyboardInterrupt:
        return 0
    finally:
        F.remove_alive(root, a.me)


if __name__ == "__main__":
    sys.exit(main())
