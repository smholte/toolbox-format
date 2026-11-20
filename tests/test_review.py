"""What the first independent review (task 0001 of github.com/smholte/ToolBox) found in the Python side: crashes,
wrong verdicts and places where Python said something else than JavaScript. Each test failed before its fix.
The JavaScript side of the same findings is in tests/test_web.py ("found by the review")."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import threading
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tbf import folder as F  # noqa: E402
from tbf.check import check  # noqa: E402
from tbf.detect import detect, load_types, pattern_problem  # noqa: E402
from tbf.names import JsonError, load_json  # noqa: E402

SAMPLES = ROOT / "samples"
RENDER, PLANNER = "nl.fresing.render", "nl.fresing.house-planner"
JOB1 = "20261118-195100-9f3c2a"


@pytest.fixture
def box(tmp_path):
    shutil.copytree(SAMPLES / "Toolbox", tmp_path / "Toolbox")
    return tmp_path / "Toolbox"


def job_folder(box, tool=RENDER, j=JOB1):
    return box / "tools" / tool / "inbox" / j


def fresh_job(box) -> Path:
    """the sample job of Fresing Render's inbox without its status: a job not taken yet"""
    folder = job_folder(box)
    (folder / "status.json").unlink()
    return folder


def with_options(folder: Path, raw: bytes):
    """put raw JSON text into the job's options"""
    text = (folder / "job.json").read_bytes().rstrip()
    assert text.endswith(b"}")
    (folder / "job.json").write_bytes(text[:-1] + b', "options": ' + raw + b"}")


def take(box, folder):
    try:
        F.take(box, F.read_tool(box, RENDER), folder)
        return "ok"
    except F.JobProblem as p:
        return p.code
    except FileNotFoundError:
        return "not-complete"


def zipped(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return buf.getvalue()


DEEP = b'{"a":' * 3000 + b"1" + b"}" * 3000
BIG_INT = b"1" + b"0" * 5000


# ---------------------------------------------------------------- JSON at its limits
def test_deeply_nested_json_is_no_crash(box):
    """Python 3.11 refuses 3000 levels, 3.12 and JavaScript read them; since 0.2 the format allows 64 (3.4), so
    both refuse. A crash is never fine."""
    try:
        load_json(b'{"x":' + DEEP + b"}")
    except JsonError:
        pass
    folder = fresh_job(box)
    with_options(folder, DEEP)
    assert not check(box).ok                    # was: RecursionError (Python 3.12 and newer)
    assert take(box, folder) == "bad-job"


def test_a_number_with_thousands_of_digits_is_read_as_javascript_reads_it(box):
    assert load_json(b'{"n": ' + BIG_INT + b"}")["n"] == float("inf")      # was: ValueError (int digits limit)
    folder = fresh_job(box)
    with_options(folder, b'{"n": ' + BIG_INT + b"}")
    assert check(box).ok and take(box, folder) == "ok"


@pytest.mark.parametrize("raw", [b'{"t": "\\ud800"}', b'{"t": "a\\udc00"}', b'{"\\ud83c": 1}'])
def test_text_that_cannot_be_utf8_is_refused(raw):
    with pytest.raises(JsonError, match="UTF-8"):
        load_json(raw)


def test_an_escaped_surrogate_pair_is_fine():
    assert load_json(b'{"t": "\\ud83c\\udfe0"}')["t"] == "\U0001f3e0"


def test_a_title_that_cannot_be_written_back_never_reaches_the_reply(box, tmp_path):
    """the receiver copies title into the reply job; a lone surrogate there made json.dumps(...).encode() fail"""
    folder = fresh_job(box)
    doc = json.loads((folder / "job.json").read_text("utf-8"))
    doc["title"] = "\ud800 house"
    (folder / "job.json").write_text(json.dumps(doc), "utf-8")      # json.dumps escapes it: valid JSON syntax
    assert take(box, folder) == "bad-job"
    assert not check(box).ok


def test_a_file_name_with_a_lone_surrogate_is_refused(box):
    folder = fresh_job(box)
    doc = json.loads((folder / "job.json").read_text("utf-8"))
    doc["files"][0]["name"] = "\ud800.hpscene"
    (folder / "job.json").write_text(json.dumps(doc), "utf-8")
    assert take(box, folder) == "bad-job"        # was: "not complete" for ever (and JavaScript read another file)


def test_a_duplicate_key_is_refused_by_the_checker_but_read_like_javascript_reads_it(box):
    """3.4: no key twice is a rule for the writer, which the checker checks; a reader need not notice. JavaScript
    cannot notice (JSON.parse keeps the last), so the reference reader in Python does the same."""
    folder = fresh_job(box)
    text = (folder / "job.json").read_bytes().rstrip()
    (folder / "job.json").write_bytes(text[:-1] + b', "title": "first", "title": "second"}')
    assert not check(box).ok
    assert take(box, folder) == "ok"
    assert F.take(box, F.read_tool(box, RENDER), folder)[0]["title"] == "second"


# ---------------------------------------------------------------- times
def test_a_date_that_does_not_exist_is_refused_by_the_reader_too(box):
    folder = fresh_job(box)
    doc = json.loads((folder / "job.json").read_text("utf-8"))
    doc["created"] = "2026-02-30T10:00:00+01:00"
    (folder / "job.json").write_text(json.dumps(doc), "utf-8")
    assert take(box, folder) == "bad-job"        # was: taken (JavaScript refused it)


@pytest.mark.parametrize("updated", ["2026-02-30T20:31:02+01:00", "٢٠٢٦-11-18T20:31:02+01:00"])
def test_a_status_with_a_time_that_is_not_one_is_not_believed(box, updated):
    folder = job_folder(box)
    doc = json.loads((folder / "status.json").read_text("utf-8"))
    doc["updated"] = updated
    (folder / "status.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
    assert F.read_status(box, RENDER, JOB1) is None       # was: read as "working" (JavaScript: not readable)


# ---------------------------------------------------------------- patterns and zips
@pytest.mark.parametrize("pattern", ["a{4294967295}", "a{1,99999999999}", "a{99999999999999999999}"])
def test_a_count_python_cannot_hold_is_refused_not_a_crash(pattern):
    assert pattern_problem(pattern)               # was: OverflowError


@pytest.mark.parametrize("pattern", [r"[\s-z]", r"[a-\d]", r"[\d-\w]", r"[\w-a]"])
def test_a_range_that_starts_or_ends_at_a_class_is_refused_with_a_plain_message(pattern):
    assert "range" in pattern_problem(pattern)


def test_patterns_near_those_are_still_fine():
    for p in ["a{4294967294}", r"[\w-]", r"[-\w]", r"[a-z-\w]", r"[\d\s-]"]:
        assert pattern_problem(p) is None, p


def test_a_house_scene_whose_json_is_deep_or_has_a_huge_number_is_no_crash(tmp_path):
    types = load_types()
    deep = tmp_path / "deep.hpscene"
    deep.write_bytes(zipped("scene.json", b'{"format":"house-scene","d":' + DEEP + b"}"))
    assert detect(deep, types)[0] in ("hpscene", "ext:hpscene")      # was: RecursionError
    big = tmp_path / "big.hpscene"
    big.write_bytes(zipped("scene.json", b'{"format":"house-scene","n":' + BIG_INT + b"}"))
    assert detect(big, types)[0] == "hpscene"               # was: ValueError; JavaScript reads it


def test_a_house_scene_with_its_format_key_twice_is_read_as_javascript_reads_it(tmp_path):
    p = tmp_path / "twice.hpscene"
    p.write_bytes(zipped("scene.json", b'{"format":"x","format":"house-scene"}'))
    assert detect(p, load_types())[0] == "hpscene"          # was: ext:hpscene (JavaScript: hpscene)


# ---------------------------------------------------------------- reading a job
def test_a_job_json_that_cannot_be_read_right_now_is_not_a_bad_job(box, monkeypatch):
    """section 2: a file another program holds open is "not there yet", never an error"""
    folder = fresh_job(box)
    real = Path.read_bytes

    def held(self):
        if self.name == "job.json":
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", held)
    assert take(box, folder) == "not-complete"   # was: bad-job, a final "failed" for a job that was fine


def test_a_file_name_this_system_cannot_hold_is_a_bad_job_not_a_crash(box):
    folder = fresh_job(box)
    doc = json.loads((folder / "job.json").read_text("utf-8"))
    doc["files"][0]["name"] = "\U0001f3e0" * 70 + ".hpscene"  # 288 bytes in UTF-8: too long for ext4 and APFS
    (folder / "job.json").write_text(json.dumps(doc), "utf-8")
    assert take(box, folder) == "bad-job"        # was: OSError (File name too long); now the name rule says so (P3)
    rep = check(box)
    assert any("longer than 255 bytes" in e for e in rep.errors), rep.text()
    assert not any(e.startswith("cannot be read") for e in rep.errors)   # the rest of the folder is still checked


# ---------------------------------------------------------------- sending
def test_send_refuses_two_files_whose_names_differ_only_in_capitals(box, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    shutil.copy(SAMPLES / "files" / "sample-house.hpscene", a / "house.hpscene")
    shutil.copy(SAMPLES / "files" / "sample-house.hpscene", b / "HOUSE.hpscene")
    with pytest.raises(ValueError, match="twice"):
        F.send(box, PLANNER, RENDER, "bake-house", [a / "house.hpscene", b / "HOUSE.hpscene"])
    assert sorted(p.name for p in (box / "tools" / RENDER / "inbox").iterdir()) == sorted(
        p.name for p in (SAMPLES / "Toolbox" / "tools" / RENDER / "inbox").iterdir())     # nothing written


def test_send_shortens_a_long_title_as_javascript_does(box):
    job = F.send(box, PLANNER, RENDER, "bake-house", [SAMPLES / "files" / "sample-house.hpscene"], title="\U0001f3e0" * 130)
    assert check(box).ok
    doc = json.loads((job_folder(box, j=job) / "job.json").read_text("utf-8"))
    assert doc["title"] == "\U0001f3e0" * 120


def test_two_copies_writing_the_same_file_at_once_do_not_crash(box):
    """alive.json is written by every copy of a tool; a shared temporary name made one copy's move fail"""
    errors = []

    def copy():
        try:
            for _ in range(300):
                F.write_alive(box, RENDER, "1.0")
        except Exception as e:                  # noqa: BLE001 – the test reports any of them
            errors.append(e)

    threads = [threading.Thread(target=copy) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:1]
    assert check(box).ok
    assert not [p.name for p in (box / "tools" / RENDER).iterdir() if p.name.endswith(".tmp")]


# ---------------------------------------------------------------- links and cleaning up
def test_a_junction_is_seen_without_os_path_isjunction(monkeypatch, tmp_path):
    """Python 3.11 (Blender's) has no os.path.isjunction; a junction is still told by its reparse tag"""
    d = tmp_path / "job"
    d.mkdir()
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    real = os.lstat

    class Junction:
        def __init__(self, st):
            self._st = st
            self.st_reparse_tag = 0xA0000003      # IO_REPARSE_TAG_MOUNT_POINT

        def __getattr__(self, name):
            return getattr(self._st, name)

    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: Junction(real(p, *a, **k)) if Path(p) == d else real(p, *a, **k))
    assert F.is_link(d)
    assert not F.is_link(tmp_path)


def test_cleaning_up_leaves_folders_that_are_not_jobs_alone(box):
    stray = box / "tools" / RENDER / "inbox" / "My notes"
    stray.mkdir()
    old = 1_000_000_000
    os.utime(stray, (old, old))
    F.clean(box, RENDER)
    assert stray.is_dir()                        # was: deleted (only job folders may go after 30 days)
