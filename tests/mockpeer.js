// A stand-in for PeerJS that links browser tabs of one origin through a BroadcastChannel,
// with a little delay and jitter, so host and guest code can be tested without the internet.
(() => {
  const LAT = 35, JIT = 25;
  const bc = new BroadcastChannel('mockpeer');
  const peers = new Map();        // ids living in this tab
  const post = m => bc.postMessage(m);
  const later = fn => setTimeout(fn, LAT + Math.random() * JIT);
  bc.onmessage = ev => later(() => route(ev.data));
  function route(m) {
    const p = peers.get(m.to);
    if (!p || p.dead) return;      // another tab owns that id, or nobody does
    p._msg(m);
  }
  class Emitter {
    constructor() { this.h = {}; }
    on(e, f) { (this.h[e] = this.h[e] || []).push(f); return this; }
    emit(e, ...a) { (this.h[e] || []).forEach(f => { try { f(...a); } catch (err) { console.error(err); } }); }
  }
  class Conn extends Emitter {
    constructor(owner, remote, cid) { super(); this.owner = owner; this.peer = remote; this.cid = cid; this.open = false; }
    send(d) { if (!this.open) return; post({ type: 'data', to: this.peer, from: this.owner.id, cid: this.cid, d: JSON.parse(JSON.stringify(d)) }); }
    close() { if (!this.open) return; this.open = false; post({ type: 'close', to: this.peer, cid: this.cid }); this.emit('close'); }
  }
  class Peer extends Emitter {
    constructor(id) {
      super();
      if (typeof id !== 'string') id = 'guest-' + Math.random().toString(36).slice(2, 10);
      this.id = id; this.conns = new Map(); this.dead = false;
      peers.set(id, this);
      later(() => this.emit('open', id));
    }
    connect(remote) {
      const cid = Math.random().toString(36).slice(2);
      const c = new Conn(this, remote, cid);
      this.conns.set(cid, c);
      post({ type: 'connect', to: remote, from: this.id, cid });
      setTimeout(() => { if (!c.open && !this.dead) this.emit('error', { type: 'peer-unavailable' }); }, 1500);
      return c;
    }
    _msg(m) {
      if (m.type === 'connect') {
        const c = new Conn(this, m.from, m.cid);
        this.conns.set(m.cid, c);
        this.emit('connection', c);
        c.open = true;
        post({ type: 'accept', to: m.from, cid: m.cid });
        later(() => c.emit('open'));
      } else if (m.type === 'accept') {
        const c = this.conns.get(m.cid); if (c) { c.open = true; c.emit('open'); }
      } else if (m.type === 'nopeer') {
        this.emit('error', { type: 'peer-unavailable' });
      } else if (m.type === 'data') {
        const c = this.conns.get(m.cid); if (c && c.open) c.emit('data', m.d);
      } else if (m.type === 'close') {
        const c = this.conns.get(m.cid); if (c && c.open) { c.open = false; c.emit('close'); }
      }
    }
    destroy() { this.dead = true; for (const c of this.conns.values()) c.close(); peers.delete(this.id); }
  }
  window.Peer = Peer;
  addEventListener('pagehide', () => { for (const p of peers.values()) p.destroy(); });
})();
