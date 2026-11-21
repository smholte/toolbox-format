"""Format 0.2 (task 0011 of github.com/smholte/ToolBox): one test per new rule, on broken copies of the samples and
on the reference code. P1–P32 are the numbers of that task. The JavaScript side of the same rules is compared case
by case in tests/test_web.py ("format 0.2")."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import unicodedata
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tbf import folder as F  # noqa: E402
from tbf.check import check  # noqa: E402
from tbf.detect import load_types, pattern_problem, rule_problems, type_problems  # noqa: E402
from tbf.names import JsonError, capitals, load_json, name_problem  # noqa: E402

SAMPLES = ROOT / "samples"
RENDER, PLANNER = "nl.fresing.render", "nl.fresing.house-planner"
JOB1, JOB2 = "20261118-195100-9f3c2a", "20261118-203000-c81e55"
SCENE = SAMPLES / "files" / "sample-house.hpscene"

# the 14 names of task 0010 (W1): .NET on Windows 11 made a real file of each; the format refuses them all (P4)
W1 = ["con .txt", "COM0.txt", "LPT0.txt", "COM\u00b9.txt", "COM\u00b2.txt", "COM\u00b3.txt", "LPT\u00b9.txt", "LPT\u00b2.txt",
      "LPT\u00b3.txt", "CONIN$", "CONOUT$", "CLOCK$", "con.txt.txt", "aux"]
# names NTFS keeps as two files and the format takes as one (P5, task 0010 W5)
PAIRS = [("\u017f.txt", "s.txt"), ("\u00b5.txt", "\u03bc.txt"), ("\u0131.txt", "I.txt")]


@pytest.fixture
def box(tmp_path):
    shutil.copytree(SAMPLES / "Toolbox", tmp_path / "Toolbox")
    return tmp_path / "Toolbox"


def edit(path: Path, change):
    doc = json.loads(path.read_text("utf-8"))
    change(doc)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), "utf-8")


def job_folder(box, tool=RENDER, j=JOB1):
    return box / "tools" / tool / "inbox" / j


def fresh(box, j=JOB1) -> Path:
    """a sample job without its status: not taken yet"""
    folder = job_folder(box, j=j)
    (folder / "status.json").unlink()
    (folder / "cancel.json").unlink(missing_ok=True)
    return folder


def take(box, folder):
    try:
        F.take(box, F.read_tool(box, RENDER), folder)
        return "ok"
    except F.JobProblem as p:
        return p.code
    except FileNotFoundError:
        return "not-complete"


def ago(minutes: float) -> str:
    return (datetime.now().astimezone() - timedelta(minutes=minutes)).isoformat(timespec="seconds")


# ---------------------------------------------------------------- P3, P4, P5, P6: names and ids
@pytest.mark.parametrize("name", W1 + ["Con", "nUl.step", "com9.a.b", "LPT\u00b2", "CONIN$.log", "clock$ .x", "prn  .txt"])
def test_device_names_are_refused(name):
    assert "device" in name_problem(name)


@pytest.mark.parametrize("name", ["console.step", "con-1.txt", "com10.txt", "lpt\u2074.txt", "a.con", "CONIN", "my con.txt",
                                  "x" * 80, "\U0001f3e0" * 63 + ".a", "Hus p\u00e5 hytta.hpscene"])
def test_names_near_those_are_fine(name):
    assert name_problem(name) is None, name


@pytest.mark.parametrize("name, why", [("x" * 81, "80 characters"), ("\U0001f3e0" * 64, "255 bytes"),
                                       ("\u00e9" * 80, None), ("e\u0301.txt", "NFC"), ("\u212b.txt", "NFC"),
                                       ("Job.Json", "own files"), ("\u017ftatus.json", "own files")])
def test_length_bytes_nfc_and_own_files(name, why):
    got = name_problem(name)
    assert (got is None) if why is None else (why in got), (name, got)


@pytest.mark.parametrize("a, b", PAIRS)
def test_pairs_ntfs_keeps_apart_are_one_name_here(a, b):
    """stricter than Windows on purpose: one job never holds both (P5)"""
    assert capitals(a) == capitals(b)


def test_capitals_leave_scripts_from_u0590_on_and_new_capitals_alone():
    assert capitals("\u019b") == "\u019b"            # ƛ: its capital (U+A7DC, Unicode 16) is above U+0590
    assert capitals("\u10d0") == "\u10d0"            # Georgian: as written
    assert capitals("stra\u00dfe") == "STRASSE" and capitals("\u0149") == "\u02bcN"


def test_the_e_written_two_ways_cannot_both_be_sent(box, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    shutil.copy(SCENE, a / "h\u00e9.hpscene")
    shutil.copy(SCENE, b / "he\u0301.hpscene")
    with pytest.raises(ValueError, match="twice"):
        F.send(box, PLANNER, RENDER, "bake-house", [a / "h\u00e9.hpscene", b / "he\u0301.hpscene"])


def test_send_writes_names_in_nfc(box, tmp_path):
    src = tmp_path / "he\u0301.hpscene"
    shutil.copy(SCENE, src)
    job = F.send(box, PLANNER, RENDER, "bake-house", [src])
    doc = json.loads((job_folder(box, j=job) / "job.json").read_text("utf-8"))
    assert doc["files"][0]["name"] == "h\u00e9.hpscene"
    assert check(box).ok, check(box).text()


@pytest.mark.parametrize("a, b", PAIRS)
def test_a_job_with_a_pair_is_refused(box, a, b):
    folder = fresh(box)
    data = (folder / "sample-house.hpscene").read_bytes()
    for n in (a, b):
        (folder / (n + ".hpscene")).write_bytes(data)
    edit(folder / "job.json", lambda d: d.update(files=[{"name": n + ".hpscene", "type": "hpscene", "size": len(data)} for n in (a, b)]))
    assert take(box, folder) == "bad-job"
    assert any("listed twice" in e for e in check(box).errors)


@pytest.mark.parametrize("name", W1)
def test_a_job_naming_a_device_is_refused(box, name):
    folder = fresh(box)
    edit(folder / "job.json", lambda d: d["files"][0].update(name=name))
    assert take(box, folder) == "bad-job"
    assert any("device" in e for e in check(box).errors)


def test_ids_are_short_enough_for_a_path_under_260(box):
    """C:\\Users\\<name>\\Toolbox\\tools\\<60>\\inbox\\<32>\\<80> stays under 260 with a user name of 30 (P6)"""
    assert len("C:\\Users\\" + "u" * 30 + "\\Toolbox\\tools\\" + "t" * 60 + "\\inbox\\" + "j" * 32 + "\\" + "n" * 80) < 260
    long_tool = "com.example." + "x" * 49                     # 61 characters
    edit(box / "tools" / RENDER / "toolbox.json", lambda d: d["actions"][0].update(accepts=["step", long_tool]))
    assert not check(box).ok
    folder = fresh(box, JOB2)
    edit(folder / "job.json", lambda d: d.update(job="2" * 33))
    assert not check(box).ok and take(box, folder) == "bad-job"
    assert len(F.new_job_id()) == 22 and all(len(t) <= 60 for t in (RENDER, PLANNER, "nl.fresing.trial.receiver"))


# ---------------------------------------------------------------- P7, P8: JSON depth and sizes
def deep(levels: int) -> bytes:
    return b'{"a":' * (levels - 1) + b"{}" + b"}" * (levels - 1)


def test_json_at_most_64_levels_deep():
    load_json(deep(64))
    load_json(b'{"a":' + b"[" * 63 + b"1" + b"]" * 63 + b"}")
    for data in (deep(65), b'{"a":' + b"[" * 64 + b"1" + b"]" * 64 + b"}", deep(3000)):
        with pytest.raises(JsonError, match="deeper than 64"):
            load_json(data)


def test_a_job_whose_options_are_too_deep_is_refused(box):
    folder = fresh(box)
    edit(folder / "job.json", lambda d: d.update(options=json.loads(deep(64))))
    assert take(box, folder) == "bad-job" and not check(box).ok


def test_a_size_beyond_what_javascript_can_count(box):
    folder = fresh(box)
    edit(folder / "job.json", lambda d: d["files"][0].update(size=2**53))
    assert take(box, folder) == "bad-job"
    assert any("maximum" in e for e in check(box).errors)


# ---------------------------------------------------------------- P2, P9, P15: rules and patterns
def test_own_types_may_not_use_head_matches(box):
    wdg = {"id": "com.example.widget", "name": "Widget", "extensions": [".wdg"], "by_content": True,
           "detect": {"all": [{"starts_with": "WDG"}, {"not": {"head_matches": "x+y"}}]}}
    edit(box / "tools" / RENDER / "toolbox.json", lambda d: d.update(types=[wdg]))
    assert any("may not use head_matches" in e for e in check(box).errors)
    assert F.read_tool(box, RENDER) is None                     # a reader does not use such a manifest
    assert type_problems(dict(wdg, id="widget"), "t", own=False) == []     # the built-in list may


def test_the_built_in_patterns_stay_fast_on_hostile_heads(tmp_path):
    """the only patterns left are those of types.json (P2); a 64 KiB head made to slow them down takes well under a
    second each (Python 3.13: about 0.01 s)"""
    pats = {t["detect"] and json.dumps(t["detect"]) for t in load_types() if "head_matches" in json.dumps(t.get("detect", {}))}
    pats = [re.findall(r'"head_matches": "(.*?)"(?=\})', p) for p in pats]
    pats = {json.loads(f'"{x}"') for group in pats for x in group}
    assert pats == {"FILE_SCHEMA\\s*\\(\\s*\\(\\s*'IFC"}
    heads = ["FILE_SCHEMA" * 6000, "FILE_SCHEMA" + " " * 65000, ("FILE_SCHEMA (" + " " * 50) * 1000,
             ("FILE_SCHEMA ( (" + " " * 20) * 1800]
    for p in pats:
        for h in heads:
            t = time.perf_counter()
            re.search(p, h[:65536], re.ASCII)
            assert time.perf_counter() - t < 1, (p, h[:30])


@pytest.mark.parametrize("pattern", ["[[a]", "[^[]", "[a[b]", "[a--b]", "[%--]", "[a&&b]", "[&&]", "[a||b]", "[~~]", "[a~~b]"])
def test_patterns_python_will_read_otherwise_one_day_are_refused(pattern):
    assert pattern_problem(pattern)


def test_no_allowed_pattern_makes_python_warn():
    import random
    rnd = random.Random(2)
    alphabet = list("ab[]^-&|~\\d(){}*+?2,.$") + ["\\[", "\\]", "\\-"]
    tried = 0
    for _ in range(20000):
        p = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 8)))
        if pattern_problem(p) is None:
            tried += 1
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                re.compile(p, re.ASCII)
    assert tried > 500


def test_zip_rules_name_ascii_files_only():
    assert rule_problems({"zip_has": {"file": "sc\u00e8ne.json"}}, "d")
    assert rule_problems({"zip_json": {"file": "a b/scene.json", "field": "format", "equals": "x"}}, "d") == []


# ---------------------------------------------------------------- P1: jobs left behind
def test_a_job_another_copy_holds_is_not_taken_up(box):
    folder = fresh(box)
    assert F.claim(box, RENDER, folder.name, "waiting", text="Waiting for you")
    left = lambda: [f.name for f, _ in F.unfinished(box, RENDER)]          # noqa: E731
    assert folder.name not in left() and not F.take_up(box, RENDER, folder.name, "working")
    edit(folder / "status.json", lambda d: d.update(updated=ago(6)))
    assert folder.name in left()
    assert F.take_up(box, RENDER, folder.name, "working", fraction=0.0)
    assert F.read_status(box, RENDER, folder.name)["state"] == "working"
    assert not F.take_up(box, RENDER, folder.name, "working")    # fresh again
    assert check(box).ok, check(box).text()


def test_of_several_copies_only_one_takes_a_job_up(box):
    folder = fresh(box)
    F.claim(box, RENDER, folder.name, "working")
    edit(folder / "status.json", lambda d: d.update(updated=ago(10)))
    won = []

    def copy(n):
        if F.take_up(box, RENDER, folder.name, "working", text=f"copy {n}"):
            won.append(n)

    for _ in range(30):
        F.write_status(box, RENDER, folder.name, "working", text="old")
        edit(folder / "status.json", lambda d: d.update(updated=ago(10)))
        won.clear()
        threads = [threading.Thread(target=copy, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(won) == 1 and F.read_status(box, RENDER, folder.name)["text"] == f"copy {won[0]}"
        assert sorted(p.name for p in folder.iterdir()) == ["job.json", "sample-house.hpscene", "status.json"]


def test_a_final_status_is_never_written_over(box):
    st = job_folder(box) / "status.json"
    before = st.read_bytes()
    assert F.write_status(box, RENDER, JOB1, "working", fraction=0.5) is False
    assert F.take_up(box, RENDER, JOB1, "working", at=datetime.now().astimezone() + timedelta(days=9)) is False
    assert st.read_bytes() == before
    assert F.write_status(box, RENDER, JOB2, "cancelled", text="Stopped") is True
    assert F.write_status(box, RENDER, JOB2, "done") is False


def test_a_reply_after_a_cancel_leaves_the_status_cancelled(box):
    folder = fresh(box)
    job, _ = F.take(box, F.read_tool(box, RENDER), folder)
    F.claim(box, RENDER, JOB1, "working")
    F.write_status(box, RENDER, JOB1, "cancelled", text="Stopped because the sender asked")
    F.send_reply(box, F.read_tool(box, RENDER), job, [SAMPLES / "files" / "sample-house.hpbake"])
    assert F.read_status(box, RENDER, JOB1)["state"] == "cancelled"


# ---------------------------------------------------------------- P20, P21, P28: what take() refuses
def test_a_job_cancelled_before_it_is_taken_ends_cancelled(box):
    folder = job_folder(box, j=JOB2)
    (folder / "status.json").unlink()
    with pytest.raises(F.JobProblem) as e:
        F.take(box, F.read_tool(box, RENDER), folder)
    assert (e.value.code, e.value.state) == ("cancelled", "cancelled")
    assert F.refuse(box, RENDER, JOB2, e.value)
    st = F.read_status(box, RENDER, JOB2)
    assert st["state"] == "cancelled" and "code" not in st
    assert check(box).items == [], check(box).text()


@pytest.mark.parametrize("change", [lambda d: d.update(reply_to={"tool": "nl.fresing.other", "job": JOB2}),
                                    lambda d: d.update(reply_to={"tool": PLANNER, "job": JOB2})])
def test_a_reply_that_breaks_6_1_is_refused_by_the_reader_too(box, change):
    folder = fresh(box)                                          # JOB1 has a return; the second change keeps it
    edit(folder / "job.json", lambda d: (change(d), d.pop("return") if d["reply_to"]["tool"] != PLANNER else None))
    assert take(box, folder) == "bad-job" and not check(box).ok


@pytest.mark.parametrize("data", [b"", b"x" * 10])
def test_a_short_or_missing_file_is_a_bad_job_at_once(box, data):
    folder = fresh(box)
    (folder / "sample-house.hpscene").write_bytes(data)
    assert take(box, folder) == "bad-job"
    (folder / "sample-house.hpscene").unlink()
    assert take(box, folder) == "bad-job"


def test_a_failed_status_always_has_a_code(box):
    folder = fresh(box)
    F.claim(box, RENDER, folder.name, "failed", text="Could not")
    assert F.read_status(box, RENDER, folder.name)["code"] == "error"


# ---------------------------------------------------------------- P23, P27, P29, P30: the checker
def test_status_warnings(box):
    edit(job_folder(box) / "status.json", lambda d: d.update(state="failed", text="x"))
    edit(job_folder(box, j=JOB2) / "status.json", lambda d: d.update(state="waiting"))
    rep = check(box)
    assert rep.ok
    assert any("a failed job has a code" in w for w in rep.warnings)
    assert any("a fraction belongs to a job that is working" in w for w in rep.warnings)


def test_a_finished_job_may_have_lost_its_files(box):
    (job_folder(box) / "sample-house.hpscene").unlink()          # done: 7.4 lets the files go
    assert check(box).items == [], check(box).text()
    (job_folder(box, j=JOB2) / "sample-house.hpscene").unlink()  # working: they are still needed
    assert any("is missing" in e for e in check(box).errors)


def test_an_icon_that_is_no_picture_is_a_warning(box):
    edit(box / "tools" / RENDER / "toolbox.json", lambda d: d.update(icon="icon.png"))
    (box / "tools" / RENDER / "icon.png").write_bytes(b"not a picture")
    rep = check(box)
    assert rep.ok and any("neither a PNG nor an SVG" in w for w in rep.warnings), rep.text()
    (box / "tools" / RENDER / "icon.png").write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"rest")
    assert check(box).items == []
    (box / "tools" / RENDER / "icon.png").unlink()
    edit(box / "tools" / RENDER / "toolbox.json", lambda d: d.update(icon="icon.svg"))
    (box / "tools" / RENDER / "icon.svg").write_bytes(b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert check(box).items == [], check(box).text()


def test_unknown_entries_are_warnings(box):
    (box / "tools" / "notes").mkdir()
    (box / "tools" / RENDER / "inbox" / "Old jobs").mkdir()
    rep = check(box)
    assert rep.ok and len(rep.warnings) == 2, rep.text()


# ---------------------------------------------------------------- P25: cleaning up by created, not by the folder's date
def test_cleaning_up_goes_by_created(box):
    inbox = box / "tools" / RENDER / "inbox"
    old = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    edit(inbox / old / "job.json", lambda d: d.update(created=ago(31 * 24 * 60)))
    young = F.send(box, PLANNER, RENDER, "bake-house", [SCENE])
    long_ago = time.time() - 40 * F.DAY
    os.utime(inbox / young, (long_ago, long_ago))                 # the folder's own date does not count
    F.clean(box, RENDER)
    names = {p.name for p in inbox.iterdir()}
    assert old not in names and young in names


# ---------------------------------------------------------------- versions
def test_a_native_tool_marks_an_older_folder_as_its_own_version(tmp_path):
    root = tmp_path / "Toolbox"
    (root / "tools").mkdir(parents=True)
    (root / "toolbox-folder.json").write_text('{"format": "toolbox-folder", "version": "0.1"}', "utf-8")
    F.ensure_folder(root)
    assert json.loads((root / "toolbox-folder.json").read_text("utf-8"))["version"] == "0.2"


def test_nfc_is_the_same_in_python_311_to_313():
    """Python 3.11 (Blender), 3.12 and 3.13 agree on every character (checked in the review of task 0011); this
    pins a few that matter for file names"""
    for a, b in (("e\u0301", "\u00e9"), ("A\u030a", "\u00c5"), ("\u212b", "\u00c5"), ("o\u0308", "\u00f6")):
        assert unicodedata.normalize("NFC", a) == b


# ---------------------------------------------------------------- found by an independent review of this branch
def test_a_status_text_with_a_line_break_or_a_broken_character_stays_readable(box):
    """a tool passes an error message as text; it must not make status.json unreadable – that let a final status be
    written over (P1) and left an empty status.json behind"""
    folder = fresh(box)
    assert F.claim(box, RENDER, folder.name, "working")
    assert F.write_status(box, RENDER, folder.name, "failed", text="Error:\nline 2\t\ud800 end")
    st = F.read_status(box, RENDER, folder.name)
    assert st["text"] == "Error: line 2 � end"
    assert F.write_status(box, RENDER, folder.name, "working") is False
    assert check(box).ok


def test_a_key_that_is_not_utf8_is_refused_with_a_status_every_reader_reads(box):
    folder = fresh(box)
    text = (folder / "job.json").read_bytes().rstrip()
    (folder / "job.json").write_bytes(text[:-1] + b', "options": {"\\ud800": 1, "a\\u0001b": 2}}')
    with pytest.raises(F.JobProblem) as e:
        F.take(box, F.read_tool(box, RENDER), folder)
    assert F.refuse(box, RENDER, folder.name, e.value)
    assert F.read_status(box, RENDER, folder.name)["code"] == "bad-job"
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "check.py"), str(box)], capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stderr


def test_take_up_never_lets_the_status_go_missing(box, monkeypatch):
    """copy B has read the old status; copy A takes the job up completely before B goes on. B must see that and
    stop – and a copy C looking at its inbox meanwhile never finds the job without a status (it did with the first
    design: B moved A's new status aside, C took the job too, two copies held it)"""
    folder = fresh(box)
    F.claim(box, RENDER, folder.name, "working")
    edit(folder / "status.json", lambda d: d.update(updated=ago(10)))
    real_open, seen = os.open, {}

    def slow_b(path, *a, **k):
        if str(path).endswith(".taking-up") and "A" not in seen:
            monkeypatch.setattr(os, "open", real_open)
            seen["A"] = F.take_up(box, RENDER, folder.name, "working", text="A")
            seen["C pending"] = [p.name for p in F.pending(box, RENDER)]
        return real_open(path, *a, **k)

    monkeypatch.setattr(os, "open", slow_b)
    assert F.take_up(box, RENDER, folder.name, "working", text="B") is False
    assert seen == {"A": True, "C pending": []}
    assert F.read_status(box, RENDER, folder.name)["text"] == "A"
    assert sorted(p.name for p in folder.iterdir()) == ["job.json", "sample-house.hpscene", "status.json"]


def test_a_take_up_lock_left_by_a_crash_goes_after_a_minute(box):
    folder = fresh(box)
    F.claim(box, RENDER, folder.name, "working")
    edit(folder / "status.json", lambda d: d.update(updated=ago(10)))
    lock = folder / F.TAKE_UP_LOCK
    lock.write_bytes(b"")
    assert not F.take_up(box, RENDER, folder.name, "working")             # another copy is taking it up
    assert check(box).ok and not any(".taking-up" in w for w in check(box).warnings)
    os.utime(lock, (time.time() - 90, time.time() - 90))
    assert not F.take_up(box, RENDER, folder.name, "working") and not lock.exists()   # a crash's lock: deleted
    assert F.take_up(box, RENDER, folder.name, "working", text="again")
    assert F.read_status(box, RENDER, folder.name)["text"] == "again"


def test_a_cancel_without_a_job_json_is_left_alone(box):
    folder = job_folder(box, j=JOB2)
    (folder / "status.json").unlink()
    (folder / "job.json").unlink()
    assert take(box, folder) == "not-complete"


# ---------------------------------------------------------------- W3: a refused status write (lead review, round 2)
# Fresing Render measured on Windows (their task 0245): a reader that holds status.json open blocks the replace as
# long as it holds it, up to 0.5 s. On Linux nothing blocks, so the refusal is simulated; the test with a real
# reader holding the file runs everywhere and sees real refusals on Windows (NTFS).
def refusing(monkeypatch, seconds: float):
    """os.replace onto status.json is refused (as Windows does) until `seconds` from now; returns the count"""
    real, until, count = os.replace, time.monotonic() + seconds, [0]

    def replace(src, dst):
        if Path(dst).name == "status.json" and time.monotonic() < until:
            count[0] += 1
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst)

    monkeypatch.setattr(F.os, "replace", replace)
    return count


def test_w3_a_refused_working_status_is_not_written_now_and_nothing_is_left(box, monkeypatch):
    folder = fresh(box)
    assert F.claim(box, RENDER, JOB1, "working", fraction=0.0)
    count = refusing(monkeypatch, 60)
    assert F.write_status(box, RENDER, JOB1, "working", fraction=0.5) is False     # no exception: the job goes on
    assert F.write_status(box, RENDER, JOB1, "waiting", text="Bake now?") is False
    assert count[0] >= 2
    assert F.read_status(box, RENDER, JOB1)["fraction"] == 0.0                     # the old one, whole
    assert sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp")) == []


def test_w3_a_final_status_waits_out_a_half_second_reader(box, monkeypatch):
    fresh(box)
    assert F.claim(box, RENDER, JOB1, "working")
    refusing(monkeypatch, 0.5)
    assert F.write_status(box, RENDER, JOB1, "done", text="Baked") is True
    assert F.read_status(box, RENDER, JOB1)["state"] == "done"


def test_w3_a_final_status_refused_for_longer_raises_after_2_seconds(box, monkeypatch):
    folder = fresh(box)
    assert F.claim(box, RENDER, JOB1, "working")
    refusing(monkeypatch, 60)
    start = time.monotonic()
    with pytest.raises(PermissionError):
        F.write_status(box, RENDER, JOB1, "failed", code="error", text="x")
    assert 1.9 <= time.monotonic() - start < 4
    assert F.read_status(box, RENDER, JOB1)["state"] == "working"                  # the caller writes it again later
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_w3_send_reply_hands_back_the_reply_id_when_done_is_refused(box, monkeypatch, tmp_path):
    """the reply went out; the caller writes "done" again with the same id and never sends twice"""
    folder = fresh(box)
    manifest = F.read_tool(box, RENDER)
    job, files = F.take(box, manifest, folder)
    assert F.claim(box, RENDER, JOB1, "working")
    out = tmp_path / "out" / "bake.hpbake"
    out.parent.mkdir()
    shutil.copy(SAMPLES / "files" / "sample-house.hpbake", out)
    refusing(monkeypatch, 60)
    monkeypatch.setattr(F, "FINAL_PATIENCE", 0.1)
    with pytest.raises(PermissionError) as e:
        F.send_reply(box, manifest, job, [out], text="Baked")
    monkeypatch.undo()
    assert e.value.reply and (box / "tools" / job["from"] / "inbox" / e.value.reply / "job.json").is_file()
    assert F.write_status(box, RENDER, JOB1, "done", text=e.value.text, reply=e.value.reply)
    assert F.read_status(box, RENDER, JOB1)["reply"] == e.value.reply


def _run_stand_in(root, job_seconds, hold):
    """the stand-in's bake() in this process while `hold` runs beside it; returns (state, its lines)"""
    from tools.standin import bake, manifest
    me = manifest("nl.fresing.trial.receiver")
    F.ensure_folder(root)
    F.write_manifest(root, me)
    F.write_manifest(root, json.loads((SAMPLES / "Toolbox" / "tools" / PLANNER / "toolbox.json").read_text("utf-8")))
    job = F.send(root, PLANNER, me["id"], "bake-house", [SCENE], ret="import-bake")
    folder = root / "tools" / me["id"] / "inbox" / job
    lines, stop = [], threading.Event()
    t = threading.Thread(target=hold, args=(folder / "status.json", stop), daemon=True)
    t.start()
    try:
        state = bake(root, me, folder, job_seconds, lines.append)
    finally:
        stop.set()
        t.join()
    return state, job, me["id"], lines


def test_w3_the_stand_in_bakes_on_while_its_status_is_refused(tmp_path, monkeypatch):
    """simulated on every system: every status write refused for the first 1.5 s (working), then from 1.9 s for
    3.6 s, longer than write_status waits for "done" (2 s): the stand-in writes it again at its next look"""
    root = tmp_path / "Toolbox"
    real, start, count = os.replace, time.monotonic(), [0]

    def replace(src, dst):
        if Path(dst).name == "status.json" and (time.monotonic() - start < 1.5 or 1.9 < time.monotonic() - start < 5.5):
            count[0] += 1
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst)

    monkeypatch.setattr(F.os, "replace", replace)
    monkeypatch.setattr("tools.standin.LOOK", 0.2)
    state, job, me, lines = _run_stand_in(root, 2, lambda path, stop: stop.wait())
    assert state == "done" and count[0] > 0, lines
    assert any("status done" in x and "trying again" in x for x in lines), lines
    st = F.read_status(root, me, job)
    assert st["state"] == "done" and st["reply"], st
    assert len(F.pending(root, PLANNER)) == 1                                    # the bake was sent once
    assert check(root).items == [], check(root).text()


def test_w3_the_stand_in_bakes_on_while_a_reader_holds_status_json_open(tmp_path):
    """a real reader: it opens status.json and holds it 0.5 s, again and again, while the stand-in bakes. On Windows
    every write in that time is refused; elsewhere none is. Either way the bake ends "done" and is sent back once."""
    root = tmp_path / "Toolbox"
    refused = [0]
    real = F.os.replace

    def counting(src, dst):
        try:
            return real(src, dst)
        except PermissionError:
            refused[0] += 1
            raise

    def hold(path, stop):
        while not stop.is_set():
            try:
                with open(path, "rb"):
                    stop.wait(0.5)
            except OSError:
                pass                                    # not there yet, or just being replaced
            stop.wait(0.05)

    F.os.replace = counting
    try:
        state, job, me, lines = _run_stand_in(root, 3, hold)
    finally:
        F.os.replace = real
    assert state == "done", lines
    st = F.read_status(root, me, job)
    assert st["state"] == "done" and st["reply"], st
    assert len(F.pending(root, PLANNER)) == 1
    if os.name == "nt":
        assert refused[0] > 0, "Windows refused no write while status.json was held open"


def test_claim_on_windows_a_folder_named_status_json_is_not_a_crash(box, monkeypatch):
    """found by the tests' first run on Windows (round 2): there open(..., "xb") on a folder gives PermissionError,
    not FileExistsError. Simulated here; tests/test_web.py ("review texts") meets the real one on Windows."""
    import builtins
    folder = fresh(box)
    (folder / "status.json").mkdir()
    real = builtins.open

    def windows_open(file, mode="r", *a, **k):
        if Path(file).name == "status.json" and "x" in mode and Path(file).exists():
            raise PermissionError(13, "Permission denied", str(file))
        return real(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", windows_open)
    assert F.claim(box, RENDER, JOB1, "working") is False
