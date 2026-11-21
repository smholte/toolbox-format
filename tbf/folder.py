"""Reference code for a native tool: find the Toolbox folder, send a job, read the inbox, answer (FORMAT.md
sections 2, 6 and 7). Plain Python, no Blender. A tool may copy this file together with names.py and detect.py.

    root = toolbox_home(); ensure_folder(root); write_manifest(root, MY_MANIFEST)
    for folder in pending(root, MY_ID):                       # every 2 seconds
        try:
            job, files = take(root, MY_MANIFEST, folder)      # checked: names, sizes, types by content
        except JobProblem as p:
            refuse(root, MY_ID, folder.name, p)               # failed with its code, or cancelled (6.3)
            continue
        except FileNotFoundError:
            continue                                          # cannot be read right now: next look
        if not claim(root, MY_ID, job["job"], "working", fraction=0.0, text="Starting"):
            continue                                          # another copy of this tool took it
        ...                                                   # the action; write_status() as it goes
        send_reply(root, MY_MANIFEST, job, [result_path])     # writes the reply job, then the status "done"
    for folder, status in unfinished(root, MY_ID):            # jobs nobody has updated for 5 minutes (6.3)
        if take_up(root, MY_ID, folder.name, "working"): ...  # or "failed" to end it
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from .check import FINAL, FOLDER_FILE, JUNCTION, Report, check_manifest, look, parse_doc, read_doc
from .detect import detect, load_types
from .names import TAKE_UP_LOCK, VERSION, capitals, is_job_id, is_tool_id, name_problem

DAY = 24 * 3600
ALIVE_FRESH = 30          # seconds: an alive.json older than this means "not watching"
MAX_SIZE = 2**53 - 1      # bytes: no file is larger; JavaScript cannot count further


class JobProblem(Exception):
    """a job this tool must not do; ``code`` and ``text`` go into status.json. ``state`` is "failed", or
    "cancelled" for a job its sender cancelled before it was taken (code "cancelled"); refuse() writes either."""

    def __init__(self, code: str, text: str):
        super().__init__(text)
        self.code, self.text = code, one_line(text)
        self.state = "cancelled" if code == "cancelled" else "failed"


# ---------------------------------------------------------------- the folder
def toolbox_home() -> Path:
    env = os.environ.get("TOOLBOX_HOME")
    return Path(env) if env else Path.home() / "Toolbox"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


STALLED = 5 * 60          # seconds a "working" status is believed after its last update (6.4)


def _bytes(doc: dict) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, doc: dict, patience: float = 0.25):
    """Whole or not at all: written beside the file, then moved over it. Windows refuses the move while another
    program has the file open (a reader holds it up to about half a second), so it is tried again for ``patience``
    seconds; after that the PermissionError is the caller's to catch, and the write is done again at its next look
    (FORMAT.md section 2)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")   # its own: copies write at once
    tmp.write_bytes(_bytes(doc))
    end = time.monotonic() + patience
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= end:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise


def is_link(p: Path) -> bool:
    """a link, or on Windows a junction: never read as a job, never followed when cleaning up. Python 3.11 has
    no os.path.isjunction (Blender 5.2 runs Python 3.13, which has it; 3.11 stays supported); the reparse tag of
    os.lstat tells it there."""
    if p.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(p):
        return True
    try:
        return getattr(os.lstat(p), "st_reparse_tag", 0) == JUNCTION
    except (OSError, ValueError):
        return False


def ensure_folder(root: Path):
    """make the Toolbox folder, or mark it as one of this version (only a native tool does this, section 2)"""
    (root / "tools").mkdir(parents=True, exist_ok=True)
    marker = read_doc(root / FOLDER_FILE, "folder-0", Report(""), FOLDER_FILE, strict=False) \
        if (root / FOLDER_FILE).is_file() else None
    if marker is None:                          # missing, broken, or of another version: until 1.0 all tools move on
        write_json(root / FOLDER_FILE, {"format": "toolbox-folder", "version": VERSION})


def write_manifest(root: Path, manifest: dict):
    d = root / "tools" / manifest["id"]
    (d / "inbox").mkdir(parents=True, exist_ok=True)
    write_json(d / "toolbox.json", manifest)


def read_tool(root: Path, tool_id: str) -> dict | None:
    """another tool's manifest, or None when it is missing, broken or of another version"""
    path = root / "tools" / tool_id / "toolbox.json"
    if not is_tool_id(tool_id) or not path.is_file():
        return None
    return check_manifest(path, Report(tool_id), load_types(), folder=tool_id, strict=False)


def all_types(root: Path) -> list[dict]:
    """the built-in types followed by every tool's own, as section 5.3 orders them"""
    own: dict[str, dict] = {}
    clash = set()
    tools = root / "tools"
    for d in sorted(tools.iterdir()) if tools.is_dir() else []:
        for t in (read_tool(root, d.name) or {}).get("types", []):
            if t["id"] in own and own[t["id"]] != t:
                clash.add(t["id"])
            own.setdefault(t["id"], t)
    return load_types() + [own[k] for k in sorted(own) if k not in clash]


def is_alive(root: Path, tool_id: str) -> bool:
    doc = read_doc(root / "tools" / tool_id / "alive.json", "alive-0", Report(""), "alive.json", strict=False) \
        if (root / "tools" / tool_id / "alive.json").is_file() else None
    try:
        seen = datetime.fromisoformat(doc["seen"].replace("Z", "+00:00"))
        return abs((datetime.now().astimezone() - seen).total_seconds()) <= ALIVE_FRESH
    except (TypeError, ValueError, KeyError):
        return False


def write_alive(root: Path, me: str, app_version: str | None = None):
    doc = {"format": "toolbox-alive", "version": VERSION, "seen": now()}
    if app_version:
        doc["app_version"] = app_version
    write_json(root / "tools" / me / "alive.json", doc)


def remove_alive(root: Path, me: str):
    """For a tool that runs as one copy only, when it closes (6.4). A tool that may run as several copies leaves
    alive.json: one copy cannot know whether another still runs; the file is old after 30 seconds anyway."""
    (root / "tools" / me / "alive.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- sending
def send(root: Path, sender: str, to: str, action: str, files: list[Path], ret: str | None = None,
         title: str | None = None, options: dict | None = None, reply_to: dict | None = None) -> str:
    """Write a job into ``to``'s inbox (section 6.2) and return its id. Raises ValueError when the receiver does
    not take it – nothing is written then."""
    tool = read_tool(root, to)
    if tool is None:
        raise ValueError(f"{to} has no readable manifest in the Toolbox folder")
    act = next((a for a in tool["actions"] if a["id"] == action), None)
    if act is None:
        raise ValueError(f"{to} has no action {action}")
    types = all_types(root)
    listed, seen = [], set()
    for f in files:
        name = unicodedata.normalize("NFC", f.name)    # names are NFC (3.3); a Mac may give é as e and an accent
        why = name_problem(name) or ("is there twice (capitals do not count)" if capitals(name) in seen else None)
        if why:
            raise ValueError(f"the file name {name!r} {why}")
        seen.add(capitals(name))
        kind, _ = detect(f, types, name=name)
        if kind not in act["accepts"]:
            raise ValueError(f"{to} does not accept {kind} for {action} ({name})")
        listed.append({"name": name, "type": kind, "size": f.stat().st_size})
    job = new_job_id()
    folder = root / "tools" / to / "inbox" / job
    folder.mkdir(parents=True)                  # also makes the inbox when the receiver has none yet (6.2)
    for f, item in zip(files, listed):
        shutil.copyfile(f, folder / item["name"])
    doc = {"format": "toolbox-job", "version": VERSION, "job": job, "created": now(), "from": sender, "to": to,
           "action": action, "files": listed}
    title = title[:120] if title else None             # at most 120 characters (6.1), as JavaScript shortens it
    for key, value in (("return", ret), ("reply_to", reply_to), ("title", title), ("options", options)):
        if value is not None:
            doc[key] = value
    write_json(folder / "job.json", doc)            # last: only now the job exists for the receiver
    return job


def read_status(root: Path, to: str, job: str) -> dict | None:
    """the status of a job this tool sent; None when there is none yet or the job is gone"""
    path = root / "tools" / to / "inbox" / job / "status.json"
    return read_doc(path, "status-0", Report(""), "status.json", strict=False) if path.is_file() else None


def cancel(root: Path, to: str, job: str):
    folder = root / "tools" / to / "inbox" / job
    if folder.is_dir():
        write_json(folder / "cancel.json", {"format": "toolbox-cancel", "version": VERSION, "job": job, "asked": now()})


# ---------------------------------------------------------------- receiving
def pending(root: Path, me: str) -> list[Path]:
    """the job folders of my inbox that have a job.json and no status.json yet, oldest first"""
    inbox = root / "tools" / me / "inbox"
    if not inbox.is_dir():
        return []
    found = [d for d in inbox.iterdir() if d.is_dir() and not is_link(d) and is_job_id(d.name)
             and (d / "job.json").is_file() and not (d / "status.json").exists()]
    return sorted(found, key=lambda d: d.name)


def one_line(text: str) -> str:
    """text a status may hold (7.1, 3.4): a control character (line break, tab …) becomes a space, an unpaired
    U+D800–U+DFFF becomes U+FFFD, and it is cut to 200 characters – so an error message cannot make the status
    unreadable"""
    return "".join(" " if ord(c) < 32 or ord(c) == 127 else "\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c
                   for c in text)[:200]


def _status_doc(job: str, state: str, fraction=None, text=None, code=None, reply=None) -> dict:
    """a status.json; a failed job always has a code (7.1): "error" when none is given"""
    if state == "failed" and code is None:
        code = "error"
    doc = {"format": "toolbox-status", "version": VERSION, "job": job, "state": state, "updated": now()}
    for key, value in (("fraction", fraction), ("text", text and one_line(text)), ("code", code), ("reply", reply)):
        if value is not None:
            doc[key] = value
    return doc


def _read_own_status(root: Path, me: str, job: str) -> dict | None:
    path = root / "tools" / me / "inbox" / job / "status.json"
    return read_doc(path, "status-0", Report(""), "", strict=False) if path.is_file() else None


def is_left(status: dict | None, at: datetime | None = None) -> bool:
    """True when a waiting or working status has not been updated for 5 minutes: nobody holds the job any more, and
    a copy of the receiving tool may take it up (6.3). A copy that keeps a job writes its status at least every 2
    minutes when it is free to."""
    if not status or status.get("state") not in ("waiting", "working"):
        return False
    try:
        seen = datetime.fromisoformat(status["updated"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return True
    return ((at or datetime.now().astimezone()) - seen).total_seconds() > STALLED


def unfinished(root: Path, me: str, at: datetime | None = None) -> list[tuple[Path, dict]]:
    """Jobs left behind: those of my inbox whose status is waiting or working and has not been updated for 5
    minutes, as (folder, status) – a run that closed or crashed, never a job another running copy holds. Take each
    up with take_up(): waiting – ask again or start; working – start again, or end it as failed (6.3)."""
    inbox = root / "tools" / me / "inbox"
    out = []
    for d in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if d.is_dir() and not is_link(d) and is_job_id(d.name) and (d / "status.json").is_file():
            st = read_doc(d / "status.json", "status-0", Report(""), "", strict=False)
            if is_left(st, at):
                out.append((d, st))
    return out


def claim(root: Path, me: str, job: str, state: str = "waiting", **more) -> bool:
    """Take a job: create its status.json only if it is not there yet. False when another copy of this tool was
    first (6.3). ``more``: fraction, text, code as for write_status."""
    data = _bytes(_status_doc(job, state, **more))      # made before the file: nothing half-made is left
    try:
        with open(root / "tools" / me / "inbox" / job / "status.json", "xb") as fh:
            fh.write(data)
        return True
    except FileExistsError:
        return False


def refuse(root: Path, me: str, job: str, problem: JobProblem) -> bool:
    """write the status a job take() refused gets: failed with the problem's code, or cancelled (6.3); only when
    the job has no status yet. False when another copy of this tool was first."""
    if problem.state == "cancelled":
        return claim(root, me, job, "cancelled", text=problem.text)
    return claim(root, me, job, "failed", code=problem.code, text=problem.text)


TAKE_UP_LOCK_STALE = 60       # seconds: a lock this old was left by a copy that crashed


def take_up(root: Path, me: str, job: str, state: str, at: datetime | None = None, **more) -> bool:
    """Take up a job left behind (6.3): only when its status is still waiting or working and still 5 minutes old.
    Of several copies that try at once only one may win: the copy that creates the lock file .taking-up (an
    exclusive create) reads the status once more, and only when it is still the one it read writes the new status
    over it (whole, as always), then deletes the lock. status.json is never missing meanwhile. A lock older than a
    minute was left by a crash and is deleted. False when the job is not left, another copy is taking it up, or a
    file cannot be written right now (try again at the next look)."""
    folder = root / "tools" / me / "inbox" / job
    path, lock = folder / "status.json", folder / TAKE_UP_LOCK
    try:
        seen = path.read_bytes()
    except OSError:
        return False
    if not is_left(parse_doc(seen, "status-0", Report(""), "", strict=False), at):
        return False
    doc = _status_doc(job, state, **more)
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        try:
            if time.time() - lock.stat().st_mtime > TAKE_UP_LOCK_STALE:
                lock.unlink()                   # left by a crash; taken up at the next look
        except OSError:
            pass
        return False
    except OSError:
        return False
    try:
        if path.read_bytes() != seen:           # another copy took it up, or its holder came back
            return False
        write_json(path, doc)
        return True
    except OSError:
        return False
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def is_stalled(status: dict | None, at: datetime | None = None) -> bool:
    """True when a working status has not been updated for 5 minutes: only then a sender may say that nothing has
    been heard (6.4). A busy tool cannot write, so a fresh "working" is believed whatever alive.json says."""
    if not status or status.get("state") != "working":
        return False
    try:
        seen = datetime.fromisoformat(status["updated"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return True
    return ((at or datetime.now().astimezone()) - seen).total_seconds() > STALLED


def take(root: Path, manifest: dict, folder: Path) -> tuple[dict, list[tuple[str, str, Path]]]:
    """Check a job of my inbox as section 6.3 says. Returns the job and its files as (name, type, path).
    Raises JobProblem (give it to refuse()): code "cancelled" when the sender cancelled before the job was taken,
    else the code of a failed status. Raises FileNotFoundError when job.json or a file cannot be read right now
    (another program holds it): try again at the next look (section 2)."""
    try:
        data = (folder / "job.json").read_bytes()
    except OSError as e:
        raise FileNotFoundError(f"job.json cannot be read right now ({e.strerror or e})") from None
    if (folder / "cancel.json").is_file():      # 6.3 step 2: before job.json is even read
        raise JobProblem("cancelled", "Cancelled by the sender before it was taken")
    rep = Report("")
    job = parse_doc(data, "job-0", rep, "job.json", strict=False)
    if job is None:
        raise JobProblem("bad-job", rep.errors[0] if rep.errors else "job.json cannot be read")
    if job["job"] != folder.name or job["to"] != manifest["id"] or job["from"] == job["to"]:
        raise JobProblem("bad-job", "the job is not for this tool, or its id is not its folder's name")
    if "reply_to" in job and (job["reply_to"]["tool"] != job["from"] or "return" in job):
        raise JobProblem("bad-job", "a reply comes from the tool that did the job and asks for no reply itself")
    action = next((a for a in manifest["actions"] if a["id"] == job["action"]), None)
    if action is None:
        raise JobProblem("unknown-action", f"{manifest['name']} has no action {job['action']}")
    types, out, seen = all_types(root), [], set()
    for f in job["files"]:
        why = name_problem(f["name"])
        if why or capitals(f["name"]) in seen:
            raise JobProblem("bad-job", f"the file name {f['name']!r} {why or 'is listed twice'}")
        seen.add(capitals(f["name"]))
        if f["size"] > MAX_SIZE:
            raise JobProblem("bad-job", f"{f['name']}: no file has {f['size']} bytes")
        p = folder / f["name"]
        kind, size = look(p)
        if kind == "bad-name":
            raise JobProblem("bad-job", f"the file name {f['name']!r} cannot be used on this system")
        if kind in ("link", "not-file"):
            raise JobProblem("bad-job", f"{f['name']} is not a plain file")
        if kind == "unreadable":
            raise FileNotFoundError(f"{f['name']} cannot be read right now ({size})")
        if kind == "missing":                   # job.json is written last, so a file that is not there never comes
            raise JobProblem("bad-job", f"{f['name']} is missing")
        if size != f["size"]:
            raise JobProblem("bad-job", f"{f['name']} is {size} bytes, job.json says {f['size']}")
        try:
            kind, _ = detect(p, types)
        except OSError as e:
            raise FileNotFoundError(f"{f['name']} cannot be read right now ({e.strerror or e})") from None
        if kind != f["type"]:
            raise JobProblem("wrong-type", f"{f['name']} is {kind}, not {f['type']}")
        if kind not in action["accepts"]:
            raise JobProblem("wrong-type", f"{action['label']} does not accept {kind} ({f['name']})")
        out.append((f["name"], kind, p))
    return job, out


FINAL_PATIENCE = 2.0          # seconds a final status keeps trying: about 4x the longest refusal measured on Windows


def write_status(root: Path, me: str, job: str, state: str, fraction: float | None = None, text: str | None = None,
                 code: str | None = None, reply: str | None = None) -> bool:
    """Write the status of a job of my inbox (7.1). A final status (done, failed, cancelled) is never written over:
    the status is read just before, and False returned when it is final already.
    Windows refuses the write while another program reads status.json (section 2). A status that is not final
    (waiting, working) is then not written now: False, and the next update writes it – a job never stops for it.
    A final status keeps trying for 2 seconds, then raises PermissionError: write it again at the next look."""
    old = _read_own_status(root, me, job)
    if old is not None and old["state"] in FINAL:
        return False
    path = root / "tools" / me / "inbox" / job / "status.json"
    doc = _status_doc(job, state, fraction=fraction, text=text, code=code, reply=reply)
    if state in FINAL:
        write_json(path, doc, patience=FINAL_PATIENCE)
        return True
    try:
        write_json(path, doc)
    except PermissionError:
        return False
    return True


def wants_cancel(root: Path, me: str, job: str) -> bool:
    return (root / "tools" / me / "inbox" / job / "cancel.json").is_file()


def send_reply(root: Path, manifest: dict, job: dict, files: list[Path], text: str | None = None) -> str | None:
    """Section 7.2: send the result back as a job when the first job asked for it and the sender can take it, then
    write the first job's status "done". Returns the reply job's id, or None when the result stays here.
    When the status "done" cannot be written right now (Windows refuses, see write_status), the PermissionError
    carries the reply's id as ``.reply`` and ``.text``: write the status again with them; never send twice."""
    me, reply = manifest["id"], None
    if "return" in job and files and (root / "tools" / job["from"]).is_dir():
        try:
            reply = send(root, me, job["from"], job["return"], files, title=job.get("title"),
                         reply_to={"tool": me, "job": job["job"]})
        except ValueError as e:
            text = f"Done, but the result could not be sent back: {e}"
    try:
        write_status(root, me, job["job"], "done", text=text, reply=reply)   # not over a final status (cancelled)
    except PermissionError as e:
        e.reply, e.text = reply, text
        raise
    return reply


def _seconds_since(at: float, time_text: str) -> float:
    return (datetime.fromtimestamp(at).astimezone()
            - datetime.fromisoformat(time_text.replace("Z", "+00:00"))) / timedelta(seconds=1)


def job_age(folder: Path, at: float) -> tuple[float | None, bool]:
    """(seconds, final) for cleaning up (7.4): a final job by its status's updated; any other by its job.json's
    created; a folder whose job.json is missing or cannot be read by its newest file; None for a folder without
    files (it may be a job a sender is writing right now). The folder's own date is not used: a page cannot read
    it. Raises OSError when a file cannot be read right now (another program holds it): next look."""

    def doc(name, schema):                      # None when missing or broken; OSError when held open (next look)
        path = folder / name
        return parse_doc(path.read_bytes(), schema, Report(""), name, strict=False) if path.is_file() else None

    status = doc("status.json", "status-0")
    if status is not None and status["state"] in FINAL:
        return _seconds_since(at, status["updated"]), True
    job = doc("job.json", "job-0")
    if job is not None:
        return _seconds_since(at, job["created"]), False
    newest = None
    for f in folder.iterdir():
        if f.is_file() and not is_link(f):
            newest = max(newest or 0.0, f.stat().st_mtime)
    return (None if newest is None else at - newest), False


def clean(root: Path, me: str, at: float | None = None):
    """Section 7.4 for my own inbox: finished jobs a day after their final status, any job 30 days after it was
    created. A delete Windows refuses now is done at a later look."""
    at = time.time() if at is None else at
    inbox = root / "tools" / me / "inbox"
    for d in list(inbox.iterdir()) if inbox.is_dir() else []:
        if not d.is_dir() or is_link(d) or not is_job_id(d.name):   # only real job folders; a link is never followed
            continue
        try:
            age, final = job_age(d, at)
        except OSError:
            continue
        if age is not None and (age > 30 * DAY or (final and age > DAY)):
            shutil.rmtree(d, ignore_errors=True)


def remove_job(root: Path, tool: str, job: str):
    """delete a job folder (a reply I took in; a job I sent whose final status I have read)"""
    folder = root / "tools" / tool / "inbox" / job
    if is_tool_id(tool) and is_job_id(job) and not is_link(folder):
        shutil.rmtree(folder, ignore_errors=True)       # what Windows will not let go now goes at the next look
