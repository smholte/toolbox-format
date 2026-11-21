/* toolbox-folder.js — reference code for a web tool that takes part in the toolbox format 0.2 (FORMAT.md).

   One plain file, no dependencies; a tool may copy it. It needs a browser that can give a page a folder
   (Chrome and Edge on a PC: showDirectoryPicker) – ask ToolboxFolder.supported() first and hide the buttons
   where it says no.

     const tb = ToolboxFolder;
     let root = await tb.remembered();                              // the folder picked at an earlier visit
     if (!root) root = await tb.pick();                             // needs a click: opens the folder picker
     if (await tb.permission(root, true) !== 'granted') return;     // true = may ask (needs a click too)
     const box = await tb.open(root, 'nl.fresing.house-planner');   // refuses a folder without toolbox-folder.json
     await box.writeManifest(MY_MANIFEST);
     const job = await box.send({ to: 'nl.fresing.render', action: 'bake-house', files: [file], ret: 'import-bake' });
     const st = await box.status('nl.fresing.render', job);         // { state, fraction, text … } or null
     await box.exclusively(async () => {                            // one window of this site at a time
       for (const j of await box.pending()) {                       // my own inbox: replies and other jobs
         let taken;
         try { taken = await box.take(MY_MANIFEST, j); }            // checked: names, sizes, types by content
         catch (e) { if (e.code !== 'not-complete') await box.refuse(j, e); continue; }   // failed, or cancelled
         if (!mine(taken.job)) continue;                            // a job this copy cannot place: leave it alone
         …; await box.remove(box.me, j);
       }
       for (const { id } of await box.unfinished()) …               // nobody has updated it for 5 minutes: takeUp(id, …)
       await box.clean();                                           // 7.4
     });

   A page asks for the permission only from a click (Send, or a "Check" bar) – never at start (FORMAT.md 9).

   Everything a tool writes with this file passes check.py of the same version; tests/test_web.py proves it in
   Chrome and compares detectType() with tbf/detect.py file by file. */
(function (global) {
  'use strict';

  const VERSION = '0.2';
  const HEAD = 65536, ZIP_JSON_MAX = 1 << 20, MAX_JSON = 1 << 20, MAX_DEPTH = 4, MAX_PATTERN = 200;
  const MAX_JSON_DEPTH = 64, MAX_TOOL_ID = 60, MAX_NAME = 80, MAX_NAME_BYTES = 255;
  const DAY = 24 * 3600 * 1000;
  const FOLDER_FILE = 'toolbox-folder.json';
  const FINAL = ['done', 'failed', 'cancelled'];
  const ALIVE_FRESH = 30;      // seconds
  const STALLED = 5 * 60;      // seconds a 'working' status is believed after its last update (6.4)

  // The built-in types: a copy of types.json ("types"). tests/test_web.py fails when the two differ.
  /* TYPES-BEGIN */
  const TYPES = [
    { "id": "hpscene", "name": "House Planner scene", "extensions": [".hpscene"], "by_content": true, "detect": { "zip_json": { "file": "scene.json", "field": "format", "equals": "house-scene" } } },
    { "id": "hpbake", "name": "House Planner bake", "extensions": [".hpbake"], "by_content": true, "detect": { "zip_json": { "file": "bake.json", "field": "format", "equals": "house-bake" } } },
    { "id": "ifc", "name": "IFC building model", "extensions": [".ifc"], "by_content": true, "detect": { "all": [{ "starts_with": "ISO-10303-21;" }, { "head_matches": "FILE_SCHEMA\\s*\\(\\s*\\(\\s*'IFC" }] } },
    { "id": "step", "name": "STEP model", "extensions": [".step", ".stp", ".p21"], "by_content": true, "detect": { "all": [{ "starts_with": "ISO-10303-21;" }, { "not": { "head_matches": "FILE_SCHEMA\\s*\\(\\s*\\(\\s*'IFC" } }] } },
    { "id": "glb", "name": "glTF model (binary)", "extensions": [".glb"], "by_content": true, "detect": { "starts_with_hex": "676c5446" } },
    { "id": "pdf", "name": "PDF document", "extensions": [".pdf"], "by_content": true, "detect": { "starts_with_hex": "255044462d" } },
    { "id": "png", "name": "PNG picture", "extensions": [".png"], "by_content": true, "detect": { "starts_with_hex": "89504e470d0a1a0a" } },
    { "id": "jpeg", "name": "JPEG picture", "extensions": [".jpg", ".jpeg"], "by_content": true, "detect": { "starts_with_hex": "ffd8ff" } },
    { "id": "gltf", "name": "glTF model (text)", "extensions": [".gltf"] },
    { "id": "stl", "name": "STL mesh", "extensions": [".stl"] },
    { "id": "obj", "name": "OBJ mesh", "extensions": [".obj"] },
    { "id": "dxf", "name": "DXF drawing", "extensions": [".dxf"] },
    { "id": "csv", "name": "CSV table", "extensions": [".csv"] },
    { "id": "json", "name": "JSON data", "extensions": [".json"] },
    { "id": "zip", "name": "Zip archive", "extensions": [".zip"], "detect": { "any": [{ "starts_with_hex": "504b0304" }, { "starts_with_hex": "504b0506" }] } }
  ];
  /* TYPES-END */

  /** an error with a short code: 'unsupported', 'not-toolbox', 'version', 'json', 'no-tool', 'no-action',
      'wrong-type', 'bad-name', 'bad-job', 'unknown-action', 'not-complete', 'cancelled', 'permission' */
  class TbError extends Error {
    constructor(code, text) { super(text); this.name = 'TbError'; this.code = code; }
  }

  // ───────────────────────── names, times, ids (FORMAT.md section 3)
  const TOOL_ID = /^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+(-[a-z0-9]+)*)+$/;
  const JOB_ID = /^[a-z0-9][a-z0-9-]{7,31}$/;
  const SHORT = /^[a-z0-9][a-z0-9-]{0,31}$/;
  const EXT = /^\.[a-z0-9]{1,16}$/;
  const TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?(Z|[+-]([01]\d|2[0-3]):[0-5]\d)$/;
  const JOB_FILES = ['job.json', 'status.json', 'cancel.json'];
  // names Windows keeps for devices, as the part of a name before its first dot (3.3): a rule of the format
  const DEVICES = new Set(['CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CLOCK$', ...['COM', 'LPT'].flatMap(d => [...'0123456789\u00b9\u00b2\u00b3'].map(n => d + n))]);
  const CAPITALS_BELOW = 0x590;    // Latin, Greek, Cyrillic, Armenian: the scripts whose capitals every version agrees on

  const isToolId = s => typeof s === 'string' && s.length <= MAX_TOOL_ID && TOOL_ID.test(s);
  const isJobId = s => typeof s === 'string' && JOB_ID.test(s);
  const hasControl = s => { for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); if (c < 32 || c === 127) return true; } return false; };
  const lone = s => typeof s.isWellFormed === 'function' ? !s.isWellFormed() : /[\ud800-\udbff](?![\udc00-\udfff])|(?:^|[^\ud800-\udbff])[\udc00-\udfff]/.test(s);

  /** the text two file names are compared by (3.3): every character below U+0590 whose capital is below U+0590 too
      becomes that capital; every other character stays as written. Plain toUpperCase() is not used: the browser and
      Python know different Unicode versions and differ from U+0590 on (and for a few letters below it, like ƛ). */
  function capitals(s) {
    let out = '';
    for (const c of s) {
      const u = c.codePointAt(0) < CAPITALS_BELOW ? c.toUpperCase() : c;
      out += [...u].every(x => x.codePointAt(0) < CAPITALS_BELOW) ? u : c;
    }
    return out;
  }
  const OWN_FILES = new Set(JOB_FILES.map(capitals));

  /** why `name` is not a file name every system takes (3.3); null when it is */
  function nameProblem(name) {
    if (typeof name !== 'string' || !name) return 'is empty';
    if ([...name].length > MAX_NAME) return `is longer than ${MAX_NAME} characters`;
    if (lone(name)) return 'is not UTF-8 text (an unpaired \\ud800–\\udfff)';
    if (new TextEncoder().encode(name).length > MAX_NAME_BYTES) return `is longer than ${MAX_NAME_BYTES} bytes in UTF-8`;
    if (hasControl(name)) return 'holds a control character';
    const bad = [...'"*/:<>?\\|'].find(c => name.includes(c));
    if (bad) return `holds '${bad}'`;
    if (' .'.includes(name[0]) || ' .'.includes(name[name.length - 1])) return 'starts or ends with a space or a dot';
    if (name.normalize('NFC') !== name) return 'is not in Unicode NFC form (an é must be one character, not e and an accent)';
    if (DEVICES.has(capitals(name.split('.')[0].replace(/ +$/, '')))) return 'is a name Windows keeps for a device';
    if (OWN_FILES.has(capitals(name))) return "is one of the format's own files";
    return null;
  }

  function extension(name) { const i = name.lastIndexOf('.'); return i > 0 ? name.slice(i).toLowerCase() : ''; }

  /** the time now as 2026-11-18T19:51:00+01:00 */
  function now(d = new Date()) {
    const p = n => String(Math.abs(n)).padStart(2, '0');
    const off = -d.getTimezoneOffset();
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` +
      `${off < 0 ? '-' : '+'}${p(Math.trunc(Math.abs(off) / 60))}:${p(Math.abs(off) % 60)}`;
  }

  function timeProblem(s) {
    if (typeof s !== 'string' || !TIME.test(s)) return 'is not a time like 2026-11-18T19:51:00+01:00';
    const [y, mo, d, h, mi, se] = s.match(/\d+/g).map(Number);
    const days = new Date(Date.UTC(y, mo, 0)).getUTCDate();
    const off = s.endsWith('Z') ? [0, 0] : s.slice(-5).split(':').map(Number);
    if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > days || h > 23 || mi > 59 || se > 59 || off[0] > 23 || off[1] > 59) return 'is not a real date and time';
    return null;
  }

  function newJobId(d = new Date()) {
    const p = n => String(n).padStart(2, '0');
    const r = [...crypto.getRandomValues(new Uint8Array(3))].map(b => b.toString(16).padStart(2, '0')).join('');
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${r}`;
  }

  // ───────────────────────── strict JSON (3.4)
  function textProblem(s) {
    if (hasControl(s)) return 'holds a control character (line break, tab …)';
    if (lone(s)) return 'is not UTF-8 text (an unpaired \\ud800–\\udfff escape)';
    return null;
  }
  /** text a status may hold (7.1, 3.4): a control character becomes a space, an unpaired U+D800–U+DFFF becomes
      U+FFFD, and it is cut to 200 characters – so an error message cannot make the status unreadable */
  function oneLine(text) {
    let out = '';
    for (const c of String(text)) { const n = c.codePointAt(0); out += n < 32 || n === 127 ? ' ' : n >= 0xd800 && n <= 0xdfff ? '\ufffd' : c; }
    return [...out].slice(0, 200).join('');
  }
  /** text for a message: control characters and unpaired surrogates written as \uXXXX */
  const printable = s => { let out = ''; for (const c of s) { const n = c.codePointAt(0); out += n < 32 || n === 127 || (n >= 0xd800 && n <= 0xdfff) ? '\\u' + n.toString(16).padStart(4, '0') : c; } return out; };

  /** [where, why] of the first key or text that breaks 3.4, or of the first object or array nested deeper than 64
      levels (the file's own object is level 1), or null – walking without recursion */
  function textAt(doc) {
    const todo = [['', doc, 1]];
    while (todo.length) {
      const [where, x, depth] = todo.pop();
      if (x && typeof x === 'object' && depth > MAX_JSON_DEPTH) return [where, `is nested deeper than ${MAX_JSON_DEPTH} levels`];
      if (typeof x === 'string') { const why = textProblem(x); if (why) return [where, why]; }
      else if (Array.isArray(x)) { for (let i = x.length - 1; i >= 0; i--) todo.push([`${where}/${i}`, x[i], depth + 1]); }
      else if (x && typeof x === 'object') {
        const keys = Object.keys(x);
        for (const k of keys) { const why = textProblem(k); if (why) return [`${where}/${k}`, why]; }
        for (let i = keys.length - 1; i >= 0; i--) todo.push([`${where}/${keys[i]}`, x[keys[i]], depth + 1]);
      }
    }
    return null;
  }

  /** a toolbox JSON file (bytes) as an object, or a TbError 'json'. A key written twice cannot be seen from
      JavaScript (the last one wins); writers must not do it and check.py refuses it. */
  function parseJson(bytes) {
    if (bytes.length > MAX_JSON) throw new TbError('json', 'is larger than 1 MiB');
    if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) throw new TbError('json', 'starts with a byte-order mark');
    let text, doc;
    try { text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes); } catch (e) { throw new TbError('json', 'is not UTF-8'); }
    try { doc = JSON.parse(text); } catch (e) { throw new TbError('json', 'is not JSON'); }
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) throw new TbError('json', 'is not a JSON object');
    const hit = textAt(doc);
    if (hit) throw new TbError('json', `${hit[1]} at ${printable(hit[0]) || '/'}`);
    return doc;
  }

  const toJson = doc => new TextEncoder().encode(JSON.stringify(doc, null, 2) + '\n');
  /** JSON text with the keys of every object in order: equal for two equal objects whatever their key order */
  const canonical = doc => JSON.stringify(doc, (k, v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(x => [x, v[x]])) : v);

  // ───────────────────────── what a file of the format must look like (the schemas, by hand)
  const str = (min, max) => v => typeof v === 'string' && [...v].length >= min && [...v].length <= max;
  const typeRef = v => typeof v === 'string' && v.length <= MAX_TOOL_ID && (/^ext:[a-z0-9]{0,16}$/.test(v) || SHORT.test(v) || TOOL_ID.test(v));
  const typeList = min => v => Array.isArray(v) && v.length >= min && v.length <= 100 && v.every(typeRef) && new Set(v).size === v.length;
  const obj = (required, optional) => v => !!v && typeof v === 'object' && !Array.isArray(v) && shape(v, required, optional) === null;
  const list = (item, min, max) => v => Array.isArray(v) && v.length >= min && v.length <= max && v.every(item);
  const time = v => timeProblem(v) === null;
  const fileItem = obj({ name: str(1, MAX_NAME), type: typeRef, size: v => Number.isSafeInteger(v) && v >= 0 }, {});   // size ≤ 2^53 − 1
  const https = v => str(1, 300)(v) && v.startsWith('https://');

  function shape(doc, required, optional) {
    const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);       // not 'constructor', 'toString' … of every object
    for (const k of Object.keys(required)) if (!own(doc, k)) return `${k} is missing`;
    for (const k of Object.keys(doc)) {
      const test = own(required, k) ? required[k] : own(optional, k) ? optional[k] : null;
      if (!test) return `unknown field ${k}`;
      if (!test(doc[k])) return `${k} is not what the format allows`;
    }
    return null;
  }

  const SPEC = {
    folder: ['toolbox-folder', {}, {}],
    alive: ['toolbox-alive', { seen: time }, { app_version: str(1, 40) }],
    cancel: ['toolbox-cancel', { job: isJobId, asked: time }, {}],
    status: ['toolbox-status', { job: isJobId, updated: time, state: v => ['waiting', 'working', ...FINAL].includes(v) },
      { fraction: v => typeof v === 'number' && v >= 0 && v <= 1, text: str(0, 200), code: v => typeof v === 'string' && SHORT.test(v), reply: isJobId }],
    job: ['toolbox-job', { job: isJobId, created: time, from: isToolId, to: isToolId, action: v => typeof v === 'string' && SHORT.test(v), files: list(fileItem, 1, 100) },
      { return: v => typeof v === 'string' && SHORT.test(v), reply_to: obj({ tool: isToolId, job: isJobId }, {}), title: str(0, 120), options: v => !!v && typeof v === 'object' && !Array.isArray(v) }],
    tool: ['toolbox-tool', {
      id: isToolId, name: str(1, 60), kind: v => v === 'native' || v === 'web',
      actions: list(obj({ id: v => typeof v === 'string' && SHORT.test(v), label: str(1, 60), accepts: typeList(1) }, { returns: typeList(0) }), 0, 50),
    }, {
      app_version: str(1, 40), description: str(0, 300), homepage: https, url: https, icon: str(1, MAX_NAME),
      start: obj({ program: str(1, 400) }, { args: list(str(0, 400), 0, 40) }),
      types: list(v => !!v && typeof v === 'object' && !Array.isArray(v), 0, 50), sends: typeList(0),
      handover: v => Array.isArray(v) && v.every(x => x === 'inbox') && new Set(v).size === v.length,
    }],
  };

  /** null when `doc` is a whole file of this kind and version; else why not */
  function docProblem(doc, kind) {
    const [format, required, optional] = SPEC[kind];
    if (typeof doc.version === 'string' && /^\d+\.\d+$/.test(doc.version) && doc.version !== VERSION)
      return `is version ${doc.version}; this app reads ${VERSION} only`;
    if (doc.format !== format) return `is not a ${format} file`;
    if (doc.version !== VERSION) return 'has no version';
    return shape(doc, { format: () => true, version: () => true, ...required }, optional);
  }

  /** what is wrong with a manifest beyond its shape (the rules of tbf/check.py that are errors); null when nothing */
  function manifestProblem(doc, folderName) {
    const why = docProblem(doc, 'tool');
    if (why) return why;
    if (folderName !== undefined && doc.id !== folderName) return `its id is ${doc.id} but its folder is named ${folderName}`;
    if (doc.kind === 'web' && 'start' in doc) return 'a web tool has no start';
    if (doc.kind === 'native' && 'url' in doc) return 'a native tool has no url';
    if ('start' in doc && !/^([A-Za-z]:[\\/]|\/)/.test(doc.start.program)) return 'start.program must be the full path of the program';
    if ('icon' in doc && nameProblem(doc.icon)) return `icon: the file name ${nameProblem(doc.icon)}`;
    const ids = doc.actions.map(a => a.id);
    if (new Set(ids).size !== ids.length) return 'an action is there twice';
    const own = new Set();
    for (const t of doc.types || []) {
      const p = typeProblem(t, true);
      if (p) return `types: ${p}`;
      if (own.has(t.id)) return `the type ${t.id} is there twice`;
      own.add(t.id);
    }
    const builtin = new Set(TYPES.map(t => t.id));
    const refs = [...doc.actions.flatMap(a => [...a.accepts, ...(a.returns || [])]), ...(doc.sends || [])];
    const unknown = refs.find(r => !r.startsWith('ext:') && !r.includes('.') && !builtin.has(r));
    return unknown ? `'${unknown}' is not a type` : null;
  }

  // ───────────────────────── file types: the rules (5.2)
  const MAX_COUNT = 4294967294;     // the largest number in a count Python's re can hold
  /** a set [ … ] that starts at p[i]: [index of its closing ], why it is not allowed or null] */
  function setProblem(p, i) {
    i++;
    if (p[i] === '^') i++;
    if (p[i] === ']') return [i, 'has an empty [] group'];
    const items = [];                // [text, is a class like \d]
    while (i < p.length && p[i] !== ']') {
      if (p[i] === '[') return [i, 'has a [ inside a set (write \\[)'];          // Python warns these will change meaning
      if ('-&|~'.includes(p[i]) && p[i + 1] === p[i]) return [i, `has ${p[i] + p[i]} inside a set`];
      if (p[i] === '\\') {
        const nxt = p[i + 1];
        if (nxt === undefined) return [i, 'ends with a backslash'];
        if (/[A-Za-z0-9]/.test(nxt) && !'sSdDwW'.includes(nxt)) return [i, `uses \\${nxt}`];
        items.push([p.slice(i, i + 2), 'sSdDwW'.includes(nxt)]);
        i += 2;
      } else { items.push([p[i], false]); i++; }
    }
    if (i >= p.length) return [i, 'has a [ that is never closed'];
    for (let k = 0; k < items.length;) {       // a - between two items is a range: neither end may be \d, \s, \w …
      if (k + 2 < items.length && items[k + 1][0] === '-' && !items[k + 1][1]) {
        if (items[k][1] || items[k + 2][1]) return [i, 'has a range in a set that starts or ends at \\s, \\d or \\w (like [\\d-z])'];
        k += 3;
      } else k++;
    }
    return [i, null];
  }

  function patternProblem(p) {
    if (typeof p !== 'string' || !p) return 'is empty';
    if (p.length > MAX_PATTERN) return `is longer than ${MAX_PATTERN} characters`;
    for (let i = 0; i < p.length; i++) { const c = p.charCodeAt(i); if (c < 32 || c > 126) return 'holds a character outside plain ASCII'; }
    let counted = false;
    for (let i = 0; i < p.length; i++) {
      const c = p[i], was = counted;
      counted = false;
      if (c === '\\') {
        const nxt = p[i + 1];
        if (nxt === undefined) return 'ends with a backslash';
        if (/[A-Za-z0-9]/.test(nxt) && !'sSdDwW'.includes(nxt)) return `uses \\${nxt}`;
        i++;
        continue;
      }
      if (c === '[') { const [end, why] = setProblem(p, i); if (why) return why; i = end; }
      else if (c === '^' || c === '$') return `uses ${c}`;
      else if (c === '.') return 'uses a bare .';
      else if (c === '(' && p[i + 1] === '?') return 'uses a (?…) group';
      else if (c === '{') {
        const m = /^\{([0-9]+)(,([0-9]*))?\}/.exec(p.slice(i));
        if (!m) return 'has a { that is not a count';
        if ([m[1], m[3]].some(n => n && (n.replace(/^0+/, '').length > 10 || Number(n) > MAX_COUNT))) return `has a count larger than ${MAX_COUNT}`;
        i += m[0].length - 1;
        counted = true;
      } else if (c === '*' || c === '+') {
        if (was) return `has ${c} right after another count`;
        counted = true;
      } else if (c === '?') counted = !was;
    }
    try { new RegExp(p); } catch (e) { return 'is not a pattern'; }
    return null;
  }

  function ruleProblem(rule, depth = 1) {
    if (!rule || typeof rule !== 'object' || Array.isArray(rule) || Object.keys(rule).length !== 1) return 'a rule is an object with exactly one key';
    const key = Object.keys(rule)[0], v = rule[key];
    if (key === 'all' || key === 'any') {
      if (depth >= MAX_DEPTH) return 'rules are nested too deep';
      if (!Array.isArray(v) || !v.length) return `${key} needs a list of at least one rule`;
      for (const r of v) { const p = ruleProblem(r, depth + 1); if (p) return p; }
      return null;
    }
    if (key === 'not') return depth >= MAX_DEPTH ? 'rules are nested too deep' : ruleProblem(v, depth + 1);
    if (key === 'starts_with') return typeof v === 'string' && /^[\x21-\x7e]{1,64}$/.test(v) ? null : 'starts_with: 1 to 64 plain ASCII characters without spaces';
    if (key === 'starts_with_hex') return typeof v === 'string' && /^([0-9a-f]{2}){1,64}$/.test(v) ? null : 'starts_with_hex: 1 to 64 bytes as lower-case hex';
    if (key === 'head_matches') { const p = patternProblem(v); return p ? `head_matches: the pattern ${p}` : null; }
    if (key === 'zip_has' || key === 'zip_json') {
      const want = key === 'zip_has' ? ['file'] : ['equals', 'field', 'file'];
      if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).sort().join() !== want.join() || !Object.values(v).every(x => typeof x === 'string' && x)) return `${key}: needs exactly ${want.join(', ')}`;
      if (!/^[\x20-\x7e]+$/.test(v.file)) return `${key}: the name of a file inside a zip is plain ASCII`;
      if (v.file.startsWith('/') || v.file.includes('\\') || v.file.split('/').some(part => ['', '.', '..'].includes(part))) return `${key}: not a plain path inside a zip`;
      return null;
    }
    return `'${key}' is not a rule this version knows`;
  }

  /** a valid rule holds a head_matches somewhere */
  function usesPattern(rule) {
    const key = Object.keys(rule)[0], v = rule[key];
    if (key === 'all' || key === 'any') return v.some(usesPattern);
    if (key === 'not') return usesPattern(v);
    return key === 'head_matches';
  }

  function typeProblem(t, own) {
    if (!t || typeof t !== 'object' || Array.isArray(t)) return 'a type is an object';
    const extra = Object.keys(t).find(k => !['id', 'name', 'extensions', 'detect', 'by_content'].includes(k));
    if (extra) return `unknown field ${extra}`;
    if (own ? !isToolId(t.id) : !(typeof t.id === 'string' && SHORT.test(t.id))) return own ? "a tool's own type is named like a tool, with dots" : 'bad type id';
    if (!str(1, 60)(t.name)) return 'a name of 1 to 60 characters';
    if (!Array.isArray(t.extensions) || !t.extensions.length || !t.extensions.every(e => typeof e === 'string' && EXT.test(e)) || new Set(t.extensions).size !== t.extensions.length) return 'extensions: at least one like ".step"';
    if ('detect' in t) {
      const p = ruleProblem(t.detect); if (p) return p;
      if (own && usesPattern(t.detect)) return "a tool's own type may not use head_matches (only the built-in list may)";
    }
    if ('by_content' in t && typeof t.by_content !== 'boolean') return 'by_content: true or false';
    if (t.by_content && !('detect' in t)) return 'by_content needs a detect rule';
    return null;
  }

  // ───────────────────────── file types: looking at a file (5.3)
  // a number in the bytes; outside them it fails, as Python's struct does (then: "not a zip")
  const inside = (b, o, n) => { if (!(o >= 0 && o + n <= b.length)) throw new RangeError('outside the bytes'); };
  const u16 = (b, o) => (inside(b, o, 2), b[o] | (b[o + 1] << 8));
  const u32 = (b, o) => (inside(b, o, 4), (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0);
  const u64 = (b, o) => u32(b, o) + u32(b, o + 4) * 4294967296;
  const bytesOf = async blob => new Uint8Array(await blob.arrayBuffer());
  let CRC = null;
  function crc32(bytes) {
    if (!CRC) { CRC = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; CRC[n] = c >>> 0; } }
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  /** the list of a zip: Map(name → entry), or null when the file is not a zip this code can read */
  async function zipIndex(file) {
    try {
      const size = file.size, tailLen = Math.min(size, 65557), tail = await bytesOf(file.slice(size - tailLen));
      let e = -1;                                               // the last end record in the tail, as unzip tools take it
      for (let i = tail.length - 22; i >= 0; i--) if (u32(tail, i) === 0x06054b50) { e = i; break; }
      if (e < 0) return null;
      const ePos = size - tailLen + e;
      let count = u16(tail, e + 10), cdSize = u32(tail, e + 12), cdOff = u32(tail, e + 16), shift = 0;
      if (count === 0xffff || cdSize === 0xffffffff || cdOff === 0xffffffff) {
        const l = e - 20;
        if (l < 0 || u32(tail, l) !== 0x07064b50) return null;
        const r = await bytesOf(file.slice(u64(tail, l + 8), u64(tail, l + 8) + 56));
        if (r.length < 56 || u32(r, 0) !== 0x06064b50) return null;
        count = u64(r, 32); cdSize = u64(r, 40); cdOff = u64(r, 48);
      } else {
        shift = ePos - cdSize - cdOff;                          // bytes put in front of the zip
        if (shift < 0) return null;
        cdOff += shift;
      }
      if (cdOff + cdSize > size || cdSize > 64 * 1048576) return null;
      const cd = await bytesOf(file.slice(cdOff, cdOff + cdSize)), out = new Map();
      let p = 0;
      for (let n = 0; n < count; n++) {
        if (p + 46 > cd.length || u32(cd, p) !== 0x02014b50) return null;
        const flags = u16(cd, p + 8), nameLen = u16(cd, p + 28), extraLen = u16(cd, p + 30), commentLen = u16(cd, p + 32);
        const ent = { flags, method: u16(cd, p + 10), crc: u32(cd, p + 16), csize: u32(cd, p + 20), usize: u32(cd, p + 24), offset: u32(cd, p + 42) + shift };
        if (p + 46 + nameLen + extraLen + commentLen > cd.length) return null;
        const raw = cd.subarray(p + 46, p + 46 + nameLen);
        const name = flags & 0x800 ? new TextDecoder('utf-8', { ignoreBOM: true }).decode(raw) : String.fromCharCode(...raw);
        for (let x = p + 46 + nameLen, end = x + extraLen; x + 4 <= end;) {      // zip64 sizes
          const id = u16(cd, x), len = u16(cd, x + 2);
          if (id === 1) {
            let q = x + 4;
            if (ent.usize === 0xffffffff) { ent.usize = u64(cd, q); q += 8; }
            if (ent.csize === 0xffffffff) { ent.csize = u64(cd, q); q += 8; }
            if (ent.offset === 0xffffffff + shift) { ent.offset = u64(cd, q) + shift; }
          }
          x += 4 + len;
        }
        out.set(name, ent);
        p += 46 + nameLen + extraLen + commentLen;
      }
      return out;
    } catch (e) { return null; }
  }

  /** the bytes of one entry (stored or deflated, not encrypted, CRC checked), or null */
  async function zipRead(file, ent) {
    try {
      if (ent.flags & 1 || (ent.method !== 0 && ent.method !== 8)) return null;
      const h = await bytesOf(file.slice(ent.offset, ent.offset + 30));
      if (h.length < 30 || u32(h, 0) !== 0x04034b50) return null;
      const start = ent.offset + 30 + u16(h, 26) + u16(h, 28);
      const packed = file.slice(start, start + ent.csize);
      if (packed.size !== ent.csize) return null;
      let data;
      if (ent.method === 0) data = await bytesOf(packed);
      else {
        const reader = packed.stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();
        const parts = []; let total = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          total += value.length;
          if (total > ent.usize) { await reader.cancel(); return null; }
          parts.push(value);
        }
        data = new Uint8Array(total); let o = 0;
        for (const part of parts) { data.set(part, o); o += part.length; }
      }
      return data.length === ent.usize && crc32(data) === ent.crc ? data : null;
    } catch (e) { return null; }
  }

  class Sniff {
    constructor(file, head) { this.file = file; this.head = head; this._zip = undefined; this._text = undefined; }
    get text() {            // every byte of 0x80 and up reads as '?'
      if (this._text === undefined) { let s = ''; for (let i = 0; i < this.head.length; i += 8192) s += String.fromCharCode(...this.head.subarray(i, i + 8192).map(b => b < 0x80 ? b : 63)); this._text = s; }
      return this._text;
    }
    startsWith(want, skip) {
      let o = 0; const h = this.head;
      if (skip) { if (h[0] === 0xef && h[1] === 0xbb && h[2] === 0xbf) o = 3; while (o < h.length && [32, 9, 13, 10].includes(h[o])) o++; }
      if (h.length - o < want.length) return false;
      for (let i = 0; i < want.length; i++) if (h[o + i] !== want[i]) return false;
      return true;
    }
    async names() { if (this._zip === undefined) this._zip = await zipIndex(this.file); return this._zip; }
    async zipJson(name) {
      const idx = await this.names(), ent = idx && idx.get(name);
      if (!ent || ent.usize > ZIP_JSON_MAX) return null;
      const data = await zipRead(this.file, ent);
      if (!data) return null;
      try { return parseJson(data); } catch (e) { return null; }
    }
  }

  async function ruleTrue(rule, f) {
    const key = Object.keys(rule)[0], v = rule[key];
    if (key === 'all') { for (const r of v) if (!await ruleTrue(r, f)) return false; return true; }
    if (key === 'any') { for (const r of v) if (await ruleTrue(r, f)) return true; return false; }
    if (key === 'not') return !await ruleTrue(v, f);
    if (key === 'starts_with') return f.startsWith([...v].map(c => c.charCodeAt(0)), true);
    if (key === 'starts_with_hex') return f.startsWith(v.match(/../g).map(x => parseInt(x, 16)), false);
    if (key === 'head_matches') return new RegExp(v).test(f.text);
    if (key === 'zip_has') return ((await f.names()) || new Map()).has(v.file);
    if (key === 'zip_json') { const doc = await f.zipJson(v.file); return doc !== null && Object.prototype.hasOwnProperty.call(doc, v.field) && doc[v.field] === v.equals; }
    return false;
  }

  /** { type, note } of a File or Blob – FORMAT.md 5.3. `types`: the built-in list followed by the tools' own.
      `name`: the name to take the extension from, when it is not file.name. */
  async function detectType(file, types = TYPES, name = undefined) {
    const f = new Sniff(file, await bytesOf(file.slice(0, HEAD)));
    const ext = extension(name !== undefined ? name : file.name || '');
    for (const t of types) {
      if (t.by_content && await ruleTrue(t.detect, f)) {
        const note = t.extensions.includes(ext) ? null : `its content is ${t.name} (${t.id}) but its name ends in ${ext || 'no extension'}`;
        return { type: t.id, note };
      }
    }
    let failed = null;
    for (const t of types) {
      if (!t.extensions.includes(ext)) continue;
      if (!('detect' in t) || await ruleTrue(t.detect, f)) return { type: t.id, note: null };
      failed = failed || t;
    }
    return { type: 'ext:' + ext.slice(1), note: failed ? `its name ends in ${ext} but its content is not ${failed.name}` : null };
  }

  // ───────────────────────── a folder handle: small helpers
  const missing = e => e && (e.name === 'NotFoundError' || e.name === 'TypeMismatchError');
  async function sub(dir, name, create = false) {
    try { return await dir.getDirectoryHandle(name, { create }); } catch (e) { if (missing(e)) return null; throw e; }
  }
  async function fileOf(dir, name) {
    try { return await (await dir.getFileHandle(name)).getFile(); } catch (e) { if (missing(e)) return null; throw e; }
  }
  /** true when the folder holds an entry of this name, a file or a folder (as Python's exists()) */
  async function there(dir, name) {
    for (const get of ['getFileHandle', 'getDirectoryHandle']) {
      try { await dir[get](name); return true; } catch (e) { if (!missing(e)) throw e; }
    }
    return false;
  }
  /** write a file whole: the browser writes beside it and swaps it in when it is closed */
  async function write(dir, name, data) {
    const w = await (await dir.getFileHandle(name, { create: true })).createWritable();
    try { await w.write(data); await w.close(); } catch (e) { try { await w.abort(); } catch (e2) { /* closed already */ } throw e; }
  }
  /** errors a write gets when another program holds the file (Windows refuses the swap) or another writer has it
      (the browser refuses): section 2's "try again at the next look" */
  const REFUSED = ['NoModificationAllowedError', 'InvalidModificationError', 'InvalidStateError', 'UnknownError'];
  const refused = (e) => !!e && REFUSED.includes(e.name);
  const settings = { finalPatience: 2 };      // seconds a final status keeps trying (a reader holds up to 0.5 s)
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
  /** write(), tried again for `patience` seconds while the write is refused */
  async function writePatient(dir, name, data, patience) {
    const end = Date.now() + patience * 1000;
    for (;;) {
      try { await write(dir, name, data); return; } catch (e) { if (!refused(e) || Date.now() >= end) throw e; }
      await sleep(50);
    }
  }
  /** a JSON file of the format, checked: the object, null when the file is missing; TbError otherwise */
  async function readDoc(dir, name, kind) {
    const f = await fileOf(dir, name);
    if (!f) return null;
    if (f.size > MAX_JSON) throw new TbError('json', `${name} is larger than 1 MiB`);
    let doc;
    try { doc = parseJson(await bytesOf(f)); } catch (e) { throw new TbError('json', `${name} ${e.message}`); }
    const why = kind === 'tool' ? manifestProblem(doc) : docProblem(doc, kind);
    if (why) throw new TbError(why.includes('is version') ? 'version' : 'json', `${name}: ${why}`);
    return doc;
  }
  async function entries(dir) { const out = []; for await (const [name, h] of dir.entries()) out.push([name, h]); return out.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0); }

  // ───────────────────────── the picked folder is kept on this device (IndexedDB)
  function db() {
    return new Promise((res, rej) => {
      const r = indexedDB.open('toolbox-format', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('kv');
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  async function kv(mode, fn) {
    const d = await db();
    try { return await new Promise((res, rej) => { const tx = d.transaction('kv', mode), q = fn(tx.objectStore('kv')); tx.oncomplete = () => res(q && q.result); tx.onerror = () => rej(tx.error); }); } finally { d.close(); }
  }

  const supported = () => typeof global.showDirectoryPicker === 'function';
  /** the folder handle kept from an earlier visit, or null */
  const remembered = async () => (await kv('readonly', s => s.get('root'))) || null;
  const remember = root => kv('readwrite', s => s.put(root, 'root'));
  const forget = () => kv('readwrite', s => s.delete('root'));
  /** open the browser's folder picker (needs a click) and keep the folder */
  async function pick() {
    if (!supported()) throw new TbError('unsupported', 'This browser cannot give a page a folder. Use Chrome or Edge on a PC.');
    const root = await global.showDirectoryPicker({ id: 'toolbox', mode: 'readwrite' });
    await remember(root);
    return root;
  }
  /** 'granted', 'prompt' or 'denied' for reading and writing; with ask = true the browser may ask (needs a click) */
  async function permission(root, ask = false) {
    const opt = { mode: 'readwrite' };
    if (!root.queryPermission) return 'granted';                  // the browser's private file system (tests)
    let p = await root.queryPermission(opt);
    if (p === 'prompt' && ask) p = await root.requestPermission(opt);
    return p;
  }

  // ───────────────────────── the Toolbox folder
  class Box {
    constructor(root, me) { this.root = root; this.me = me; this.tools = null; }

    async _tool(id, create = false) { return isToolId(id) ? sub(this.tools, id, create) : null; }
    async _job(tool, job) { const t = await this._tool(tool), inbox = t && await sub(t, 'inbox'); return inbox && isJobId(job) ? sub(inbox, job) : null; }

    /** write my manifest (and make my tool folder and inbox) */
    async writeManifest(manifest) {
      const why = manifestProblem(manifest, this.me);
      if (why) throw new TbError('json', `my own manifest: ${why}`);
      const t = await this._tool(this.me, true);
      await sub(t, 'inbox', true);
      await write(t, 'toolbox.json', toJson(manifest));
    }

    /** another tool: { manifest, open } – open: it is watching its inbox right now. null when there is no such
        tool; TbError 'version' / 'json' when its manifest cannot be used. */
    async tool(id) {
      const t = await this._tool(id);
      const manifest = t && await readDoc(t, 'toolbox.json', 'tool');
      if (!manifest) return null;
      if (manifest.id !== id) throw new TbError('json', `the manifest in ${id} names another tool`);
      let open = false;
      try { const a = await readDoc(t, 'alive.json', 'alive'); open = !!a && Math.abs(Date.now() - Date.parse(a.seen)) <= ALIVE_FRESH * 1000; } catch (e) { /* a broken alive.json = not open */ }
      return { manifest, open };
    }

    /** every tool of the folder with a usable manifest: [{ manifest, open }] */
    async all() {
      const out = [];
      for (const [name, h] of await entries(this.tools)) {
        if (h.kind !== 'directory' || !isToolId(name)) continue;
        try { const t = await this.tool(name); if (t) out.push(t); } catch (e) { /* skip a broken one */ }
      }
      return out;
    }

    /** the built-in types followed by every tool's own, ordered by id; a type two tools define differently is left out
        (the order of the keys is no difference) */
    async types() {
      const own = new Map(), clash = new Set();
      for (const { manifest } of await this.all()) for (const t of manifest.types || []) {
        if (own.has(t.id) && canonical(own.get(t.id)) !== canonical(t)) clash.add(t.id);
        if (!own.has(t.id)) own.set(t.id, t);
      }
      return [...TYPES, ...[...own.keys()].filter(k => !clash.has(k)).sort().map(k => own.get(k))];
    }

    /** Run fn unless another window of this site is doing so right now (then: undefined). For reading the inbox:
        a page has no exclusive create, so one window at a time looks (6.3). */
    async exclusively(fn) {
      if (!global.navigator || !navigator.locks) return fn();
      return navigator.locks.request('toolbox-format:' + this.me, { ifAvailable: true }, lock => lock ? fn() : undefined);
    }

    /** optional for a web tool (6.4): a page cannot write while it closes and is slowed down in the background */
    async alive(appVersion) {
      const t = await this._tool(this.me, true), doc = { format: 'toolbox-alive', version: VERSION, seen: now() };
      if (appVersion) doc.app_version = appVersion;
      await write(t, 'alive.json', toJson(doc));
    }
    async notAlive() { const t = await this._tool(this.me); if (t) try { await t.removeEntry('alive.json'); } catch (e) { if (!missing(e)) throw e; } }

    /** Send a job (6.2): files are File objects (or { name, blob }). Returns the job id. Throws TbError before
        anything is written when the receiver would not take it. onProgress(bytesWritten, bytesTotal). */
    async send({ to, action, files, ret, title, options, replyTo, onProgress }) {
      const tool = await this.tool(to);
      if (!tool) throw new TbError('no-tool', `${to} is not in the Toolbox folder`);
      const act = tool.manifest.actions.find(a => a.id === action);
      if (!act) throw new TbError('no-action', `${tool.manifest.name} has no action ${action}`);
      const types = await this.types(), listed = [], seen = new Set();
      for (const f of files) {
        const name = f.name.normalize('NFC'), blob = f.blob || f, why = nameProblem(name);   // names are NFC (3.3)
        if (why || seen.has(capitals(name))) throw new TbError('bad-name', `the file name '${name}' ${why || 'is there twice'}`);
        seen.add(capitals(name));
        const { type } = await detectType(blob, types, name);
        if (!act.accepts.includes(type)) throw new TbError('wrong-type', `${tool.manifest.name} does not accept ${type} for ${act.label} (${name})`);
        listed.push({ name, type, size: blob.size, blob });
      }
      const job = newJobId(), inbox = await sub(await this._tool(to), 'inbox', true), folder = await sub(inbox, job, true);   // makes a missing inbox (6.2)
      const total = listed.reduce((s, f) => s + f.size, 0); let done = 0;
      for (const f of listed) {
        const w = await (await folder.getFileHandle(f.name, { create: true })).createWritable();
        try {
          for (let o = 0; o < f.size || o === 0; o += 8 << 20) {
            const part = f.blob.slice(o, o + (8 << 20));
            await w.write(part); done += part.size;
            if (onProgress) onProgress(done, total);
            if (f.size === 0) break;
          }
          await w.close();
        } catch (e) { try { await w.abort(); } catch (e2) { /* closed already */ } throw e; }
      }
      const doc = { format: 'toolbox-job', version: VERSION, job, created: now(), from: this.me, to, action, files: listed.map(({ name, type, size }) => ({ name, type, size })) };
      if (ret) doc.return = ret;
      if (replyTo) doc.reply_to = replyTo;
      if (title) doc.title = [...title].slice(0, 120).join('');
      if (options) doc.options = options;
      await write(folder, 'job.json', toJson(doc));            // last: only now the job exists for the receiver
      return job;
    }

    /** the status of a job I sent: the status object; { state: 'sent' } when the receiver has not seen it yet;
        null when the job is gone */
    async status(to, job) {
      const folder = await this._job(to, job);
      if (!folder) return null;
      try { return (await readDoc(folder, 'status.json', 'status')) || { state: 'sent' }; } catch (e) { return { state: 'sent' }; }
    }

    async cancel(to, job) {
      const folder = await this._job(to, job);
      if (folder) await write(folder, 'cancel.json', toJson({ format: 'toolbox-cancel', version: VERSION, job, asked: now() }));
    }

    /** the ids of the jobs in my inbox that have a job.json and no status.json yet, oldest first */
    async pending() {
      const t = await this._tool(this.me), inbox = t && await sub(t, 'inbox'), out = [];
      if (!inbox) return out;
      for (const [name, h] of await entries(inbox)) {
        if (h.kind !== 'directory' || !isJobId(name)) continue;
        if (await fileOf(h, 'job.json') && !await there(h, 'status.json')) out.push(name);
      }
      return out;
    }

    async _status(jobId) {
      const folder = await this._job(this.me, jobId);
      if (!folder) return null;
      try { return await readDoc(folder, 'status.json', 'status'); } catch (e) { return null; }   // half there: next time
    }

    /** Jobs left behind: those of my inbox whose status is waiting or working and has not been updated for 5
        minutes, as [{ id, status }] – a run that closed or crashed, never a job another open copy holds. Take each
        up with takeUp(). Look at start and about once a minute (6.3). */
    async unfinished(at = Date.now()) {
      const t = await this._tool(this.me), inbox = t && await sub(t, 'inbox'), out = [];
      if (!inbox) return out;
      for (const [name, h] of await entries(inbox)) {
        if (h.kind !== 'directory' || !isJobId(name)) continue;
        let st = null;
        try { st = await readDoc(h, 'status.json', 'status'); } catch (e) { /* half there: next time */ }
        if (isLeft(st, at)) out.push({ id: name, status: st });
      }
      return out;
    }

    /** Take a job: write its first status unless it has one already. true when this call wrote it. A page cannot
        create a file exclusively, so call this inside exclusively(). */
    async claim(jobId, state = 'waiting', extra = {}) {
      const folder = await this._job(this.me, jobId);
      if (!folder || await there(folder, 'status.json')) return false;
      return this.writeStatus(jobId, state, extra);
    }

    /** the status a job take() refused gets: failed with the error's code, or cancelled when the sender cancelled
        it before it was taken (6.3); only when the job has no status yet */
    async refuse(jobId, err) {
      if (err.code === 'cancelled') return this.claim(jobId, 'cancelled', { text: err.message });
      return this.claim(jobId, 'failed', { code: err.code, text: err.message });
    }

    /** Take up a job left behind (6.3): only when its status is still waiting or working and still 5 minutes old,
        read again just before. Call it inside exclusively(). */
    async takeUp(jobId, state, extra = {}, at = Date.now()) {
      if (!isLeft(await this._status(jobId), at)) return false;
      return this.writeStatus(jobId, state, extra);
    }

    /** Check a job of my inbox as 6.3 says: { job, files: [{ name, type, file }] }. Throws TbError with the
        status code to write ('bad-job', 'unknown-action', 'wrong-type'), or 'not-complete' when a file is still
        being written (try again shortly). */
    async take(manifest, jobId) {
      const folder = await this._job(this.me, jobId);
      if (!folder) throw new TbError('bad-job', 'the job is gone');
      let hasJob, cancel;
      try { hasJob = await fileOf(folder, 'job.json'); cancel = hasJob && await fileOf(folder, 'cancel.json'); } catch (e) { throw new TbError('not-complete', `job.json cannot be read right now (${e.name})`); }
      if (!hasJob) throw new TbError('not-complete', 'no job.json yet');
      if (cancel) throw new TbError('cancelled', 'Cancelled by the sender before it was taken');   // 6.3 step 2
      let job;
      try { job = await readDoc(folder, 'job.json', 'job'); } catch (e) {
        if (e instanceof TbError) throw new TbError('bad-job', e.message);
        throw new TbError('not-complete', `job.json cannot be read right now (${e.name})`);   // held by another program (2)
      }
      if (!job) throw new TbError('not-complete', 'no job.json yet');
      if (job.job !== jobId || job.to !== this.me || job.from === job.to) throw new TbError('bad-job', "the job is not for this tool, or its id is not its folder's name");
      if ('reply_to' in job && (job.reply_to.tool !== job.from || 'return' in job)) throw new TbError('bad-job', 'a reply comes from the tool that did the job and asks for no reply itself');
      const act = manifest.actions.find(a => a.id === job.action);
      if (!act) throw new TbError('unknown-action', `${manifest.name} has no action ${job.action}`);
      const types = await this.types(), files = [], seen = new Set();
      for (const f of job.files) {
        const why = nameProblem(f.name);
        if (why || seen.has(capitals(f.name))) throw new TbError('bad-job', `the file name '${f.name}' ${why || 'is listed twice'}`);
        seen.add(capitals(f.name));
        let file = null;
        try { file = await (await folder.getFileHandle(f.name)).getFile(); } catch (e) {
          if (e.name === 'TypeMismatchError') throw new TbError('bad-job', `${f.name} is not a plain file`);
          if (e.name === 'TypeError') throw new TbError('bad-job', `the file name '${f.name}' cannot be used on this system`);
          if (e.name !== 'NotFoundError') throw new TbError('not-complete', `${f.name} cannot be read right now (${e.name})`);
        }
        if (!file) throw new TbError('bad-job', `${f.name} is missing`);        // job.json is written last: it never comes
        if (file.size !== f.size) throw new TbError('bad-job', `${f.name} is ${file.size} bytes, job.json says ${f.size}`);
        let type;
        try { ({ type } = await detectType(file, types, f.name)); } catch (e) { throw new TbError('not-complete', `${f.name} cannot be read right now (${e.name})`); }
        if (type !== f.type) throw new TbError('wrong-type', `${f.name} is ${type}, not ${f.type}`);
        if (!act.accepts.includes(type)) throw new TbError('wrong-type', `${act.label} does not accept ${type} (${f.name})`);
        files.push({ name: f.name, type, file });
      }
      return { job, files };
    }

    /** Write the status of a job of my inbox (7.1): state, and optional fraction, text, code, reply. A failed job
        always has a code ('error' when none is given). A final status is never written over: it is read just before,
        and false returned when it is final already.
        Another program may hold status.json (Windows refuses the write, section 2). A status that is not final
        (waiting, working) is then not written now: false, and the next update writes it – a job never stops for
        it. A final status keeps trying for 2 seconds, then throws: write it again at the next look. */
    async writeStatus(jobId, state, extra = {}) {
      const folder = await this._job(this.me, jobId);
      if (!folder) return false;
      const old = await this._status(jobId);
      if (old && FINAL.includes(old.state)) return false;
      const doc = { format: 'toolbox-status', version: VERSION, job: jobId, state, updated: now() };
      const more = state === 'failed' && (extra.code === undefined || extra.code === null) ? { ...extra, code: 'error' } : extra;
      for (const k of ['fraction', 'text', 'code', 'reply']) if (more[k] !== undefined && more[k] !== null) doc[k] = k === 'text' ? oneLine(more[k]) : more[k];
      if (FINAL.includes(state)) { await writePatient(folder, 'status.json', toJson(doc), settings.finalPatience); return true; }
      try { await writePatient(folder, 'status.json', toJson(doc), 0.25); } catch (e) { if (refused(e)) return false; throw e; }
      return true;
    }

    async wantsCancel(jobId) { const folder = await this._job(this.me, jobId); return !!folder && !!await fileOf(folder, 'cancel.json'); }

    /** 7.2: send the result back as a job when the first job asked for it, then write its status 'done'.
        Returns the reply job's id, or null when the result stays here. When the status 'done' cannot be written
        right now (see writeStatus), the error carries the reply's id as .reply and .text: write the status again
        with them; never send twice. */
    async sendReply(job, files, text) {
      let reply = null;
      if ('return' in job && files.length && await this._tool(job.from)) {
        try { reply = await this.send({ to: job.from, action: job.return, files, title: job.title, replyTo: { tool: this.me, job: job.job } }); } catch (e) { text = `Done, but the result could not be sent back: ${e.message}`; }
      }
      try { await this.writeStatus(job.job, 'done', { text, reply }); } catch (e) { if (e && typeof e === 'object') { e.reply = reply; e.text = text; } throw e; }
      return reply;
    }

    /** Clean up my inbox (7.4): a job a day after its final status, any job 30 days after it was created; a folder
        whose job.json is missing or cannot be read is dated by its newest file, one without files is left alone. */
    async clean(at = Date.now()) {
      const t = await this._tool(this.me), inbox = t && await sub(t, 'inbox');
      if (!inbox) return;
      const doc = async (h, name, kind) => { try { return await readDoc(h, name, kind); } catch (e) { if (e instanceof TbError) return null; throw e; } };
      for (const [name, h] of await entries(inbox)) {
        if (h.kind !== 'directory' || !isJobId(name)) continue;
        let age = null, final = false;
        try {
          const st = await doc(h, 'status.json', 'status'), job = st && FINAL.includes(st.state) ? null : await doc(h, 'job.json', 'job');
          if (st && FINAL.includes(st.state)) { age = at - Date.parse(st.updated); final = true; }
          else if (job) age = at - Date.parse(job.created);
          else {
            let newest = null;
            for (const [, f] of await entries(h)) if (f.kind === 'file') newest = Math.max(newest === null ? 0 : newest, (await f.getFile()).lastModified);
            if (newest !== null) age = at - newest;
          }
        } catch (e) { continue; }                                   // cannot be read right now: next time
        if (age !== null && (age > 30 * DAY || (final && age > DAY))) await this.remove(this.me, name);
      }
    }

    /** Delete a job folder: a reply I took in, or a job I sent whose final status I have read (7.4). false when
        the system would not let it go right now (another program reads it): try again at the next look. */
    async remove(tool, jobId) {
      const t = await this._tool(tool), inbox = t && await sub(t, 'inbox');
      if (!inbox || !isJobId(jobId)) return true;
      try { await inbox.removeEntry(jobId, { recursive: true }); return true; } catch (e) { return missing(e); }
    }
  }

  /** Open a picked folder as the Toolbox folder for the tool `me`. TbError 'not-toolbox' when it holds no
      toolbox-folder.json, 'version' when it is of another version. A web tool never makes the folder: a page cannot
      see where the folder lies (FORMAT.md 2). `create` is for the trial page (true: an empty folder named "Toolbox"
      becomes one) and for tests ('any': an empty folder of any name). */
  async function open(root, me, create = false) {
    if (!isToolId(me)) throw new TbError('json', `${me} is not a tool id`);
    let marker;
    try { marker = await readDoc(root, FOLDER_FILE, 'folder'); } catch (e) { throw new TbError(e.code === 'version' ? 'version' : 'not-toolbox', e.message); }
    if (!marker) {
      const empty = (await entries(root)).filter(([n]) => !n.endsWith('.crswap')).length === 0;
      const named = create === 'any' || root.name.toLowerCase() === 'toolbox';
      if (!create || !empty || !named) throw new TbError('not-toolbox', `This is not the Toolbox folder: there is no ${FOLDER_FILE} in "${root.name}". A program that uses the toolbox, like Fresing Render, makes the folder.`);
      await write(root, FOLDER_FILE, toJson({ format: 'toolbox-folder', version: VERSION }));
    }
    const box = new Box(root, me);
    box.tools = await sub(root, 'tools', true);
    return box;
  }

  /** true when a waiting or working status has not been updated for 5 minutes: nobody holds the job any more, and a
      copy of the receiving tool may take it up (6.3). A copy that keeps a job writes its status every 2 minutes. */
  function isLeft(status, at = Date.now()) {
    if (!status || (status.state !== 'waiting' && status.state !== 'working')) return false;
    const seen = Date.parse(status.updated);
    return Number.isNaN(seen) || at - seen > STALLED * 1000;
  }

  /** true when a working status has not been updated for 5 minutes: only then say that nothing has been heard.
      A busy tool cannot write, so a fresh 'working' is believed whatever alive.json says (6.4). */
  function stalled(status, at = Date.now()) {
    if (!status || status.state !== 'working') return false;
    const seen = Date.parse(status.updated);
    return Number.isNaN(seen) || at - seen > STALLED * 1000;
  }

  global.ToolboxFolder = {
    VERSION, TYPES, FINAL, TbError, stalled, isLeft, supported, remembered, remember, forget, pick, permission, open,
    detectType, nameProblem, capitals, timeProblem, patternProblem, ruleProblem, typeProblem, docProblem, manifestProblem,
    parseJson, toJson, now, newJobId, isToolId, isJobId, crc32, settings,
  };
})(typeof window !== 'undefined' ? window : globalThis);
