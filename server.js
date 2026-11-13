// Ethan’s Tank Duel - game server.
// Serves the game page and runs online rooms. For each room created with POST /create, the server
// starts its own copy of the game script (the same code a host tablet runs, with drawing switched
// off) in a sandbox. That copy is the room's host; every player is a guest, so nobody's tablet or
// connection holds the others up. Messages travel over WebSocket; the relay below also still lets
// a tablet host a room itself. No dependencies: a small WebSocket implementation (RFC 6455, text
// frames) sits on Node's http module.
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const vm = require('vm');

const PORT = process.env.PORT || 8080;
const MAX_FRAME = 64 * 1024;          // nothing in this game is anywhere near this
const MAX_GUESTS = 4;                 // 5 tanks in all
const TEST_LAG = +process.env.TEST_LAG_MS || 0;   // tests only: delay every message this many ms
const TEST_SPIKE = +process.env.TEST_SPIKE || 0;  // tests only: chance of an extra 150 ms stall
const MAX_ROOMS = 30;                 // server-run rooms at once
const TICK_MS = 1000 / 60;            // how often each room's game loop is driven
const page = () => fs.readFileSync(path.join(__dirname, 'index.html'));

/* ---------- leaderboard: the results of online matches between players with names ---------- */
// Kept in a JSON file on a disk that survives deploys (a volume mounted at /data on Railway).
const DATA_DIR = process.env.DATA_DIR || (fs.existsSync('/data') ? '/data' : path.join(__dirname, 'data'));
const BOARD_FILE = path.join(DATA_DIR, 'board.json');
const MAX_MATCHES = 5000;
let board = { matches: [] };
try { const b = JSON.parse(fs.readFileSync(BOARD_FILE, 'utf8')); if (Array.isArray(b.matches)) board = b; } catch (e) {}
console.log(`leaderboard: ${board.matches.length} matches in ${BOARD_FILE}`);
let saveTimer = null;
function saveBoard() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    try { fs.mkdirSync(DATA_DIR, { recursive: true }); fs.writeFileSync(BOARD_FILE + '.tmp', JSON.stringify(board)); fs.renameSync(BOARD_FILE + '.tmp', BOARD_FILE); }
    catch (e) { console.error('leaderboard not saved:', e.message); }
  }, 1500);
}
const MODES = ['classic', 'teams', 'dm', 'hill', 'base', 'zombie', 'potato', 'gun', 'soccer'];
const seenIds = new Map();                 // match ids already recorded (a result can arrive twice)
const cleanName = v => String(v || '').replace(/[<>]/g, '').trim().slice(0, 12);
const count = v => Math.max(0, Math.min(999, v | 0));
function addResult(r) {
  if (!r || typeof r !== 'object' || !Array.isArray(r.p) || r.p.length < 2 || r.p.length > 5) return false;
  const id = String(r.id || '').slice(0, 16);
  if (!id || seenIds.has(id)) return false;
  const p = r.p.map(q => ({ n: cleanName(q && q.n), w: !!(q && q.w), k: count(q && q.k), d: count(q && q.d), bot: !!(q && q.bot) }));
  if (p.filter(q => q.n && !q.bot).length < 2) return false;   // it takes two people with names
  seenIds.set(id, Date.now());
  for (const [k, t] of seenIds) if (Date.now() - t > 3600e3) seenIds.delete(k);
  board.matches.push({ t: Date.now(), m: MODES.includes(r.m) ? r.m : 'classic', u: String(r.u || '').slice(0, 12), p });
  if (board.matches.length > MAX_MATCHES) board.matches.splice(0, board.matches.length - MAX_MATCHES);
  saveBoard();
  return true;
}
// totals per player (all time), the week's leaders, and who has beaten whom
function boardStats() {
  const weekAgo = Date.now() - 7 * 864e5, all = new Map(), week = new Map(), h2h = {};
  const key = n => n.toLowerCase();
  const add = (map, q, m) => {
    const o = map.get(key(q.n)) || { name: q.n, games: 0, wins: 0, kills: 0, deaths: 0, modes: {} };
    o.name = q.n; o.games++; if (q.w) o.wins++; o.kills += q.k; o.deaths += q.d; o.modes[m.m] = (o.modes[m.m] || 0) + 1;
    map.set(key(q.n), o);
  };
  for (const m of board.matches) {
    const people = m.p.filter(q => q.n && !q.bot);
    for (const q of people) { add(all, q, m); if (m.t >= weekAgo) add(week, q, m); }
    for (const a of people) if (a.w) for (const b of people) if (!b.w && key(a.n) !== key(b.n)) {
      const x = h2h[key(a.n)] || (h2h[key(a.n)] = {});
      x[key(b.n)] = (x[key(b.n)] || 0) + 1;
    }
  }
  const fav = o => Object.keys(o.modes).sort((a, b) => o.modes[b] - o.modes[a])[0] || '';
  const players = [...all.values()].map(o => ({ name: o.name, games: o.games, wins: o.wins, kills: o.kills, deaths: o.deaths, fav: fav(o) }))
    .sort((a, b) => b.wins - a.wins || a.games - b.games || b.kills - a.kills).slice(0, 40);
  const w = [...week.values()], top = f => w.length ? w.reduce((a, b) => f(b) > f(a) ? b : a) : null;
  const most = (f, label) => { const o = top(f); return o && f(o) > 0 ? { name: o.name, n: Math.round(f(o) * 100) / 100, label } : null; };
  const titles = [most(o => o.wins, 'most wins'), most(o => o.kills, 'most kills'),
    most(o => o.games >= 5 ? o.kills / Math.max(1, o.deaths) : 0, 'best K/D'), most(o => o.games, 'most games')].filter(Boolean);
  return { players, titles, h2h, total: board.matches.length };
}

/* ---------- http: the page, and a marker that tells the page a relay is here ---------- */
const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  if (url === '/' || url === '/index.html') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache' });
    return res.end(page());
  }
  if (url === '/relay.json') {
    res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    return res.end(JSON.stringify({ relay: true, rooms: rooms.size }));
  }
  if (url === '/create' && req.method === 'POST') {
    const reply = (status, obj) => { res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(obj)); };
    createRoom().then(code => reply(200, { code }), e => reply(503, { error: String(e.message || e) }));
    return;
  }
  if (url === '/healthz') { res.writeHead(200); return res.end('ok'); }
  if (url === '/board' && req.method === 'GET') {
    res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    return res.end(JSON.stringify(boardStats()));
  }
  if (url === '/result' && req.method === 'POST') {
    // a tablet that hosted a Same Wi-Fi game reports how it ended
    let body = '';
    req.on('data', d => { body += d; if (body.length > 8192) req.destroy(); });
    req.on('end', () => {
      let r = null; try { r = JSON.parse(body); } catch (e) {}
      const ok = addResult(r);
      res.writeHead(ok ? 200 : 400, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok }));
    });
    return;
  }
  if (process.env.TEST_HOOKS && url === '/test/endround' && req.method === 'POST') {
    // tests only: in every server-run room, knock out all tanks but the first one still alive
    for (const room of hosted) {
      const t = room.env.__tank, alive = t.tanksNow.filter(k => k.alive);
      if (t.state === 'play') alive.slice(1).forEach(k => t.kill(k));
    }
    res.writeHead(200); return res.end('ok');
  }
  res.writeHead(404); res.end('not found');
});

/* ---------- websocket ---------- */
server.on('upgrade', (req, socket) => {
  if (req.url.split('?')[0] !== '/ws' || (req.headers.upgrade || '').toLowerCase() !== 'websocket') { socket.destroy(); return; }
  const key = req.headers['sec-websocket-key'];
  if (!key) { socket.destroy(); return; }
  const accept = crypto.createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n' +
    `Sec-WebSocket-Accept: ${accept}\r\n\r\n`);
  socket.setNoDelay(true);
  onClient(wrap(socket));
});

function wrap(socket) {
  const c = { socket, buf: Buffer.alloc(0), alive: true, onmsg: null, onclose: null, closed: false };
  c.send = obj => {
    if (TEST_LAG) {
      // tests only: delay with jitter and occasional stalls, but keep order like a real TCP connection
      let t = Date.now() + TEST_LAG * (0.7 + Math.random() * 0.6) + (Math.random() < TEST_SPIKE ? 150 : 0);
      t = Math.max(t, c.lastOut || 0); c.lastOut = t;
      setTimeout(() => sendNow(obj), t - Date.now());
      return;
    }
    sendNow(obj);
  };
  const sendNow = obj => {
    if (c.closed) return;
    const data = Buffer.from(JSON.stringify(obj));
    let head;
    if (data.length < 126) head = Buffer.from([0x81, data.length]);
    else if (data.length < 65536) { head = Buffer.alloc(4); head[0] = 0x81; head[1] = 126; head.writeUInt16BE(data.length, 2); }
    else { head = Buffer.alloc(10); head[0] = 0x81; head[1] = 127; head.writeBigUInt64BE(BigInt(data.length), 2); }
    socket.write(Buffer.concat([head, data]));
  };
  c.close = () => {
    if (c.closed) return;
    c.closed = true;
    try { socket.write(Buffer.from([0x88, 0])); } catch (e) {}
    socket.end();
    if (c.onclose) c.onclose();
  };
  const control = (op, payload) => { try { socket.write(Buffer.concat([Buffer.from([0x80 | op, payload.length]), payload])); } catch (e) {} };
  // network round trip as the server sees it: browsers answer a ping with a pong carrying the same bytes
  c.ping = () => control(0x9, Buffer.from(String(Math.round(performance.now()))));
  socket.on('data', chunk => {
    c.buf = Buffer.concat([c.buf, chunk]);
    while (c.buf.length >= 2) {
      const b0 = c.buf[0], b1 = c.buf[1], op = b0 & 0x0f, masked = b1 & 0x80;
      let len = b1 & 0x7f, off = 2;
      if (len === 126) { if (c.buf.length < 4) return; len = c.buf.readUInt16BE(2); off = 4; }
      else if (len === 127) { if (c.buf.length < 10) return; len = Number(c.buf.readBigUInt64BE(2)); off = 10; }
      if (len > MAX_FRAME || !masked) { c.close(); return; }          // clients must mask; frames stay small
      if (c.buf.length < off + 4 + len) return;
      const mask = c.buf.subarray(off, off + 4), body = Buffer.from(c.buf.subarray(off + 4, off + 4 + len));
      for (let i = 0; i < body.length; i++) body[i] ^= mask[i & 3];
      c.buf = c.buf.subarray(off + 4 + len);
      c.alive = true;
      if (op === 0x8) { c.close(); return; }
      if (op === 0x9) { control(0xA, body.subarray(0, 125)); continue; }
      if (op === 0xA) {
        const sent = Number(body.toString());
        if (sent > 0) { const r = performance.now() - sent; c.rtt = c.rtt ? c.rtt * 0.7 + r * 0.3 : r; c.rttMax = Math.max(c.rttMax || 0, r); }
        continue;
      }
      if (op !== 0x1) continue;                                        // only whole text frames are used
      let msg; try { msg = JSON.parse(body.toString('utf8')); } catch (e) { continue; }
      if (msg && typeof msg === 'object' && c.onmsg) c.onmsg(msg);
    }
  });
  const gone = () => { if (!c.closed) { c.closed = true; if (c.onclose) c.onclose(); } };
  socket.on('close', gone);
  socket.on('error', gone);
  return c;
}

// keepalive: a ping every 20 s keeps proxies from closing quiet connections, and finds dead ones
const clients = new Set();
setInterval(() => {
  for (const c of clients) {
    if (c.virtual) continue;                      // server-run hosts live in this process
    if (!c.alive) { c.close(); clients.delete(c); continue; }
    c.alive = false;
    try { c.socket.write(Buffer.from([0x89, 0])); } catch (e) {}
  }
}, 20000);

// every 2 s: measure each player's network round trip and tell them, so the game can show it next to
// its own figure; every 10 s: log each busy room (network times, unsent bytes, server tick gaps)
setInterval(() => {
  for (const c of clients) {
    if (c.virtual || c.closed) continue;
    c.ping();
    if (c.rtt) c.send({ t: 'net', rtt: Math.round(c.rtt) });
  }
}, 2000);
setInterval(() => {
  for (const [code, r] of rooms) {
    if (!r.guests.size) continue;
    const room = [...hosted].find(h => h.code === code);
    const ps = [...r.guests.values()].map(g => `${g.id.slice(-4)} ${Math.round(g.rtt || 0)}/${Math.round(g.rttMax || 0)}ms q${g.socket ? g.socket.writableLength : 0}`);
    console.log(`room ${code}${room ? ` server-run tick gap max ${Math.round(room.maxGap || 0)}ms` : ' tablet-hosted'} | ${ps.join(' | ')}`);
    for (const g of r.guests.values()) g.rttMax = 0;
    if (room) room.maxGap = 0;
  }
}, 10000);

/* ---------- rooms: code -> { host, hostKey, hostAway, guests: Map(id -> client) } ---------- */
const rooms = new Map();
let nextId = 1;
// A player who joins with the key their device keeps gets the same id every time, so after dropping out
// (browser in the background, network gone) they come back as themselves. A tablet host that drops out
// keeps its room for HOST_GRACE; the guests are told it is away and wait.
const HOST_GRACE = 180000;
const validKey = k => typeof k === 'string' && /^[a-z0-9]{6,16}$/.test(k);
setInterval(() => {
  const now = Date.now();
  for (const [code, r] of rooms) {
    if (r.host || !r.hostAway || now - r.hostAway < HOST_GRACE) continue;
    for (const g of r.guests.values()) { g.send({ t: 'hostleft' }); g.room = null; g.role = null; }
    rooms.delete(code);
  }
}, 5000);

function onClient(c) {
  clients.add(c);
  c.id = 'p' + (nextId++).toString(36) + crypto.randomBytes(3).toString('hex');
  c.room = null; c.role = null;
  c.send({ t: 'hello', id: c.id });
  c.onmsg = m => {
    if (m.t === 'host' && !c.room) {
      const code = /^[0-9]{4}$/.test(m.code) ? m.code : null, key = validKey(m.key) ? m.key : null;
      const r0 = code && rooms.get(code);
      if (r0 && key && r0.hostKey === key) {
        // the same host coming back: take the room over (from a line the server may not yet know is dead)
        const old = r0.host;
        if (old && old !== c) { old.room = null; old.role = null; try { old.close(); } catch (e) {} }
        r0.host = c; r0.hostAway = 0;
        c.room = code; c.role = 'host';
        c.send({ t: 'hosting', code });
        for (const g of r0.guests.values()) { c.send({ t: 'guest', id: g.id }); g.send({ t: 'hostback' }); }
        return;
      }
      if (!code || r0) { c.send({ t: 'taken' }); return; }
      rooms.set(code, { host: c, hostKey: key, hostAway: 0, guests: new Map() });
      c.room = code; c.role = 'host';
      c.send({ t: 'hosting', code });
      if (c.onHosting) c.onHosting(code);
    } else if (m.t === 'join' && !c.room) {
      const r = rooms.get(String(m.code));
      if (!r) { c.send({ t: 'nogame' }); return; }
      if (validKey(m.key)) {
        c.id = 'k' + m.key;
        const old = r.guests.get(c.id);
        if (old && old !== c) { r.guests.delete(c.id); old.room = null; old.role = null; try { old.close(); } catch (e) {} }   // the same player again
      }
      if (r.guests.size >= MAX_GUESTS + 8) { c.send({ t: 'full' }); return; }   // a few spectators beyond the seats
      r.guests.set(c.id, c);
      c.room = String(m.code); c.role = 'guest';
      c.send({ t: 'joined', id: c.id });
      if (r.host) r.host.send({ t: 'guest', id: c.id });
      else c.send({ t: 'hostaway' });
    } else if (m.t === 'd' && c.role === 'guest') {
      const r = rooms.get(c.room);
      if (r && r.host) r.host.send({ t: 'from', id: c.id, d: m.d });
    } else if (m.t === 'to' && c.role === 'host') {
      const r = rooms.get(c.room);
      if (!r) return;
      if (m.id) { const g = r.guests.get(m.id); if (g) g.send({ t: 'd', d: m.d }); }
      else for (const g of r.guests.values()) g.send({ t: 'd', d: m.d });
    } else if (m.t === 'end' && c.role === 'host') {
      const r = rooms.get(c.room);
      if (r && r.host === c) { for (const g of r.guests.values()) { g.send({ t: 'hostleft' }); g.room = null; g.role = null; } rooms.delete(c.room); }
      c.room = null; c.role = null;
    } else if (m.t === 'kick' && c.role === 'host') {
      const r = rooms.get(c.room), g = r && r.guests.get(m.id);
      if (g) { r.guests.delete(m.id); g.send({ t: 'hostleft' }); }
    }
  };
  c.onclose = () => {
    clients.delete(c);
    const r = c.room && rooms.get(c.room);
    if (!r) return;
    if (c.role === 'host' && r.host === c) {
      if (r.hostKey && !c.virtual) {
        // a tablet host dropped out: keep the room a while; it may come back
        r.host = null; r.hostAway = Date.now();
        for (const g of r.guests.values()) g.send({ t: 'hostaway' });
        return;
      }
      for (const g of r.guests.values()) { g.send({ t: 'hostleft' }); g.room = null; g.role = null; }
      rooms.delete(c.room);
    } else if (c.role === 'guest' && r.guests.get(c.id) === c) {
      r.guests.delete(c.id);
      if (r.host) r.host.send({ t: 'left', id: c.id });
    }
  };
}

/* ---------- server-run rooms ---------- */
// The game's inline script, compiled once and run in a fresh sandbox per room.
const gameScript = (() => {
  const m = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8').match(/<script>([\s\S]*)<\/script>/);
  if (!m) throw new Error('game script not found in index.html');
  return new vm.Script(m[1], { filename: 'game-host.js' });
})();
const hosted = new Set();

// Just enough of a browser for the game to run without a screen: drawing calls go nowhere,
// and the game loop is driven by the room's timer instead of requestAnimationFrame.
function makeSandbox() {
  const noop = () => {};
  const ctx2d = new Proxy({}, { get: (t, k) => k === 'measureText' ? () => ({ width: 0 }) : noop, set: () => true });
  const canvas = () => ({ width: 0, height: 0, style: {}, getContext: () => ctx2d, addEventListener: noop,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 700 }), setPointerCapture: noop, releasePointerCapture: noop });
  const store = new Map();
  let rafCb = null;
  const env = {
    __headless: true, console, setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask, AbortController,
    performance: { now: () => performance.now() },
    innerWidth: 1000, innerHeight: 700, devicePixelRatio: 1,
    navigator: { maxTouchPoints: 0 },
    matchMedia: () => ({ matches: false, addEventListener: noop, addListener: noop }),
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    document: { getElementById: () => canvas(), createElement: t => t === 'canvas' ? canvas() : { remove: noop },
      head: { appendChild: noop }, documentElement: {}, addEventListener: noop },
    localStorage: { getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    addEventListener: noop, removeEventListener: noop,
    requestAnimationFrame: cb => { rafCb = cb; return 1; },
    location: { protocol: 'http:', host: 'server' },
    fetch: async () => ({ ok: true, json: async () => ({ relay: true }) })
  };
  env.window = env;
  env.__report = r => { try { addResult(JSON.parse(JSON.stringify(r))); } catch (e) {} };
  env.__tick = () => { const cb = rafCb; rafCb = null; if (cb) cb(performance.now()); };
  return env;
}

function createRoom() {
  return new Promise((resolve, reject) => {
    if (hosted.size >= MAX_ROOMS) { reject(new Error('The server is full. Try again in a few minutes.')); return; }
    const env = makeSandbox();
    const room = { env, client: null, code: null, timer: null, emptySince: Date.now(), everJoined: false, done: false };
    const fail = setTimeout(() => { destroy(room); reject(new Error('room did not start')); }, 5000);
    // The game opens a WebSocket to its relay; here that socket is a pipe into this process.
    env.WebSocket = class {
      constructor() {
        this.readyState = 1;
        const ws = this;
        const c = this._c = {
          virtual: true, closed: false, alive: true,
          send: obj => { const data = JSON.stringify(obj); setImmediate(() => { if (!c.closed && ws.onmessage) ws.onmessage({ data }); }); },
          close: () => { if (c.closed) return; c.closed = true; if (c.onclose) c.onclose(); setImmediate(() => { if (ws.onclose) ws.onclose(); }); },
          onHosting: code => { room.code = code; clearTimeout(fail); resolve(code); }
        };
        room.client = c;
        onClient(c);
      }
      send(str) {
        const c = this._c;
        if (c.closed) return;
        let m; try { m = JSON.parse(str); } catch (e) { return; }
        setImmediate(() => { if (!c.closed && c.onmsg) c.onmsg(m); });
      }
      close() { this._c.close(); }
    };
    vm.createContext(env);
    try { gameScript.runInContext(env); env.__tank.net.hostGame(); }
    catch (e) { clearTimeout(fail); destroy(room); reject(e); return; }
    hosted.add(room);
    room.timer = setInterval(() => {
      const now = performance.now();
      if (room.lastTick) room.maxGap = Math.max(room.maxGap || 0, now - room.lastTick);
      room.lastTick = now;
      try { env.__tick(); } catch (e) { console.error('room', room.code, e); destroy(room); return; }
      if (room.code) watch(room);
    }, TICK_MS);
  });
}

// Close a room once nobody has been in it for a while (5 minutes once someone had joined, so players who
// all dropped out can come back), or if its game gave up.
function watch(room) {
  if (room.env.__tank.net.mode !== 'host') { destroy(room); return; }
  const r = rooms.get(room.code), n = r ? r.guests.size : 0;
  if (n > 0) { room.everJoined = true; room.emptySince = 0; return; }
  if (!room.emptySince) room.emptySince = Date.now();
  if (Date.now() - room.emptySince > (room.everJoined ? 300000 : 120000)) destroy(room);
}
function destroy(room) {
  if (room.done) return;
  room.done = true;
  clearInterval(room.timer);
  hosted.delete(room);
  if (room.client) room.client.close();      // tells anyone left that the game has ended
}

server.listen(PORT, () => console.log(`tank duel server on :${PORT}`));
