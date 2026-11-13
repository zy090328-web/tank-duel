# Random maps: every one fair (turned 180 degrees), every open cell reachable, starts apart; a new one each round;
# the same on a guest's screen. Needs the server on port 8790 (TEST_HOOKS=1).
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
SHOTS = '/tmp/terr/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    L = await page('local', 820, 1180)

    r = await ev(L, """() => { const T = __tank, out = { bad: [], sight: 0, dens: [], ms: 0, gadgets: 0 };
      for (const terrain of [false, true]) {
        T.setSettings(Object.assign({}, T.settings(), { game: 'classic', terrain, soft: true, maps: 'random' }));
        for (let k = 0; k < 300; k++) {
          const id = T.RANDOM_BASE + 2 * (k + (terrain ? 5000 : 0)) + (k % 2);
          const t0 = performance.now(); const rows = T.genMap(id); out.ms = Math.max(out.ms, performance.now() - t0);
          const W = rows[0].length, H = rows.length;
          if (W !== (id % 2 ? 13 : 11) || H !== W) out.bad.push(['size', id]);
          for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) if ((rows[r][c] === '#') !== (rows[H - 1 - r][W - 1 - c] === '#')) out.bad.push(['not turned', id]);
          let w = 0; for (const row of rows) for (const ch of row) if (ch === '#') w++; out.dens.push(w / (W * H));
          T.showMap(id);
          const s0 = T.spawn[0], s1 = T.spawn[1], d = T.distField(Math.floor(s0.x), Math.floor(s0.y));
          if (d[Math.floor(s1.y) * T.COLS + Math.floor(s1.x)] < 0) out.bad.push(['starts cut off', id]);
          let open = 0, reach = 0;
          for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (!T.walls[r][c] && !T.water[r * T.COLS + c] && !T.mirror[r * T.COLS + c]) { open++; if (d[r * T.COLS + c] >= 0) reach++; }
          if (reach < open) out.bad.push(['pocket', id, open - reach]);
          if (T.lineClear(s0.x, s0.y, s1.x, s1.y, 0.05)) out.sight++;
          out.gadgets += T.portals.length + T.barrels.length + [...T.mirror].filter(Boolean).length;
          if (!terrain && (T.portals.length || T.barrels.length || [...T.mirror].some(Boolean))) out.bad.push(['gadgets without terrain', id]);
        }
      }
      const dd = out.dens; out.dens = [Math.min(...dd), Math.max(...dd)]; out.bad = out.bad.slice(0, 10); return out; }""")
    check(not r['bad'], f"600 random maps: right size, turned 180 degrees, all reachable, no gadgets without terrain {r['bad']}")
    check(r['sight'] <= 18, f"starts out of each other's sight in nearly all ({r['sight']} of 600 can see)")
    check(0.15 <= r['dens'][0] and r['dens'][1] <= 0.4 and r['ms'] < 30 and r['gadgets'] > 300, f"walls cover {r['dens'][0]:.2f}-{r['dens'][1]:.2f}; slowest {r['ms']:.1f} ms; gadgets {r['gadgets']}")

    # a match: a new map every round; 11 by 11 for two, 13 by 13 for three
    r = await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 1, maps: 'random', terrain: true, soft: true, powerups: true, mut: 'off', winScore: 5 }));
      T.beginFromMenu(); T.bots.add(0); const ids = [T.mapId]; let st = T.state;
      for (let i = 0; i < 120 * 300 && T.state !== 'matchEnd'; i++) { T.update(1 / 120); if (T.state === 'countdown' && st !== 'countdown') ids.push(T.mapId); st = T.state; }
      return [T.state, ids, T.COLS]; }""")
    ids = r[1]
    check(r[0] == 'matchEnd' and len(set(ids)) == len(ids) and all(i >= 10000 and i % 2 == 0 for i in ids), f'two tanks: a match on a new 11x11 map every round {r[0]} {ids[:6]}')
    r = await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'dm', cpu: 3, maps: 'random' })); T.beginFromMenu(); T.bots.add(0);
      for (let i = 0; i < 120 * 200 && T.state !== 'matchEnd'; i++) T.update(1 / 120); return [T.state, T.mapId % 2, T.COLS]; }""")
    check(r == ['matchEnd', 1, 13], f'four tanks: 13x13, and computer tanks finish a deathmatch on it {r}')
    for g in ['base', 'soccer']:
      r = await ev(L, """(g) => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: g, cpu: 1, maps: 'random' })); T.beginFromMenu(); return T.mapId; }""", g)
      check(r < 10000, f'{g} keeps its own maps ({r})')
    await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 0, maps: 'random', terrain: true })); T.menuStep = 'rules'; }""")
    await L.wait_for_timeout(300)
    await L.screenshot(path=SHOTS + 'rm_rules.png')
    await L.close()

    # online: the guest draws the same map
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'random', winScore: 5, game: 'classic', soft: true, terrain: true, mut: 'off' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(300)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()'); await G.wait_for_timeout(3000)
    sig = "(() => { const T = __tank; return [T.mapId, T.walls.map(r => r.map(v => v ? 1 : 0).join('')).join('/'), [...T.mirror].join(''), T.portals.map(p => p.x + ',' + p.y).join(' '), T.barrels.length]; })()"
    hs = await ev(H, sig); gs = await ev(G, sig)
    check(hs[0] >= 10000 and hs == gs, f'guest has the same random map {hs[0]} {gs[0]}')
    await G.screenshot(path=SHOTS + 'rm_guest.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
