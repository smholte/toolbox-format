"""web/toolbox-folder.js in a real Chrome: what it writes passes the checker, it reads what Python writes, and it
names file types exactly as tbf/detect.py does. The Toolbox folder is a folder in the browser's private file
system – the same kind of handle the folder picker gives. Needs `playwright` and an installed Chrome."""
from __future__ import annotations

import base64
import functools
import http.server
import json
import random
import shutil
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tbf import folder as F  # noqa: E402
from tbf.check import check  # noqa: E402
from tbf.detect import detect, load_types, pattern_problem, rule_problems  # noqa: E402
from tbf.names import name_problem, time_problem  # noqa: E402

sync_api = pytest.importorskip("playwright.sync_api")
SAMPLES = ROOT / "samples"
RENDER, PLANNER = "nl.fresing.render", "nl.fresing.house-planner"
JOB1 = "20261118-195100-9f3c2a"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def page():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            exe = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
            if not exe:
                pytest.skip("no Chrome on this machine")
            browser = p.chromium.launch(executable_path=exe)
        pg = browser.new_context().new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://localhost:{server.server_address[1]}/tests/web_harness.html")
        assert pg.evaluate("typeof ToolboxFolder") == "object", errors
        yield pg
        browser.close()
    server.shutdown()
    assert not errors, errors


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def tree_of(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): b64(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}


def write_tree(tree: dict[str, str], folder: Path):
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for path, data in tree.items():
        p = folder / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64decode(data))


def manifests_only() -> dict[str, str]:
    """the sample folder with its two tools and no jobs"""
    return {k: v for k, v in tree_of(SAMPLES / "Toolbox").items() if "/inbox/" not in k and not k.endswith("alive.json")}


def dump_and_check(page, tmp_path, name="Toolbox") -> Path:
    out = tmp_path / name
    write_tree(page.evaluate("harness.dump()"), out)
    rep = check(out)
    assert rep.items == [], rep.text()
    return out


# ---------------------------------------------------------------- the copies agree
def test_types_in_the_js_file_are_types_json():
    js = (ROOT / "web" / "toolbox-folder.js").read_text("utf-8")
    block = js[js.index("/* TYPES-BEGIN */"):js.index("/* TYPES-END */")]
    listed = json.loads(block[block.index("["):block.rindex("]") + 1])
    assert listed == json.loads((ROOT / "types.json").read_text("utf-8"))["types"]


def test_version(page):
    assert page.evaluate("ToolboxFolder.VERSION") == F.VERSION


# ---------------------------------------------------------------- file types: JavaScript and Python say the same
def variants() -> list[tuple[str, bytes]]:
    rnd = random.Random(11)
    base = {p.name: p.read_bytes() for p in sorted((SAMPLES / "files").iterdir())}
    out = list(base.items())
    names = ["a.step", "a.STP", "a.ifc", "a.hpscene", "a.hpbake", "a.zip", "a.glb", "a.pdf", "a", "a.b.csv", ".step",
             "a.json", "a.unknownkind", "a.p21", "a.jpeg"]
    for data in base.values():
        for n in rnd.sample(names, 4):
            out.append((n, data))
    step = base["sample-part.step"]
    out += [("bom.step", b"\xef\xbb\xbf \r\n\t" + step), ("space.stp", b"\n\n" + step), ("hi.step", step.replace(b"made-up", b"\xe5\xff\x80\x1c")),
            ("ifc-late.step", step.replace(b"AUTOMOTIVE_DESIGN", b"IFC4X3")), ("empty.step", b""), ("empty", b""),
            ("pdf.pdf", b"%PDF-1.7\n"), ("pdf.txt", b" %PDF-1.7\n"), ("png.png", bytes.fromhex("89504e470d0a1a0a") + b"x"),
            ("jpg.jpg", b"\xff\xd8\xff\xe0"), ("empty.zip", b"PK\x05\x06" + b"\0" * 18), ("glb.step", base["sample-model.glb"])]
    import io
    import zipfile
    for comp, name, doc in ((zipfile.ZIP_DEFLATED, "scene.json", b'{"format":"house-scene"}'),
                            (zipfile.ZIP_STORED, "scene.json", b'{"format":"house-bake"}'),
                            (zipfile.ZIP_DEFLATED, "bake.json", b'{"format":"house-bake","x":"' + b"y" * 5000 + b'"}'),
                            (zipfile.ZIP_DEFLATED, "scene.json", b'{"format":"house-scene","format":"x"}'),
                            (zipfile.ZIP_DEFLATED, "scene.json", b'["house-scene"]'),
                            (zipfile.ZIP_DEFLATED, "scene.json", b'{"format":"house-scene","n":NaN}'),
                            (zipfile.ZIP_DEFLATED, "sub/scene.json", b'{"format":"house-scene"}'),
                            (zipfile.ZIP_DEFLATED, "scene.json", b'{"format":"house-scene","big":"' + b"z" * 2**20 + b'"}')):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", comp) as z:
            z.writestr("other.txt", b"x" * 100)
            z.writestr(name, doc)
        out.append((f"made-{len(out)}.hpscene", buf.getvalue()))
        out.append((f"made-{len(out)}.zip", buf.getvalue() + b"trailing"))
    for name, data in list(base.items()):                     # damaged copies
        for _ in range(150 if data[:2] == b"PK" else 25):
            b = bytearray(data)
            for _ in range(rnd.randint(1, 5)):
                if b:
                    b[rnd.randrange(len(b))] = rnd.randrange(256)
            if rnd.random() < 0.3:
                b = b[:rnd.randrange(len(b) + 1)]
            out.append((name, bytes(b)))
    return out


def test_detect_type_is_the_same_in_javascript_and_python(page, tmp_path):
    types = load_types()
    cases = variants()
    got = page.evaluate("""async cases => { const out = []; for (const [name, data] of cases) { const r = await ToolboxFolder.detectType(harness.file(name, data)); out.push([r.type, r.note]); } return out; }""",
                        [[n, b64(d)] for n, d in cases])
    differ = []
    for i, ((name, data), js) in enumerate(zip(cases, got)):
        p = tmp_path / f"{i}" / name
        p.parent.mkdir()
        p.write_bytes(data)
        py = list(detect(p, types))
        if py != js:
            differ.append((i, name, py, js))
    assert not differ, differ[:5]
    assert len({t for t, _ in got}) >= 9          # the cases really cover many types


def test_names_times_patterns_and_rules_are_judged_the_same(page):
    names = ["", "a/b", "a\\b", "..", ".hidden", "trailing.", "trailing ", " leading", "con", "COM1.step", "a:b", "what?.step",
             "x" * 81, "x" * 80, "tab\there", "job.json", "Status.JSON", "part.step", "Hus – versjon 3.hpscene",
             "a.b.c.tar.gz", "console.step", "\U0001f3e0" * 63, "\U0001f3e0" * 64, "nul", "lpt9.txt", "a|b", 'a"b', "a*"]
    times = ["2026-11-18T19:51:00+01:00", "2026-11-18T18:51:00Z", "2026-11-18T19:51:00.250+01:00", "2026-11-18 19:51:00",
             "2026-11-18T19:51:00", "2026-13-01T00:00:00Z", "2026-02-30T10:00:00+01:00", "2024-02-29T10:00:00Z",
             "2026-02-29T10:00:00Z", "2026-11-18T24:00:00Z", "2026-11-18T19:60:00Z", "2026-11-18T19:51:61Z",
             "2026-11-18T19:51:00+24:00", "2026-11-18T19:51:00+01:60", "0000-01-01T00:00:00Z", "2026-11-18T19:51:00.1Z"]
    patterns = ["^ISO", "end$", "(?i)step", "(?=x)", "a\\bz", "\\x41", "[abc", "[]", "x" * 201, "café", "a\\", "", "a.b",
                "a{,3}", "a{x}", "a*+", "a++", "a{2}+", "a**", "FILE_SCHEMA\\s*\\(\\s*\\(\\s*'IFC", "[^a-z]+\\d{2,4}", "a|b",
                "\\$\\^", "[$^.{]x", "a\\.b", "a{2}", "a{2,}?", "a+?b*?c??", "x}", "(a", "a)", "[^]", "a{2,1}", "+a", "a|*"]
    rules = [{}, {"starts_with": "A", "starts_with_hex": "41"}, {"magic": "A"}, {"starts_with": "two words"},
             {"starts_with_hex": "4G"}, {"starts_with_hex": "ABCD"}, {"all": []}, {"zip_has": {"file": "../x"}},
             {"zip_json": {"file": "a.json", "field": "format"}}, {"not": {"not": {"not": {"not": {"starts_with": "A"}}}}},
             {"not": {"any": [{"zip_has": {"file": "a/b.json"}}]}}, {"starts_with": "A"}, {"head_matches": "a.b"},
             {"all": [{"any": [{"not": {"starts_with": "A"}}]}]}, {"zip_has": {"file": "a", "x": "y"}}, [], "x", {"all": "x"}]
    js = page.evaluate("""([names, times, patterns, rules]) => [names.map(n => ToolboxFolder.nameProblem(n) === null),
        times.map(t => ToolboxFolder.timeProblem(t) === null), patterns.map(p => ToolboxFolder.patternProblem(p) === null),
        rules.map(r => ToolboxFolder.ruleProblem(r) === null)]""", [names, times, patterns, rules])
    assert js[0] == [name_problem(n) is None for n in names]
    assert js[1] == [time_problem(t) is None for t in times]
    assert js[2] == [pattern_problem(p) is None for p in patterns]
    assert js[3] == [rule_problems(r, "") == [] for r in rules]


# ---------------------------------------------------------------- a round trip, all in the browser
SEND = """async ([me, to, name, data]) => { const box = await harness.box(me);
  return box.send({ to, action: 'bake-house', files: [harness.file(name, data)], ret: 'import-bake', title: 'Sample house – version 3' }); }"""


def test_round_trip_in_the_browser(page, tmp_path):
    page.evaluate("t => harness.load(t)", manifests_only())
    scene = (SAMPLES / "files" / "sample-house.hpscene").read_bytes()
    bake = (SAMPLES / "files" / "sample-house.hpbake").read_bytes()
    job = page.evaluate(SEND, [PLANNER, RENDER, "sample-house.hpscene", b64(scene)])
    out = dump_and_check(page, tmp_path)
    assert json.loads((out / "tools" / RENDER / "inbox" / job / "job.json").read_text("utf-8"))["files"] == [
        {"name": "sample-house.hpscene", "type": "hpscene", "size": len(scene)}]
    assert page.evaluate("async ([me, to, job]) => (await (await harness.box(me)).status(to, job)).state", [PLANNER, RENDER, job]) == "sent"
    reply = page.evaluate("""async ([me, bake]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      await box.alive('0.0.0-test');
      const [id] = await box.pending(); const { job, files } = await box.take(m, id);
      await box.writeStatus(id, 'working', { fraction: 0.5, text: 'Halfway ' + files[0].type });
      return box.sendReply(job, [harness.file('sample-house.hpbake', bake)], 'Baked'); }""", [RENDER, b64(bake)])
    dump_and_check(page, tmp_path)
    st = page.evaluate("async ([me, to, job]) => { const box = await harness.box(me); return [await box.status(to, job), (await box.tool(to)).open]; }", [PLANNER, RENDER, job])
    assert st[0]["state"] == "done" and st[0]["reply"] == reply and st[1] is True
    got = page.evaluate("""async ([me, to, sent]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      const [id] = await box.pending(); const { job, files } = await box.take(m, id);
      const size = files[0].file.size; await box.remove(me, id); await box.remove(to, sent);
      return [job.action, job.reply_to.job, files[0].type, size, await box.pending(), await box.status(to, sent)]; }""", [PLANNER, RENDER, job])
    assert got == ["import-bake", job, "hpbake", len(bake), [], None]
    out = dump_and_check(page, tmp_path)
    assert not list(out.glob("tools/*/inbox/*"))


def test_cancel_and_a_job_that_is_refused_before_it_is_written(page, tmp_path):
    page.evaluate("t => harness.load(t)", manifests_only())
    scene = b64((SAMPLES / "files" / "sample-house.hpscene").read_bytes())
    job = page.evaluate(SEND, [PLANNER, RENDER, "sample-house.hpscene", scene])
    assert page.evaluate("""async ([me, to, job]) => { const a = await harness.box(me), b = await harness.box(to);
      const before = await b.wantsCancel(job); await a.cancel(to, job); return [before, await b.wantsCancel(job)]; }""", [PLANNER, RENDER, job]) == [False, True]
    dump_and_check(page, tmp_path)
    step = b64((SAMPLES / "files" / "sample-part.step").read_bytes())
    for args, code in (([PLANNER, RENDER, "part.hpscene", step], "wrong-type"), ([PLANNER, RENDER, "a/b.hpscene", scene], "bad-name"),
                       ([PLANNER, "com.example.nobody", "x.hpscene", scene], "no-tool")):
        r = page.evaluate(f"a => harness.tried(() => ({SEND})(a))", args)
        assert r.get("code") == code, r
    assert len(list(dump_and_check(page, tmp_path).glob("tools/*/inbox/*"))) == 1


# ---------------------------------------------------------------- the browser and Python hand over to each other
def test_browser_sends_python_answers_browser_takes_the_reply(page, tmp_path):
    page.evaluate("t => harness.load(t)", manifests_only())
    job = page.evaluate(SEND, [PLANNER, RENDER, "sample-house.hpscene", b64((SAMPLES / "files" / "sample-house.hpscene").read_bytes())])
    box = dump_and_check(page, tmp_path)
    me = F.read_tool(box, RENDER)
    (folder,) = F.pending(box, RENDER)
    doc, files = F.take(box, me, folder)
    assert doc["job"] == job and files[0][1] == "hpscene"
    reply = F.send_reply(box, me, doc, [SAMPLES / "files" / "sample-house.hpbake"], text="Baked")
    assert check(box).items == []
    page.evaluate("t => harness.load(t)", tree_of(box))
    got = page.evaluate("""async me => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      const [id] = await box.pending(); const { job, files } = await box.take(m, id); return [id, job.reply_to.job, files[0].type]; }""", PLANNER)
    assert got == [reply, job, "hpbake"]


def test_python_sends_browser_takes(page, tmp_path):
    box = tmp_path / "Toolbox"
    write_tree(manifests_only(), box)
    job = F.send(box, RENDER, PLANNER, "import-bake", [SAMPLES / "files" / "sample-house.hpbake"], title="From Python")
    page.evaluate("t => harness.load(t)", tree_of(box))
    got = page.evaluate("""async me => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      const [id] = await box.pending(); const { job, files } = await box.take(m, id); await box.writeStatus(id, 'done', { text: 'Imported' });
      return [id, job.title, files[0].type]; }""", PLANNER)
    assert got == [job, "From Python", "hpbake"]
    out = dump_and_check(page, tmp_path, "back")
    assert F.read_status(out, PLANNER, job)["state"] == "done"


BAD_JOBS = {
    "another version": lambda d: d.update(version="0.1"),
    "unknown field": lambda d: d.update(priority=1),
    "job is not the folder": lambda d: d.update(job="20261118-195100-000000"),
    "for another tool": lambda d: d.update(to="nl.fresing.other"),
    "unknown action": lambda d: d.update(action="polish"),
    "to itself": lambda d: d.update({"from": RENDER}),
    "bad time": lambda d: d.update(created="18 Nov 2026"),
    "no files": lambda d: d.update(files=[]),
    "file too large": lambda d: d["files"][0].update(size=5),
    "file too short": lambda d: d["files"][0].update(size=10**6),
    "wrong type": lambda d: d["files"][0].update(type="hpbake"),
    "type the action does not accept": lambda d: d.update(action="import-step"),
    "missing file": lambda d: d["files"][0].update(name="other.hpscene"),
    "path in a name": lambda d: d["files"][0].update(name="../sample-house.hpscene"),
    "listed twice": lambda d: d["files"].append(dict(d["files"][0], name="SAMPLE-HOUSE.hpscene")),
    "not json": None,
}


@pytest.mark.parametrize("name", BAD_JOBS)
def test_a_bad_job_gets_the_same_answer_from_javascript_and_python(page, tmp_path, name):
    box = tmp_path / "Toolbox"
    shutil.copytree(SAMPLES / "Toolbox", box)
    folder = box / "tools" / RENDER / "inbox" / JOB1
    (folder / "status.json").unlink()
    if BAD_JOBS[name] is None:
        (folder / "job.json").write_bytes(b"{")
    else:
        doc = json.loads((folder / "job.json").read_text("utf-8"))
        BAD_JOBS[name](doc)
        (folder / "job.json").write_text(json.dumps(doc), "utf-8")
    try:
        F.take(box, F.read_tool(box, RENDER), folder)
        py = "ok"
    except F.JobProblem as p:
        py = p.code
    except FileNotFoundError:
        py = "not-complete"
    page.evaluate("t => harness.load(t)", tree_of(box))
    r = page.evaluate("""async ([me, id]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      return harness.tried(() => box.take(m, id).then(() => 'ok')); }""", [RENDER, JOB1])
    js = r.get("code") or r.get("ok")
    assert py == js and py != "ok", (py, r)


# ---------------------------------------------------------------- the folder itself
def test_a_folder_that_is_not_the_toolbox_folder(page):
    page.evaluate("harness.load({'notes.txt': 'eA=='})")
    r = page.evaluate("harness.tried(async () => { await harness.box('nl.fresing.house-planner'); })")
    assert r.get("code") == "not-toolbox", r
    page.evaluate("t => harness.load(t)", {"toolbox-folder.json": b64(b'{"format":"toolbox-folder","version":"0.1"}')})
    r = page.evaluate("harness.tried(async () => { await harness.box('nl.fresing.house-planner'); })")
    assert r.get("code") == "version", r


def test_an_empty_folder_becomes_the_toolbox_folder_and_a_manifest_is_written(page, tmp_path):
    page.evaluate("harness.load({})")
    manifest = json.loads((SAMPLES / "Toolbox" / "tools" / PLANNER / "toolbox.json").read_text("utf-8"))
    page.evaluate("async m => { const box = await harness.box(m.id); await box.writeManifest(m); await box.alive(); await box.notAlive(); await box.notAlive(); }", manifest)
    out = dump_and_check(page, tmp_path)
    assert json.loads((out / "tools" / PLANNER / "toolbox.json").read_text("utf-8")) == manifest
    r = page.evaluate("m => harness.tried(async () => { const box = await harness.box(m.id); await box.writeManifest({ ...m, kind: 'native' }); })", manifest)
    assert r.get("code") == "json", r


def test_a_page_never_makes_the_folder(page):
    page.evaluate("harness.load({})")
    r = page.evaluate("harness.tried(async () => { await ToolboxFolder.open(await harness.root(), 'nl.fresing.house-planner'); })")
    assert r.get("code") == "not-toolbox" and "Fresing Render" in r["message"], r
    assert page.evaluate("harness.dump()") == {}
    # also not with create = true when the folder is not empty
    page.evaluate("harness.load({'notes.txt': 'eA=='})")
    r = page.evaluate("harness.tried(async () => { await ToolboxFolder.open(await harness.root(), 'nl.fresing.house-planner', true); })")
    assert r.get("code") == "not-toolbox", r


def test_a_web_tool_without_an_address_and_one_window_at_a_time(page, tmp_path):
    tree = manifests_only()
    key = f"tools/{PLANNER}/toolbox.json"
    doc = json.loads(base64.b64decode(tree[key]))
    del doc["url"]
    page.evaluate("t => harness.load(t)", {**tree, key: b64(json.dumps(doc).encode())})
    assert page.evaluate("async me => (await (await harness.box(me)).tool(me)).manifest.kind", PLANNER) == "web"
    got = page.evaluate("""async me => { const box = await harness.box(me); let inner;
      const outer = await box.exclusively(async () => { inner = await box.exclusively(async () => 'second'); return 'first'; });
      return [outer, inner === undefined, await box.exclusively(async () => 'free again')]; }""", PLANNER)
    assert got == ["first", True, "free again"]


def test_claim_leftovers_and_a_stalled_job(page, tmp_path):
    page.evaluate("t => harness.load(t)", manifests_only())
    scene = b64((SAMPLES / "files" / "sample-house.hpscene").read_bytes())
    a = page.evaluate(SEND, [PLANNER, RENDER, "sample-house.hpscene", scene])
    page.wait_for_timeout(1100)                                          # job ids carry the second
    b = page.evaluate(SEND, [PLANNER, RENDER, "sample-house.hpscene", scene])
    got = page.evaluate("""async ([me, a, b]) => { const box = await harness.box(me), later = Date.now() + 6 * 60000;
      const first = await box.claim(a, 'waiting', { text: 'Waiting for you' }), second = await box.claim(a, 'working');
      await box.claim(b, 'done');
      return [first, second, (await box.unfinished()).length, (await box.unfinished(later)).map(x => [x.id, x.status.state]), await box.pending()]; }""", [RENDER, a, b])
    assert got == [True, False, 0, [[a, "waiting"]], []]
    out = dump_and_check(page, tmp_path)
    from datetime import datetime, timedelta, timezone
    assert F.unfinished(out, RENDER) == []
    later = datetime.now().astimezone() + timedelta(minutes=6)
    assert [(f.name, st["state"]) for f, st in F.unfinished(out, RENDER, at=later)] == [(a, "waiting")]
    at = datetime(2026, 11, 18, 20, 0, 0, tzinfo=timezone.utc)
    cases = [{"state": s, "updated": (at - timedelta(seconds=ago)).isoformat(timespec="seconds")}
             for s in ("working", "waiting", "done") for ago in (0, 299, 301, 9999)] + [None, {"state": "working"}]
    js = page.evaluate("([cases, at]) => cases.map(c => ToolboxFolder.stalled(c, at))", [cases, int(at.timestamp() * 1000)])
    assert js == [F.is_stalled(c, at) for c in cases] and js.count(True) == 3


def test_a_broken_or_newer_manifest_of_another_tool(page):
    tree = manifests_only()
    key = f"tools/{RENDER}/toolbox.json"
    doc = json.loads(base64.b64decode(tree[key]))
    for change, code in ((lambda d: d.update(version="0.1"), "version"), (lambda d: d.update(colour="red"), "json"),
                         (lambda d: d["actions"][0].update(accepts=["stepp"]), "json")):
        d = json.loads(json.dumps(doc))
        change(d)
        page.evaluate("t => harness.load(t)", {**tree, key: b64(json.dumps(d).encode())})
        r = page.evaluate("async ([me, to]) => harness.tried(async () => { await (await harness.box(me)).tool(to); })", [PLANNER, RENDER])
        assert r.get("code") == code, r
        assert page.evaluate("async me => (await (await harness.box(me)).all()).map(t => t.manifest.id)", PLANNER) == [PLANNER]


# ---------------------------------------------------------------- the trial page (trial/index.html)
# The folder as {path: base64}. Another tab may be writing (a browser writes beside a file, in "<name>.crswap", and
# swaps it in when it closes): such files, and files that vanish while the folder is read, are not part of it.
DUMP = """async () => { const out = {}; const b64 = bytes => { let s = ''; for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(s); };
  const gone = e => e && e.name === 'NotFoundError';
  const walk = async (dir, pre) => { for await (const [name, h] of dir.entries()) { if (name.endsWith('.crswap')) continue;
    try { if (h.kind === 'directory') await walk(h, pre + name + '/'); else out[pre + name] = b64(new Uint8Array(await (await h.getFile()).arrayBuffer())); } catch (e) { if (!gone(e)) throw e; } } };
  await walk(await (await navigator.storage.getDirectory()).getDirectoryHandle('Toolbox'), ''); return out; }"""
IDLE = "!document.getElementById('send').disabled"      # the sender page has finished with its job, removing included


def test_the_trial_page_does_a_round_trip(page, tmp_path):
    base = page.url.rsplit("/tests/", 1)[0] + "/trial/index.html"
    page.evaluate("harness.reset()")
    ctx = page.context
    receiver, sender = ctx.new_page(), ctx.new_page()
    errors = []
    for pg in (receiver, sender):
        pg.on("pageerror", lambda e: errors.append(str(e)))
    try:
        receiver.goto(base + "?role=receiver&opfs=1&bake=2")
        receiver.wait_for_function("document.getElementById('folderState').textContent.startsWith('Connected')")
        receiver.click("#watch")
        sender.goto(base + "?role=sender&opfs=1")
        sender.wait_for_function("document.getElementById('peerState').textContent.includes('open and watching')", timeout=15000)
        sender.click("#send")
        sender.wait_for_function("document.getElementById('sendState').textContent.startsWith('The bake came back')", timeout=30000)
        assert "checked as hpbake" in sender.inner_text("#sendState")
        report = sender.input_value("#report")
        assert "Round trip" in report and "ERROR" not in report, report
        assert "bake sent back as job" in receiver.input_value("#report")
        out = tmp_path / "Toolbox"
        write_tree(sender.evaluate(DUMP), out)
        rep = check(out)
        assert rep.items == [], rep.text()
        assert not list(out.glob("tools/*/inbox/*")), "both jobs are cleaned up"
        # a job sent while the stand-in bakes can be cancelled
        sender.click("#send")
        sender.wait_for_function("document.getElementById('sendState').textContent.startsWith('Baking moment')", timeout=15000)
        sender.click("#cancel")
        sender.wait_for_function("document.getElementById('sendState').textContent.startsWith('Cancelled')", timeout=15000)
        sender.wait_for_function(IDLE, timeout=15000)               # it removes the cancelled job after saying so
        receiver.click("#stop")                                     # nothing else writes while the folder is read
        receiver.wait_for_function("!document.getElementById('watch').hidden", timeout=15000)
        # a bake that answers a job this browser did not send is left alone, for another copy
        box = tmp_path / "Toolbox2"
        write_tree(sender.evaluate(DUMP), box)
        stray = F.send(box, "nl.fresing.trial.receiver", "nl.fresing.trial.sender", "import-bake", [SAMPLES / "files" / "sample-house.hpbake"],
                       reply_to={"tool": "nl.fresing.trial.receiver", "job": "20260101-000000-nobody"})
        page.evaluate("t => harness.load(t)", tree_of(box))
        sender.wait_for_function("document.getElementById('report').value.includes('Left alone')", timeout=15000)
        write_tree(sender.evaluate(DUMP), box)
        assert (box / "tools" / "nl.fresing.trial.sender" / "inbox" / stray / "job.json").is_file()
        assert not (box / "tools" / "nl.fresing.trial.sender" / "inbox" / stray / "status.json").exists()
        # an empty folder is only set up after the owner says so
        page.evaluate("harness.reset()")
        sender.goto(base + "?role=sender&opfs=strict")
        sender.wait_for_selector("#setup:not([hidden])")
        assert "is empty" in sender.inner_text("#folderState") and sender.evaluate(DUMP) == {}
        sender.click("#setup")
        sender.wait_for_function("document.getElementById('folderState').textContent.startsWith('Connected')")
        assert "toolbox-folder.json" in sender.evaluate(DUMP)
        # after a reload the folder is still known
        sender.reload()
        sender.wait_for_function("document.getElementById('memoryState').textContent.startsWith('Chrome remembered the folder and the permission')")
        assert not errors, errors
    finally:
        receiver.close()
        sender.close()
    assert not errors, errors


# ---------------------------------------------------------------- found by the review (task 0001 of smholte/ToolBox)
# Each case below gave a different answer in JavaScript and Python before its fix.
import io  # noqa: E402
import struct  # noqa: E402
import zipfile  # noqa: E402
import zlib  # noqa: E402

from tbf.names import JsonError, load_json  # noqa: E402


def test_review_patterns_are_judged_the_same(page):
    patterns = [r"[\s-z]", r"[a-\d]", r"[\d-\w]", r"[\w-a]", r"[\w-]", r"[-\w]", r"[a-z-\w]", r"[\d\s-]", r"[%--]",
                r"[!-#-%]", "a{4294967294}", "a{4294967295}", "a{1,99999999999}", "a{99999999999999999999}",
                "a{0004294967294}", r"[\]]", r"[a\-z]", "[^-a]", "[a\\", r"[\b]", "x]"]
    js = page.evaluate("ps => ps.map(p => ToolboxFolder.patternProblem(p) === null)", patterns)
    assert js == [pattern_problem(p) is None for p in patterns], list(zip(patterns, js))


JSON_CASES = [b'{"t": "\\ud800"}', b'{"t": "a\\udc00b"}', b'{"\\ud83c": 1}', b'{"t": "\\udfe0\\ud83c"}', b'{"t": "\\ud83c\\udfe0"}',
              b'{"n": 1' + b"0" * 5000 + b"}", b'{"n": -1' + b"0" * 400 + b"}", b'{"n": 1e400}', b'{"a": 1, "a": 2}',
              b'{"t": "\\u0000"}', b'{"t": "\x7f"}', b'{"t": "\xc2\x85"}', b"\xef\xbb\xbf{}", b'{"n": NaN}', b"[1]"]


def test_review_strict_json_is_read_the_same(page):
    """a reader's view: JavaScript cannot see a key written twice, so the Python reader takes the last one too"""
    js = page.evaluate("cs => cs.map(c => { try { ToolboxFolder.parseJson(unb64(c)); return true; } catch (e) { return e.code; } })",
                       [b64(c) for c in JSON_CASES])
    py = []
    for c in JSON_CASES:
        try:
            load_json(c, "last")
            py.append(True)
        except JsonError:
            py.append("json")
    assert js == py, [(c[:30], a, b) for c, a, b in zip(JSON_CASES, py, js) if a != b]


def _zip(name: str | bytes, data: bytes, flags=0, cd_extra=b"", patch=None) -> bytes:
    """one stored entry, written by hand so that every field can be set"""
    name = name.encode() if isinstance(name, str) else name
    crc = zlib.crc32(data)
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, 0, 0, 0, crc, len(data), len(data), len(name), 0) + name + data
    cd = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, 0, 0, 0, crc, len(data), len(data), len(name),
                     len(cd_extra), 0, 0, 0, 0, 0) + name + cd_extra
    if patch:
        cd = bytearray(cd)
        for offset, value in patch.items():
            struct.pack_into("<I", cd, offset, value)
        cd = bytes(cd)
    return local + cd + struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(cd), len(local), 0)


def _deflated(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return buf.getvalue()


def test_review_zips_are_named_the_same(page, tmp_path):
    scene = b'{"format":"house-scene"}'
    own = load_types() + [{"id": "com.example.has-scene", "name": "Has a scene", "extensions": [".zz"], "by_content": True,
                           "detect": {"zip_has": {"file": "scene.json"}}}]
    cut_short = struct.pack("<HH", 1, 0)          # a zip64 field that holds nothing, at the very end of the list
    cases = [("bom.hpscene", _zip(b"\xef\xbb\xbfscene.json", scene, flags=0x800)),
             ("bom-noflag.hpscene", _zip(b"\xef\xbb\xbfscene.json", scene)),
             ("usize64.zz", _zip("scene.json", scene, cd_extra=cut_short, patch={24: 0xFFFFFFFF})),
             ("offset64.zz", _zip("scene.json", scene, cd_extra=cut_short, patch={42: 0xFFFFFFFF})),
             ("offset64.hpscene", _zip("scene.json", scene, cd_extra=cut_short, patch={42: 0xFFFFFFFF})),
             ("twice.hpscene", _deflated("scene.json", b'{"format":"x","format":"house-scene"}')),
             ("twice2.hpscene", _deflated("scene.json", b'{"format":"house-scene","format":"x"}')),
             ("bigint.hpscene", _deflated("scene.json", b'{"format":"house-scene","n":1' + b"0" * 5000 + b"}")),
             ("lone.hpscene", _deflated("scene.json", b'{"format":"house-scene","n":"\\ud800"}')),
             ("plain.hpscene", _zip("scene.json", scene))]
    got = page.evaluate("""async ([cases, types]) => { const out = []; for (const [name, data] of cases) out.push((await ToolboxFolder.detectType(harness.file(name, data), types)).type); return out; }""",
                        [[[n, b64(d)] for n, d in cases], own])
    py = []
    for i, (name, data) in enumerate(cases):
        p = tmp_path / str(i) / name
        p.parent.mkdir()
        p.write_bytes(data)
        py.append(detect(p, own)[0])
    assert got == py, [(c[0], a, b) for c, a, b in zip(cases, py, got) if a != b]
    assert (py[0], py[-1], py[3]) == ("ext:hpscene", "hpscene", "ext:zz")


def test_review_own_types_written_in_another_key_order_are_the_same_type(page, tmp_path):
    tree = {"toolbox-folder.json": b64(b'{"format":"toolbox-folder","version":"0.2"}')}
    for tid, own in (("com.example.a", {"id": "com.example.w", "name": "W", "extensions": [".w"]}),
                     ("com.example.b", {"name": "W", "extensions": [".w"], "id": "com.example.w"})):
        m = {"format": "toolbox-tool", "version": "0.2", "id": tid, "name": tid, "kind": "native", "actions": [], "types": [own]}
        tree[f"tools/{tid}/toolbox.json"] = b64(json.dumps(m).encode())
    write_tree(tree, tmp_path / "Toolbox")
    page.evaluate("t => harness.load(t)", tree)
    js = page.evaluate("async () => (await (await harness.box('com.example.a')).types()).map(t => t.id)")
    assert js == [t["id"] for t in F.all_types(tmp_path / "Toolbox")] and "com.example.w" in js


def _set(key, value):
    return lambda folder: _edit_job(folder, lambda d: d.update({key: value}))


def _edit_job(folder, change):
    doc = json.loads((folder / "job.json").read_text("utf-8"))
    change(doc)
    (folder / "job.json").write_text(json.dumps(doc), "utf-8")


def _file_is_a_folder(folder):
    (folder / "sample-house.hpscene").unlink()
    (folder / "sample-house.hpscene").mkdir()


def _key_twice(folder):
    text = (folder / "job.json").read_bytes().rstrip()
    (folder / "job.json").write_bytes(text[:-1] + b', "title": "a", "title": "b"}')


REVIEW_JOBS = {
    "a date that does not exist": (_set("created", "2026-02-30T10:00:00+01:00"), "bad-job"),
    "a lone surrogate in the title": (_set("title", "\ud800"), "bad-job"),
    "a lone surrogate in a file name": (lambda f: _edit_job(f, lambda d: d["files"][0].update(name="\ud800.hpscene")), "bad-job"),
    "a size no file has": (lambda f: _edit_job(f, lambda d: d["files"][0].update(size=2**53 + 1)), "bad-job"),
    "a folder in place of the file": (_file_is_a_folder, "bad-job"),
    "a key twice (readers need not notice)": (_key_twice, "ok"),
    "a field named like a part of every JavaScript object": (_set("constructor", 1), "bad-job"),
    "a field named toString": (_set("toString", "x"), "bad-job"),
    "a field named __proto__": (lambda f: (f / "job.json").write_bytes((f / "job.json").read_bytes().rstrip()[:-1]
                                                                       + b', "__proto__": {"x": 1}}'), "bad-job"),
    "a version in other digits": (_set("version", "\u0660.\u0661"), "bad-job"),
    "a huge number in the options": (lambda f: (f / "job.json").write_bytes((f / "job.json").read_bytes().rstrip()[:-1]
                                                                             + b', "options": {"n": 1' + b"0" * 5000 + b"}}"), "ok"),
}


@pytest.mark.parametrize("name", REVIEW_JOBS)
def test_review_jobs_get_the_same_answer(page, tmp_path, name):
    change, expect = REVIEW_JOBS[name]
    box = tmp_path / "Toolbox"
    shutil.copytree(SAMPLES / "Toolbox", box)
    folder = box / "tools" / RENDER / "inbox" / JOB1
    (folder / "status.json").unlink()
    change(folder)
    try:
        F.take(box, F.read_tool(box, RENDER), folder)
        py = "ok"
    except F.JobProblem as p:
        py = p.code
    except FileNotFoundError:
        py = "not-complete"
    page.evaluate("t => harness.load(t)", tree_of(box) | ({f"tools/{RENDER}/inbox/{JOB1}/sample-house.hpscene/keep": b64(b"")}
                                                        if name == "a folder in place of the file" else {}))
    r = page.evaluate("""async ([me, id]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      return harness.tried(() => box.take(m, id).then(() => 'ok')); }""", [RENDER, JOB1])
    js = r.get("code") or r.get("ok")
    assert py == js == expect, (py, r)


def test_review_a_job_json_held_by_another_program_is_read_later(page):
    """section 2: what cannot be read right now is "not there yet" – before, JavaScript failed the job for good"""
    tree = tree_of(SAMPLES / "Toolbox")
    tree = {k: v for k, v in tree.items() if k != f"tools/{RENDER}/inbox/{JOB1}/status.json"}
    page.evaluate("t => harness.load(t)", tree)
    r = page.evaluate("""async ([me, id]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      const real = FileSystemFileHandle.prototype.getFile;
      FileSystemFileHandle.prototype.getFile = function () { if (this.name === 'job.json') return Promise.reject(new DOMException('held', 'NotReadableError')); return real.call(this); };
      try { return await harness.tried(() => box.take(m, id).then(() => 'ok')); } finally { FileSystemFileHandle.prototype.getFile = real; } }""", [RENDER, JOB1])
    assert r.get("code") == "not-complete", r


# ---------------------------------------------------------------- format 0.2 (task 0011 of smholte/ToolBox)
# Every new rule both languages judge, case by case. The Python-only broken copies are in tests/test_format_0_2.py.
import time  # noqa: E402
import unicodedata  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from tbf.detect import type_problems  # noqa: E402
from tbf.names import capitals  # noqa: E402

JOB2 = "20261118-203000-c81e55"
W1 = ["con .txt", "COM0.txt", "LPT0.txt", "COM¹.txt", "COM².txt", "COM³.txt", "LPT¹.txt", "LPT².txt",
      "LPT³.txt", "CONIN$", "CONOUT$", "CLOCK$", "con.txt.txt", "aux"]


def test_0_2_names_are_judged_the_same(page):
    names = W1 + ["Con", "prn  .x", "com10.txt", "console.step", "lpt⁴.txt", "CONIN", "x" * 80, "x" * 81,
                  "\U0001f3e0" * 63 + ".a", "\U0001f3e0" * 64, "é" * 80, "é.txt", "Å.txt", "Å.txt",
                  "Job.Json", "ſtatus.json", "ſ.txt", "\ud800.txt", "a\udc00", "Hus på hytta.hpscene",
                  "İ.txt", "K.txt", "ა.txt"]
    js = page.evaluate("ns => ns.map(n => ToolboxFolder.nameProblem(n) === null)", names)
    assert js == [name_problem(n) is None for n in names], [(n, a) for n, a in zip(names, js) if a != (name_problem(n) is None)]
    assert js.count(True) == 12          # \u212a (Kelvin) is not NFC: NFC makes it K


def test_0_2_capitals_are_the_same_for_every_character(page):
    """names are compared by capitals() (3.3); plain upper() differs between Python 3.11–3.13 and Chrome for about
    55 characters (capitals new in Unicode 16), capitals() for none"""
    js = page.evaluate("""() => { const out = {}; for (let cp = 0; cp < 0x110000; cp++) { if (cp >= 0xd800 && cp <= 0xdfff) continue;
      const c = String.fromCodePoint(cp), k = ToolboxFolder.capitals(c); if (k !== c) out[cp] = k; } return out; }""")
    py = {str(cp): capitals(chr(cp)) for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF and capitals(chr(cp)) != chr(cp)}
    assert js == py
    assert len(py) > 400 and py[str(0x17F)] == "S" and py[str(0xB5)] == "Μ" and py[str(0x131)] == "I"


def test_0_2_nfc_is_judged_the_same_for_every_character_python_knows(page):
    """A name must be NFC (3.3). Chrome knows a newer Unicode than Python; the only differences allowed are
    sequences that make a character Python does not know yet (Unicode 16: Todhri, Tulu-Tigalari, Gurung Khema,
    Kirat Rai – 20 characters, all above U+105C0)."""
    js = page.evaluate("""() => { const single = [], seq = []; for (let cp = 0; cp < 0x110000; cp++) { if (cp >= 0xd800 && cp <= 0xdfff) continue;
      const c = String.fromCodePoint(cp); if (c.normalize('NFC') !== c) single.push(cp);
      const d = c.normalize('NFD'); if (d !== c) seq.push([cp, d, d.normalize('NFC') === d]); } return [single, seq]; }""")
    single = [cp for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF and unicodedata.normalize("NFC", chr(cp)) != chr(cp)]
    assert js[0] == single
    differ = [cp for cp, d, ok in js[1] if (unicodedata.normalize("NFC", d) == d) != ok]
    assert all(unicodedata.category(chr(cp)) == "Cn" and cp > 0x10000 for cp in differ), [hex(c) for c in differ]
    assert len(js[1]) > 2000


def test_0_2_json_depth_is_judged_the_same(page):
    deep = lambda n: b'{"a":' * (n - 1) + b"{}" + b"}" * (n - 1)          # noqa: E731
    cases = [deep(64), deep(65), b'{"a":' + b"[" * 63 + b"1" + b"]" * 63 + b"}", b'{"a":' + b"[" * 64 + b"1" + b"]" * 64 + b"}",
             deep(2000), b'{"a":[[],[[{}]]]}']
    js = page.evaluate("cs => cs.map(c => { try { ToolboxFolder.parseJson(unb64(c)); return true; } catch (e) { return e.code; } })",
                       [b64(c) for c in cases])
    py = []
    for c in cases:
        try:
            load_json(c, "last")
            py.append(True)
        except JsonError:
            py.append("json")
    assert js == py == [True, "json", True, "json", "json", True]


def test_0_2_patterns_rules_and_own_types_are_judged_the_same(page):
    rnd = random.Random(5)
    alphabet = list("ab[]^-&|~\\d(){}*+?2,.$") + ["\\[", "\\]", "\\-"]
    patterns = ["[[a]", "[^[]", "[a[b]", "[a--b]", "[%--]", "[a&&b]", "[&&]", "[a||b]", "[~~]", "[a~~b]", "[\\[]", "[-]",
                "[!-#-%]", "[a-]", "[-a-]"] + ["".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 8))) for _ in range(3000)]
    js = page.evaluate("ps => ps.map(p => ToolboxFolder.patternProblem(p) === null)", patterns)
    assert js == [pattern_problem(p) is None for p in patterns], [p for p, a in zip(patterns, js) if a != (pattern_problem(p) is None)][:10]
    rules = [{"zip_has": {"file": "scène.json"}}, {"zip_has": {"file": "a b.json"}}, {"zip_has": {"file": "tab\t.json"}}]
    assert page.evaluate("rs => rs.map(r => ToolboxFolder.ruleProblem(r) === null)", rules) == [rule_problems(r, "") == [] for r in rules] == [False, True, False]
    base = {"id": "com.example.w", "name": "W", "extensions": [".w"], "by_content": True}
    types = [dict(base, detect={"starts_with": "W"}), dict(base, detect={"head_matches": "W"}),
             dict(base, detect={"all": [{"starts_with": "W"}, {"not": {"head_matches": "x"}}]}),
             dict(base, detect={"any": [{"zip_has": {"file": "w.json"}}]}), dict(base, id="w", detect={"head_matches": "W"})]
    for own in (True, False):
        js = page.evaluate("([ts, own]) => ts.map(t => ToolboxFolder.typeProblem(t, own) === null)", [types, own])
        assert js == [type_problems(t, "", own=own) == [] for t in types], (own, js)
    assert page.evaluate("([ts]) => ts.map(t => ToolboxFolder.typeProblem(t, true) === null)", [types]) == [True, False, False, True, False]


def _cancel_first(folder):
    (folder / "cancel.json").write_text(json.dumps({"format": "toolbox-cancel", "version": "0.2", "job": JOB1,
                                                    "asked": "2026-11-18T19:52:00+01:00"}), "utf-8")


def _pair(folder):
    data = (folder / "sample-house.hpscene").read_bytes()
    for n in ("ſ.hpscene", "s.hpscene"):
        (folder / n).write_bytes(data)
    _edit_job(folder, lambda d: d.update(files=[{"name": n, "type": "hpscene", "size": len(data)} for n in ("ſ.hpscene", "s.hpscene")]))


def _renamed(name):
    def change(folder):
        (folder / "sample-house.hpscene").rename(folder / name)
        _edit_job(folder, lambda d: d["files"][0].update(name=name))
    return change


JOBS_0_2 = {
    "cancelled before it was taken": (_cancel_first, "cancelled"),
    "a reply from another tool": (lambda f: _edit_job(f, lambda d: (d.pop("return"), d.update(reply_to={"tool": "nl.fresing.other", "job": JOB1}))), "bad-job"),
    "a reply that asks for a reply": (_set("reply_to", {"tool": PLANNER, "job": JOB1}), "bad-job"),
    "a missing file": (lambda f: (f / "sample-house.hpscene").unlink(), "bad-job"),
    "a short file": (lambda f: (f / "sample-house.hpscene").write_bytes(b"PK"), "bad-job"),
    "a device name": (_renamed("COM¹.hpscene"), "bad-job"),
    "con with a space": (_renamed("con .hpscene"), "bad-job"),
    "a name that is not NFC": (_renamed("hé.hpscene"), "bad-job"),
    "a name of 81 characters": (_renamed("x" * 73 + ".hpscene"), "bad-job"),
    "a name of 80 characters": (_renamed("x" * 72 + ".hpscene"), "ok"),
    "two names that are one": (_pair, "bad-job"),
    "a job 65 levels deep": (_set("options", json.loads(b'{"a":' * 63 + b"{}" + b"}" * 63)), "bad-job"),
    "a job 64 levels deep": (_set("options", json.loads(b'{"a":' * 62 + b"{}" + b"}" * 62)), "ok"),
    "a size of 2^53": (lambda f: _edit_job(f, lambda d: d["files"][0].update(size=2**53)), "bad-job"),
    "a job id of 33": (_set("job", "2" * 33), "bad-job"),
    "a name that is NFC and not ASCII": (_renamed("hé på hytta.hpscene"), "ok"),
}


@pytest.mark.parametrize("name", JOBS_0_2)
def test_0_2_jobs_get_the_same_answer(page, tmp_path, name):
    change, expect = JOBS_0_2[name]
    box = tmp_path / "Toolbox"
    shutil.copytree(SAMPLES / "Toolbox", box)
    folder = box / "tools" / RENDER / "inbox" / JOB1
    (folder / "status.json").unlink()
    change(folder)
    try:
        F.take(box, F.read_tool(box, RENDER), folder)
        py = "ok"
    except F.JobProblem as p:
        py = p.code
    except FileNotFoundError:
        py = "not-complete"
    page.evaluate("t => harness.load(t)", tree_of(box))
    r = page.evaluate("""async ([me, id]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      return harness.tried(() => box.take(m, id).then(() => 'ok')); }""", [RENDER, JOB1])
    js = r.get("code") or r.get("ok")
    assert py == js == expect, (py, r)


def test_0_2_refuse_write_and_take_up_do_the_same(page, tmp_path):
    """cancelled before it was taken (P21); a final status is never written over and a failed one has a code (P1,
    P23); only a job nobody has updated for 5 minutes is taken up (P1)"""
    box = tmp_path / "Toolbox"
    shutil.copytree(SAMPLES / "Toolbox", box)
    old = (datetime.now().astimezone() - timedelta(minutes=6)).isoformat(timespec="seconds")
    st2 = box / "tools" / RENDER / "inbox" / JOB2 / "status.json"
    st2.write_text(st2.read_text("utf-8").replace("2026-11-18T20:31:02+01:00", old), "utf-8")
    (box / "tools" / RENDER / "inbox" / JOB2 / "cancel.json").unlink()
    page.evaluate("t => harness.load(t)", tree_of(box))
    js = page.evaluate("""async ([me, j1, j2]) => { const box = await harness.box(me), out = [];
      out.push((await box.unfinished()).map(x => x.id));
      out.push(await box.writeStatus(j1, 'working'));           // j1 is done: never written over
      out.push(await box.takeUp(j1, 'working'));
      out.push(await box.takeUp(j2, 'failed', { text: 'Closed while it worked on this' }));
      out.push(await box.takeUp(j2, 'working'));
      const st = await box._status(j2); out.push([st.state, st.code]);
      return out; }""", [RENDER, JOB1, JOB2])
    py = [[f.name for f, _ in F.unfinished(box, RENDER)], F.write_status(box, RENDER, JOB1, "working"),
          F.take_up(box, RENDER, JOB1, "working"), F.take_up(box, RENDER, JOB2, "failed", text="Closed while it worked on this"),
          F.take_up(box, RENDER, JOB2, "working")]
    st = F.read_status(box, RENDER, JOB2)
    py.append([st["state"], st["code"]])
    assert js == py == [[JOB2], False, False, True, False, ["failed", "error"]]
    assert check(box).items == [], check(box).text()
    out = dump_and_check(page, tmp_path, "js")
    assert F.read_status(out, RENDER, JOB2)["state"] == "failed"
    at = datetime(2026, 11, 18, 20, 0, 0, tzinfo=timezone.utc)
    cases = [{"state": s, "updated": (at - timedelta(seconds=a)).isoformat(timespec="seconds")}
             for s in ("waiting", "working", "done", "failed", "cancelled") for a in (0, 299, 301, 9999)] + [None, {"state": "waiting"}]
    js = page.evaluate("([cases, at]) => cases.map(c => ToolboxFolder.isLeft(c, at))", [cases, int(at.timestamp() * 1000)])
    assert js == [F.is_left(c, at) for c in cases] and js.count(True) == 5


def test_0_2_a_cancelled_job_is_refused_as_cancelled_by_both(page, tmp_path):
    box = tmp_path / "Toolbox"
    shutil.copytree(SAMPLES / "Toolbox", box)
    (box / "tools" / RENDER / "inbox" / JOB2 / "status.json").unlink()
    page.evaluate("t => harness.load(t)", tree_of(box))
    js = page.evaluate("""async ([me, id]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest;
      try { await box.take(m, id); } catch (e) { await box.refuse(id, e); } return box._status(id); }""", [RENDER, JOB2])
    try:
        F.take(box, F.read_tool(box, RENDER), box / "tools" / RENDER / "inbox" / JOB2)
    except F.JobProblem as p:
        F.refuse(box, RENDER, JOB2, p)
    py = F.read_status(box, RENDER, JOB2)
    assert [js["state"], "code" in js] == [py["state"], "code" in py] == ["cancelled", False]
    dump_and_check(page, tmp_path, "js")


def test_0_2_cleaning_up_is_the_same(page, tmp_path):
    """7.4 by created and by the final status's updated, never by the folder's date (a page cannot read it)"""
    box = tmp_path / "Toolbox"
    write_tree(manifests_only(), box)
    now = datetime.now().astimezone()
    jobs = {}
    for name, created, state, updated in (("young", 0, None, None), ("old", 31, None, None), ("done-today", 0, "done", 0.5),
                                          ("done-before", 3, "done", 2), ("working-long", 40, "working", 0.1)):
        j = F.send(box, PLANNER, RENDER, "bake-house", [SAMPLES / "files" / "sample-house.hpscene"])
        _edit_job(box / "tools" / RENDER / "inbox" / j, lambda d, c=created: d.update(created=(now - timedelta(days=c)).isoformat(timespec="seconds")))
        if state:
            F.claim(box, RENDER, j, state)
            st = box / "tools" / RENDER / "inbox" / j / "status.json"
            doc = json.loads(st.read_text("utf-8"))
            doc["updated"] = (now - timedelta(days=updated)).isoformat(timespec="seconds")
            st.write_text(json.dumps(doc), "utf-8")
        jobs[j] = name
        time.sleep(1.05)                                       # job ids carry the second
    stray = box / "tools" / RENDER / "inbox" / "20260101-000000-nojobjson"
    stray.mkdir()
    (stray / "part.step").write_bytes(b"x")
    (box / "tools" / RENDER / "inbox" / "20260101-000000-emptyfolder").mkdir()
    page.evaluate("""async ([t, me]) => { await harness.load(t); const root = await harness.root();
      const inbox = await (await (await root.getDirectoryHandle('tools')).getDirectoryHandle(me)).getDirectoryHandle('inbox');
      await inbox.getDirectoryHandle('20260101-000000-emptyfolder', { create: true }); }""", [tree_of(box), RENDER])
    for days in (0, 2, 32):
        at = time.time() + days * F.DAY
        F.clean(box, RENDER, at=at)
        js = page.evaluate("async ([me, at]) => { const box = await harness.box(me); await box.clean(at); return (await harness.dump()); }",
                           [RENDER, int(at * 1000)])
        js_jobs = sorted({k.split("/")[3] for k in js if "/inbox/" in k})
        assert page.evaluate("""async me => { const box = await harness.box(me); const t = await box._tool(me), inbox = await t.getDirectoryHandle('inbox');
          try { await inbox.getDirectoryHandle('20260101-000000-emptyfolder'); return true; } catch (e) { return false; } }""", RENDER)
        py_jobs = sorted(p.name for p in (box / "tools" / RENDER / "inbox").iterdir() if p.name != "20260101-000000-emptyfolder")
        assert js_jobs == py_jobs, (days, js_jobs, py_jobs)
        assert (box / "tools" / RENDER / "inbox" / "20260101-000000-emptyfolder").is_dir()
    left = {jobs.get(j, j) for j in py_jobs}
    assert left == set(), left


def test_0_2_send_writes_nfc_names_and_refuses_a_pair(page, tmp_path):
    page.evaluate("t => harness.load(t)", manifests_only())
    scene = b64((SAMPLES / "files" / "sample-house.hpscene").read_bytes())
    r = page.evaluate("""async ([me, to, data]) => { const box = await harness.box(me);
      const ok = await box.send({ to, action: 'bake-house', files: [harness.file('he\\u0301.hpscene', data)] });
      const pair = await harness.tried(() => box.send({ to, action: 'bake-house', files: [harness.file('\\u017f.hpscene', data), harness.file('s.hpscene', data)] }));
      return [ok, pair.code]; }""", [PLANNER, RENDER, scene])
    out = dump_and_check(page, tmp_path)
    assert json.loads((out / "tools" / RENDER / "inbox" / r[0] / "job.json").read_text("utf-8"))["files"][0]["name"] == "hé.hpscene"
    assert r[1] == "bad-name"


def test_0_2_review_texts_keys_and_odd_entries_are_handled_the_same(page, tmp_path):
    """found by an independent review of this branch: a status text with a line break or a broken character, a key
    that is not UTF-8, a folder named status.json, a cancel.json without a job.json"""
    box = tmp_path / "Toolbox"
    shutil.copytree(SAMPLES / "Toolbox", box)
    inbox = box / "tools" / RENDER / "inbox"
    (inbox / JOB1 / "status.json").unlink()
    text = (inbox / JOB1 / "job.json").read_bytes().rstrip()
    (inbox / JOB1 / "job.json").write_bytes(text[:-1] + b', "options": {"\\ud800": 1}}')
    (inbox / JOB2 / "status.json").unlink()
    (inbox / JOB2 / "job.json").unlink()
    odd = inbox / "20261118-210000-dddddd"
    shutil.copytree(inbox / JOB1, odd)
    (odd / "status.json").mkdir()
    page.evaluate("t => harness.load(t)", tree_of(box) | {f"tools/{RENDER}/inbox/{odd.name}/status.json/keep": b64(b"")})
    js = page.evaluate("""async ([me, j1, j2, odd]) => { const box = await harness.box(me), m = (await box.tool(me)).manifest, out = [];
      out.push(await box.pending());
      const r = await harness.tried(() => box.take(m, j1)); out.push(r.code);
      try { await box.take(m, j1); } catch (e) { out.push(await box.refuse(j1, e)); }
      out.push((await box._status(j1)).code);
      out.push((await harness.tried(() => box.take(m, j2))).code);
      out.push(await box.claim(odd, 'working'));
      await box.writeStatus(j1, 'failed', { text: 'x' });     // final already: nothing
      return out; }""", [RENDER, JOB1, JOB2, odd.name])
    me = F.read_tool(box, RENDER)
    py = [[p.name for p in F.pending(box, RENDER)]]
    try:
        F.take(box, me, inbox / JOB1)
    except F.JobProblem as p:
        py += [p.code, F.refuse(box, RENDER, JOB1, p)]
    py.append(F.read_status(box, RENDER, JOB1)["code"])
    try:
        F.take(box, me, inbox / JOB2)
    except FileNotFoundError:
        py.append("not-complete")
    py.append(F.claim(box, RENDER, odd.name, "working"))
    assert js == py == [[JOB1], "bad-job", True, "bad-job", "not-complete", False]
    texts = ["Error:\nline 2\t\ud800 end", "x" * 300, "\U0001f3e0" * 201, "a\x7fb", "plain"]
    page.evaluate("t => harness.load(t)", tree_of(SAMPLES / "Toolbox"))
    js = page.evaluate("""async ([me, j, texts]) => { const box = await harness.box(me), out = [];
      for (const t of texts) { await box.writeStatus(j, 'working', { text: t }); out.push((await box._status(j)).text); }
      return out; }""", [RENDER, JOB2, texts])
    assert js == [F.one_line(t) for t in texts]
    assert js[0] == "Error: line 2 \ufffd end" and len(js[2]) == 200 and js[3] == "a b"
