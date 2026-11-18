"""tbf/folder.py: a native sender and a native receiver hand a file over in a real folder, and everything they
write passes the checker."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tbf import folder as F  # noqa: E402
from tbf.check import check  # noqa: E402

SAMPLES = ROOT / "samples"
RENDER, PLANNER = "nl.fresing.render", "nl.fresing.house-planner"
SCENE, BAKE, STEP = (SAMPLES / "files" / n for n in ("sample-house.hpscene", "sample-house.hpbake", "sample-part.step"))


@pytest.fixture
def box(tmp_path):
    root = tmp_path / "Toolbox"
    F.ensure_folder(root)
    for tool in (RENDER, PLANNER):
        F.write_manifest(root, json.loads((SAMPLES / "Toolbox" / "tools" / tool / "toolbox.json").read_text("utf-8")))
    assert check(root).items == []
    return root


def clean(root):
    rep = check(root)
    assert rep.items == [], rep.text()


def test_where_the_folder_is(monkeypatch, tmp_path):
    monkeypatch.delenv("TOOLBOX_HOME", raising=False)
    assert F.toolbox_home() == Path.home() / "Toolbox"
    monkeypatch.setenv("TOOLBOX_HOME", str(tmp_path / "elsewhere"))
    assert F.toolbox_home() == tmp_path / "elsewhere"


def test_round_trip(box):
    me, planner = F.read_tool(box, RENDER), F.read_tool(box, PLANNER)
    assert not F.is_alive(box, RENDER)
    F.write_alive(box, RENDER, "0.0.0-test")
    assert F.is_alive(box, RENDER)
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE], ret="import-bake", title="Sample house")
    clean(box)
    assert F.read_status(box, RENDER, job) is None
    (folder,) = F.pending(box, RENDER)
    doc, files = F.take(box, me, folder)
    assert (doc["job"], files[0][:2]) == (job, ("sample-house.hpscene", "hpscene"))
    F.write_status(box, RENDER, job, "working", fraction=0.25, text="Baking")
    assert F.pending(box, RENDER) == [] and F.read_status(box, RENDER, job)["fraction"] == 0.25
    clean(box)
    reply = F.send_reply(box, me, doc, [BAKE], text="Baked")
    clean(box)
    assert F.read_status(box, RENDER, job) == {**F.read_status(box, RENDER, job), "state": "done", "reply": reply}
    (back,) = F.pending(box, PLANNER)
    rdoc, rfiles = F.take(box, planner, back)
    assert rdoc["reply_to"] == {"tool": RENDER, "job": job} and rdoc["title"] == "Sample house" and rfiles[0][1] == "hpbake"
    F.remove_job(box, PLANNER, reply)
    F.remove_job(box, RENDER, job)
    F.remove_alive(box, RENDER)
    clean(box)
    assert not list(box.glob("tools/*/inbox/*"))


def test_send_refuses_before_it_writes(box):
    for args, expect in (((PLANNER, RENDER, "bake-house", [STEP]), "does not accept step"),
                         ((PLANNER, RENDER, "polish", [SCENE]), "has no action polish"),
                         ((PLANNER, "com.example.nobody", "bake-house", [SCENE]), "no readable manifest")):
        with pytest.raises(ValueError, match=expect):
            F.send(box, *args)
    assert not list(box.glob("tools/*/inbox/*"))


def test_no_return_and_a_sender_that_is_not_there(box):
    me = F.read_tool(box, RENDER)
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    doc, _ = F.take(box, me, F.pending(box, RENDER)[0])
    assert F.send_reply(box, me, doc, [BAKE], text="Baked; open Fresing Render to export") is None
    assert F.read_status(box, RENDER, job)["state"] == "done" and "reply" not in F.read_status(box, RENDER, job)
    job2 = F.send(box, PLANNER, RENDER, "bake-house", [SCENE], ret="import-bake")
    doc2, _ = F.take(box, me, F.pending(box, RENDER)[0])
    shutil.rmtree(box / "tools" / PLANNER)
    assert F.send_reply(box, me, doc2, [BAKE]) is None
    assert F.read_status(box, RENDER, job2)["state"] == "done"


def test_a_reply_the_sender_cannot_take_is_said_in_the_status(box):
    me = F.read_tool(box, RENDER)
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE], ret="import-bake")
    doc, _ = F.take(box, me, F.pending(box, RENDER)[0])
    assert F.send_reply(box, me, doc, [STEP]) is None                     # import-bake does not accept STEP
    st = F.read_status(box, RENDER, job)
    assert st["state"] == "done" and "could not be sent back" in st["text"]
    clean(box)


def test_a_file_that_is_still_being_written_is_not_read(box):
    me = F.read_tool(box, RENDER)
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    folder = box / "tools" / RENDER / "inbox" / job
    whole = (folder / SCENE.name).read_bytes()
    (folder / SCENE.name).write_bytes(whole[:50])
    with pytest.raises(FileNotFoundError):
        F.take(box, me, folder)
    (folder / SCENE.name).write_bytes(whole + b"x")
    with pytest.raises(F.JobProblem) as e:
        F.take(box, me, folder)
    assert e.value.code == "bad-job"
    (folder / SCENE.name).unlink()
    os.symlink(SCENE, folder / SCENE.name)
    with pytest.raises(F.JobProblem):
        F.take(box, me, folder)


def test_cancel_and_cleaning_up(box):
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    assert not F.wants_cancel(box, RENDER, job)
    F.cancel(box, PLANNER if False else RENDER, job)
    assert F.wants_cancel(box, RENDER, job)
    F.write_status(box, RENDER, job, "cancelled", text="Stopped because the sender asked")
    clean(box)
    old = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])            # never looked at
    (box / "tools" / RENDER / "inbox" / "20260101-000000-abandon").mkdir()  # no job.json
    now = time.time()
    F.clean(box, RENDER, at=now + 3600)
    assert len(list((box / "tools" / RENDER / "inbox").iterdir())) == 3   # an hour later: all still there
    F.clean(box, RENDER, at=now + 2 * F.DAY)
    assert sorted(p.name for p in (box / "tools" / RENDER / "inbox").iterdir()) == sorted([old, "20260101-000000-abandon"])
    F.clean(box, RENDER, at=now + 31 * F.DAY)
    assert not list((box / "tools" / RENDER / "inbox").iterdir())


def test_the_stand_in_program_answers_a_job(tmp_path):
    root = tmp_path / "Toolbox"
    F.ensure_folder(root)
    F.write_manifest(root, json.loads((SAMPLES / "Toolbox" / "tools" / PLANNER / "toolbox.json").read_text("utf-8")))
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "standin.py"), "--folder", str(root), "--seconds", "1", "--once"],
                            stdout=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if F.is_alive(root, "nl.fresing.trial.receiver"):
                break
            time.sleep(0.1)
        job = F.send(root, PLANNER, "nl.fresing.trial.receiver", "bake-house", [SCENE], ret="import-bake")
        out, _ = proc.communicate(timeout=30)
    finally:
        proc.kill()
    assert proc.returncode == 0 and "bake sent back" in out, out
    st = F.read_status(root, "nl.fresing.trial.receiver", job)
    assert st["state"] == "done"
    (back,) = F.pending(root, PLANNER)
    assert back.name == st["reply"]
    assert check(root).items == [], check(root).text()
    assert not F.is_alive(root, "nl.fresing.trial.receiver")
