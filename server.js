// Graph Paper Tank Duel - game server.
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
      if (op === 0xA) continue;
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

/* ---------- rooms: code -> { host, guests: Map(id -> client) } ---------- */
const rooms = new Map();
let nextId = 1;

function onClient(c) {
  clients.add(c);
  c.id = 'p' + (nextId++).toString(36) + crypto.randomBytes(3).toString('hex');
  c.room = null; c.role = null;
  c.send({ t: 'hello', id: c.id });
  c.onmsg = m => {
    if (m.t === 'host' && !c.room) {
      const code = /^[0-9]{4}$/.test(m.code) ? m.code : null;
      if (!code || rooms.has(code)) { c.send({ t: 'taken' }); return; }
      rooms.set(code, { host: c, guests: new Map() });
      c.room = code; c.role = 'host';
      c.send({ t: 'hosting', code });
      if (c.onHosting) c.onHosting(code);
    } else if (m.t === 'join' && !c.room) {
      const r = rooms.get(String(m.code));
      if (!r) { c.send({ t: 'nogame' }); return; }
      if (r.guests.size >= MAX_GUESTS + 8) { c.send({ t: 'full' }); return; }   // a few spectators beyond the seats
      r.guests.set(c.id, c);
      c.room = String(m.code); c.role = 'guest';
      c.send({ t: 'joined' });
      r.host.send({ t: 'guest', id: c.id });
    } else if (m.t === 'd' && c.role === 'guest') {
      const r = rooms.get(c.room);
      if (r) r.host.send({ t: 'from', id: c.id, d: m.d });
    } else if (m.t === 'to' && c.role === 'host') {
      const r = rooms.get(c.room);
      if (!r) return;
      if (m.id) { const g = r.guests.get(m.id); if (g) g.send({ t: 'd', d: m.d }); }
      else for (const g of r.guests.values()) g.send({ t: 'd', d: m.d });
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
      for (const g of r.guests.values()) { g.send({ t: 'hostleft' }); g.room = null; g.role = null; }
      rooms.delete(c.room);
    } else if (c.role === 'guest') {
      r.guests.delete(c.id);
      r.host.send({ t: 'left', id: c.id });
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
      try { env.__tick(); } catch (e) { console.error('room', room.code, e); destroy(room); return; }
      if (room.code) watch(room);
    }, TICK_MS);
  });
}

// Close a room once nobody is in it (sooner if someone had joined), or if its game gave up.
function watch(room) {
  if (room.env.__tank.net.mode !== 'host') { destroy(room); return; }
  const r = rooms.get(room.code), n = r ? r.guests.size : 0;
  if (n > 0) { room.everJoined = true; room.emptySince = 0; return; }
  if (!room.emptySince) room.emptySince = Date.now();
  if (Date.now() - room.emptySince > (room.everJoined ? 15000 : 60000)) destroy(room);
}
function destroy(room) {
  if (room.done) return;
  room.done = true;
  clearInterval(room.timer);
  hosted.delete(room);
  if (room.client) room.client.close();      // tells anyone left that the game has ended
}

server.listen(PORT, () => console.log(`tank duel server on :${PORT}`));
