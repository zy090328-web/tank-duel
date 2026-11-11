// Graph Paper Tank Duel - relay server.
// Serves the game page and passes messages between one host tablet and its guests.
// The host tablet still runs the game; this server only forwards. No dependencies:
// a small WebSocket implementation (RFC 6455, text frames) sits on Node's http module.
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 8080;
const MAX_FRAME = 64 * 1024;          // nothing in this game is anywhere near this
const MAX_GUESTS = 4;                 // 5 tanks in all
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
  if (url === '/healthz') { res.writeHead(200); return res.end('ok'); }
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

server.listen(PORT, () => console.log(`tank duel relay on :${PORT}`));
