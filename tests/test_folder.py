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

from datetime import datetime, timedelta  # noqa: E402

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


def test_a_file_shorter_longer_or_missing_is_a_bad_job(box):
    """job.json is written last, so a file that is short or missing when it is there never comes (6.3, P20)"""
    me = F.read_tool(box, RENDER)
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    folder = box / "tools" / RENDER / "inbox" / job
    whole = (folder / SCENE.name).read_bytes()
    (folder / SCENE.name).write_bytes(whole[:50])
    with pytest.raises(F.JobProblem) as e:
        F.take(box, me, folder)
    assert e.value.code == "bad-job" and e.value.state == "failed"
    (folder / SCENE.name).unlink()
    with pytest.raises(F.JobProblem, match="is missing"):
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
    inbox = box / "tools" / RENDER / "inbox"
    (inbox / "20260101-000000-abandon").mkdir()                          # no job.json: dated by its newest file
    (inbox / "20260101-000000-abandon" / "part.step").write_bytes(b"x")
    (inbox / "20260101-000000-emptyjob").mkdir()                         # no files: perhaps being written right now
    now = time.time()
    F.clean(box, RENDER, at=now + 3600)
    assert len(list(inbox.iterdir())) == 4                               # an hour later: all still there
    F.clean(box, RENDER, at=now + 2 * F.DAY)
    assert sorted(p.name for p in inbox.iterdir()) == sorted([old, "20260101-000000-abandon", "20260101-000000-emptyjob"])
    F.clean(box, RENDER, at=now + 31 * F.DAY)
    assert [p.name for p in inbox.iterdir()] == ["20260101-000000-emptyjob"]


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


def test_only_one_copy_takes_a_job(box):
    job = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    assert F.claim(box, RENDER, job, "waiting", text="Waiting for you in Fresing Render: press Bake now")
    assert not F.claim(box, RENDER, job, "working")                       # the second copy loses
    assert F.read_status(box, RENDER, job)["state"] == "waiting" and F.pending(box, RENDER) == []
    clean(box)


def test_jobs_left_from_an_earlier_run(box):
    a = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    b = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    c = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    F.claim(box, RENDER, a, "waiting")
    F.claim(box, RENDER, b, "working", fraction=0.5)
    F.claim(box, RENDER, c, "done")
    assert F.unfinished(box, RENDER) == []                               # fresh: another copy may hold them (P1)
    later = datetime.now().astimezone() + timedelta(minutes=6)
    left = {folder.name: st["state"] for folder, st in F.unfinished(box, RENDER, at=later)}
    assert left == {a: "waiting", b: "working"}
    (box / "tools" / RENDER / "inbox" / a / "status.json").write_bytes(b'{"format": "toolbox-st')   # half written
    assert [f.name for f, _ in F.unfinished(box, RENDER, at=later)] == [b]   # read again at the next look, no crash


def test_a_working_job_is_believed_for_five_minutes():
    from datetime import datetime, timedelta, timezone
    at = datetime(2026, 11, 18, 20, 0, 0, tzinfo=timezone.utc)
    st = lambda state, ago: {"state": state, "updated": (at - timedelta(seconds=ago)).isoformat(timespec="seconds")}  # noqa: E731
    assert not F.is_stalled(st("working", 299), at) and F.is_stalled(st("working", 301), at)
    assert not F.is_stalled(st("waiting", 9999), at) and not F.is_stalled(st("done", 9999), at) and not F.is_stalled(None, at)
    assert F.is_stalled({"state": "working", "updated": "2026-11-18T21:00:00+01:00"}, at + timedelta(minutes=6))


def test_a_link_is_never_a_job_and_never_followed(box, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("the owner's file")
    shutil.copy(box / "toolbox-folder.json", outside / "job.json")
    inbox = box / "tools" / RENDER / "inbox"
    os.symlink(outside, inbox / "20260101-000000-linked", target_is_directory=True)
    assert F.pending(box, RENDER) == [] and F.unfinished(box, RENDER) == []
    F.clean(box, RENDER, at=time.time() + 40 * F.DAY)
    F.remove_job(box, RENDER, "20260101-000000-linked")
    assert (outside / "keep.txt").read_text() == "the owner's file"


def test_the_stand_in_ends_what_an_earlier_run_left(tmp_path):
    root = tmp_path / "Toolbox"
    F.ensure_folder(root)
    F.write_manifest(root, json.loads((SAMPLES / "Toolbox" / "tools" / PLANNER / "toolbox.json").read_text("utf-8")))
    from tools.standin import manifest
    F.write_manifest(root, manifest("nl.fresing.trial.receiver"))
    old = F.send(root, PLANNER, "nl.fresing.trial.receiver", "bake-house", [SCENE])
    F.claim(root, "nl.fresing.trial.receiver", old, "working", fraction=0.3)
    held = F.send(root, PLANNER, "nl.fresing.trial.receiver", "bake-house", [SCENE])
    F.claim(root, "nl.fresing.trial.receiver", held, "waiting")         # fresh: another copy may hold it
    status = root / "tools" / "nl.fresing.trial.receiver" / "inbox" / old / "status.json"
    doc = json.loads(status.read_text("utf-8"))
    doc["updated"] = (datetime.now().astimezone() - timedelta(minutes=6)).isoformat(timespec="seconds")
    status.write_text(json.dumps(doc), "utf-8")                          # nobody has written it for 6 minutes
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "standin.py"), "--folder", str(root), "--seconds", "1", "--once"],
                            stdout=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if F.is_alive(root, "nl.fresing.trial.receiver"):
                break
            time.sleep(0.1)
        st = F.read_status(root, "nl.fresing.trial.receiver", old)
        assert (st["state"], st["code"]) == ("failed", "error")
        assert F.read_status(root, "nl.fresing.trial.receiver", held)["state"] == "waiting"
        F.send(root, PLANNER, "nl.fresing.trial.receiver", "bake-house", [SCENE])
        proc.communicate(timeout=30)
    finally:
        proc.kill()
    assert check(root).items == [], check(root).text()
