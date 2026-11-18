"""The checker on the samples and on broken copies of them. Every rule of FORMAT.md the checker enforces has a
broken copy here that it must refuse."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tbf.check import check  # noqa: E402
from tbf.detect import detect, load_types, pattern_problem, rule_problems  # noqa: E402
from tbf.names import JsonError, load_json, name_problem, time_problem  # noqa: E402

SAMPLES = ROOT / "samples"
RENDER, PLANNER = "nl.fresing.render", "nl.fresing.house-planner"
JOB1, JOB2, REPLY1 = "20261118-195100-9f3c2a", "20261118-203000-c81e55", "20261118-201500-4b7d10"


@pytest.fixture
def box(tmp_path):
    shutil.copytree(SAMPLES / "Toolbox", tmp_path / "Toolbox")
    return tmp_path / "Toolbox"


def edit(path: Path, change):
    doc = json.loads(path.read_text("utf-8"))
    change(doc)
    path.write_text(json.dumps(doc, indent=2), "utf-8")


def manifest(box, tool=RENDER):
    return box / "tools" / tool / "toolbox.json"


def job(box, tool=RENDER, j=JOB1):
    return box / "tools" / tool / "inbox" / j


# ---------------------------------------------------------------- the samples
def test_samples_are_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_samples.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_sample_folder_is_clean():
    rep = check(SAMPLES / "Toolbox")
    assert rep.items == [], rep.text()


def test_types_file_is_clean():
    assert check(ROOT / "types.json").items == []


def test_one_manifest_and_one_job_alone():
    assert check(manifest(SAMPLES / "Toolbox")).items == []
    assert check(job(SAMPLES / "Toolbox")).items == []


def test_command_line(box):
    r = subprocess.run([sys.executable, str(ROOT / "check.py"), str(box)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().endswith("OK")
    (job(box) / "sample-house.hpscene").unlink()
    r = subprocess.run([sys.executable, str(ROOT / "check.py"), str(box)], capture_output=True, text=True)
    assert r.returncode == 1 and "is missing" in r.stdout
    r = subprocess.run([sys.executable, str(ROOT / "check.py"), "--type", str(SAMPLES / "files" / "sample-part.step")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().endswith(": step")


# ---------------------------------------------------------------- broken manifests
MANIFEST_BREAKS = {
    "another version": (lambda d: d.update(version="0.2"), "this checker reads 0.1 only"),
    "a newer major": (lambda d: d.update(version="1.0"), "this checker reads 0.1 only"),
    "wrong format": (lambda d: d.update(format="toolbox-job"), "'toolbox-tool' was expected"),
    "id is not the folder": (lambda d: d.update(id="nl.fresing.other"), "but its folder is named"),
    "id with capitals": (lambda d: d.update(id="NL.Fresing.Render"), "does not match"),
    "id of one part": (lambda d: d.update(id="render"), "does not match"),
    "unknown field": (lambda d: d.update(colour="red"), "Additional properties"),
    "no actions key": (lambda d: d.pop("actions"), "'actions' is a required property"),
    "action twice": (lambda d: d["actions"].append(dict(d["actions"][0])), "the action import-step is there twice"),
    "unknown short type": (lambda d: d["actions"][0].update(accepts=["stepp"]), "'stepp' is not a type"),
    "accepts nothing": (lambda d: d["actions"][0].update(accepts=[]), "accepts"),
    "native with url": (lambda d: d.update(url="https://example.com/"), "a native tool has no url"),
    "program not a full path": (lambda d: d["start"].update(program="blender.exe"), "full path"),
    "http homepage": (lambda d: d.update(homepage="http://example.com/"), "does not match"),
    "own type without dots": (lambda d: d.update(types=[{"id": "widget", "name": "Widget", "extensions": [".wdg"]}]),
                              "named like a tool"),
    "own type twice": (lambda d: d.update(types=[{"id": "com.example.widget", "name": "Widget", "extensions": [".wdg"]}] * 2),
                       "is there twice"),
    "own type with a bad rule": (lambda d: d.update(types=[{"id": "com.example.widget", "name": "W", "extensions": [".wdg"],
                                                            "detect": {"head_matches": "^WDG"}}]), "uses ^"),
    "by_content without a rule": (lambda d: d.update(types=[{"id": "com.example.widget", "name": "W", "extensions": [".wdg"],
                                                             "by_content": True}]), "by_content needs a detect rule"),
    "icon in another folder": (lambda d: d.update(icon="../icon.png"), "icon: the file name"),
    "unknown handover": (lambda d: d.update(handover=["bridge"]), "is not one of"),
}


@pytest.mark.parametrize("name", MANIFEST_BREAKS)
def test_broken_manifest(box, name):
    change, expect = MANIFEST_BREAKS[name]
    edit(manifest(box), change)
    rep = check(box)
    assert not rep.ok and any(expect in e for e in rep.errors), rep.text()


def test_web_tool_needs_url_and_no_start(box):
    edit(manifest(box, PLANNER), lambda d: d.pop("url"))
    assert any("a web tool needs its url" in e for e in check(box).errors)
    edit(manifest(box, PLANNER), lambda d: d.update(url="https://example.com/", start={"program": "C:/x.exe"}))
    assert any("a web tool has no start" in e for e in check(box).errors)


def test_manifest_warnings(box):
    edit(manifest(box), lambda d: d.update(icon="icon.png", handover=[]))
    edit(manifest(box, PLANNER), lambda d: d["actions"][0].update(accepts=["hpbake", "com.example.widget"]))
    rep = check(box)
    assert rep.ok and len(rep.warnings) == 3, rep.text()
    assert any("icon.png is not next to the manifest" in w for w in rep.warnings)
    assert any("nothing can be sent to it" in w for w in rep.warnings)
    assert any("com.example.widget is not defined in this manifest" in w for w in rep.warnings)


def test_own_type_is_used_for_jobs(box):
    wdg = {"id": "com.example.widget", "name": "Widget", "extensions": [".wdg"], "by_content": True,
           "detect": {"starts_with": "WIDGET"}}
    edit(manifest(box), lambda d: (d.update(types=[wdg]), d["actions"][0].update(accepts=["step", "com.example.widget"])))
    j = job(box, j="20261118-210000-aaaaaa")
    j.mkdir()
    (j / "part.wdg").write_bytes(b"WIDGET 1\n")
    (j / "job.json").write_text(json.dumps({
        "format": "toolbox-job", "version": "0.1", "job": j.name, "created": "2026-11-18T21:00:00+01:00",
        "from": PLANNER, "to": RENDER, "action": "import-step",
        "files": [{"name": "part.wdg", "type": "com.example.widget", "size": 9}]}), "utf-8")
    assert check(box).items == [], check(box).text()
    edit(manifest(box, PLANNER), lambda d: d.update(types=[dict(wdg, name="Another widget")]))
    assert any("defined differently by another tool" in e for e in check(box).errors)


def test_folder_level_problems(box):
    (box / "tools" / "Not A Tool").mkdir()
    (box / "tools" / "com.example.empty").mkdir()
    (box / "notes.txt").write_text("x")
    (box / "tools" / RENDER / "outbox").mkdir()
    (box / "tools" / RENDER / "inbox" / "short").mkdir()
    (box / "tools" / RENDER / "inbox" / "20261118-220000-bbbbbb").mkdir()
    rep = check(box)
    assert any("tools/Not A Tool: not a tool id" in e for e in rep.errors)
    assert any("tools/com.example.empty: no toolbox.json" in e for e in rep.errors)
    assert any("inbox/short: not a job id" in e for e in rep.errors)
    assert any("notes.txt" in w for w in rep.warnings)
    assert any("outbox" in w for w in rep.warnings)
    assert any("20261118-220000-bbbbbb: no job.json" in w for w in rep.warnings)


def test_no_marker_file(box):
    (box / "toolbox-folder.json").unlink()
    assert any("not a Toolbox folder" in e for e in check(box).errors)


# ---------------------------------------------------------------- broken jobs
JOB_BREAKS = {
    "job is not the folder": (lambda d: d.update(job="20261118-195100-000000"), "but its folder is named"),
    "for another tool": (lambda d: d.update(to="nl.fresing.other"), "lies in the inbox of"),
    "unknown action": (lambda d: d.update(action="polish"), "has no action polish"),
    "to itself": (lambda d: d.update({"from": RENDER}), "from and to are the same tool"),
    "bad time": (lambda d: d.update(created="18 Nov 2026"), "does not match"),
    "impossible date": (lambda d: d.update(created="2026-02-30T10:00:00+01:00"), "is not a real date"),
    "no files": (lambda d: d.update(files=[]), "files"),
    "wrong size": (lambda d: d["files"][0].update(size=5), "not written to the end"),
    "wrong type": (lambda d: d["files"][0].update(type="hpbake"), "calls it hpbake, but it is hpscene"),
    "missing file": (lambda d: d["files"][0].update(name="other.hpscene"), "the file other.hpscene is missing"),
    "path in a name": (lambda d: d["files"][0].update(name="../sample-house.hpscene"), "holds '/'"),
    "windows name": (lambda d: d["files"][0].update(name="nul.hpscene"), "Windows keeps for itself"),
    "own file as payload": (lambda d: d["files"][0].update(name="status.json"), "one of the format's own files"),
    "listed twice": (lambda d: d["files"].append(dict(d["files"][0], name="SAMPLE-HOUSE.hpscene")), "listed twice"),
    "return the sender lacks": (lambda d: d.update({"return": "import-step"}), "which the sender"),
    "reply from somebody else": (lambda d: d.update(reply_to={"tool": "nl.fresing.other", "job": JOB2}),
                                 "a reply comes from the tool that did the job"),
    "reply that asks for a reply": (lambda d: d.update(reply_to={"tool": PLANNER, "job": JOB2}), "a reply job has no return"),
    "unknown field": (lambda d: d.update(priority=1), "Additional properties"),
    "another version": (lambda d: d.update(version="0.3"), "this checker reads 0.1 only"),
}


@pytest.mark.parametrize("name", JOB_BREAKS)
def test_broken_job(box, name):
    change, expect = JOB_BREAKS[name]
    edit(job(box) / "job.json", change)
    rep = check(box)
    assert not rep.ok and any(expect in e for e in rep.errors), rep.text()


def test_type_the_action_does_not_accept(box):
    j = job(box)
    shutil.copy(SAMPLES / "files" / "sample-part.step", j / "sample-part.step")
    size = (j / "sample-part.step").stat().st_size
    edit(j / "job.json", lambda d: d.update(files=[{"name": "sample-part.step", "type": "step", "size": size}]))
    rep = check(box)
    assert any("bake-house does not accept step" in e for e in rep.errors)
    assert any("sample-house.hpscene is not named by job.json" in w for w in rep.warnings)


def test_renamed_file_is_found_out(box):
    j = job(box)
    (j / "sample-house.hpscene").rename(j / "sample-house.zip")
    edit(j / "job.json", lambda d: d["files"][0].update(name="sample-house.zip", type="zip"))
    assert any("calls it zip, but it is hpscene" in e for e in check(box).errors)
    edit(j / "job.json", lambda d: d["files"][0].update(type="hpscene"))
    rep = check(box)
    assert rep.ok and any("its name ends in .zip" in w for w in rep.warnings), rep.text()


def test_sender_without_manifest_and_return_that_does_not_fit(box):
    edit(job(box) / "job.json", lambda d: d.update({"from": "com.example.unknown"}))
    assert any("has no manifest in this Toolbox folder" in w for w in check(box).warnings)
    edit(job(box, j=JOB2) / "job.json", lambda d: d.update({"return": "import-model"}))
    assert any("accepts none of them" in w for w in check(box).warnings)


STATUS_BREAKS = {
    "another job": (lambda d: d.update(job=JOB2), "is about the job"),
    "unknown state": (lambda d: d.update(state="paused"), "is not one of"),
    "fraction above one": (lambda d: d.update(fraction=1.5), "greater than the maximum"),
    "bad time": (lambda d: d.update(updated="yesterday"), "does not match"),
}


@pytest.mark.parametrize("name", STATUS_BREAKS)
def test_broken_status(box, name):
    change, expect = STATUS_BREAKS[name]
    edit(job(box) / "status.json", change)
    rep = check(box)
    assert not rep.ok and any(expect in e for e in rep.errors), rep.text()


def test_status_warnings_and_cancel(box):
    edit(job(box, j=JOB2) / "status.json", lambda d: d.update(code="error", reply=REPLY1))
    rep = check(box)
    assert rep.ok and sum("status.json" in w for w in rep.warnings) == 2, rep.text()
    edit(job(box, j=JOB2) / "cancel.json", lambda d: d.update(job=JOB1))
    assert any("cancel.json: is about the job" in e for e in check(box).errors)


def test_alive(box):
    edit(box / "tools" / RENDER / "alive.json", lambda d: d.update(seen="now"))
    assert any("alive.json" in e for e in check(box).errors)


# ---------------------------------------------------------------- strict JSON
@pytest.mark.parametrize("data, expect", [
    (b'\xef\xbb\xbf{"a":1}', "byte-order mark"),
    (b'{"a":1,"a":2}', "there twice"),
    (b'{"a":NaN}', "not allowed"),
    (b'{"a":"line\\nbreak"}', "control character"),
    (b'["a"]', "not a JSON object"),
    (b'{"a":"\xff"}', "not UTF-8"),
    (b'{"a":', "not JSON"),
    (b'{"a":"' + b"x" * 2**20 + b'"}', "larger than 1 MiB"),
])
def test_strict_json(data, expect):
    with pytest.raises(JsonError, match=expect):
        load_json(data)


def test_broken_json_file_is_an_error_not_a_crash(box):
    (job(box) / "job.json").write_bytes(b"{")
    (box / "tools" / RENDER / "alive.json").write_bytes(b"\xff\xfe")
    rep = check(box)
    assert len(rep.errors) == 2, rep.text()


# ---------------------------------------------------------------- names and times
@pytest.mark.parametrize("name", ["", "a/b", "a\\b", "..", ".hidden", "trailing.", "trailing ", " leading", "con",
                                  "COM1.step", "a:b", "what?.step", "x" * 121, "tab\there", "job.json", "Status.JSON"])
def test_bad_names(name):
    assert name_problem(name)


@pytest.mark.parametrize("name", ["part.step", "Hus – versjon 3.hpscene", "a.b.c.tar.gz", "console.step", "x" * 120])
def test_good_names(name):
    assert name_problem(name) is None


def test_times():
    for good in ("2026-11-18T19:51:00+01:00", "2026-11-18T18:51:00Z", "2026-11-18T19:51:00.250+01:00"):
        assert time_problem(good) is None
    for bad in ("2026-11-18 19:51:00", "2026-11-18T19:51:00", "2026-13-01T00:00:00Z", 5, None):
        assert time_problem(bad)


# ---------------------------------------------------------------- file types
def test_every_sample_file_type():
    types = load_types()
    want = {"sample-part.step": "step", "sample-building.ifc": "ifc", "sample-house.hpscene": "hpscene",
            "sample-house.hpbake": "hpbake", "sample-model.glb": "glb", "sample-notes.csv": "csv",
            "sample-archive.zip": "zip", "sample.unknownkind": "ext:unknownkind"}
    for name, tid in want.items():
        assert detect(SAMPLES / "files" / name, types) == (tid, None), name
    assert set(want) == {p.name for p in (SAMPLES / "files").iterdir()}


def test_content_wins_over_the_name(tmp_path):
    types = load_types()
    ifc = tmp_path / "building.step"
    shutil.copy(SAMPLES / "files" / "sample-building.ifc", ifc)
    tid, note = detect(ifc, types)
    assert tid == "ifc" and ".step" in note
    fake = tmp_path / "fake.step"
    fake.write_bytes(b"this is not STEP\n")
    tid, note = detect(fake, types)
    assert tid == "ext:step" and "is not STEP model" in note
    plain = tmp_path / "plain.hpscene"
    shutil.copy(SAMPLES / "files" / "sample-archive.zip", plain)
    assert detect(plain, types)[0] == "ext:hpscene"
    assert detect(SAMPLES / "files" / "sample-part.step", types, name="PART.STP") == ("step", None)
    bare = tmp_path / "README"
    bare.write_bytes(b"x")
    assert detect(bare, types) == ("ext:", None)
    empty = tmp_path / "empty.step"
    empty.write_bytes(b"")
    assert detect(empty, types)[0] == "ext:step"


def test_step_with_a_byte_order_mark_and_blank_lines(tmp_path):
    p = tmp_path / "bom.stp"
    p.write_bytes(b"\xef\xbb\xbf\r\n  " + (SAMPLES / "files" / "sample-part.step").read_bytes())
    assert detect(p, load_types()) == ("step", None)


def test_step_with_bytes_outside_ascii_in_its_header(tmp_path):
    p = tmp_path / "latin.step"
    data = (SAMPLES / "files" / "sample-part.step").read_bytes().replace(b"made-up sample", b"gjort p\xe5 kontoret \xff")
    p.write_bytes(data)
    assert detect(p, load_types()) == ("step", None)


def test_broken_zip_is_no_house_scene(tmp_path):
    p = tmp_path / "cut.hpscene"
    p.write_bytes((SAMPLES / "files" / "sample-house.hpscene").read_bytes()[:40])
    assert detect(p, load_types())[0] == "ext:hpscene"


@pytest.mark.parametrize("pattern", ["^ISO", "end$", "(?i)step", "(?=x)", "a\\bz", "\\x41", "[abc", "[]", "x" * 201,
                                     "caf\u00e9", "a\\", ""])
def test_patterns_that_are_refused(pattern):
    assert pattern_problem(pattern)


@pytest.mark.parametrize("pattern", ["FILE_SCHEMA\\s*\\(\\s*\\(\\s*'IFC", "[^a-z]+\\d{2,4}", "a|b", "\\$\\^", "[$^]x"])
def test_patterns_that_are_fine(pattern):
    assert pattern_problem(pattern) is None


@pytest.mark.parametrize("rule", [
    {}, {"starts_with": "A", "starts_with_hex": "41"}, {"magic": "A"}, {"starts_with": "two words"},
    {"starts_with_hex": "4G"}, {"starts_with_hex": "ABCD"}, {"all": []}, {"zip_has": {"file": "../x"}},
    {"zip_json": {"file": "a.json", "field": "format"}}, {"not": {"not": {"not": {"not": {"starts_with": "A"}}}}},
])
def test_rules_that_are_refused(rule):
    assert rule_problems(rule, "detect")


def test_rules_that_are_fine():
    for t in load_types():
        assert rule_problems(t.get("detect", {"starts_with": "A"}), "detect") == []
    assert rule_problems({"not": {"any": [{"zip_has": {"file": "a/b.json"}}]}}, "detect") == []


# ---------------------------------------------------------------- nothing makes the checker crash
JUNK = [None, True, 0, -1, 1.5, 10**30, "", "x", "../x", "a\u0000b", [], [[]], {}, {"a": {}}, ["x", 1], "ext:",
        "é" * 300, {"all": []}, [{"id": 1}], {"not": {"not": {"not": {"not": {"not": {}}}}}}]


def _paths(d, pre=()):
    out = [pre] if pre else []
    items = d.items() if isinstance(d, dict) else enumerate(d) if isinstance(d, list) else ()
    for k, v in items:
        out += _paths(v, pre + (k,))
    return out


def test_junk_never_crashes_the_checker(tmp_path):
    import random
    rnd = random.Random(7)
    for n in range(300):
        box = tmp_path / str(n) / "Toolbox"
        shutil.copytree(SAMPLES / "Toolbox", box)
        files = sorted(box.rglob("*.json"))
        for _ in range(rnd.choice([1, 1, 2, 3])):
            f = rnd.choice(files)
            if not f.is_file():
                continue
            doc = json.loads(f.read_text("utf-8"))
            p = rnd.choice(_paths(doc))
            d = doc
            for k in p[:-1]:
                d = d[k]
            if rnd.random() < 0.15 and isinstance(d, dict):
                d.pop(p[-1])
            else:
                d[p[-1]] = rnd.choice(JUNK)
            f.write_text(json.dumps(doc), "utf-8")
        if rnd.random() < 0.1:
            f = rnd.choice(files)
            if f.is_file():
                f.unlink()
                f.mkdir()
        if rnd.random() < 0.1:
            f = rnd.choice([p for p in box.rglob("*") if p.is_file()])
            f.write_bytes(rnd.randbytes(rnd.randint(0, 80)))
        check(box)
        for j in box.glob("tools/*/inbox/*"):
            check(j)
        for m in box.glob("tools/*/toolbox.json"):
            check(m)
        shutil.rmtree(box.parent)
